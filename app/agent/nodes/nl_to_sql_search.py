"""
nl_to_sql_search — ANALYTICAL retrieval path.

Delegates to app.search.nl_to_sql.run_nl_to_sql(), which:
  - Generates SELECT SQL via Bedrock Haiku
  - Validates with sqlparse (blocks all non-SELECT and dangerous keywords)
  - Retries up to 2 times on validation failure
  - Logs every attempt to nl_sql_audit

If validation_passed is False after all retries, sets final_response to an
error message so synthesise is bypassed and the user gets a clear signal.

Reads:  state.messages (last user message), state.user_id
Writes: state.sql_results (list[dict] — rows with query-specific column names)
        state.generated_sql (str)
        state.final_response (str — only on validation failure)

Outgoing edge: → synthesise (bypasses personalise)
"""

import logging

from app.agent.state import ShopSenseState
from app.database import AsyncSessionLocal
from app.search.nl_to_sql import run_nl_to_sql

log = logging.getLogger(__name__)

_VALIDATION_FAILURE_MSG = (
    "I couldn't turn that into a valid database query. "
    "Could you rephrase? For example: 'which brand has the highest rating?'"
)


async def nl_to_sql_search(state: ShopSenseState) -> dict:
    messages = state.get("messages", [])
    query = messages[-1]["content"] if messages else ""
    user_id = state.get("user_id") or None

    async with AsyncSessionLocal() as db:
        result = await run_nl_to_sql(
            query=query,
            schema_scope=["products", "reviews", "price_history"],
            db=db,
            user_id=user_id,
            source="agent",
        )

    if not result.validation_passed:
        log.warning(
            "NL-to-SQL validation failed for agent query: %.100s | SQL: %.120s",
            query,
            result.generated_sql,
        )
        return {
            "sql_results": [],
            "generated_sql": result.generated_sql,
            "final_response": _VALIDATION_FAILURE_MSG,
        }

    return {
        "sql_results": result.rows,
        "generated_sql": result.generated_sql,
    }
