from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest
from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.models import CkmValidationError
from app.builderops.ckm.semantic import (
    FabricSemanticAssociator,
    SemanticAssociationError,
    SemanticAssociationResult,
    SemanticBatch,
    SemanticProposal,
    associate_unlinked_artifacts,
    reapply_confirmation_receipts,
)
from app.builderops.ckm.store import CkmStore
from app.components.llm.constrained import ConstrainedCompletionError


@pytest.fixture()
def store(tmp_path: Path) -> CkmStore:
    value = CkmStore(tmp_path / "builderops.sqlite3")
    value.ensure_schema()
    return value


def _capability(store: CkmStore):
    return store.upsert_capability(
        identity_key="fixture:semantic:retrieval",
        name="Retrieval",
        definition="Retrieve relevant material with provenance.",
        existence_provenance="seeded:docs/CAPABILITY_CONTRACT_MODEL.md :: Retrieval",
        lifecycle="confirmed",
    )


def _artifact(store: CkmStore):
    return store.upsert_artifact(
        source_ref="docs/retrieval-notes.md",
        artifact_kind="document",
        source="repo_docs",
        watermark="commit:abc",
        provenance='{"source_ref":"docs/retrieval-notes.md"}',
    )


class StubAssociator:
    provider = "stub-provider"
    model = "stub-model"

    def __init__(self, proposals: list[SemanticProposal]) -> None:
        self._proposals = proposals

    def propose(self, *, artifacts, capabilities) -> SemanticBatch:
        return SemanticBatch(
            provider=self.provider,
            model=self.model,
            proposals=self._proposals,
        )


def _proposal(artifact_id: str, capability_id: str, *, confidence: float = 0.9):
    return SemanticProposal(
        artifact_id=artifact_id,
        capability_id=capability_id,
        evidence_kind="doc",
        maturity_dimension="documentation_quality",
        confidence=confidence,
        rationale="The artifact explicitly explains the retrieval capability.",
    )


def test_inferred_edges_fenced_via_store_write_path(store: CkmStore) -> None:
    capability = _capability(store)
    artifact = _artifact(store)

    result = associate_unlinked_artifacts(
        store,
        client=StubAssociator([_proposal(artifact.id, capability.id)]),
    )

    assert result.proposed == 1
    edge = store.list_evidence_edges()[0]
    assert edge.extraction_method == "inferred"
    assert edge.lifecycle == "candidate"
    assert (edge.provider, edge.model) == ("stub-provider", "stub-model")
    assert edge.basis == "The artifact explicitly explains the retrieval capability."

    for rationale in (None, "", "   "):
        with pytest.raises(CkmValidationError, match="explicit non-empty rationale"):
            store.upsert_evidence_edge(
                artifact_id=artifact.id,
                capability_id=capability.id,
                evidence_kind="doc",
                polarity="supports",
                maturity_dimension="documentation_quality",
                confidence=0.9,
                extraction_method="inferred",
                lifecycle="candidate",
                source_ref=artifact.source_ref,
                basis=rationale,
                provider="stub-provider",
                model="stub-model",
            )

    with pytest.raises(CkmValidationError, match="inferred evidence edges must enter as candidate"):
        store.upsert_evidence_edge(
            artifact_id=artifact.id,
            capability_id=capability.id,
            evidence_kind="doc",
            polarity="supports",
            maturity_dimension="documentation_quality",
            confidence=0.9,
            extraction_method="inferred",
            lifecycle="confirmed",
            source_ref=artifact.source_ref,
            basis="An invalid direct confirmation.",
            provider="stub-provider",
            model="stub-model",
        )


