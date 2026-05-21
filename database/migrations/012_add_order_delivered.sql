-- 012: order delivery tracking + order_reviews table
-- orders.status is VARCHAR with a CHECK constraint (not a native PG enum),
-- so no ALTER TYPE needed — 'delivered' is already in the constraint from migration 004.
--
-- delivered_at: timestamp written by deliver_order() in app/orders/service.py;
--   used by the post-purchase worker to trigger the 3-day review reminder.
--
-- order_reviews: written by submit_review MCP tool (real impl in Day 15);
--   one row per order (UNIQUE order_id enforced at DB level).

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_orders_delivered_at
    ON orders (delivered_at)
    WHERE delivered_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS order_reviews (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    UUID        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    user_id     UUID        NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    rating      INT         NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_text TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT order_reviews_order_unique UNIQUE (order_id)
);

CREATE INDEX IF NOT EXISTS idx_order_reviews_order_id ON order_reviews (order_id);
CREATE INDEX IF NOT EXISTS idx_order_reviews_user_id  ON order_reviews (user_id);
