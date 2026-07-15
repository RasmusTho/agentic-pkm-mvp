from __future__ import annotations

from dataclasses import replace

import pytest

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
