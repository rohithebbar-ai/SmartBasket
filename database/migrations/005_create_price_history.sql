-- Migration 005: price_history table
-- Append-only audit trail. Every pricing engine cycle that changes a price
-- writes a row here. Used by NL-to-SQL ("which products had most price changes?")
-- and by the agent's get_price_history tool (Section 19.4).

CREATE TABLE IF NOT EXISTS price_history (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id          UUID         NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    old_price           DECIMAL(12,2) NOT NULL,
    new_price           DECIMAL(12,2) NOT NULL,
    change_percentage   FLOAT        NOT NULL,
    reason              VARCHAR      NOT NULL,  -- high_demand | low_stock_high_demand | high_abandonment | low_demand_high_stock
    changed_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_price_history_product_id ON price_history (product_id);
CREATE INDEX IF NOT EXISTS idx_price_history_changed_at ON price_history (changed_at DESC);
