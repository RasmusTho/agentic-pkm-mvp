from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

import app.knowledge_compilation.trace_harness as trace_harness
from app.context_bundles.schema import (
    AuthorityFlags,
    BundleScope,
    BundleTrigger,
    ContextBundle,
    ExpiryPosture,
    IncludedItem,
    ItemProvenance,
)
from app.knowledge_compilation.proposal_builders import (
    ProposalContext,
    build_compilation_draft,
    build_curation_candidate,
)
from app.knowledge_compilation.reorientation_packet import (
    assemble_reorientation_packet_from_bundle,
)
from app.knowledge_compilation.review_admission import (
    AdmissionDecision,
    AdmissionReceiptPosture,
    AdmissionScope,
    record_admission_decision,
)
from app.knowledge_compilation.runtime_artifacts import (
    AdmissionState,
    CompilationDraft,
    ContextAuthorityLimits,
    SourceRef,
)
from app.knowledge_compilation.trace_harness import (
    KnowledgeCompilationTraceError,
    evaluate_knowledge_compilation_trace,
)


_NOW = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _RuntimeFlow:
    draft: object
    candidate: object
    packet: object
    handoff: object


def _source() -> SourceRef:
    return SourceRef(artifact_id="note:source", note_path="vault://source.md")


def _bundle() -> ContextBundle:
    return ContextBundle(
        id="ctx_trace_harness",
        created_at=_NOW,
        trigger=BundleTrigger(type="orientation", source="test"),
        intended_use=["orient"],
        scope=BundleScope(project="knowledge-compilation"),
        included=[
            IncludedItem(
                artifact_id="note:source",
                path="vault://source.md",
                reason="trace harness source",
                source_role="source",
                trust_state="reviewed",
                review_state="confirmed",
                provenance=ItemProvenance(origin="vault note"),
            )
        ],
        authority=AuthorityFlags(may_orient=True),
        expiry=ExpiryPosture(),
    )


def _runtime_flow() -> _RuntimeFlow:
    context = ProposalContext(
        source_refs=(_source(),),
        content="compiled observation",
        rationale="retain the reviewed source",
        trace_ref="trace:kc:1538",
        generated_by="knowledge_compiler",
    )
    draft = build_compilation_draft(context, title="Compiled observation")
    candidate = build_curation_candidate(context, title="Retained source set")
    packet = assemble_reorientation_packet_from_bundle(
        _bundle(),
        trace_ref="trace:kc:1538",
        now=_NOW,
    )
    handoff = record_admission_decision(
        draft,
        reviewer_ref="reviewer:rasmus",
        actor_ref="agent:codex",
        decision=AdmissionDecision.ADMIT,
        scope=AdmissionScope.MEMORY_REVIEW_QUEUE,
        authority_basis="reviewed for memory queue only",
        receipt_ref="receipt:admission:1538",
        receipt_posture=AdmissionReceiptPosture.DURABLE_RECEIPT_REF,
    )
    return _RuntimeFlow(draft=draft, candidate=candidate, packet=packet, handoff=handoff)


def _tamper(artifact: CompilationDraft, **updates: object) -> CompilationDraft:
    values = dict(artifact.__dict__)
    values.update(updates)
    return artifact.__class__.model_construct(**values)


def test_harness_records_trace_for_each_generated_artifact() -> None:
    flow = _runtime_flow()

    report = evaluate_knowledge_compilation_trace(
        artifacts=(flow.draft, flow.candidate, flow.packet),
        handoffs=(flow.handoff,),
    )

    assert report.provider_free is True
    assert report.diagnostic_only is True
    assert report.is_receipt is False
    assert [record.artifact_class for record in report.artifact_records] == [
        "compilation_draft",
        "curation_candidate",
        "reorientation_packet",
    ]
    assert report.artifact_records[0].trace_ref == "trace:kc:1538"
    assert report.artifact_records[0].source_ids == ("note:source",)
    assert report.artifact_records[0].canonical is False
    assert report.artifact_records[0].trust_verb == "SUGGEST"
    assert report.admission_records[0].artifact_id == flow.draft.artifact_id
    assert report.admission_records[0].decision is AdmissionDecision.ADMIT
    assert report.admission_records[0].receipt_ref == "receipt:admission:1538"
    assert report.admission_records[0].source_ids == ("note:source",)