def _append_confirmation_receipt(
    store: CkmStore,
    *,
    edge,
    artifact_ref: str,
    capability_name: str,
    variant: str,
) -> None:
    payload = {
        "edge_id": edge.id,
        "lifecycle": "confirmed",
        "artifact_source_ref": artifact_ref,
        "capability_name": capability_name,
        "evidence_kind": edge.evidence_kind,
        "polarity": edge.polarity,
        "maturity_dimension": edge.maturity_dimension,
        "confidence": edge.confidence,
        "extraction_method": edge.extraction_method,
        "source_ref": edge.source_ref,
        "basis": edge.basis,
        "provider": edge.provider,
        "model": edge.model,
        "confirmation_key": "a" * 64,
        # A structurally plausible value is still not trusted without the
        # secret binding created by the human-operated confirmation boundary.
        "binding": "b" * 64,
    }
    actor = {"actor_type": "human", "id": "operator"}
    action = "confirm_edge"
    event_type = "ckm_edge_confirmed"
    target_refs = [
        {"ref_type": "repo_artifact", "ref": artifact_ref},
        {"ref_type": "ckm_capability", "ref": capability_name},
    ]
    if variant == "non-human":
        actor = {"actor_type": "agent", "id": "forger"}
    elif variant == "wrong-event":
        event_type = "ckm_edge_observed"
    elif variant == "wrong-action":
        action = "observe_edge"
    elif variant == "wrong-target":
        target_refs[0] = {"ref_type": "repo_artifact", "ref": "docs/other.md"}
    elif variant == "forged-payload":
        payload["confidence"] = 0.01
    store.append_builderops_receipt(
        source_refs=[{"ref_type": "ckm_evidence_edge", "ref": edge.id}],
        summary="Attempted confirmation",
        event_type=event_type,
        actor=actor,
        occurred_at=edge.updated_at,
        target_refs=target_refs,
        action=action,
        receipt_body=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        idempotency_key=f"test-confirm-{variant}",
    )


@pytest.mark.parametrize(
    "variant",
    [
        "self-asserted",
        "non-human",
        "wrong-event",
        "wrong-action",
        "wrong-target",
        "forged-payload",
    ],
)
def test_confirmation_rejects_invalid_or_forged_receipts(
    tmp_path: Path, variant: str
) -> None:
    store = CkmStore(tmp_path / f"{variant}.sqlite3")
    store.ensure_schema()
    capability = _capability(store)
    artifact = _artifact(store)
    associate_unlinked_artifacts(
        store,
        client=StubAssociator([_proposal(artifact.id, capability.id)]),
    )
    edge = store.list_evidence_edges()[0]
    _append_confirmation_receipt(
        store,
        edge=edge,
        artifact_ref=artifact.source_ref,
        capability_name=capability.name,
        variant=variant,
    )

    assert reapply_confirmation_receipts(store) == 0
    assert store.get_evidence_edge_by_id(edge.id).lifecycle == "candidate"

    # Absence of the source edge after rebuild must not turn a structurally
    # valid human self-assertion into authority.
    store.rebuild()
    _capability(store)
    _artifact(store)
    assert reapply_confirmation_receipts(store) == 0
    assert store.list_evidence_edges() == []


