-- 007: nl_sql_audit
-- Every NL-to-SQL attempt is logged here regardless of success or failure.
-- Retries for a single user question each get their own row (retry_count increments).
-- After ~500 rows this becomes fine-tuning training data for a ShopSense-specific
-- NL-to-SQL model (platform plan Section 17.3).
-- source distinguishes where the query originated:
--   customer → /api/search endpoint
--   admin    → /api/analytics endpoint (require_admin)
--   agent    → LangGraph nl_to_sql_search node

CREATE TABLE IF NOT EXISTS nl_sql_audit (
    id                     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    natural_language_query TEXT        NOT NULL,
    generated_sql          TEXT        NOT NULL,
    rows_returned          INTEGER,
    validation_passed      BOOLEAN     NOT NULL DEFAULT false,
    retry_count            INTEGER     NOT NULL DEFAULT 0 CHECK (retry_count BETWEEN 0 AND 2),
    source                 VARCHAR     NOT NULL DEFAULT 'customer'
                                       CHECK (source IN ('customer', 'admin', 'agent')),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nl_sql_audit_source     ON nl_sql_audit (source);
CREATE INDEX IF NOT EXISTS idx_nl_sql_audit_created_at ON nl_sql_audit (created_at DESC);
-- Supports validation failure analysis: WHERE validation_passed = false
CREATE INDEX IF NOT EXISTS idx_nl_sql_audit_failed
    ON nl_sql_audit (created_at DESC)
    WHERE validation_passed = false;
