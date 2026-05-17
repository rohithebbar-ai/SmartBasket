# Implement tests in Week 2 (Day 10) alongside the analytics module.
#
# Test coverage targets:
#   - Admin endpoint: requires admin JWT role; rejects customer tokens
#   - Query execution: "which brand has highest rating?" returns correct ranked result
#   - Insight synthesis: Bedrock Sonnet called after SQL execution
#   - Audit logging: every admin query logged to nl_sql_audit with source="admin"
