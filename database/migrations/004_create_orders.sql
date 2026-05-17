-- Migration 004: orders table
-- Cart state is ephemeral and lives in Redis (cart:{user_id}).
-- An order is created when the cart is checked out; price is snapshotted at that moment.
-- items JSONB: [{"product_id": "...", "name": "...", "price_at_order": 125000, "qty": 1}]

CREATE TABLE IF NOT EXISTS orders (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID         NOT NULL REFERENCES users (id),
    items          JSONB        NOT NULL DEFAULT '[]',
    total_amount   DECIMAL(12,2) NOT NULL,
    status         VARCHAR      NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'confirmed', 'shipped',
                                                  'delivered', 'cancelled', 'refunded')),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_orders_user_id   ON orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status    ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_created   ON orders (created_at DESC);
