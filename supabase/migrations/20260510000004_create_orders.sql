-- 004: orders
-- Cart state is ephemeral and lives in Redis (key: cart:{user_id}, TTL 7 days).
-- An order row is created when the agent's place_order tool executes checkout.
-- items JSONB structure (validated in app/orders/schemas.py, not here):
--   [{"product_id": "<uuid>", "name": "...", "price_at_order": 1299.99, "qty": 1}]
-- price_at_order is a snapshot — never recalculated after the order is placed.

CREATE TABLE IF NOT EXISTS orders (
    id            UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID          NOT NULL REFERENCES users (id),
    items         JSONB         NOT NULL DEFAULT '[]',
    total_amount  DECIMAL(12,2) NOT NULL CHECK (total_amount >= 0),
    status        VARCHAR       NOT NULL DEFAULT 'pending'
                                CHECK (status IN (
                                    'pending', 'confirmed', 'shipped',
                                    'delivered', 'cancelled', 'refunded'
                                )),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_orders_user_id  ON orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_created  ON orders (created_at DESC);
