# Admin NL-to-SQL — implement in Week 2 (Day 10):
#   Thin wrapper around app.search.nl_to_sql with analytics-specific context.
#   Adds: insight synthesis via Bedrock Sonnet after query execution.
#   Logs all admin queries to nl_sql_audit with source="admin".
