"""
NL-to-SQL engine — implement in Week 2 (Day 10).

CRITICAL SAFETY RULES (enforced at all times, no exceptions):
  - SELECT only. generate_sql() rejects any statement that is not SELECT.
  - validate_sql() runs sqlparse before any execution — blocks DROP, DELETE,
    UPDATE, INSERT, ALTER, TRUNCATE.
  - Max 2 retries on validation failure.
  - Every attempt is logged to nl_sql_audit via NLToSQLResult regardless of
    success or failure.
  - Schema injection uses only the four ShopSense tables — never full DB metadata.
  - Always LIMIT 50 unless user explicitly asks for all rows.

Public interface:
    generate_sql(question: str) -> str
    validate_sql(sql: str) -> tuple[bool, str]
    execute_query(question: str) -> NLToSQLResult

The LLM response (raw SQL string) and execution results are wrapped in
NLToSQLResult immediately — never returned as raw strings or bare lists.
"""

import sqlparse

from app.schemas.search import NLToSQLResult

DANGEROUS_KEYWORDS = {"DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"}


def validate_sql(sql: str) -> tuple[bool, str]:
    """
    Parses sql with sqlparse. Returns (True, "Valid") or (False, error_message).
    Called before every execution — never skipped.
    """
    parsed = sqlparse.parse(sql.strip())
    if not parsed:
        return False, "Could not parse SQL"

    statement = parsed[0]
    if statement.get_type() != "SELECT":
        return False, f"Expected SELECT, got {statement.get_type()}"

    sql_upper = sql.upper()
    for keyword in DANGEROUS_KEYWORDS:
        if keyword in sql_upper:
            return False, f"Dangerous keyword: {keyword}"

    return True, "Valid"


async def generate_sql(question: str) -> str:
    """Calls Bedrock Haiku with NL_TO_SQL_PROMPT + schema injection. Returns raw SQL."""
    raise NotImplementedError("Implement in Week 2 — NL-to-SQL engine (Day 10)")


async def execute_query(question: str) -> NLToSQLResult:
    """
    Full pipeline: generate → validate → execute, with up to 2 retries.
    Always returns NLToSQLResult — caller reads result.validation_passed to
    check success. Result is logged to nl_sql_audit before returning.
    """
    raise NotImplementedError("Implement in Week 2 — NL-to-SQL engine (Day 10)")
