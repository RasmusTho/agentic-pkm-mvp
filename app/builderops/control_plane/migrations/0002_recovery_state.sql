CREATE TABLE IF NOT EXISTS builderops_recovery_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    activated_authority_epoch bigint NOT NULL CHECK (activated_authority_epoch > 0),
    recovery_id text,
    restored_lsn pg_lsn,
    reconciliation_required boolean NOT NULL DEFAULT false,
    executor_enabled boolean NOT NULL DEFAULT true,
    activated_at timestamptz,
    reconciled_at timestamptz,
    CHECK (NOT executor_enabled OR NOT reconciliation_required),
    CHECK (recovery_id IS NULL OR recovery_id <> '')
);

-- Fresh databases run all migration files before initialize() writes the
-- authority-metadata singleton. Seed the bootstrap floor directly; a restored
-- database keeps its existing row and activate_recovered_epoch advances it.
INSERT INTO builderops_recovery_state(singleton, activated_authority_epoch)
VALUES (true, 1)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS builderops_service_heartbeats (
    service_name text PRIMARY KEY,
    state text NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (service_name <> '' AND state <> '')
);
