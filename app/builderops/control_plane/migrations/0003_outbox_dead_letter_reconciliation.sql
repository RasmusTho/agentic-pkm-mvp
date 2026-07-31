ALTER TABLE builderops_outbox_reconciliations
    DROP CONSTRAINT IF EXISTS builderops_outbox_reconciliations_status_check;

ALTER TABLE builderops_outbox_reconciliations
    ADD CONSTRAINT builderops_outbox_reconciliations_status_check
    CHECK (status IN ('pending', 'succeeded', 'dead_letter'));
