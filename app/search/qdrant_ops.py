# Qdrant operations — implement in Week 2 (Day 8):
#   upsert_product(product_id, embedding, payload)
#     payload keys: product_id, name, brand, category, price, avg_rating,
#                   stock_available, battery_sentiment, display_sentiment,
#                   build_quality_sentiment, value_sentiment, performance_sentiment,
#                   use_cases, key_specs
#
#   search(query_embedding, filters, limit) -> list[ScoredPoint]
#     filters: Qdrant Filter objects built from extracted price/brand/category constraints
#
# Collection: products | Dimensions: varies by provider | Distance: Cosine
