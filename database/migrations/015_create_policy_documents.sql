-- TODO: Policy document metadata store (chunks stored in Qdrant, not here)
CREATE TABLE IF NOT EXISTS policy_documents (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        VARCHAR(255) NOT NULL,
    filename     VARCHAR(255) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    chunk_count  INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
