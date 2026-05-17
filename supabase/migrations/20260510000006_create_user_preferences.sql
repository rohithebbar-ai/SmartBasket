-- 006: user_preferences
-- Written exclusively by the personalisation worker (workers/personalisation_consumer.py).
-- Read by app/agent/nodes/personalise.py to re-rank search results.
-- One row per user, upserted by the worker on each kafka event batch.
-- Never written directly by user-facing API routes.
-- feature_priorities JSONB: {"battery_life": 0.9, "display": 0.7, "performance": 0.8}

CREATE TABLE IF NOT EXISTS user_preferences (
    id                   UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID          NOT NULL UNIQUE
                                       REFERENCES users (id) ON DELETE CASCADE,
    preferred_brands     JSONB         NOT NULL DEFAULT '[]',
    preferred_categories JSONB         NOT NULL DEFAULT '[]',
    typical_price_min    DECIMAL(12,2) CHECK (typical_price_min >= 0),
    typical_price_max    DECIMAL(12,2) CHECK (typical_price_max >= 0),
    feature_priorities   JSONB         NOT NULL DEFAULT '{}',
    last_updated         TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences (user_id);
