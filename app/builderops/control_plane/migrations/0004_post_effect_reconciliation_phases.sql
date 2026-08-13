ALTER TABLE builderops_outbox
    ADD COLUMN IF NOT EXISTS post_effect_phase text,
    ADD COLUMN IF NOT EXISTS post_effect_identity jsonb,
    ADD COLUMN IF NOT EXISTS post_effect_readback jsonb,
    ADD COLUMN IF NOT EXISTS post_effect_pending_receipt_sequence bigint,
    ADD COLUMN IF NOT EXISTS post_effect_reconciled_receipt_sequence bigint;

ALTER TABLE builderops_outbox
    DROP CONSTRAINT IF EXISTS builderops_outbox_post_effect_phase_check;

ALTER TABLE builderops_outbox
    ADD CONSTRAINT builderops_outbox_post_effect_phase_check CHECK (
        (post_effect_phase IS NULL
            AND post_effect_identity IS NULL
            AND post_effect_readback IS NULL
            AND post_effect_pending_receipt_sequence IS NULL
            AND post_effect_reconciled_receipt_sequence IS NULL)
        OR
        (post_effect_phase = 'pending'
            AND jsonb_typeof(post_effect_identity) = 'object'
            AND post_effect_identity = jsonb_build_object(
                'operation_key', post_effect_identity->'operation_key',
                'fencing_token', post_effect_identity->'fencing_token',
                'repository', post_effect_identity->'repository',
                'task_id', post_effect_identity->'task_id',
                'pr_number', post_effect_identity->'pr_number',
                'head_sha', post_effect_identity->'head_sha')
            AND jsonb_typeof(post_effect_identity->'operation_key') = 'string'
            AND jsonb_typeof(post_effect_identity->'fencing_token') = 'number'
            AND (post_effect_identity->>'fencing_token')::bigint > 0
            AND jsonb_typeof(post_effect_identity->'repository') = 'string'
            AND jsonb_typeof(post_effect_identity->'task_id') = 'string'
            AND jsonb_typeof(post_effect_identity->'pr_number') = 'number'
            AND (post_effect_identity->>'pr_number')::bigint > 0
            AND jsonb_typeof(post_effect_identity->'head_sha') = 'string'
            AND post_effect_identity->>'head_sha' ~ '^[0-9a-f]{40}$'
            AND post_effect_readback IS NULL
            AND post_effect_pending_receipt_sequence IS NOT NULL
            AND post_effect_pending_receipt_sequence > 0
            AND post_effect_reconciled_receipt_sequence IS NULL)
        OR
        (post_effect_phase = 'reconciled'
            AND jsonb_typeof(post_effect_identity) = 'object'
            AND post_effect_identity = jsonb_build_object(
                'operation_key', post_effect_identity->'operation_key',
                'fencing_token', post_effect_identity->'fencing_token',
                'repository', post_effect_identity->'repository',
                'task_id', post_effect_identity->'task_id',
                'pr_number', post_effect_identity->'pr_number',
                'head_sha', post_effect_identity->'head_sha')
            AND jsonb_typeof(post_effect_identity->'operation_key') = 'string'
            AND jsonb_typeof(post_effect_identity->'fencing_token') = 'number'
            AND (post_effect_identity->>'fencing_token')::bigint > 0
            AND jsonb_typeof(post_effect_identity->'repository') = 'string'
            AND jsonb_typeof(post_effect_identity->'task_id') = 'string'
            AND jsonb_typeof(post_effect_identity->'pr_number') = 'number'
            AND (post_effect_identity->>'pr_number')::bigint > 0
            AND jsonb_typeof(post_effect_identity->'head_sha') = 'string'
            AND post_effect_identity->>'head_sha' ~ '^[0-9a-f]{40}$'
            AND jsonb_typeof(post_effect_readback) = 'object'
            AND jsonb_typeof(post_effect_readback->'merged') = 'boolean'
            AND post_effect_readback->>'head_sha' = post_effect_identity->>'head_sha'
            AND post_effect_pending_receipt_sequence IS NOT NULL
            AND post_effect_pending_receipt_sequence > 0
            AND post_effect_reconciled_receipt_sequence IS NOT NULL
            AND post_effect_reconciled_receipt_sequence > post_effect_pending_receipt_sequence)
    );
