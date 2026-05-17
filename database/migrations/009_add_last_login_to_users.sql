-- Migration 009: add last_login to users
-- Tracks when a user last authenticated. NULL = never logged in since this migration.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;
