-- 003: reviews
-- Five aspect sentiment scores (1.0–5.0) are populated by the Bedrock batch
-- sentiment job (data/ingestion/run_sentiment.py), not by user input at write time.
-- They are NULL until the sentiment job runs; the app reads them as optional floats.

CREATE TABLE IF NOT EXISTS reviews (
    id                      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id              UUID          NOT NULL
                                          REFERENCES products (id) ON DELETE CASCADE,
    rating                  INTEGER       NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_text             TEXT,
    battery_sentiment       FLOAT         CHECK (battery_sentiment BETWEEN 1.0 AND 5.0),
    display_sentiment       FLOAT         CHECK (display_sentiment BETWEEN 1.0 AND 5.0),
    build_quality_sentiment FLOAT         CHECK (build_quality_sentiment BETWEEN 1.0 AND 5.0),
    value_sentiment         FLOAT         CHECK (value_sentiment BETWEEN 1.0 AND 5.0),
    performance_sentiment   FLOAT         CHECK (performance_sentiment BETWEEN 1.0 AND 5.0),
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reviews_product_id ON reviews (product_id);
-- Supports avg_rating back-fill query: SELECT AVG(rating) FROM reviews WHERE product_id = $1
CREATE INDEX IF NOT EXISTS idx_reviews_product_rating ON reviews (product_id, rating);
