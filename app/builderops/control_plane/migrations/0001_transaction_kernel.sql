CREATE TABLE IF NOT EXISTS builderops_schema_migrations (
    version integer PRIMARY KEY,
    name text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS builderops_authority_metadata (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    authority_epoch bigint NOT NULL CHECK (authority_epoch > 0),
    schema_version integer NOT NULL CHECK (schema_version > 0),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION builderops_valid_authority_envelope(
    envelope jsonb, expected_repository text
) RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT
        jsonb_typeof(envelope) = 'object'
        AND expected_repository ~ '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
        AND split_part(expected_repository, '/', 1) NOT IN ('.', '..')
        AND split_part(expected_repository, '/', 2) NOT IN ('.', '..')
        AND jsonb_typeof(envelope->'repository') = 'string'
        AND jsonb_typeof(envelope->'scope') = 'string'
        AND jsonb_typeof(envelope->'stack') = 'string'
        AND jsonb_typeof(envelope->'actor') = 'string'
        AND envelope->>'repository' = expected_repository
        AND COALESCE(envelope->>'scope', '') ~ '[^[:space:]]'
        AND COALESCE(envelope->>'stack', '') ~ '[^[:space:]]'
        AND COALESCE(envelope->>'actor', '') ~ '[^[:space:]]'
        AND CASE
            WHEN jsonb_typeof(envelope->'source_refs') = 'array'
            THEN jsonb_array_length(envelope->'source_refs') > 0
                AND NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(envelope->'source_refs') AS source_ref
                    WHERE jsonb_typeof(source_ref) <> 'string'
                        OR NOT COALESCE(source_ref #>> '{}', '') ~ '[^[:space:]]'
                )
            ELSE false
        END
        AND jsonb_typeof(envelope->'schema_version') = 'number'
        AND COALESCE((envelope->>'schema_version') ~ '^[1-9][0-9]*$', false)
$$;

CREATE TABLE IF NOT EXISTS builderops_tasks (
    repository text NOT NULL,
    task_id text NOT NULL,
    state text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    authority_envelope jsonb NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (repository, task_id),
    CHECK (repository <> '' AND task_id <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);

CREATE TABLE IF NOT EXISTS builderops_attempts (
    repository text NOT NULL, task_id text NOT NULL, attempt_id text NOT NULL,
    state text NOT NULL, payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    authority_envelope jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (repository, task_id, attempt_id),
    CHECK (repository <> '' AND task_id <> '' AND attempt_id <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);

CREATE TABLE IF NOT EXISTS builderops_records (
    repository text NOT NULL, record_id text NOT NULL, record_type text NOT NULL,
    state text NOT NULL, payload jsonb NOT NULL, authority_envelope jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (repository, record_id),
    CHECK (repository <> '' AND record_id <> '' AND record_type <> '' AND state <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);

CREATE TABLE IF NOT EXISTS builderops_transitions (
    transition_sequence bigserial PRIMARY KEY, repository text NOT NULL, task_id text NOT NULL,
    from_state text, to_state text NOT NULL, authority_envelope jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (repository <> '' AND task_id <> '' AND to_state <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);

CREATE TABLE IF NOT EXISTS builderops_promotions (
    repository text NOT NULL, promotion_id text NOT NULL, status text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb, authority_envelope jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (repository, promotion_id),
    CHECK (repository <> '' AND promotion_id <> '' AND status <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);

CREATE SEQUENCE IF NOT EXISTS builderops_receipt_sequence;

CREATE TABLE IF NOT EXISTS builderops_receipts (
    receipt_sequence bigint PRIMARY KEY DEFAULT nextval('builderops_receipt_sequence'),
    repository text NOT NULL,
    task_id text NOT NULL,
    event_type text NOT NULL,
    idempotency_key text NOT NULL,
    lease_holder text,
    lease_fencing_token bigint CHECK (lease_fencing_token IS NULL OR lease_fencing_token > 0),
    authority_envelope jsonb NOT NULL,
    recovery_lsn pg_lsn,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (repository <> '' AND task_id <> '' AND idempotency_key <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);

CREATE TABLE IF NOT EXISTS builderops_idempotency (
    repository text NOT NULL,
    idempotency_key text NOT NULL,
    request_hash text NOT NULL,
    result jsonb,
    recovery_lsn pg_lsn,
    authority_envelope jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (repository, idempotency_key),
    CHECK (repository <> '' AND idempotency_key <> '' AND request_hash <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);

CREATE TABLE IF NOT EXISTS builderops_leases (
    repository text NOT NULL,
    resource_id text NOT NULL,
    holder text NOT NULL,
    fencing_token bigint NOT NULL CHECK (fencing_token > 0),
    expires_at timestamptz NOT NULL,
    authority_envelope jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (repository, resource_id),
    CHECK (repository <> '' AND resource_id <> '' AND holder <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);

CREATE TABLE IF NOT EXISTS builderops_outbox (
    repository text NOT NULL,
    operation_key text NOT NULL,
    task_id text NOT NULL,
    effect_type text NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','claimed','unknown','succeeded','dead_letter')),
    intent_receipt_sequence bigint NOT NULL,
    intent_lsn pg_lsn,
    worker_id text,
    claim_fencing_token bigint NOT NULL DEFAULT 0,
    claim_expires_at timestamptz,
    claim_lsn pg_lsn,
    claim_receipt_sequence bigint,
    unknown_detail text,
    reconciliation_evidence jsonb,
    reconciliation_receipt_sequence bigint,
    reconciliation_lsn pg_lsn,
    authority_envelope jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (repository, operation_key),
    CHECK (repository <> '' AND operation_key <> '' AND task_id <> '' AND effect_type <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);

CREATE INDEX IF NOT EXISTS builderops_outbox_pending_idx
    ON builderops_outbox (status, updated_at)
    WHERE status IN ('pending', 'claimed');

CREATE TABLE IF NOT EXISTS builderops_outbox_reconciliations (
    repository text NOT NULL,
    operation_key text NOT NULL,
    claim_fencing_token bigint NOT NULL CHECK (claim_fencing_token > 0),
    task_id text NOT NULL,
    worker_id text NOT NULL,
    claim_receipt_sequence bigint NOT NULL,
    claim_lsn pg_lsn NOT NULL,
    observed_applied boolean NOT NULL,
    evidence jsonb NOT NULL,
    request_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending','succeeded')),
    receipt_sequence bigint NOT NULL,
    recovery_lsn pg_lsn,
    authority_envelope jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (repository, operation_key, claim_fencing_token),
    CHECK (repository <> '' AND operation_key <> '' AND task_id <> '' AND worker_id <> ''),
    CHECK (request_hash <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);

CREATE TABLE IF NOT EXISTS builderops_dead_letters (
    repository text NOT NULL, operation_key text NOT NULL, outcome jsonb NOT NULL,
    authority_envelope jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (repository, operation_key),
    CHECK (repository <> '' AND operation_key <> ''),
    CHECK (builderops_valid_authority_envelope(authority_envelope, repository))
);
