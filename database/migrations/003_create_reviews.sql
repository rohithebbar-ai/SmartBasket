-- Migration 003: reviews table
-- Five aspect sentiment floats (1.0–5.0) are populated by the Bedrock batch
-- sentiment job (data/ingestion/run_sentiment.py), not by user input.

CREATE TABLE IF NOT EXISTS reviews (
    id                       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id               UUID         NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    rating                   INTEGER      NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_text              TEXT,
    battery_sentiment        FLOAT,
    display_sentiment        FLOAT,
    build_quality_sentiment  FLOAT,
    value_sentiment          FLOAT,
    performance_sentiment    FLOAT,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reviews_product_id ON reviews (product_id);
