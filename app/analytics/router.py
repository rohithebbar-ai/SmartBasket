"""
Admin analytics — NL-to-SQL endpoint.

POST /api/analytics/query
    Accepts a plain-English question, runs it through the centralized
    NL-to-SQL engine, synthesises an insight with Bedrock Sonnet, and
    returns AnalyticsResponse.

Auth: require_admin — never expose to unauthenticated callers.
Audit: every attempt is logged to nl_sql_audit with source="admin".
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.llm import call_llm
from app.schemas.search import AnalyticsResponse
from app.search.nl_to_sql import run_nl_to_sql

log = logging.getLogger(__name__)
router = APIRouter()

# Tables available to admin analytics — full catalogue + price history
ADMIN_SCHEMA_SCOPE = ["products", "reviews", "price_history", "orders"]


# ── Request schema ────────────────────────────────────────────────────────────

class AnalyticsQuery(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


# ── Insight synthesis ─────────────────────────────────────────────────────────

async def _synthesise(question: str, rows: list[dict]) -> str:
    if not rows:
        return "The query returned no results."

    rows_text = "\n".join(str(r) for r in rows[:20])  # cap at 20 rows for prompt
    prompt = (
        f"You are ShopSense, an intelligent product analytics assistant.\n\n"
        f"Admin question: {question}\n\n"
        f"Query results ({len(rows)} rows):\n{rows_text}\n\n"
        f"Write a concise 1-2 sentence insight summarising the key finding. "
        f"Be specific — cite numbers from the results."
    )
    return await call_llm(prompt, tier="generation", max_tokens=200, temperature=0.3)


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/query", response_model=AnalyticsResponse)
async def analytics_query(
    body: AnalyticsQuery,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
) -> AnalyticsResponse:
    """
    Admin-only NL-to-SQL endpoint.
    1. Run centralized NL-to-SQL engine (products + reviews + price_history + orders).
    2. Synthesise a one-sentence insight with Bedrock Sonnet.
    3. Return AnalyticsResponse with question, SQL, rows, insight.
    """
    result = await run_nl_to_sql(
        query=body.question,
        schema_scope=ADMIN_SCHEMA_SCOPE,
        db=db,
        source="admin",
        use_few_shot=True,
    )

    if not result.validation_passed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Could not generate valid SQL after 3 attempts.",
                "question": body.question,
                "last_sql": result.generated_sql,
            },
        )

    try:
        insight = await _synthesise(body.question, result.rows)
    except Exception as exc:
        log.warning("Insight synthesis failed (non-fatal): %s", exc)
        insight = f"Query returned {result.rows_returned} rows."

    return AnalyticsResponse(
        question=body.question,
        sql=result.generated_sql,
        results=result.rows,
        insight=insight,
        rows_returned=result.rows_returned,
    )
