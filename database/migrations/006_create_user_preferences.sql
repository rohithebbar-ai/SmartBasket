-- Migration 006: user_preferences table
-- Written exclusively by the personalisation worker (workers/personalisation_worker.py).
-- Read by the agent module to personalise search results.
-- Never updated directly by the user — one row per user, upserted by the worker.

CREATE TABLE IF NOT EXISTS user_preferences (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID         NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
    preferred_brands      JSONB        NOT NULL DEFAULT '[]',
    preferred_categories  JSONB        NOT NULL DEFAULT '[]',
    typical_price_min     DECIMAL(12,2),
    typical_price_max     DECIMAL(12,2),
    feature_priorities    JSONB        NOT NULL DEFAULT '{}',
    last_updated          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences (user_id);
