from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.models import CkmValidationError
from app.builderops.ckm.semantic import (
    SemanticAssociationError,
    SemanticAssociationResult,
    SemanticBatch,
    SemanticProposal,
    associate_unlinked_artifacts,
    reapply_confirmation_receipts,
)
from app.builderops.ckm.store import CkmStore


@pytest.fixture()
def store(tmp_path: Path) -> CkmStore:
    value = CkmStore(tmp_path / "builderops.sqlite3")
    value.ensure_schema()
    return value


def _capability(store: CkmStore):
    return store.upsert_capability(
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


def test_confirmation_receipt_survives_rebuild(store: CkmStore) -> None:
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
    assert f"edge {original.id} confirmed; receipt builderops://receipts/" in confirmation.output
    receipt = store.list_builderops_receipts("ckm_edge_confirmed")[0]
    assert store.get_evidence_edge_by_id(original.id).lifecycle == "confirmed"
    assert receipt["event_type"] == "ckm_edge_confirmed"

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
