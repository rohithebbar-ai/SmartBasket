from app.agent.state import ShopSenseState
from app.schemas.search import NLToSQLResult


async def nl_to_sql_search(state: ShopSenseState) -> ShopSenseState:
    """
    Runs the analytical retrieval path for ANALYTICAL queries.

    Delegates to app.search.nl_to_sql.execute_query(), which returns NLToSQLResult.
    state.sql_results is populated from NLToSQLResult.rows.
    state.generated_sql is populated from NLToSQLResult.generated_sql.
    Check NLToSQLResult.validation_passed before continuing — if False, surface the
    error rather than passing empty results to synthesise.

    SQL validation happens before any execution — no exceptions.
    Max 2 retries on validation failure; every attempt logged to nl_sql_audit.

    Reads:  state.messages (last user message)
    Writes: state.sql_results (list[dict] — rows with query-specific column names),
            state.generated_sql (str)

    Outgoing edge: → synthesise (bypasses personalise — structured data is not personalised)
    """
    raise NotImplementedError("Implement in Week 3 — LangGraph agent phase (Days 12–13)")
