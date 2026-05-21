-- 011: payment_methods table
-- Stores tokenised Stripe payment methods per user.
-- Raw card numbers are never stored — only the Stripe token and masked display fields.
-- stripe_payment_method_id is the pm_... token from Stripe; never exposed via API.

CREATE TABLE IF NOT EXISTS payment_methods (
    id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                   UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stripe_payment_method_id  TEXT        NOT NULL,
    card_type                 TEXT        NOT NULL,
    last4                     CHAR(4)     NOT NULL,
    expiry_month              INT         NOT NULL,
    expiry_year               INT         NOT NULL,
    is_default                BOOLEAN     DEFAULT FALSE,
    created_at                TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payment_methods_user
    ON payment_methods(user_id);

-- ── Test seed — one saved card for development ────────────────────────────────
-- Insert a Visa test card for the first user (or whichever user you're testing with).
-- Stripe test token pm_card_visa always succeeds in test mode.
-- Remove or replace this block before production.
INSERT INTO payment_methods
    (user_id, stripe_payment_method_id, card_type, last4, expiry_month, expiry_year, is_default)
SELECT
    id,
    'pm_card_visa',
    'visa',
    '4242',
    12,
    27,
    TRUE
FROM users
ORDER BY created_at ASC
LIMIT 1
ON CONFLICT DO NOTHING;
