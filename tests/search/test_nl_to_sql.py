"""
Tests for app/search/nl_to_sql.py

Strategy:
  - validate_sql: pure Python, no mocking needed.
  - run_nl_to_sql: mock _call_bedrock_sync (Bedrock) and _execute_sql (DB).
  - _write_audit: always mocked — we verify it is called, not what it writes.
  - _fetch_few_shot: mocked to return empty list unless explicitly testing it.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.search import NLToSQLResult
from app.search.nl_to_sql import validate_sql


# ── validate_sql — pure Python, no mocking ───────────────────────────────────

class TestValidateSQL:
    def test_valid_select_passes(self):
        ok, msg = validate_sql("SELECT * FROM products WHERE is_active = true LIMIT 50")
        assert ok is True
        assert msg == "Valid"

    def test_empty_string_fails(self):
        ok, msg = validate_sql("")
        assert ok is False

    def test_update_blocked(self):
        ok, msg = validate_sql("UPDATE products SET current_price = 999 WHERE id = '1'")
        assert ok is False
        assert "UPDATE" in msg

    def test_delete_blocked(self):
        ok, msg = validate_sql("DELETE FROM products WHERE id = '1'")
        assert ok is False
        assert "DELETE" in msg

    def test_drop_blocked(self):
        ok, msg = validate_sql("DROP TABLE products")
        assert ok is False
        assert "DROP" in msg

    def test_insert_blocked(self):
        ok, msg = validate_sql("INSERT INTO products (name) VALUES ('hack')")
        assert ok is False
        assert "INSERT" in msg

    def test_alter_blocked(self):
        ok, msg = validate_sql("ALTER TABLE products ADD COLUMN hack TEXT")
        assert ok is False
        assert "ALTER" in msg

    def test_truncate_blocked(self):
        ok, msg = validate_sql("TRUNCATE TABLE products")
        assert ok is False
        assert "TRUNCATE" in msg

    def test_select_with_aggregation_passes(self):
        ok, _ = validate_sql(
            "SELECT brand, AVG(avg_rating) FROM products "
            "WHERE is_active = true GROUP BY brand ORDER BY 2 DESC LIMIT 50"
        )
        assert ok is True

    def test_select_with_join_passes(self):
        ok, _ = validate_sql(
            "SELECT p.name, AVG(r.rating) FROM products p "
            "JOIN reviews r ON r.product_id = p.id GROUP BY p.name LIMIT 50"
        )
        assert ok is True

    def test_select_with_jsonb_passes(self):
        ok, _ = validate_sql(
            "SELECT name, (specs->>'ram_gb')::NUMERIC AS ram "
            "FROM products WHERE is_active = true LIMIT 50"
        )
        assert ok is True

    def test_injection_via_natural_language_blocked(self):
        # A prompt injection attempt that produces SQL with a dangerous keyword
        ok, msg = validate_sql("SELECT 1; DROP TABLE products")
        # sqlparse sees the first statement type as SELECT but dangerous keyword scan catches DROP
        assert ok is False

    def test_non_select_type_blocked(self):
        ok, msg = validate_sql("EXPLAIN SELECT * FROM products")
        assert ok is False  # get_type() returns None for EXPLAIN


# ── run_nl_to_sql — full pipeline ────────────────────────────────────────────

def _make_db_mock():
    """Returns a mock AsyncSession that supports await session.execute()."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.keys.return_value = ["brand", "avg_rating"]
    result_mock.fetchall.return_value = [("Dell", 4.6), ("Apple", 4.5)]
    db.execute = AsyncMock(return_value=result_mock)
    return db


VALID_SQL = "SELECT brand, AVG(avg_rating) FROM products GROUP BY brand LIMIT 50"


