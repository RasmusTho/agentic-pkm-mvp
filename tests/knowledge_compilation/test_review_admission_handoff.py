from __future__ import annotations

import ast
import inspect

import pytest
from pydantic import ValidationError

import app.knowledge_compilation.review_admission as review_admission
from app.agent_memory.candidate import MemoryType, ReviewState
from app.agent_memory.review_queue import MemoryCandidateReviewQueue, ReviewStatus
from app.knowledge_compilation.proposal_builders import ProposalContext, build_compilation_draft
from app.knowledge_compilation.review_admission import (
    AdmissionDecision,
    AdmissionHandoffError,
    AdmissionReceiptPosture,
    AdmissionScope,
    record_admission_decision,
    route_admitted_memory_to_review_queue,
)
from app.knowledge_compilation.runtime_artifacts import (
    AdmissionState,
    CompilationDraft,
    ContextAuthorityLimits,
    SourceRef,
    TrustVerb,
)


def _source() -> SourceRef:
    return SourceRef(artifact_id="note:source", note_path="vault://source.md")


def _draft() -> CompilationDraft:
    return build_compilation_draft(
        ProposalContext(
            source_refs=(_source(),),
            content="Candidate memory-like observation.",
            uncertainty_notes="single source",
            trace_ref="trace:kc:1537",
            generated_by="knowledge_compiler",
        ),
        title="Draft observation",
    )


def test_admission_requires_explicit_reviewer_decision_and_receipt_posture() -> None:
    draft = _draft()

    handoff = record_admission_decision(
        draft,
        reviewer_ref="reviewer:human",
        actor_ref="agent:codex",
        decision=AdmissionDecision.ADMIT,
        scope=AdmissionScope.MEMORY_REVIEW_QUEUE,
        authority_basis="human review of proposed memory candidate",
        receipt_ref="receipt:admission:1537",
        receipt_posture=AdmissionReceiptPosture.DURABLE_RECEIPT_REF,
    )

    assert handoff.decision_record.reviewer_ref == "reviewer:human"
    assert handoff.decision_record.actor_ref == "agent:codex"
    assert handoff.decision_record.decision is AdmissionDecision.ADMIT
    assert handoff.decision_record.scope is AdmissionScope.MEMORY_REVIEW_QUEUE
    assert handoff.decision_record.authority_basis == (
        "human review of proposed memory candidate"
    )
    assert handoff.decision_record.receipt_ref == "receipt:admission:1537"
    assert handoff.decision_record.receipt_posture is (
        AdmissionReceiptPosture.DURABLE_RECEIPT_REF
    )
    assert handoff.admitted_artifact.admission_state is AdmissionState.ADMITTED
    assert handoff.admitted_artifact.admission_receipt_ref == "receipt:admission:1537"
    assert handoff.admitted_artifact.canonical is False
    assert handoff.can_promote_directly is False

    required = {
        "reviewer_ref": "",
        "actor_ref": "",
        "authority_basis": "",
        "receipt_ref": "",
    }
    for field, value in required.items():
        kwargs = {
            "reviewer_ref": "reviewer:human",
            "actor_ref": "agent:codex",
            "decision": AdmissionDecision.ADMIT,
            "scope": AdmissionScope.MEMORY_REVIEW_QUEUE,
            "authority_basis": "human review",
            "receipt_ref": "receipt:admission:1537",
            "receipt_posture": AdmissionReceiptPosture.DURABLE_RECEIPT_REF,
        }
        kwargs[field] = value
        with pytest.raises(ValidationError):
            record_admission_decision(draft, **kwargs)


def test_handoff_routes_to_review_queue_without_promoting() -> None:
    handoff = record_admission_decision(
        _draft(),
        reviewer_ref="reviewer:human",
        actor_ref="agent:codex",
        decision=AdmissionDecision.ADMIT,
        scope=AdmissionScope.MEMORY_REVIEW_QUEUE,
        authority_basis="reviewed for memory queue only",
        receipt_ref="receipt:admission:queue",
        receipt_posture=AdmissionReceiptPosture.DURABLE_RECEIPT_REF,
    )
    queue = MemoryCandidateReviewQueue()

    entry = route_admitted_memory_to_review_queue(
        handoff,
        queue,
        memory_type=MemoryType.EPISODIC_MEMORY,
    )

    assert entry.status is ReviewStatus.PENDING
    assert entry.decision is None
    assert entry.candidate.review_state is ReviewState.UNREVIEWED
    assert entry.candidate.activation_policy.value == "review_queue_only"
    assert entry.candidate.title == "Draft observation"
    assert entry.candidate.content == "Candidate memory-like observation."
    assert entry.candidate.derived_from == handoff.admitted_artifact.artifact_id
    assert entry.candidate.generated_by == "knowledge_compiler"
    assert entry.candidate.source_refs == ["note:source"]
    assert queue.pending() == [entry]
    assert queue.recallable_for_working_context() == []


