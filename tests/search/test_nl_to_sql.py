# Implement tests in Week 2 (Day 10) alongside the NL-to-SQL engine.
# Golden test set target: >= 85% of 20 queries generate correct SQL.
#
# Test coverage targets:
#   - validate_sql: rejects UPDATE, DELETE, DROP, INSERT, ALTER, TRUNCATE
#   - validate_sql: accepts valid SELECT statements
#   - generate_sql: produces valid SQL for aggregation queries
#   - generate_sql: correctly uses JSONB operators (specs->>'ram_gb')::NUMERIC
#   - Safety: "DROP TABLE products" injected via natural language → blocked
#   - nl_sql_audit: every query logged regardless of success/failure
#   - Retry loop: invalid SQL triggers retry, bounded at 2 retries
