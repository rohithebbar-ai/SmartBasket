-- TODO: user-item interaction matrix for ALS recommender
-- Tracks product views, cart adds, purchases per user for collaborative filtering
CREATE TABLE IF NOT EXISTS user_item_interactions (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id  UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    event_type  VARCHAR(20) NOT NULL,  -- 'view' | 'cart_add' | 'purchase'
    weight      FLOAT NOT NULL DEFAULT 1.0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_uii_user_id   ON user_item_interactions (user_id);
CREATE INDEX idx_uii_product_id ON user_item_interactions (product_id);
