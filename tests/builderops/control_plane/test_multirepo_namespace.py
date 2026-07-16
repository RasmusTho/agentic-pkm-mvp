from __future__ import annotations

from dataclasses import replace

import pytest
import psycopg
from psycopg.types.json import Jsonb

from app.builderops.control_plane import AuthorityEnvelope, EnvelopeValidationError

pytestmark = pytest.mark.pg


def test_authority_envelope_is_required_and_repo_namespaces_are_isolated(
    control_plane_store, envelope
) -> None:
    with pytest.raises(EnvelopeValidationError):
        AuthorityEnvelope(
            repository="",
            scope="issue:1",
            stack="builderops",
            actor="agent:a",
            source_refs=("issue:1",),
        )

    repo_b = replace(envelope, repository="example/second-repo")
    first = control_plane_store.commit_transition(
        envelope=envelope,
        task_id="same-id",
        to_state="ready",
        idempotency_key="same-key",
        request={"command": "create"},
        outbox={"effect_type": "github.comment", "payload": {}},
    )
    second = control_plane_store.commit_transition(
        envelope=repo_b,
        task_id="same-id",
        to_state="ready",
        idempotency_key="same-key",
        request={"command": "create"},
        outbox={"effect_type": "github.comment", "payload": {}},
    )
    assert first.operation_key != second.operation_key
    lease_a = control_plane_store.claim_lease(envelope=envelope, resource_id="same-id", holder="a")
    lease_b = control_plane_store.claim_lease(envelope=repo_b, resource_id="same-id", holder="b")
    assert lease_a.repository != lease_b.repository
    assert lease_a.fencing_token == lease_b.fencing_token == 1


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO builderops_tasks(repository, task_id, state, authority_envelope) "
        "VALUES (%s, 'bad-task', 'ready', %s)",
        "INSERT INTO builderops_attempts(repository, task_id, attempt_id, state, authority_envelope) "
        "VALUES (%s, 'bad-task', 'bad-attempt', 'running', %s)",
        "INSERT INTO builderops_records(repository, record_id, record_type, state, payload, "
        "authority_envelope) VALUES (%s, 'bad-record', 'LearningSignal', 'active', '{}'::jsonb, %s)",
        "INSERT INTO builderops_transitions(repository, task_id, to_state, authority_envelope) "
        "VALUES (%s, 'bad-task', 'ready', %s)",
        "INSERT INTO builderops_promotions(repository, promotion_id, status, authority_envelope) "
        "VALUES (%s, 'bad-promotion', 'pending', %s)",
        "INSERT INTO builderops_receipts(repository, task_id, event_type, idempotency_key, "
        "authority_envelope) VALUES (%s, 'bad-task', 'bad.event', 'bad-receipt', %s)",
        "INSERT INTO builderops_idempotency(repository, idempotency_key, request_hash, "
        "authority_envelope) VALUES (%s, 'bad-key', 'bad-hash', %s)",
        "INSERT INTO builderops_leases(repository, resource_id, holder, fencing_token, expires_at, "
        "authority_envelope) VALUES (%s, 'bad-resource', 'bad-holder', 1, "
        "clock_timestamp() + interval '1 minute', %s)",
        "INSERT INTO builderops_outbox(repository, operation_key, task_id, effect_type, payload, "
        "intent_receipt_sequence, authority_envelope) VALUES "
        "(%s, 'bad-operation', 'bad-task', 'github.comment', '{}'::jsonb, 1, %s)",
        "INSERT INTO builderops_outbox_reconciliations(repository, operation_key, "
        "claim_fencing_token, task_id, worker_id, claim_receipt_sequence, claim_lsn, "
        "observed_applied, evidence, request_hash, status, receipt_sequence, authority_envelope) "
        "VALUES (%s, 'bad-operation', 1, 'bad-task', 'bad-worker', 1, '0/0', false, "
        "'{}'::jsonb, 'bad-hash', 'pending', 2, %s)",
        "INSERT INTO builderops_dead_letters(repository, operation_key, outcome, authority_envelope) "
        "VALUES (%s, 'bad-operation', '{}'::jsonb, %s)",
    ],
)
def test_database_rejects_cross_repo_envelope_on_every_authority_table(
    control_plane_store, envelope, statement: str
) -> None:
    invalid = envelope.as_json()
    invalid["repository"] = "OtherOrg/other-repo"
    with pytest.raises(psycopg.errors.CheckViolation):
        with control_plane_store._connect() as conn:
            conn.execute(statement, (envelope.repository, Jsonb(invalid)))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scope", " "),
        ("scope", 1),
        ("stack", ""),
        ("actor", "\t"),
        ("source_refs", []),
        ("source_refs", ["valid", " "]),
        ("source_refs", ["valid", 1]),
        ("schema_version", 0),
        ("schema_version", 1.5),
        ("schema_version", "1"),
    ],
)
def test_database_rejects_malformed_authority_envelope_content(
    control_plane_store, envelope, field: str, value
) -> None:
    invalid = envelope.as_json()
    invalid[field] = value
    with pytest.raises(psycopg.errors.CheckViolation):
        with control_plane_store._connect() as conn:
            conn.execute(
                "INSERT INTO builderops_records(repository, record_id, record_type, state, payload, "
                "authority_envelope) VALUES (%s, 'malformed-record', 'LearningSignal', "
                "'active', '{}'::jsonb, %s)",
                (envelope.repository, Jsonb(invalid)),
            )
