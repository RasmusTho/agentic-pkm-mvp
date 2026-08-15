-- Dormant #4898 substrate; existing legacy consumers retain authority.
ALTER TABLE builderops_outbox
    ADD COLUMN IF NOT EXISTS post_effect_phase text,
    ADD COLUMN IF NOT EXISTS post_effect_fencing_token bigint,
    ADD COLUMN IF NOT EXISTS post_effect_intent_lsn pg_lsn,
    ADD COLUMN IF NOT EXISTS post_effect_claim_lsn pg_lsn,
    ADD COLUMN IF NOT EXISTS post_effect_claim_receipt_sequence bigint,
    ADD COLUMN IF NOT EXISTS post_effect_receipt_sequence bigint,
    ADD COLUMN IF NOT EXISTS post_effect_recovery_lsn pg_lsn,
    ADD COLUMN IF NOT EXISTS post_effect_evidence jsonb,
    ADD COLUMN IF NOT EXISTS post_effect_observed_applied boolean,
    ADD COLUMN IF NOT EXISTS post_effect_terminal_unknown boolean;

ALTER TABLE builderops_outbox
    DROP CONSTRAINT IF EXISTS builderops_outbox_post_effect_phase_check;
ALTER TABLE builderops_outbox
    ADD CONSTRAINT builderops_outbox_post_effect_phase_check
    CHECK (post_effect_phase IS NULL OR post_effect_phase IN ('pending', 'reconciled'));
