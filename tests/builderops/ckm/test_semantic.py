from __future__ import annotations

import hmac
import json
from pathlib import Path
import sqlite3
from hashlib import sha256
from threading import Barrier, Event, Thread
from typing import Any, Mapping

import pytest
import yaml
from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.models import CkmValidationError
from app.builderops.ckm.semantic import (
    BuilderSemanticAssociator,
    CKM_SEMANTIC_CONSUMER,
    CKM_SEMANTIC_RESOLUTION_GROUP,
    CKM_SEMANTIC_ROLE,
    SEMANTIC_SCHEMA_REF,
    SemanticAssociationError,
    SemanticAssociationResult,
    SemanticBatch,
    SemanticProposal,
    SemanticProviderUnavailable,
    _http_adapter_factory,
    _binding_document,
    _canonical_json,
    associate_unlinked_artifacts,
    reapply_confirmation_receipts,
)
from app.builderops.ckm.store import CkmStore
from app.builderops.model_inquiry_adapters import HttpModelAdapter
from app.builderops.model_access_resolver import BuilderModelAccessResolver
from llm_contract import AdapterResult, ModelCapabilities, ResolvedModelAccess


PROVIDER_CENSUS_PATH = Path("docs/settings/models/providers.yaml")
HOST_SECRET_CONTRACT_PATH = Path("config/secrets/host_secret_contract.json")


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


class RecordingResolver:
    def __init__(
        self,
        *,
        provider: str = "openai",
        model: str = "gpt-5.6-sol",
        effective_identity: str = "openai/gpt-5.6-sol",
        degraded: bool = False,
        degradation_reason: str | None = None,
        credential: str = "declared-openai-credential-0001",
    ) -> None:
        self.provider = provider
        self.model = model
        self.effective_identity = effective_identity
        self.degraded = degraded
        self.degradation_reason = degradation_reason
        self.credential = credential
        self.calls: list[dict[str, Any]] = []

    def resolve(self, request, *, runtime: str, channel: str, consumer: str):
        self.calls.append(
            {
                "request": request,
                "runtime": runtime,
                "channel": channel,
                "consumer": consumer,
            }
        )
        return ResolvedModelAccess(
            request=request,
            provider=self.provider,
            model=self.model,
            adapter_id=f"{self.provider}-{self.model}",
            effective_identity=self.effective_identity,
            capabilities=ModelCapabilities(
                structured_output=True,
                system_prompt_channel=True,
            ),
            credential_identity_ref=f"{self.provider}.api-key",
            degraded=self.degraded,
            degradation_reason=self.degradation_reason,
        )

    def endpoint_for(self, resolved: ResolvedModelAccess) -> str:
        return f"https://{resolved.provider}.example.invalid/model"

    def credential_value(self, resolved: ResolvedModelAccess) -> str:
        del resolved
        return self.credential


class RecordingAdapter:
    adapter_id = "openai-gpt-5.6-sol"
    provider = "openai"
    model = "gpt-5.6-sol"

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: list[dict[str, Any]] = []

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        self.calls.append(dict(request))
        return AdapterResult(
            response_text=self.response_text,
            provider_request_id="provider-request-1",
        )


def _builder_associator(
    resolver: RecordingResolver,
    adapter: RecordingAdapter,
) -> BuilderSemanticAssociator:
    return BuilderSemanticAssociator(
        resolver=resolver,
        env={"PKM_ENVIRONMENT": "dev"},
        adapter_factory=lambda _resolved, _endpoint, _credential: adapter,
    )


def _response(proposals: list[SemanticProposal]) -> str:
    return json.dumps(
        {
            "proposals": [
                {
                    "artifact_id": item.artifact_id,
                    "capability_id": item.capability_id,
                    "evidence_kind": item.evidence_kind,
                    "maturity_dimension": item.maturity_dimension,
                    "confidence": item.confidence,
                    "rationale": item.rationale,
                }
                for item in proposals
            ]
        }
    )


