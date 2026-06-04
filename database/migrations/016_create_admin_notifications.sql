-- TODO: Admin notification queue (restock predictions, catalogue gaps)
CREATE TABLE IF NOT EXISTS admin_notifications (
    id           BIGSERIAL PRIMARY KEY,
    type         VARCHAR(50) NOT NULL,  -- 'restock' | 'catalogue_gap' | 'price_alert'
    title        VARCHAR(255) NOT NULL,
    body         TEXT NOT NULL,
    product_id   UUID REFERENCES products(id) ON DELETE SET NULL,
    is_read      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_admin_notif_unread ON admin_notifications (is_read, created_at DESC);
