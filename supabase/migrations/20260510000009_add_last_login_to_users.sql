-- 009: add last_login to users
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;
