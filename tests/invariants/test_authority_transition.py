"""Invariant skeletons: durable mutation is governed; execution cannot self-authorize.

Invariant registry: docs/testing/invariant-tests.md
  :: authority_transition_required_for_durable_mutation, authority_transition_requires_decision_token_and_receipt,
     authority_transition_state_is_consistent, storage_write_is_not_authority_transition,
     execution_cannot_authorize_itself, promote_requires_governance
Issues: #2550 (registry), #2552 (skeletons).
Contracts: docs/architecture/authority-transition-flow.md (#2547), docs/architecture/memory-model.md (#2546).
"""

from __future__ import annotations

import json

import pytest

from tests.invariants._helpers import future_runtime, load_schema


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


@pytest.mark.xfail(
    reason=(
        "Runtime governed-write (WriteGuard/GovernedWriteProtocol) path not implemented for the "
        "Yggdrasil contract yet; this skeleton protects invariant "
        "authority_transition_required_for_durable_mutation (#2550). Future vertical slice: GOV durable mutation."
    ),
    strict=True,
)
def test_authority_transition_required_for_durable_mutation() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: authority_transition_required_for_durable_mutation
    gov = future_runtime("authority")  # raises until governed-mutation runtime exists
    # Intended assertion: a durable change to accepted knowledge without a transition is rejected.
    with pytest.raises(Exception):
        gov.mutate_durable(object_id="art-1", new_content="x", transition=None)


@pytest.mark.xfail(
    reason=(
        "Runtime storage/authority separation not implemented yet; this skeleton protects invariant "
        "storage_write_is_not_authority_transition (#2550). Persisting bytes (PDM) is not changing "
        "standing. Future vertical slice: PDM store vs GOV transition."
    ),
    strict=True,
)
def test_storage_write_is_not_authority_transition() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: storage_write_is_not_authority_transition
    pdm = future_runtime("storage")  # raises until storage runtime exists
    before = pdm.get_authority_state(object_id="art-1")
    pdm.write_bytes(object_id="art-1", payload=b"...")
    after = pdm.get_authority_state(object_id="art-1")
    # Intended assertion: a raw storage write never changes authority standing.
    assert before == after


@pytest.mark.xfail(
    reason=(
        "Runtime execution/authorization (EXE/GOV) not implemented yet; this skeleton protects "
        "invariant execution_cannot_authorize_itself (#2550). Execution consumes authorization; it "
        "never mints it. Future vertical slice: EXE."
    ),
    strict=True,
)
def test_execution_cannot_authorize_itself() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: execution_cannot_authorize_itself
    exe = future_runtime("execution")  # raises until execution runtime exists
    # Intended assertion: an execution effect with no prior GOV grant/receipt is refused.
    with pytest.raises(Exception):
        exe.execute(effect="send_email", authority_receipt=None)


@pytest.mark.xfail(
    reason=(
        "Runtime memory promotion path (MEM -> GOV -> HKA) not implemented yet; this skeleton "
        "protects invariant promote_requires_governance (#2550). Promotion needs an AuthorityTransition "
        "+ receipt and materializes a SEPARATE canonical artifact. Future vertical slice: MEM promotion."
    ),
    strict=True,
)
def test_promote_requires_governance() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: promote_requires_governance
    mem = future_runtime("memory")  # raises until memory runtime exists
    # Intended assertion: promoting a memory without governance is refused; a governed promotion
    # leaves the memory record noncanonical and creates a separate canonical HKA artifact.
    with pytest.raises(Exception):
        mem.promote(memory_id="mem-1", transition=None)