class TestRunNLToSQL:
    @pytest.mark.asyncio
    async def test_happy_path_returns_result(self):
        db = _make_db_mock()
        with (
            patch("app.search.nl_to_sql.call_llm", new_callable=AsyncMock, return_value=VALID_SQL),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=[]),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock),
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            result = await run_nl_to_sql(
                query="which brand has highest average rating",
                schema_scope=["products", "reviews"],
                db=db,
            )

        assert isinstance(result, NLToSQLResult)
        assert result.validation_passed is True
        assert result.generated_sql == VALID_SQL
        assert result.rows_returned == 2
        assert result.rows == [{"brand": "Dell", "avg_rating": 4.6}, {"brand": "Apple", "avg_rating": 4.5}]

    @pytest.mark.asyncio
    async def test_retry_on_invalid_sql_then_success(self):
        """First call returns dangerous SQL, second call returns valid SQL."""
        db = _make_db_mock()
        call_count = 0

        async def _llm_side_effect(prompt: str, **_: object) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "DROP TABLE products"
            return VALID_SQL

        with (
            patch("app.search.nl_to_sql.call_llm", side_effect=_llm_side_effect),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=[]),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock),
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            result = await run_nl_to_sql(
                query="which brand has highest rating",
                schema_scope=["products"],
                db=db,
            )

        assert result.validation_passed is True
        assert result.retry_count == 1
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_returns_failure(self):
        """All 3 attempts return invalid SQL — result has validation_passed=False."""
        db = _make_db_mock()
        with (
            patch("app.search.nl_to_sql.call_llm", new_callable=AsyncMock, return_value="DELETE FROM products"),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=[]),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock) as mock_audit,
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            result = await run_nl_to_sql(
                query="delete all products",
                schema_scope=["products"],
                db=db,
            )

        assert result.validation_passed is False
        assert result.retry_count == 2
        assert result.rows == []
        mock_audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_always_written_on_success(self):
        db = _make_db_mock()
        with (
            patch("app.search.nl_to_sql.call_llm", new_callable=AsyncMock, return_value=VALID_SQL),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=[]),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock) as mock_audit,
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            await run_nl_to_sql("which brand has highest rating", ["products"], db)

        mock_audit.assert_called_once()
        logged = mock_audit.call_args[0][0]  # first positional arg is NLToSQLResult
        assert logged.validation_passed is True

    @pytest.mark.asyncio
    async def test_audit_always_written_on_failure(self):
        db = _make_db_mock()
        with (
            patch("app.search.nl_to_sql.call_llm", new_callable=AsyncMock, return_value="DROP TABLE products"),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=[]),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock) as mock_audit,
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            await run_nl_to_sql("do something bad", ["products"], db)

        mock_audit.assert_called_once()
        logged = mock_audit.call_args[0][0]
        assert logged.validation_passed is False

    @pytest.mark.asyncio
    async def test_source_passed_to_audit(self):
        db = _make_db_mock()
        with (
            patch("app.search.nl_to_sql.call_llm", new_callable=AsyncMock, return_value=VALID_SQL),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=[]),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock) as mock_audit,
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            await run_nl_to_sql("which brand leads", ["products"], db, source="admin")

        _, source_arg = mock_audit.call_args[0]
        assert source_arg == "admin"

    @pytest.mark.asyncio
    async def test_user_id_scope_note_in_prompt(self):
        """When user_id is provided, the prompt must mention the user_id constraint."""
        db = _make_db_mock()
        captured_prompts: list[str] = []

        async def _capture(prompt: str, **_: object) -> str:
            captured_prompts.append(prompt)
            return VALID_SQL

        with (
            patch("app.search.nl_to_sql.call_llm", side_effect=_capture),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=[]),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock),
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            await run_nl_to_sql(
                "show my orders",
                ["orders"],
                db,
                user_id="usr-abc-123",
            )

        assert "usr-abc-123" in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_schema_scope_controls_which_tables_injected(self):
        """Only requested tables appear in the prompt — not full DB schema."""
        db = _make_db_mock()
        captured_prompts: list[str] = []

        async def _capture(prompt: str, **_: object) -> str:
            captured_prompts.append(prompt)
            return VALID_SQL

        with (
            patch("app.search.nl_to_sql.call_llm", side_effect=_capture),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=[]),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock),
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            await run_nl_to_sql("avg rating by brand", ["products"], db)

        prompt = captured_prompts[0]
        assert "products(" in prompt
        assert "reviews(" not in prompt
        assert "price_history(" not in prompt
        assert "orders(" not in prompt

    @pytest.mark.asyncio
    async def test_few_shot_examples_injected_into_prompt(self):
        db = _make_db_mock()
        captured_prompts: list[str] = []
        examples = [
            {"natural_language_query": "avg price by brand", "generated_sql": "SELECT brand, AVG(current_price) FROM products GROUP BY brand LIMIT 50"},
        ]

        async def _capture(prompt: str, **_: object) -> str:
            captured_prompts.append(prompt)
            return VALID_SQL

        with (
            patch("app.search.nl_to_sql.call_llm", side_effect=_capture),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=examples),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock),
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            await run_nl_to_sql("which brand has highest rating", ["products"], db)

        assert "avg price by brand" in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_retry_prompt_includes_previous_error(self):
        """On retry, the prompt must include the previous bad SQL and the error."""
        db = _make_db_mock()
        captured_prompts: list[str] = []
        call_count = 0

        async def _llm(prompt: str, **_: object) -> str:
            nonlocal call_count
            call_count += 1
            captured_prompts.append(prompt)
            return "DELETE FROM products" if call_count == 1 else VALID_SQL

        with (
            patch("app.search.nl_to_sql.call_llm", side_effect=_llm),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=[]),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock),
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            await run_nl_to_sql("which brand leads", ["products"], db)

        retry_prompt = captured_prompts[1]
        assert "DELETE FROM products" in retry_prompt   # previous bad SQL shown
        assert "Error:" in retry_prompt                  # error reason shown

    @pytest.mark.asyncio
    async def test_no_retries_on_first_success(self):
        db = _make_db_mock()
        with (
            patch("app.search.nl_to_sql.call_llm", new_callable=AsyncMock, return_value=VALID_SQL),
            patch("app.search.nl_to_sql._fetch_few_shot", return_value=[]),
            patch("app.search.nl_to_sql._write_audit", new_callable=AsyncMock),
        ):
            from app.search.nl_to_sql import run_nl_to_sql
            result = await run_nl_to_sql("which brand leads", ["products"], db)

        assert result.retry_count == 0