def test_semantic_association_resolves_through_builder_adapter(store: CkmStore) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    resolver = RecordingResolver()
    adapter = RecordingAdapter(_response([_proposal(artifact.id, capability.id)]))

    result = associate_unlinked_artifacts(
        store,
        client=_builder_associator(resolver, adapter),
    )

    assert result.proposed == 1
    assert len(adapter.calls) == 1
    assert store.list_evidence_edges()[0].provider == "openai"
    assert "FabricSemanticAssociator" not in Path("app/builderops/ckm/semantic.py").read_text(
        encoding="utf-8"
    )


def test_semantic_production_call_uses_provider_free_builder_resolver(
    store: CkmStore,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    resolver = RecordingResolver()
    adapter = RecordingAdapter(_response([_proposal(artifact.id, capability.id)]))

    associate_unlinked_artifacts(
        store,
        client=_builder_associator(resolver, adapter),
    )

    assert len(resolver.calls) == 1
    call = resolver.calls[0]
    request = call["request"]
    assert call == {
        "request": request,
        "runtime": "builder",
        "channel": "dev",
        "consumer": CKM_SEMANTIC_CONSUMER,
    }
    assert request.role_profile == CKM_SEMANTIC_ROLE
    assert request.resolution_group_id == CKM_SEMANTIC_RESOLUTION_GROUP
    assert request.intent.output_schema_ref == SEMANTIC_SCHEMA_REF
    assert {"provider", "model", "credential", "endpoint"}.isdisjoint(
        request.model_dump(mode="json")
    )


def test_semantic_default_factory_accepts_declared_ckm_intent() -> None:
    resolver = RecordingResolver()

    associator = BuilderSemanticAssociator(
        resolver=resolver,
        env={"PKM_ENVIRONMENT": "dev"},
        adapter_factory=_http_adapter_factory,
    )

    assert isinstance(associator._adapter, HttpModelAdapter)
    assert associator._adapter.required_reasoning_effort == "low"
    assert associator._adapter.required_output_schema_ref == SEMANTIC_SCHEMA_REF
    assert associator._adapter.required_side_effect_class == "derived_candidate_evidence"


def test_product_fallback_cannot_execute_builder_task(
    store: CkmStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    product_calls: list[str] = []

    def fail_product_route(*_args: object, **_kwargs: object) -> None:
        product_calls.append("called")
        raise AssertionError("Product routing must not execute CKM semantic association")

    monkeypatch.setattr(
        "app.components.llm.fabric.get_chat_client",
        fail_product_route,
    )
    resolver = RecordingResolver()
    adapter = RecordingAdapter(_response([_proposal(artifact.id, capability.id)]))

    result = associate_unlinked_artifacts(
        store,
        client=_builder_associator(resolver, adapter),
    )

    assert result.proposed == 1
    assert product_calls == []


def test_semantic_request_declares_fallback_forbidden(store: CkmStore) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    resolver = RecordingResolver()
    adapter = RecordingAdapter(_response([_proposal(artifact.id, capability.id)]))

    associate_unlinked_artifacts(
        store,
        client=_builder_associator(resolver, adapter),
    )

    assert resolver.calls[0]["request"].intent.fallback_requirement == "fallback_forbidden"


def test_mock_identity_is_refused_before_route_selection(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(PROVIDER_CENSUS_PATH.read_text(encoding="utf-8"))
    payload["runtime_channels"]["builder"]["dev"]["frontier"] = {
        "provider": "mock",
        "model": "mock-chat",
        "requires": ["structured_output", "deterministic_execution"],
    }
    census_path = tmp_path / "providers.yaml"
    census_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    resolver = BuilderModelAccessResolver.from_declared_sources(
        env={"PKM_ENVIRONMENT": "dev"},
        census_path=census_path,
        contract_path=HOST_SECRET_CONTRACT_PATH,
    )
    adapter_selected: list[str] = []

    with pytest.raises(SemanticProviderUnavailable, match="mock identity"):
        BuilderSemanticAssociator(
            resolver=resolver,
            env={"PKM_ENVIRONMENT": "dev"},
            adapter_factory=lambda *_args: adapter_selected.append("selected"),
        )

    assert adapter_selected == []


def test_credential_unavailable_skips_with_visible_reason(store: CkmStore) -> None:
    _capability(store)
    _artifact(store)

    result = associate_unlinked_artifacts(
        store,
        client_factory=lambda: BuilderSemanticAssociator(env={"PKM_ENVIRONMENT": "dev"}),
    )

    assert result.status == "skipped"
    assert result.reason == "declared credential unavailable: openai.api-key"
    assert result.proposed == 0
    assert store.list_evidence_edges() == []
    assert store.get_watermark("semantic_association") is None


def test_subscription_session_cannot_execute_ckm_semantic_task(
    store: CkmStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capability(store)
    _artifact(store)
    subscription_calls: list[str] = []

    def fail_subscription(*_args: object, **_kwargs: object) -> None:
        subscription_calls.append("called")
        raise AssertionError("subscription session must not execute CKM")

    monkeypatch.setattr(
        "app.builderops.model_inquiry_adapters.LocalCommandAdapter.execute",
        fail_subscription,
    )

    result = associate_unlinked_artifacts(
        store,
        client_factory=lambda: BuilderSemanticAssociator(env={"PKM_ENVIRONMENT": "dev"}),
    )

    assert result.status == "skipped"
    assert result.proposed == 0
    assert subscription_calls == []


def test_degraded_builder_route_writes_zero_edges_with_visible_reason(
    store: CkmStore,
) -> None:
    _capability(store)
    _artifact(store)
    resolver = RecordingResolver(
        degraded=True,
        degradation_reason="declared Builder route degraded",
    )
    adapter_selected: list[str] = []

    result = associate_unlinked_artifacts(
        store,
        client_factory=lambda: BuilderSemanticAssociator(
            resolver=resolver,
            env={"PKM_ENVIRONMENT": "dev"},
            adapter_factory=lambda *_args: adapter_selected.append("selected"),
        ),
    )

    assert result.status == "skipped"
    assert result.reason == "degraded Builder route: declared Builder route degraded"
    assert result.proposed == 0
    assert store.list_evidence_edges() == []
    assert adapter_selected == []


def test_existing_semantic_contract_regression_suite(store: CkmStore) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    accepted = _proposal(artifact.id, capability.id)
    discarded = _proposal(artifact.id, capability.id, confidence=0.59)

    result = associate_unlinked_artifacts(
        store,
        client=StubAssociator([accepted, discarded]),
    )

    assert result == SemanticAssociationResult(
        status="ok",
        proposed=1,
        discarded=1,
        no_match=0,
        provider="stub-provider",
        model="stub-model",
    )
    edge = store.list_evidence_edges()[0]
    assert edge.lifecycle == "candidate"
    assert edge.extraction_method == "inferred"


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


def test_semantic_batch_and_watermark_rollback_together_on_interruption(
    store: CkmStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)

    def interrupt_before_watermark(
        _conn: sqlite3.Connection,
        *,
        source: str,
        value: str,
    ) -> bool:
        del source, value
        raise RuntimeError("simulated interruption before watermark")

    monkeypatch.setattr(
        CkmStore,
        "_set_watermark_in_connection",
        staticmethod(interrupt_before_watermark),
    )

    with pytest.raises(RuntimeError, match="simulated interruption"):
        associate_unlinked_artifacts(
            store,
            client=StubAssociator([_proposal(artifact.id, capability.id)]),
        )

    assert store.list_evidence_edges() == []
    assert store.get_watermark("semantic_association") is None


def test_concurrent_semantic_batches_converge_without_duplicate_edges(
    store: CkmStore,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    barrier = Barrier(2)
    results: list[SemanticAssociationResult] = []
    failures: list[BaseException] = []

    class BarrierAssociator(StubAssociator):
        def propose(self, *, artifacts, capabilities) -> SemanticBatch:
            barrier.wait()
            return super().propose(artifacts=artifacts, capabilities=capabilities)

    def run() -> None:
        try:
            results.append(
                associate_unlinked_artifacts(
                    store,
                    client=BarrierAssociator([_proposal(artifact.id, capability.id)]),
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [Thread(target=run), Thread(target=run)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert sorted(result.proposed for result in results) == [0, 1]
    assert sorted(result.status for result in results) == ["ok", "skipped"]
    assert len(store.list_evidence_edges()) == 1
    assert store.get_watermark("semantic_association") is not None


def test_semantic_snapshot_drift_during_propose_writes_nothing(
    store: CkmStore,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    proposing = Event()
    resume = Event()
    results: list[SemanticAssociationResult] = []

    class PausingAssociator(StubAssociator):
        def propose(self, *, artifacts, capabilities) -> SemanticBatch:
            proposing.set()
            assert resume.wait(timeout=5)
            return super().propose(artifacts=artifacts, capabilities=capabilities)

    thread = Thread(
        target=lambda: results.append(
            associate_unlinked_artifacts(
                store,
                client=PausingAssociator([_proposal(artifact.id, capability.id)]),
            )
        )
    )
    thread.start()
    assert proposing.wait(timeout=5)
    changed = store.upsert_artifact(
        source_ref=artifact.source_ref,
        artifact_kind=artifact.artifact_kind,
        source=artifact.source,
        watermark="commit:changed-during-propose",
        provenance='{"source_ref":"docs/retrieval-notes.md","changed":true}',
    )
    assert changed.id == artifact.id
    resume.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert results == [
        SemanticAssociationResult(
            status="skipped",
            proposed=0,
            discarded=0,
            no_match=1,
            provider="stub-provider",
            model="stub-model",
            reason="semantic input snapshot changed before commit; rerun required",
        )
    ]
    assert store.list_evidence_edges() == []
    assert store.get_watermark("semantic_association") is None


def test_semantic_capability_set_drift_during_propose_writes_nothing(
    store: CkmStore,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    proposing = Event()
    resume = Event()
    results: list[SemanticAssociationResult] = []

    class PausingAssociator(StubAssociator):
        def propose(self, *, artifacts, capabilities) -> SemanticBatch:
            proposing.set()
            assert resume.wait(timeout=5)
            return super().propose(artifacts=artifacts, capabilities=capabilities)

    thread = Thread(
        target=lambda: results.append(
            associate_unlinked_artifacts(
                store,
                client=PausingAssociator([_proposal(artifact.id, capability.id)]),
            )
        )
    )
    thread.start()
    assert proposing.wait(timeout=5)
    store.upsert_capability(
        identity_key="fixture:semantic:concurrent-capability",
        name="Concurrent capability",
        definition="Added while the semantic provider work is in flight.",
        existence_provenance="test:concurrent-capability",
        lifecycle="confirmed",
    )
    resume.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert results[0].status == "skipped"
    assert results[0].reason == (
        "semantic input snapshot changed before commit; rerun required"
    )
    assert store.list_evidence_edges() == []
    assert store.get_watermark("semantic_association") is None


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_duplicate_semantic_proposals_fail_before_write(
    store: CkmStore,
    reverse: bool,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    first = _proposal(artifact.id, capability.id)
    conflicting = SemanticProposal(
        artifact_id=first.artifact_id,
        capability_id=first.capability_id,
        evidence_kind="spec",
        maturity_dimension=first.maturity_dimension,
        confidence=first.confidence,
        rationale=first.rationale,
    )
    proposals = [first, conflicting]
    if reverse:
        proposals.reverse()

    with pytest.raises(SemanticAssociationError, match="conflicting duplicate"):
        associate_unlinked_artifacts(
            store,
            client=StubAssociator(proposals),
        )

    assert store.list_evidence_edges() == []
    assert store.get_watermark("semantic_association") is None


def test_semantic_watermark_binds_input_batch_and_material_edge_state(
    tmp_path: Path,
) -> None:
    def run(
        name: str,
        *,
        source_ref: str,
        rationale: str,
    ) -> str:
        candidate_store = CkmStore(tmp_path / f"{name}.sqlite3")
        candidate_store.ensure_schema()
        capability = _capability(candidate_store)
        artifact = candidate_store.upsert_artifact(
            source_ref=source_ref,
            artifact_kind="document",
            source="repo_docs",
            watermark="commit:shared",
            provenance=f'{{"source_ref":"{source_ref}"}}',
        )
        proposal = _proposal(artifact.id, capability.id)
        proposal = SemanticProposal(
            artifact_id=proposal.artifact_id,
            capability_id=proposal.capability_id,
            evidence_kind=proposal.evidence_kind,
            maturity_dimension=proposal.maturity_dimension,
            confidence=proposal.confidence,
            rationale=rationale,
        )
        result = associate_unlinked_artifacts(
            candidate_store,
            client=StubAssociator([proposal]),
        )
        assert result.status == "ok"
        watermark = candidate_store.get_watermark("semantic_association")
        assert watermark is not None
        return watermark

    baseline = run(
        "baseline",
        source_ref="docs/retrieval-notes.md",
        rationale="The artifact explicitly explains retrieval.",
    )
    assert (
        run(
            "idempotent",
            source_ref="docs/retrieval-notes.md",
            rationale="The artifact explicitly explains retrieval.",
        )
        == baseline
    )
    assert (
        run(
            "different-batch",
            source_ref="docs/other-retrieval-notes.md",
            rationale="The artifact explicitly explains retrieval.",
        )
        != baseline
    )
    assert (
        run(
            "different-edge",
            source_ref="docs/retrieval-notes.md",
            rationale="Materially different semantic evidence.",
        )
        != baseline
    )


def _append_confirmation_receipt(
    store: CkmStore,
    *,
    edge,
    variant: str,
) -> None:
    artifact = next(item for item in store.list_artifacts() if item.id == edge.artifact_id)
    capability = store.get_capability(edge.capability_id)
    assert capability is not None
    payload = {
        "edge_id": edge.id,
        "lifecycle": "confirmed",
        "edge_public_id": edge.public_id,
        "artifact_public_id": artifact.public_id,
        "capability_public_id": capability.public_id,
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
        {"ref_type": "ckm_artifact", "ref": artifact.public_id},
        {"ref_type": "ckm_capability", "ref": capability.public_id},
    ]
    if variant == "non-human":
        actor = {"actor_type": "agent", "id": "forger"}
    elif variant == "wrong-event":
        event_type = "ckm_edge_observed"
    elif variant == "wrong-action":
        action = "observe_edge"
    elif variant == "wrong-target":
        target_refs[0] = {"ref_type": "ckm_artifact", "ref": "ckm_art_other"}
    elif variant == "forged-payload":
        payload["confidence"] = 0.01
    store.append_builderops_receipt(
        source_refs=[{"ref_type": "ckm_evidence_edge", "ref": edge.public_id}],
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
def test_confirmation_rejects_invalid_or_forged_receipts(tmp_path: Path, variant: str) -> None:
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
        variant=variant,
    )

    assert reapply_confirmation_receipts(store) == 0
    assert store.get_evidence_edge_by_id(edge.id).lifecycle == "candidate"

    # Absence of the source edge after rebuild must not turn a structurally
    # valid human self-assertion into authority.
    store.rebuild(retained_public_ids=[capability.public_id, artifact.public_id])
    _capability(store)
    _artifact(store)
    assert reapply_confirmation_receipts(store) == 0
    assert store.list_evidence_edges() == []


@pytest.mark.parametrize("failure", ["schema", "constrained"])
def test_builder_adapter_maps_structured_output_failures(failure: str) -> None:
    resolver = RecordingResolver()
    response = '{"proposals": [{"artifact_id": "x"}]}'
    if failure == "constrained":
        response = "not-json"
    adapter = RecordingAdapter(response)
    associator = _builder_associator(resolver, adapter)

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
    monkeypatch.setattr("app.builderops.ckm.semantic.utc_now", lambda: "2099-01-01T00:00:00Z")
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

    store.rebuild(retained_public_ids=store.active_public_ids())
    rebuilt_capability = store.upsert_capability(
        identity_key="fixture:semantic:retrieval",
        name="Renamed Retrieval",
        definition="Retrieve relevant material with provenance.",
        existence_provenance="seeded:docs/CAPABILITY_CONTRACT_MODEL.md :: Retrieval",
        lifecycle="confirmed",
    )
    rebuilt_artifact = _artifact(store)
    assert reapply_confirmation_receipts(store) == 1

    restored = store.list_evidence_edges()
    assert len(restored) == 1
    assert restored[0].artifact_id == rebuilt_artifact.id
    assert restored[0].capability_id == rebuilt_capability.id
    assert restored[0].lifecycle == "confirmed"
    assert restored[0].basis == original.basis


def test_authenticated_pre_v5_confirmation_migrates_before_rebuild(store: CkmStore) -> None:
    capability = _capability(store)
    artifact = _artifact(store)
    associate_unlinked_artifacts(
        store,
        client=StubAssociator([_proposal(artifact.id, capability.id)]),
    )
    edge = store.list_evidence_edges()[0]
    payload = {
        "edge_id": edge.id,
        "artifact_source_ref": artifact.source_ref,
        "capability_name": capability.name,
        "evidence_kind": edge.evidence_kind,
        "polarity": edge.polarity,
        "maturity_dimension": edge.maturity_dimension,
        "confidence": edge.confidence,
        "extraction_method": "inferred",
        "lifecycle": "confirmed",
        "source_ref": edge.source_ref,
        "basis": edge.basis,
        "provider": edge.provider,
        "model": edge.model,
    }
    stable_claim = {key: value for key, value in payload.items() if key != "edge_id"}
    payload["confirmation_key"] = sha256(_canonical_json(stable_claim).encode("utf-8")).hexdigest()
    envelope = {
        "event_type": "ckm_edge_confirmed",
        "action": "confirm_edge",
        "actor": {"actor_type": "human", "id": "legacy-operator"},
        "source_refs": [{"ref_type": "ckm_evidence_edge", "ref": edge.id}],
        "target_refs": [
            {"ref_type": "repo_artifact", "ref": artifact.source_ref},
            {"ref_type": "ckm_capability", "ref": capability.name},
        ],
    }
    key = store._confirmation_signing_key(create=True)
    assert key is not None
    payload["binding"] = hmac.new(
        key,
        _canonical_json(_binding_document(envelope, payload)).encode("utf-8"),
        sha256,
    ).hexdigest()
    store.append_builderops_receipt(
        source_refs=envelope["source_refs"],
        summary="Legacy confirmed inferred CKM edge",
        event_type=envelope["event_type"],
        actor=envelope["actor"],
        occurred_at=edge.updated_at,
        target_refs=envelope["target_refs"],
        action=envelope["action"],
        receipt_body=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        idempotency_key=f"legacy-confirm:{payload['confirmation_key']}",
    )

    store.ensure_schema()
    store.ensure_schema()
    receipts = store.list_builderops_receipts("ckm_edge_confirmed")
    assert len(receipts) == 2
    receipt_payloads = [json.loads(item["receipt_body"]) for item in receipts]
    migrated = [item for item in receipt_payloads if "edge_public_id" in item]
    assert len(migrated) == 1
    assert migrated[0]["edge_public_id"] == edge.public_id
    assert migrated[0]["artifact_public_id"] == artifact.public_id
    assert migrated[0]["capability_public_id"] == capability.public_id

    store.rebuild(retained_public_ids=store.active_public_ids())
    store.upsert_capability(
        identity_key="fixture:semantic:retrieval",
        name="Renamed Retrieval",
        definition="Retrieve relevant material with provenance.",
        existence_provenance="seeded:docs/CAPABILITY_CONTRACT_MODEL.md :: Retrieval",
        lifecycle="confirmed",
    )
    _artifact(store)

    assert reapply_confirmation_receipts(store) == 1
    assert store.list_evidence_edges()[0].lifecycle == "confirmed"


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

    store.rebuild(retained_public_ids=store.active_public_ids())
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
    store.rebuild(retained_public_ids=[capability.public_id, artifact.public_id])
    _capability(store)
    _artifact(store)
    assert reapply_confirmation_receipts(store) == 0
    assert store.list_evidence_edges() == []
