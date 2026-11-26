-- Older vector records have no recorded source version; do not infer one.
ALTER TABLE vector_documents
    ADD COLUMN IF NOT EXISTS source_version INTEGER
    CHECK (source_version IS NULL OR source_version >= 1);

COMMENT ON COLUMN vector_documents.source_version IS
    'Version of the authoritative source used to compute this embedding; NULL for legacy or unversioned documents.';
