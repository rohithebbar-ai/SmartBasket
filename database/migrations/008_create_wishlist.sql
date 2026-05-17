-- Migration 008: wishlist table
-- Used by Phase 1 MCP tool calling (Section 19.4):
--   add_to_wishlist, get_wishlist, move_wishlist_to_cart, notify_when_in_stock
-- The agent proactively offers to save to wishlist when a user says "maybe later".
-- UNIQUE(user_id, product_id) prevents duplicate wishlist entries.

CREATE TABLE IF NOT EXISTS wishlist (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID         NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    product_id  UUID         NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT  wishlist_user_product_unique UNIQUE (user_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_wishlist_user_id    ON wishlist (user_id);
CREATE INDEX IF NOT EXISTS idx_wishlist_product_id ON wishlist (product_id);
