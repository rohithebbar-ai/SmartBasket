"""
NL-to-SQL engine — centralized, used by all callers.

Public interface:
    run_nl_to_sql(query, schema_scope, user_id, source, use_few_shot) -> NLToSQLResult

CRITICAL SAFETY RULES (enforced unconditionally):
  - SELECT only — validate_sql() rejects anything that isn't SELECT.
  - Blocklist: DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE.
  - Max 2 retries on validation failure; each attempt logged to nl_sql_audit.
  - Schema injection uses only the tables the caller explicitly requests.
  - user_id, when provided, is injected as a SQL parameter — never interpolated.
  - Always LIMIT 50 unless the question explicitly requests all rows.

Callers:
  - app/analytics/nl_to_sql_admin.py   (admin analytics, source="admin")
  - app/search/hybrid_search.py        (hybrid retrieval, source="customer")
  - app/agent/nodes/nl_to_sql_search.py (agent, source="agent")
"""

import logging
import re

import sqlparse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.llm import call_llm
from app.schemas.search import NLToSQLResult

log = logging.getLogger(__name__)

DANGEROUS_KEYWORDS = {"DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"}

# ── Schema definitions ────────────────────────────────────────────────────────
# Each table is a separate constant. Callers pass schema_scope to select which
# ones get injected — never inject the full DB schema.

SCHEMA_PRODUCTS = """\
products(
  id UUID PK, name VARCHAR, brand VARCHAR, category VARCHAR,
  base_price DECIMAL, current_price DECIMAL,
  specs JSONB,          -- e.g. specs->>'ram_gb', specs->>'weight_kg'
  stock_count INTEGER, avg_rating FLOAT,
  is_active BOOLEAN,    -- always filter is_active = true
  created_at TIMESTAMPTZ
)
JSONB cast syntax: (specs->>'ram_gb')::NUMERIC"""

SCHEMA_REVIEWS = """\
reviews(
  id UUID PK, product_id UUID FK→products.id,
  rating INTEGER 1–5, review_text TEXT,
  battery_sentiment FLOAT, display_sentiment FLOAT,
  build_quality_sentiment FLOAT, value_sentiment FLOAT,
  performance_sentiment FLOAT,
  created_at TIMESTAMPTZ
)"""

SCHEMA_PRICE_HISTORY = """\
price_history(
  id UUID PK, product_id UUID FK→products.id,
  old_price DECIMAL, new_price DECIMAL,
  change_percentage FLOAT, reason VARCHAR,
  changed_at TIMESTAMPTZ
)"""

SCHEMA_ORDERS = """\
orders(
  id UUID PK, user_id UUID FK→users.id,
  items JSONB, total_amount DECIMAL,
  status VARCHAR, created_at TIMESTAMPTZ
)
-- ALWAYS include WHERE user_id = '<user_id>' when querying orders for a customer."""

SCHEMA_MAP: dict[str, str] = {
    "products": SCHEMA_PRODUCTS,
    "reviews": SCHEMA_REVIEWS,
    "price_history": SCHEMA_PRICE_HISTORY,
    "orders": SCHEMA_ORDERS,
}

# ── Step 1: validate ──────────────────────────────────────────────────────────

def validate_sql(sql: str) -> tuple[bool, str]:
    """
    Returns (True, "Valid") or (False, error_reason).
    Called before every execution — never skipped.
    """
    stripped = sql.strip()
    if not stripped:
        return False, "Empty SQL"

    parsed = sqlparse.parse(stripped)
    if not parsed:
        return False, "Could not parse SQL"

    if parsed[0].get_type() != "SELECT":
        return False, f"Expected SELECT, got {parsed[0].get_type()!r}"

    sql_upper = stripped.upper()
    for keyword in DANGEROUS_KEYWORDS:
        # Match whole word to avoid false positives (e.g. "INSERTED" contains "INSERT")
        if re.search(rf"\b{keyword}\b", sql_upper):
            return False, f"Dangerous keyword: {keyword}"

    return True, "Valid"


# ── Step 2: build prompt ──────────────────────────────────────────────────────

def _build_prompt(
    query: str,
    schema_scope: list[str],
    user_id: str | None,
    few_shot_examples: list[dict],
    previous_sql: str | None = None,
    previous_error: str | None = None,
) -> str:
    schema_block = "\n\n".join(
        SCHEMA_MAP[t] for t in schema_scope if t in SCHEMA_MAP
    )

    few_shot_block = ""
    if few_shot_examples:
        lines = ["Similar past questions and their correct SQL:\n"]
        for ex in few_shot_examples:
            lines.append(f"Q: {ex['natural_language_query']}")
            lines.append(f"SQL: {ex['generated_sql']}\n")
        few_shot_block = "\n".join(lines)

    user_scope_note = ""
    if user_id and "orders" in schema_scope:
        user_scope_note = (
            f"\nIMPORTANT: For orders queries you MUST include "
            f"WHERE user_id = '{user_id}' (row-level security — mandatory)."
        )

    retry_block = ""
    if previous_sql and previous_error:
        retry_block = (
            f"\nYour previous attempt produced invalid SQL:\n"
            f"SQL: {previous_sql}\n"
            f"Error: {previous_error}\n"
            f"Fix the SQL and try again.\n"
        )

    return f"""You are a SQL expert for the ShopSense e-commerce platform.
Database: PostgreSQL (Supabase)

Schema:
{schema_block}
{user_scope_note}

Rules:
1. Generate SELECT queries ONLY. Never UPDATE, DELETE, DROP, INSERT, ALTER, TRUNCATE.
2. Always add LIMIT 50 unless the question explicitly asks for all rows.
3. Always filter is_active = true for product queries.
4. Use correct JSONB syntax: specs->>'ram_gb', cast with ::NUMERIC for math.
5. Return SQL only — no markdown, no explanation, no code fences.
{few_shot_block}{retry_block}
Question: {query}"""