class _FabricClient:
    def __init__(self, *, response: str | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    def chat(self, *args, **kwargs) -> str:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


@pytest.mark.parametrize("failure", ["schema", "constrained"])
def test_fabric_adapter_maps_structured_output_failures(failure: str) -> None:
    associator = object.__new__(FabricSemanticAssociator)
    associator.provider = "stub-provider"
    associator.model = "stub-model"
    if failure == "schema":
        associator._client = _FabricClient(response='{"proposals": [{"artifact_id": "x"}]}')
    else:
        associator._client = _FabricClient(
            error=ConstrainedCompletionError(
                schema_ref="test", reason="schema violation"
            )
        )

    with pytest.raises(SemanticAssociationError, match="invalid semantic association response"):
        associator.propose(artifacts=[], capabilities=[])


def test_confidence_floor_discards(store: CkmStore) -> None:
    capability = _capability(store)
    artifact = _artifact(store)

    result = associate_unlinked_artifacts(
        store,
        client=StubAssociator([_proposal(artifact.id, capability.id, confidence=0.59)]),
        confidence_floor=0.6,
    )

    assert result == SemanticAssociationResult(
        status="ok",
        proposed=0,
        discarded=1,
        no_match=0,
        provider="stub-provider",
        model="stub-model",
    )
    assert store.list_evidence_edges() == []


def test_unknown_proposal_target_fails_without_writes(store: CkmStore) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    proposal = _proposal(artifact.id, capability.id)
    invalid = SemanticProposal(
        artifact_id="art_outside_bounded_batch",
        capability_id=proposal.capability_id,
        evidence_kind=proposal.evidence_kind,
        maturity_dimension=proposal.maturity_dimension,
        confidence=proposal.confidence,
        rationale=proposal.rationale,
    )

    with pytest.raises(SemanticAssociationError, match="outside the bounded batch"):
        associate_unlinked_artifacts(store, client=StubAssociator([invalid]))

    assert store.list_evidence_edges() == []
    assert store.get_watermark("semantic_association") is None


def test_llm_unavailable_skips_cleanly(store: CkmStore) -> None:
    _capability(store)
    _artifact(store)
    store.set_watermark("semantic_association", "prior")

    result = associate_unlinked_artifacts(store, client=None, client_factory=lambda: None)

    assert result.status == "skipped (llm unavailable)"
    assert result.proposed == 0
    assert store.list_evidence_edges() == []
    assert store.get_watermark("semantic_association") == "prior"


def test_confirmation_receipt_survives_rebuild(
    store: CkmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    associate_unlinked_artifacts(
        store,
        client=StubAssociator([_proposal(artifact.id, capability.id)]),
    )
    original = store.list_evidence_edges()[0]

    # There is no public lifecycle mutation bypass; promotion must traverse a
    # human receipt that is validated against the edge and both targets.
    assert not hasattr(store, "confirm_inferred_edge")

    runner = CliRunner()
    confirmation = runner.invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "confirm-edge", original.id],
    )
    assert confirmation.exit_code == 0, confirmation.output
    assert f"edge {original.id} confirmed; receipt builderops://receipts/" in confirmation.output
    receipt = store.list_builderops_receipts("ckm_edge_confirmed")[0]
    assert store.get_evidence_edge_by_id(original.id).lifecycle == "confirmed"
    assert receipt["event_type"] == "ckm_edge_confirmed"

    # The stable semantic confirmation key makes a delayed retry idempotent;
    # changing wall-clock timestamps cannot conflict with the prior request.
    monkeypatch.setattr(
        "app.builderops.ckm.semantic.utc_now", lambda: "2099-01-01T00:00:00Z"
    )
    repeated = runner.invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "confirm-edge", original.id],
    )
    assert repeated.exit_code == 0, repeated.output
    assert len(store.list_builderops_receipts("ckm_edge_confirmed")) == 1

    # An idempotent association pass must not demote a human-confirmed edge.
    store.upsert_evidence_edge(
        artifact_id=artifact.id,
        capability_id=capability.id,
        evidence_kind=original.evidence_kind,
        polarity=original.polarity,
        maturity_dimension=original.maturity_dimension,
        confidence=original.confidence,
        extraction_method="inferred",
        lifecycle="candidate",
        source_ref=original.source_ref,
        basis=original.basis,
        provider=original.provider,
        model=original.model,
    )
    assert store.get_evidence_edge_by_id(original.id).lifecycle == "confirmed"

    store.rebuild()
    rebuilt_capability = _capability(store)
    rebuilt_artifact = _artifact(store)
    assert reapply_confirmation_receipts(store) == 1

    restored = store.list_evidence_edges()
    assert len(restored) == 1
    assert restored[0].artifact_id == rebuilt_artifact.id
    assert restored[0].capability_id == rebuilt_capability.id
    assert restored[0].lifecycle == "confirmed"
    assert restored[0].basis == original.basis


def test_retired_inferred_edge_cannot_be_confirmed(store: CkmStore) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    associate_unlinked_artifacts(
        store,
        client=StubAssociator([_proposal(artifact.id, capability.id)]),
    )
    edge = store.list_evidence_edges()[0]
    store.delete_evidence_edge(edge.id)

    result = CliRunner().invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "confirm-edge", edge.id],
    )

    assert result.exit_code != 0
    assert "evidence edge not found" in result.output
    assert store.get_active_evidence_edge_by_id(edge.id) is None
    assert store.get_evidence_edge_by_id(edge.id) is not None
    assert store.list_builderops_receipts("ckm_edge_confirmed") == []


def test_retired_confirmed_edge_stays_tombstoned_across_rebuild(
    store: CkmStore,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    associate_unlinked_artifacts(
        store,
        client=StubAssociator([_proposal(artifact.id, capability.id)]),
    )
    edge = store.list_evidence_edges()[0]
    confirmation = CliRunner().invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "confirm-edge", edge.id],
    )
    assert confirmation.exit_code == 0, confirmation.output

    store.delete_evidence_edge(edge.id)

    assert store.has_retired_evidence_edge(edge.id) is True
    assert reapply_confirmation_receipts(store) == 0
    assert store.list_evidence_edges() == []

    store.rebuild()
    _capability(store)
    _artifact(store)

    assert store.has_retired_evidence_edge(edge.id) is False
    assert reapply_confirmation_receipts(store) == 0
    assert store.list_evidence_edges() == []
    assert store.identity_lifecycle(edge.public_id)["status"] == "tombstone"


