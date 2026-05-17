# Implement tests in Phase 1 tool calling (after Week 3 agent phase).
#
# Test coverage targets:
#   - MCP server list_tools: returns all 8 checkout tools with correct schemas
#   - add_to_cart: reads live price from Redis (not base_price)
#   - process_payment: only executes after CONFIRM classification; never on AMBIGUOUS
#   - process_payment idempotency: duplicate call with same idempotency key does not double-charge
#   - send_confirmation_email: called automatically after successful process_payment
#   - await_confirmation: "sure", "maybe", "" classified as AMBIGUOUS (not CONFIRM)
