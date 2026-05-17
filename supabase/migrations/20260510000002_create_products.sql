-- 002: products
-- Source of truth for the catalogue. Every other table FKs to this one.
-- current_price is the live dynamic price managed by the pricing engine.
-- base_price is the pricing floor: current_price must never go below
--   base_price * 0.80 (settings.pricing_min_multiplier).
-- specs JSONB stores processor, ram_gb, storage_gb, display_*, gpu, use_cases, etc.
--   Shape is validated by the ingestion pipeline, not by the DB.

CREATE TABLE IF NOT EXISTS products (
    id             UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    name           VARCHAR       NOT NULL,
    brand          VARCHAR       NOT NULL,
    category       VARCHAR       NOT NULL,
    base_price     DECIMAL(12,2) NOT NULL CHECK (base_price > 0),
    current_price  DECIMAL(12,2) NOT NULL CHECK (current_price > 0),
    specs          JSONB         NOT NULL DEFAULT '{}',
    stock_count    INTEGER       NOT NULL DEFAULT 0 CHECK (stock_count >= 0),
    avg_rating     FLOAT         NOT NULL DEFAULT 0.0
                                 CHECK (avg_rating >= 0.0 AND avg_rating <= 5.0),
    is_active      BOOLEAN       NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- Equality lookups used by NL-to-SQL filters and analytics queries
CREATE INDEX IF NOT EXISTS idx_products_brand     ON products (brand);
CREATE INDEX IF NOT EXISTS idx_products_category  ON products (category);

-- The pricing engine and search endpoint always filter on is_active = true.
-- Partial index eliminates inactive products from all these scans.
CREATE INDEX IF NOT EXISTS idx_products_active_rating
    ON products (avg_rating DESC)
    WHERE is_active = true;

-- GIN index enables fast JSONB containment queries on specs fields:
--   WHERE specs @> '{"brand": "Dell"}' or specs->>'processor' = '...'
CREATE INDEX IF NOT EXISTS idx_products_specs_gin ON products USING GIN (specs);
