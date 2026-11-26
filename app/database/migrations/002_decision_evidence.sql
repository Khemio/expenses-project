-- Add audit evidence to future decisions without fabricating historical values.
-- The columns are nullable so existing decisions remain valid and distinguishable.
ALTER TABLE decisions
    ADD COLUMN IF NOT EXISTS rule_version TEXT;

ALTER TABLE decisions
    ADD COLUMN IF NOT EXISTS evidence_snapshot JSONB;

COMMENT ON COLUMN decisions.rule_version IS
    'Version of the workflow rules that produced this decision. NULL on legacy rows.';

COMMENT ON COLUMN decisions.evidence_snapshot IS
    'Inputs and checks observed at decision time. NULL on legacy rows; does not capture the complete Neo4j path.';
