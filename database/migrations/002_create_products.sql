-- Migration 002: products table
-- Source of truth for the product catalogue. Every other table references product IDs from here.
-- current_price is the live dynamic price; base_price is the floor for pricing rules.

CREATE TABLE IF NOT EXISTS products (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR      NOT NULL,
    brand           VARCHAR      NOT NULL,
    category        VARCHAR      NOT NULL,
    base_price      DECIMAL(12,2) NOT NULL,
    current_price   DECIMAL(12,2) NOT NULL,
    specs           JSONB        NOT NULL DEFAULT '{}',
    stock_count     INTEGER      NOT NULL DEFAULT 0,
    avg_rating      FLOAT        NOT NULL DEFAULT 0.0,
    is_active       BOOLEAN      NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_products_brand      ON products (brand);
CREATE INDEX IF NOT EXISTS idx_products_category   ON products (category);
CREATE INDEX IF NOT EXISTS idx_products_is_active  ON products (is_active);
CREATE INDEX IF NOT EXISTS idx_products_avg_rating ON products (avg_rating DESC);
