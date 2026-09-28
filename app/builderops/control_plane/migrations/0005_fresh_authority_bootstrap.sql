-- Keep the checksum history intact. Both fresh and upgraded databases must
-- obtain authenticated authority readback before any writer can resume.
ALTER TABLE builderops_recovery_state
    ADD COLUMN bootstrap_id uuid NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN bootstrap_status text NOT NULL DEFAULT 'unknown'
        CHECK (bootstrap_status IN ('unknown', 'conflict', 'converged')),
    ADD COLUMN bootstrap_config jsonb,
    ADD COLUMN bootstrap_readback jsonb,
    ADD COLUMN bootstrap_receipt jsonb,
    ADD COLUMN bootstrap_reason text NOT NULL DEFAULT 'authority_readback_required';

ALTER TABLE builderops_recovery_state
    ALTER COLUMN reconciliation_required SET DEFAULT true,
    ALTER COLUMN executor_enabled SET DEFAULT false;
UPDATE builderops_recovery_state
    SET reconciliation_required = true, executor_enabled = false, reconciled_at = NULL;
UPDATE builderops_leases
    SET holder = 'bootstrap-fence', fencing_token = fencing_token + 1,
        expires_at = clock_timestamp(), updated_at = clock_timestamp();
UPDATE builderops_outbox
    SET status = 'unknown', unknown_detail = 'bootstrap requires authoritative effect readback',
        claim_expires_at = NULL, updated_at = clock_timestamp()
    WHERE status IN ('pending', 'claimed');

-- Reuse the existing integer epoch protocol. The UUID-derived fresh generation
-- is distinct from the legacy floor and fits losslessly in JSON/JS integers.
UPDATE builderops_recovery_state
SET activated_authority_epoch = GREATEST(activated_authority_epoch + 1,
    COALESCE((SELECT authority_epoch + 1 FROM builderops_authority_metadata WHERE singleton), 2),
    ('x' || substr(replace(bootstrap_id::text, '-', ''), 1, 13))::bit(52)::bigint + 2);
UPDATE builderops_authority_metadata
SET authority_epoch = (SELECT activated_authority_epoch FROM builderops_recovery_state WHERE singleton);

-- Old binaries do not establish the new transaction admission and cannot write
-- through this migration's fence, even after a new process has converged.
CREATE FUNCTION builderops_authority_write_fence() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE authority builderops_recovery_state%ROWTYPE;
BEGIN
    SELECT * INTO authority FROM builderops_recovery_state WHERE singleton FOR SHARE;
    IF authority.singleton IS NULL OR
       current_setting('builderops.authority_epoch', true) IS DISTINCT FROM authority.activated_authority_epoch::text THEN
        RAISE EXCEPTION 'BuilderOps authority epoch admission required' USING ERRCODE = '55000';
    END IF;
    IF current_setting('builderops.reconciliation', true) = 'on' AND
       TG_TABLE_NAME IN ('builderops_outbox', 'builderops_receipts',
                        'builderops_outbox_reconciliations', 'builderops_dead_letters', 'builderops_idempotency',
                        'builderops_leases') THEN
        IF TG_TABLE_NAME = 'builderops_leases' AND
           (TG_OP <> 'UPDATE' OR to_jsonb(NEW)->>'holder' <> 'recovery-fence' OR
            (to_jsonb(NEW)->>'expires_at')::timestamptz > clock_timestamp() OR
            (to_jsonb(NEW)->>'fencing_token')::bigint <= (to_jsonb(OLD)->>'fencing_token')::bigint) THEN
            RAISE EXCEPTION 'Recovery may only retire an existing lease' USING ERRCODE = '55000';
        END IF;
        IF TG_TABLE_NAME = 'builderops_idempotency' AND TG_OP <> 'UPDATE' THEN
            RAISE EXCEPTION 'Reconciliation cannot invent idempotency history' USING ERRCODE = '55000';
        END IF;
        IF TG_TABLE_NAME = 'builderops_outbox' AND
           (TG_OP <> 'UPDATE' OR (to_jsonb(NEW)->>'status' = 'claimed' AND
                                  to_jsonb(OLD)->>'status' IS DISTINCT FROM 'claimed')) THEN
            RAISE EXCEPTION 'Reconciliation cannot create or execute an effect' USING ERRCODE = '55000';
        END IF;
    ELSIF NOT authority.executor_enabled OR authority.reconciliation_required OR
          authority.bootstrap_status <> 'converged' OR authority.bootstrap_receipt IS NULL OR
          authority.bootstrap_receipt->>'bootstrap_id' IS DISTINCT FROM authority.bootstrap_id::text OR
          authority.bootstrap_receipt->>'authority_epoch' IS DISTINCT FROM authority.activated_authority_epoch::text THEN
        RAISE EXCEPTION 'BuilderOps writers fenced pending authority readback' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

DO $$ DECLARE relation_name text;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'builderops_tasks', 'builderops_attempts', 'builderops_records',
        'builderops_transitions', 'builderops_promotions', 'builderops_receipts',
        'builderops_idempotency', 'builderops_leases', 'builderops_outbox',
        'builderops_outbox_reconciliations', 'builderops_dead_letters'
    ] LOOP
        EXECUTE format('CREATE TRIGGER builderops_authority_fence BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION builderops_authority_write_fence()', relation_name);
    END LOOP;
END $$;
