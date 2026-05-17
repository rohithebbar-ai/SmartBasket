# Implement tests in Week 1 (Days 4–5) alongside Kafka producers/consumers.
#
# Test coverage targets:
#   - product.viewed payload: contains event_type, product_id, user_id, session_id, source, timestamp
#   - price.updated payload: contains old_price, new_price, change_percentage, reason
#   - Demand signal flow: product.viewed → Redis INCR views:{product_id}
#   - Price update consumer: price.updated → active cart totals recalculated
#   - No PII in plaintext payloads (email, full name never in event body)
