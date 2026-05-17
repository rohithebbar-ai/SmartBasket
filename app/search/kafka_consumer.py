# Kafka consumer — implement in Week 1 (Days 4–5, alongside orders module):
#   consume_product_viewed() — listens on product.viewed topic
#     On each event: INCR views:{product_id} in Redis (TTL: 24h)
#     This counter is the demand signal read by the pricing engine every 120s.
