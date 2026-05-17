-- 008: wishlist
-- Used by Phase 1 MCP tool calling (platform plan Section 19.4):
--   add_to_wishlist      → INSERT ON CONFLICT DO NOTHING
--   get_wishlist         → SELECT with product JOIN
--   move_wishlist_to_cart → copy items to Redis cart, DELETE from wishlist
--   notify_when_in_stock → read wishlist when stock_count goes from 0 → positive
-- The agent proactively offers to save to wishlist when intent is PURCHASE_INTENT
-- but the user says "maybe later" or "save for later".
-- UNIQUE(user_id, product_id) prevents duplicate entries at the DB level.

CREATE TABLE IF NOT EXISTS wishlist (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    product_id UUID        NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT wishlist_user_product_unique UNIQUE (user_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_wishlist_user_id    ON wishlist (user_id);
CREATE INDEX IF NOT EXISTS idx_wishlist_product_id ON wishlist (product_id);
