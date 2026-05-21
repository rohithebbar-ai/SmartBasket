-- Migration 010: price_alerts table
-- Stores price-drop alerts set by the agent when a product is above the user's
-- acceptable price. The pricing engine triggers these when current_price drops
-- to or below target_price and the alert is still active.

CREATE TABLE IF NOT EXISTS price_alerts (
    id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id      UUID          NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    target_price    NUMERIC(10,2) NOT NULL,
    user_email      TEXT          NOT NULL,
    is_active       BOOLEAN       DEFAULT TRUE,
    triggered_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_price_alerts_product_active
    ON price_alerts(product_id, is_active);
