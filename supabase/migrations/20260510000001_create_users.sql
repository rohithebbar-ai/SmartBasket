-- 001: users
-- Owned by app/auth/models.py for ORM querying.
-- role is enforced by CHECK; the app layer uses the UserRole enum on top of this.

CREATE TABLE IF NOT EXISTS users (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email            VARCHAR     NOT NULL UNIQUE,
    hashed_password  VARCHAR     NOT NULL,
    role             VARCHAR     NOT NULL DEFAULT 'customer'
                                 CHECK (role IN ('customer', 'admin')),
    is_active        BOOLEAN     NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