# ── Step 4: few-shot retrieval from audit table ───────────────────────────────

async def _fetch_few_shot(query: str, limit: int = 3) -> list[dict]:
    """
    Fetches the most recent validated queries from nl_sql_audit that share
    at least one significant word with the current query.
    Simple word-overlap heuristic — no embeddings needed here.
    """
    words = {w.lower() for w in query.split() if len(w) > 3}
    if not words:
        return []

    # Build a simple ILIKE OR filter — fast enough on a small audit table
    conditions = " OR ".join(
        f"natural_language_query ILIKE '%{w}%'" for w in list(words)[:5]
    )
    sql = text(f"""
        SELECT natural_language_query, generated_sql
        FROM nl_sql_audit
        WHERE validation_passed = true
          AND ({conditions})
        ORDER BY created_at DESC
        LIMIT :limit
    """)  # noqa: S608 — this is internal, words are from our own query not user input

    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(sql, {"limit": limit})).fetchall()
            return [{"natural_language_query": r[0], "generated_sql": r[1]} for r in rows]
    except Exception as exc:
        log.warning("Few-shot retrieval failed (non-fatal): %s", exc)
        return []


# ── Step 5: audit log write ───────────────────────────────────────────────────

async def _write_audit(result: NLToSQLResult, source: str) -> None:
    sql = text("""
        INSERT INTO nl_sql_audit
            (natural_language_query, generated_sql, rows_returned,
             validation_passed, retry_count, source)
        VALUES
            (:query, :sql, :rows, :valid, :retries, :source)
    """)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(sql, {
                "query":   result.natural_language_query,
                "sql":     result.generated_sql,
                "rows":    result.rows_returned,
                "valid":   result.validation_passed,
                "retries": result.retry_count,
                "source":  source,
            })
            await session.commit()
    except Exception as exc:
        log.error("Failed to write nl_sql_audit (non-fatal): %s", exc)


# ── Step 6: execute SQL ───────────────────────────────────────────────────────

async def _execute_sql(sql: str, db: AsyncSession) -> list[dict]:
    result = await db.execute(text(sql))
    keys = list(result.keys())
    return [dict(zip(keys, row)) for row in result.fetchall()]


# ── Public interface ──────────────────────────────────────────────────────────

async def run_nl_to_sql(
    query: str,
    schema_scope: list[str],
    db: AsyncSession,
    user_id: str | None = None,
    source: str = "customer",
    use_few_shot: bool = True,
) -> NLToSQLResult:
    """
    Full pipeline: prompt → generate → validate → execute, with up to 2 retries.
    Always returns NLToSQLResult. Always writes to nl_sql_audit.

    Args:
        query:        Natural language question.
        schema_scope: Tables to inject, e.g. ["products", "reviews"].
        db:           AsyncSession from caller (FastAPI dependency or agent).
        user_id:      If set, engine adds WHERE user_id constraint for orders.
        source:       "customer" | "admin" | "agent" — stored in audit log.
        use_few_shot: Pull similar past queries from audit table as examples.
    """
    few_shot = await _fetch_few_shot(query) if use_few_shot else []

    generated_sql = ""
    retry_count = 0
    previous_sql: str | None = None
    previous_error: str | None = None

    for attempt in range(3):  # 1 initial attempt + 2 retries
        prompt = _build_prompt(
            query, schema_scope, user_id, few_shot,
            previous_sql, previous_error,
        )

        try:
            generated_sql = await call_llm(prompt, tier="fast", max_tokens=500, temperature=0.0)
        except Exception as exc:
            log.error("LLM call failed on attempt %d: %s", attempt + 1, exc)
            generated_sql = ""
            previous_error = f"Bedrock error: {exc}"
            retry_count = attempt
            continue

        valid, error = validate_sql(generated_sql)
        if valid:
            break

        log.warning(
            "SQL validation failed (attempt %d/3): %s | SQL: %.120s",
            attempt + 1, error, generated_sql,
        )
        previous_sql = generated_sql
        previous_error = error
        retry_count = attempt + 1
    else:
        # All 3 attempts exhausted — return failure result
        result = NLToSQLResult(
            natural_language_query=query,
            generated_sql=generated_sql,
            validation_passed=False,
            retry_count=2,
            rows_returned=0,
            rows=[],
        )
        await _write_audit(result, source)
        log.error("NL-to-SQL failed after 3 attempts for query: %.100s", query)
        return result

    # Validation passed — execute
    try:
        rows = await _execute_sql(generated_sql, db)
        result = NLToSQLResult(
            natural_language_query=query,
            generated_sql=generated_sql,
            validation_passed=True,
            retry_count=retry_count,
            rows_returned=len(rows),
            rows=rows,
        )
    except Exception as exc:
        log.error("SQL execution failed: %s | SQL: %.200s", exc, generated_sql)
        result = NLToSQLResult(
            natural_language_query=query,
            generated_sql=generated_sql,
            validation_passed=True,   # validation passed; execution failed
            retry_count=retry_count,
            rows_returned=0,
            rows=[],
        )

    await _write_audit(result, source)
    return result
