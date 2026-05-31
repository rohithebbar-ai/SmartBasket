-- Migration 017: add fashion-domain columns to products table
-- Required for H&M data ingestion (Day 18).
-- Adds external_product_id for upsert keying, fashion sentiment dimensions,
-- image_url, attributes JSONB, embedding_status, and ingestion tracking.

-- Upsert key — H&M article_id stored here; ON CONFLICT (external_product_id) DO UPDATE
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS external_product_id  VARCHAR UNIQUE,
    ADD COLUMN IF NOT EXISTS description          TEXT,
    ADD COLUMN IF NOT EXISTS image_url            TEXT,
    ADD COLUMN IF NOT EXISTS attributes           JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS embedding_status     VARCHAR NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS last_ingested_at     TIMESTAMPTZ;

-- Fashion sentiment dimensions (replace electronics-specific ones for fashion products)
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS style_sentiment        FLOAT,
    ADD COLUMN IF NOT EXISTS quality_sentiment      FLOAT,
    ADD COLUMN IF NOT EXISTS fit_sentiment          FLOAT,
    ADD COLUMN IF NOT EXISTS comfort_sentiment      FLOAT,
    ADD COLUMN IF NOT EXISTS versatility_sentiment  FLOAT,
    ADD COLUMN IF NOT EXISTS delivery_sentiment     FLOAT;

-- Indexes for ETL and search
CREATE INDEX IF NOT EXISTS idx_products_external_id      ON products (external_product_id);
CREATE INDEX IF NOT EXISTS idx_products_embedding_status ON products (embedding_status);
CREATE INDEX IF NOT EXISTS idx_products_attributes       ON products USING gin (attributes);
