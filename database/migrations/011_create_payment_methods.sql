-- Migration 011: payment_methods table
-- Stores tokenised payment methods (Stripe payment_method_id) per user.
-- Raw card numbers are never stored; only the Stripe token and masked display fields.
-- A user can have multiple methods; is_default = TRUE indicates the preferred one.

CREATE TABLE IF NOT EXISTS payment_methods (
    id                        UUID      PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                   UUID      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stripe_payment_method_id  TEXT      NOT NULL,
    card_type                 TEXT      NOT NULL,
    last4                     CHAR(4)   NOT NULL,
    expiry_month              INT       NOT NULL,
    expiry_year               INT       NOT NULL,
    is_default                BOOLEAN   DEFAULT FALSE,
    created_at                TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payment_methods_user
    ON payment_methods(user_id);