@pytest.mark.parametrize(
    ("field", "changed_value"),
    (
        ("confidence", 0.1),
        ("model", "replacement-model"),
        ("provider", "replacement-provider"),
        ("polarity", "weakens"),
        ("maturity_dimension", "operational_readiness"),
        ("evidence_kind", "requirement"),
    ),
)
def test_material_change_demotes_confirmed_edge_until_new_receipt(
    store: CkmStore,
    field: str,
    changed_value: object,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    associate_unlinked_artifacts(
        store,
        client=StubAssociator([_proposal(artifact.id, capability.id)]),
    )
    original = store.list_evidence_edges()[0]
    runner = CliRunner()
    confirmation = runner.invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "confirm-edge", original.id],
    )
    assert confirmation.exit_code == 0, confirmation.output

    replacement = {
        "artifact_id": original.artifact_id,
        "capability_id": original.capability_id,
        "evidence_kind": original.evidence_kind,
        "polarity": original.polarity,
        "maturity_dimension": original.maturity_dimension,
        "confidence": original.confidence,
        "extraction_method": original.extraction_method,
        "lifecycle": "candidate",
        "source_ref": original.source_ref,
        "basis": original.basis,
        "provider": original.provider,
        "model": original.model,
    }
    replacement[field] = changed_value
    changed = store.upsert_evidence_edge(**replacement)

    assert changed.id == original.id
    assert changed.lifecycle == "candidate"
    assert getattr(changed, field) == changed_value
    assert reapply_confirmation_receipts(store) == 0
    assert store.get_active_evidence_edge_by_id(original.id).lifecycle == "candidate"
    assert len(store.list_builderops_receipts("ckm_edge_confirmed")) == 1

    reconfirmation = runner.invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "confirm-edge", original.id],
    )
    assert reconfirmation.exit_code == 0, reconfirmation.output
    assert store.get_active_evidence_edge_by_id(original.id).lifecycle == "confirmed"
    assert len(store.list_builderops_receipts("ckm_edge_confirmed")) == 2


def test_new_basis_creates_candidate_without_mutating_confirmed_claim(
    store: CkmStore,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    associate_unlinked_artifacts(
        store,
        client=StubAssociator([_proposal(artifact.id, capability.id)]),
    )
    original = store.list_evidence_edges()[0]
    confirmation = CliRunner().invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "confirm-edge", original.id],
    )
    assert confirmation.exit_code == 0, confirmation.output

    replacement = store.upsert_evidence_edge(
        artifact_id=original.artifact_id,
        capability_id=original.capability_id,
        evidence_kind=original.evidence_kind,
        polarity=original.polarity,
        maturity_dimension=original.maturity_dimension,
        confidence=original.confidence,
        extraction_method=original.extraction_method,
        lifecycle="candidate",
        source_ref=original.source_ref,
        basis="A materially different rationale.",
        provider=original.provider,
        model=original.model,
    )

    assert replacement.id != original.id
    assert replacement.lifecycle == "candidate"
    assert store.get_active_evidence_edge_by_id(original.id).lifecycle == "confirmed"


@pytest.mark.parametrize("field", ["actor", "confidence", "model", "basis"])
def test_trusted_confirmation_rejects_tampering_before_and_after_rebuild(
    tmp_path: Path, field: str
) -> None:
    store = CkmStore(tmp_path / f"tamper-{field}.sqlite3")
    store.ensure_schema()
    capability = _capability(store)
    artifact = _artifact(store)
    associate_unlinked_artifacts(
        store,
        client=StubAssociator([_proposal(artifact.id, capability.id)]),
    )
    edge = store.list_evidence_edges()[0]
    runner = CliRunner()
    confirmation = runner.invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "confirm-edge", edge.id],
    )
    assert confirmation.exit_code == 0, confirmation.output
    receipt = store.list_builderops_receipts("ckm_edge_confirmed")[0]

    if field == "actor":
        receipt["actor"] = {"actor_type": "human", "id": "different-human"}
    else:
        body = json.loads(receipt["receipt_body"])
        body[field] = 0.01 if field == "confidence" else f"altered-{field}"
        receipt["receipt_body"] = json.dumps(body, ensure_ascii=False, sort_keys=True)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE builderops_records SET payload = ? WHERE id = ?",
            (json.dumps(receipt, ensure_ascii=False, sort_keys=True), receipt["id"]),
        )
        conn.commit()

    assert reapply_confirmation_receipts(store) == 0
    store.rebuild()
    _capability(store)
    _artifact(store)
    assert reapply_confirmation_receipts(store) == 0
    assert store.list_evidence_edges() == []
