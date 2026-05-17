-- 005: price_history
-- Append-only audit trail written by the pricing engine every 120s cycle.
-- Each row records the before/after prices and the demand signal that triggered it.
-- Used by NL-to-SQL ("which products had the most price changes this week?")
-- and the agent's get_price_history tool (Section 19.4 of the platform plan).
-- Never UPDATE or DELETE rows — append only.

CREATE TABLE IF NOT EXISTS price_history (
    id                UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id        UUID          NOT NULL
                                    REFERENCES products (id) ON DELETE CASCADE,
    old_price         DECIMAL(12,2) NOT NULL CHECK (old_price > 0),
    new_price         DECIMAL(12,2) NOT NULL CHECK (new_price > 0),
    change_percentage FLOAT         NOT NULL,
    reason            VARCHAR       NOT NULL
                                    CHECK (reason IN (
                                        'high_demand',
                                        'low_stock_high_demand',
                                        'high_abandonment',
                                        'low_demand_high_stock'
                                    )),
    changed_at        TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_price_history_product_id ON price_history (product_id);
CREATE INDEX IF NOT EXISTS idx_price_history_changed_at ON price_history (changed_at DESC);
-- Supports "most price changes in the last N days" NL-to-SQL pattern
CREATE INDEX IF NOT EXISTS idx_price_history_product_changed
    ON price_history (product_id, changed_at DESC);
