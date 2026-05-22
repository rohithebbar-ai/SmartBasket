-- Migration 013: add sentiment columns to products table
-- run_sentiment.py (data/ingestion) writes these after Bedrock Haiku batch scoring.
-- All floats are nullable — products are unscored until the pipeline runs.

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS battery_sentiment        FLOAT,
    ADD COLUMN IF NOT EXISTS display_sentiment        FLOAT,
    ADD COLUMN IF NOT EXISTS build_quality_sentiment  FLOAT,
    ADD COLUMN IF NOT EXISTS value_sentiment          FLOAT,
    ADD COLUMN IF NOT EXISTS performance_sentiment    FLOAT,
    ADD COLUMN IF NOT EXISTS keyboard_sentiment       FLOAT,
    ADD COLUMN IF NOT EXISTS thermal_sentiment        FLOAT,
    ADD COLUMN IF NOT EXISTS top_complaint            TEXT,
    ADD COLUMN IF NOT EXISTS top_praise               TEXT,
    ADD COLUMN IF NOT EXISTS sentiment_scored_at      TIMESTAMPTZ;