def test_admission_outcomes_preserve_provenance_and_origin() -> None:
    draft = _draft()
    outcomes = (
        (AdmissionDecision.ADMIT, AdmissionState.ADMITTED),
        (AdmissionDecision.REJECT, AdmissionState.REJECTED),
        (AdmissionDecision.REVISE, AdmissionState.REVISION_REQUESTED),
    )

    for decision, expected_state in outcomes:
        handoff = record_admission_decision(
            draft,
            reviewer_ref="reviewer:human",
            actor_ref="agent:codex",
            decision=decision,
            scope=AdmissionScope.COMPILATION_REVIEW,
            authority_basis=f"{decision.value} after explicit review",
            receipt_ref=f"receipt:admission:{decision.value}",
            receipt_posture=AdmissionReceiptPosture.DURABLE_RECEIPT_REF,
            decision_notes=f"{decision.value} notes",
        )

        assert handoff.admitted_artifact.admission_state is expected_state
        assert handoff.admitted_artifact.source_refs == draft.source_refs
        assert handoff.admitted_artifact.trace_ref == "trace:kc:1537"
        assert handoff.admitted_artifact.generated_by == "knowledge_compiler"
        assert handoff.admitted_artifact.artifact_class == "compilation_draft"
        assert handoff.admitted_artifact.canonical is False
        assert handoff.original_artifact == draft
        assert handoff.decision_record.decision is decision
        assert handoff.decision_record.decision_notes == f"{decision.value} notes"


def test_direct_apply_or_promotion_without_receipt_is_rejected() -> None:
    draft = _draft()

    apply_artifact = CompilationDraft(
        title="Direct apply",
        source_refs=(_source(),),
        trust_verb=TrustVerb.APPLY,
        admission_state=AdmissionState.ADMITTED,
        admission_receipt_ref="receipt:already",
    )
    with pytest.raises(AdmissionHandoffError, match="APPLY"):
        record_admission_decision(
            apply_artifact,
            reviewer_ref="reviewer:human",
            actor_ref="agent:codex",
            decision=AdmissionDecision.ADMIT,
            scope=AdmissionScope.MEMORY_REVIEW_QUEUE,
            authority_basis="would bypass admission",
            receipt_ref="receipt:admission:apply",
            receipt_posture=AdmissionReceiptPosture.DURABLE_RECEIPT_REF,
        )

    with pytest.raises(ValidationError):
        record_admission_decision(
            draft,
            reviewer_ref="reviewer:human",
            actor_ref="agent:codex",
            decision=AdmissionDecision.ADMIT,
            scope="vault_write",
            authority_basis="write directly to vault",
            receipt_ref="receipt:admission:vault",
            receipt_posture=AdmissionReceiptPosture.DURABLE_RECEIPT_REF,
        )

    with pytest.raises(ValidationError):
        record_admission_decision(
            draft,
            reviewer_ref="reviewer:human",
            actor_ref="agent:codex",
            decision=AdmissionDecision.ADMIT,
            scope=AdmissionScope.MEMORY_REVIEW_QUEUE,
            authority_basis="missing durable receipt",
            receipt_ref="",
            receipt_posture=AdmissionReceiptPosture.DURABLE_RECEIPT_REF,
        )

    with pytest.raises(ValueError, match="hidden authority"):
        CompilationDraft(
            title="Promote directly",
            source_refs=(_source(),),
            authority_limits=ContextAuthorityLimits(may_promote=True),
        )

    src = inspect.getsource(review_admission)
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
        "app.objects",
        "app.outbox",
        "app.events",
        "app.agent_memory.promotion",
        "objectstore",
        "knowledgeport",
        "vaultport",
        "writeguard",
    )
    for forbidden in forbidden_imports:
        assert not any(forbidden in module for module in imported_modules), (
            f"review_admission must not import {forbidden!r}; "
            f"imports={sorted(imported_modules)}"
        )
    assert "promote" not in used_names
