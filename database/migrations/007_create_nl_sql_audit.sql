-- Migration 007: nl_sql_audit table
-- Logs every NL-to-SQL query regardless of success or failure.
-- After 500+ rows this table becomes training data for a fine-tuned NL-to-SQL
-- model specific to the ShopSense schema (Section 17.3 of platform plan).
-- source distinguishes customer chat, admin dashboard, and agent-internal calls.

CREATE TABLE IF NOT EXISTS nl_sql_audit (
    id                       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    natural_language_query   TEXT         NOT NULL,
    generated_sql            TEXT         NOT NULL,
    rows_returned            INTEGER,
    validation_passed        BOOLEAN      NOT NULL DEFAULT false,
    retry_count              INTEGER      NOT NULL DEFAULT 0,
    source                   VARCHAR      NOT NULL DEFAULT 'customer'
                                          CHECK (source IN ('customer', 'admin', 'agent')),
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nl_sql_audit_source     ON nl_sql_audit (source);
CREATE INDEX IF NOT EXISTS idx_nl_sql_audit_created_at ON nl_sql_audit (created_at DESC);
-- Partial index for failed validations — used to surface bad SQL patterns during review.
CREATE INDEX IF NOT EXISTS idx_nl_sql_audit_failed     ON nl_sql_audit (created_at DESC) WHERE validation_passed = false;
