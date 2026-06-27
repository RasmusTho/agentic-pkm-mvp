"""Invariant skeletons: durable mutation is governed; execution cannot self-authorize.

Invariant registry: docs/testing/invariant-tests.md
  :: authority_transition_required_for_durable_mutation, authority_transition_requires_decision_token_and_receipt,
     authority_transition_state_is_consistent, storage_write_is_not_authority_transition,
     execution_cannot_authorize_itself, promote_requires_governance
Issues: #2550 (registry), #2552 (skeletons).
Contracts: docs/architecture/authority-transition-flow.md (#2547), docs/architecture/memory-model.md (#2546).

Runtime skeletons xfail *only* on the missing runtime import (require_future_runtime); their
assertions run for real once the runtime exists.
"""

from __future__ import annotations

import json

import pytest

from tests.invariants._helpers import load_schema, require_future_runtime


def test_authority_transition_requires_decision_token_and_receipt() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: authority_transition_requires_decision_token_and_receipt
    # Static (schema_enforced): the schema carries conditional logic binding accepted/canonical grants
    # to a decision_token_ref + authority_receipt_id (mirrors the GovernedWriteProtocol invariant).
    schema = load_schema("authority-transition.schema.json")
    assert schema.get("allOf"), "authority-transition must use conditional allOf rules"
    text = json.dumps(schema)
    assert "decision_token_ref" in text
    assert "authority_receipt_id" in text
    assert "canonical_authority_state" in text or "approved_authority_state" in text


def test_authority_transition_state_is_consistent() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: authority_transition_state_is_consistent
    # Static (schema_enforced): approval_required/approval_state stay consistent and non-grant states
    # carry no grant artifacts. We assert the constraint surface exists in the schema.
    schema = load_schema("authority-transition.schema.json")
    text = json.dumps(schema)
    assert "approval_state" in text and "approval_required" in text
    assert "not_required" in text  # the required<->state consistency value
    assert "allOf" in schema


def test_execution_policy_requires_authorization_in_schema() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: execution_cannot_authorize_itself
    # Static companion (schema_enforced): a ContextEnvelope pins execution_policy.requires_authorization
    # and mutation_policy.requires_authority_transition to true.
    ce = load_schema("context-envelope.schema.json")
    exec_policy = ce["properties"]["execution_policy"]["properties"]
    assert exec_policy["requires_authorization"].get("const") is True
    mut_policy = ce["properties"]["mutation_policy"]["properties"]
    assert mut_policy["requires_authority_transition"].get("const") is True


def test_authority_transition_required_for_durable_mutation() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: authority_transition_required_for_durable_mutation
    gov = require_future_runtime(
        "authority",
        "Runtime governed-write path not implemented yet; protects "
        "authority_transition_required_for_durable_mutation (#2550).",
    )
    # A durable change to accepted knowledge without a transition is rejected.
    with pytest.raises(Exception):
        gov.mutate_durable(object_id="art-1", new_content="x", transition=None)


def test_storage_write_is_not_authority_transition() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: storage_write_is_not_authority_transition
    pdm = require_future_runtime(
        "storage",
        "Runtime storage/authority separation not implemented yet; protects "
        "storage_write_is_not_authority_transition (#2550).",
    )
    before = pdm.get_authority_state(object_id="art-1")
    pdm.write_bytes(object_id="art-1", payload=b"...")
    after = pdm.get_authority_state(object_id="art-1")
    # A raw storage write never changes authority standing.
    assert before == after


def test_execution_cannot_authorize_itself() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: execution_cannot_authorize_itself
    exe = require_future_runtime(
        "execution",
        "Runtime execution/authorization (EXE/GOV) not implemented yet; protects "
        "execution_cannot_authorize_itself (#2550).",
    )
    # An execution effect with no prior GOV grant/receipt is refused.
    with pytest.raises(Exception):
        exe.execute(effect="send_email", authority_receipt=None)


def test_promote_requires_governance() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: promote_requires_governance
    mem = require_future_runtime(
        "memory",
        "Runtime memory promotion path (MEM -> GOV -> HKA) not implemented yet; protects "
        "promote_requires_governance (#2550).",
    )
    # Promoting a memory without governance is refused; a governed promotion leaves the memory record
    # noncanonical and creates a separate canonical HKA artifact.
    with pytest.raises(Exception):
        mem.promote(memory_id="mem-1", transition=None)