def test_harness_fails_on_missing_provenance_or_authority_escalation() -> None:
    flow = _runtime_flow()
    draft = flow.draft

    missing_provenance = _tamper(draft, source_refs=())
    with pytest.raises(KnowledgeCompilationTraceError, match="provenance"):
        evaluate_knowledge_compilation_trace(artifacts=(missing_provenance,))

    canonical_drift = _tamper(draft, canonical=True)
    with pytest.raises(KnowledgeCompilationTraceError, match="canonical"):
        evaluate_knowledge_compilation_trace(artifacts=(canonical_drift,))

    elevated_authority = _tamper(
        draft,
        authority_limits=ContextAuthorityLimits(may_write=True),
    )
    with pytest.raises(KnowledgeCompilationTraceError, match="authority"):
        evaluate_knowledge_compilation_trace(artifacts=(elevated_authority,))

    bad_handoff = flow.handoff.__class__.model_construct(
        original_artifact=flow.handoff.original_artifact,
        admitted_artifact=_tamper(
            flow.handoff.admitted_artifact,
            authority_limits=ContextAuthorityLimits(may_write=True),
        ),
        decision_record=flow.handoff.decision_record,
    )
    with pytest.raises(KnowledgeCompilationTraceError, match="authority"):
        evaluate_knowledge_compilation_trace(artifacts=(), handoffs=(bad_handoff,))


def test_harness_requires_admission_receipt_before_promotion_path() -> None:
    flow = _runtime_flow()

    with pytest.raises(KnowledgeCompilationTraceError, match="admission receipt"):
        evaluate_knowledge_compilation_trace(
            artifacts=(flow.draft,),
            promotion_like_artifact_ids=(flow.draft.artifact_id,),
        )

    report = evaluate_knowledge_compilation_trace(
        artifacts=(flow.handoff.admitted_artifact,),
        handoffs=(flow.handoff,),
        promotion_like_artifact_ids=(flow.draft.artifact_id,),
    )

    assert report.promotion_path_records == (flow.draft.artifact_id,)
    assert report.artifact_records[0].admission_state == AdmissionState.ADMITTED.value
    assert report.artifact_records[0].admission_receipt_ref == "receipt:admission:1538"


def test_harness_runs_provider_free_without_db_or_vault_mutation() -> None:
    flow = _runtime_flow()

    report = evaluate_knowledge_compilation_trace(
        artifacts=(flow.draft, flow.candidate, flow.packet),
        handoffs=(flow.handoff,),
    )

    assert report.provider_free is True
    assert report.diagnostic_only is True
    assert report.emits_events is False
    assert report.durable_writes is False
    assert report.is_receipt is False

    src = inspect.getsource(trace_harness)
    tree = ast.parse(src)
    imported_modules: set[str] = set()
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            imported_modules.add(module)
            for alias in node.names:
                imported_modules.add(f"{module}.{alias.name}".lower())
        elif isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            used_names.add(node.attr)

    forbidden_imports = (
        "sqlalchemy",
        "app.db",
        "app.events",
        "app.outbox",
        "app.agent_memory.promotion",
        "app.llm",
        "app.vault",
        "objectstore",
        "knowledgeport",
        "vaultport",
        "writeguard",
    )
    for forbidden in forbidden_imports:
        assert not any(forbidden in module for module in imported_modules), (
            f"trace_harness must not import {forbidden!r}; "
            f"imports={sorted(imported_modules)}"
        )
    assert "open" not in used_names
    assert "emit" not in used_names
