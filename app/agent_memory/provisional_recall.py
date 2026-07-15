"""Production recall boundary for provisional, low-trust memory.

Vault Markdown remains the only meaning-bearing input. Lifecycle and recall
receipts contain identifiers and posture only; they cannot reconstruct claim
content or confer authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import unicodedata
from uuid import UUID, uuid4

from app.activation.gate import (
    AdmissionTier,
    AdmissibilityDecision,
    CandidateContext,
    ConsumingAuthority,
    ConsumingContext,
    TrustArchetype,
    evaluate_admissibility,
)
from app.agent_memory.authority_guard import (
    MemoryAuthorityDecision,
    evaluate_provisional_memory_authority,
)
from app.agent_memory.provisional_memory import (
    ProvisionalMemoryReconciliation,
    ProvisionalMemoryRecord,
    ProvisionalReconciliationState,
    rebuild_provisional_memory,
)
from app.agent_memory.provisional_write import (
    PROVISIONAL_MEMORY_DIR,
    ProvisionalReceiptStore,
    load_provisional_markdown,
)
from app.agent_memory.recall_explanation import (
    ActivationReason,
    MemoryLifecycleState,
    RecallExplanation,
    RecallUseRight,
    SourceProvenance,
)

DEFAULT_PROVISIONAL_RECALL_RECEIPTS_PATH = Path(
    "runtime/agent_memory/provisional_recall_receipts.jsonl"
)
PROVISIONAL_RECALL_RECEIPT_EVENT = "agent_memory.provisional_recall.evaluated"
_TOKEN_RE = re.compile(r"[^\W_]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "att",
    "av",
    "det",
    "en",
    "ett",
    "for",
    "för",
    "i",
    "in",
    "is",
    "it",
    "med",
    "of",
    "och",
    "om",
    "on",
    "or",
    "på",
    "som",
    "the",
    "to",
    "vad",
    "which",
    "with",
}


@dataclass(frozen=True)
class ProvisionalRecallCandidate:
    record: ProvisionalMemoryRecord
    reconciliation: ProvisionalMemoryReconciliation
    score: float
    reason_code: str


@dataclass(frozen=True)
class ProvisionalRecallExclusion:
    memory_id: str
    artifact_ref: str
    reason_code: str


@dataclass(frozen=True)
class ProvisionalRecallSearch:
    candidates: tuple[ProvisionalRecallCandidate, ...]
    excluded: tuple[ProvisionalRecallExclusion, ...]


@dataclass(frozen=True)
class ProvisionalGuardedRecall:
    memory_id: str
    admitted: bool
    may_answer: bool
    may_propose: bool
    may_write: bool
    admissibility_decision: AdmissibilityDecision
    authority_decision: MemoryAuthorityDecision
    explanation: RecallExplanation | None
    receipt_id: str


def retrieve_relevant_provisional(
    query: str,
    *,
    vault_root: Path,
    receipt_store: ProvisionalReceiptStore | None = None,
    active_scope_id: str,
    k: int = 3,
) -> ProvisionalRecallSearch:
    """Rebuild and rank complete same-scope provisional records.

    Scope filtering and lifecycle reconstruction happen before relevance
    ranking. Invalid or incomplete records yield content-free exclusions.
    """

    if k <= 0 or not _tokens(query):
        return ProvisionalRecallSearch(candidates=(), excluded=())
    store = receipt_store or ProvisionalReceiptStore()
    try:
        receipts = store.list_all()
    except Exception:
        return ProvisionalRecallSearch(
            candidates=(),
            excluded=(
                ProvisionalRecallExclusion(
                    memory_id="unknown",
                    artifact_ref="vault://Memory/Provisional/unknown",
                    reason_code="receipt_store_unreadable",
                ),
            ),
        )
    by_memory: dict[UUID, list] = {}
    for receipt in receipts:
        by_memory.setdefault(receipt.memory_id, []).append(receipt)
    excluded: list[ProvisionalRecallExclusion] = []
    directory = vault_root / PROVISIONAL_MEMORY_DIR
    if directory.exists():
        for path in directory.glob("*.md"):
            try:
                memory_id = UUID(path.stem)
            except ValueError:
                excluded.append(
                    ProvisionalRecallExclusion(
                        memory_id=path.stem,
                        artifact_ref=f"vault://{PROVISIONAL_MEMORY_DIR}/{path.name}",
                        reason_code="artifact_identity_invalid",
                    )
                )
                continue
            if memory_id.version != 4 or path.name != f"{memory_id}.md":
                excluded.append(
                    ProvisionalRecallExclusion(
                        memory_id=path.stem,
                        artifact_ref=f"vault://{PROVISIONAL_MEMORY_DIR}/{path.name}",
                        reason_code="artifact_identity_invalid",
                    )
                )
                continue
            by_memory.setdefault(memory_id, [])

    query_tokens = _tokens(query)
    candidates: list[ProvisionalRecallCandidate] = []
    for memory_id in sorted(by_memory, key=str):
        artifact_ref = f"vault://{PROVISIONAL_MEMORY_DIR}/{memory_id}.md"
        path = vault_root / PROVISIONAL_MEMORY_DIR / f"{memory_id}.md"
        artifact_invalid = False
        try:
            artifact = (
                load_provisional_markdown(path, vault_root=vault_root)
                if path.exists()
                else None
            )
        except Exception:
            artifact = None
            artifact_invalid = True
        reconciliation = rebuild_provisional_memory(
            memory_id=memory_id,
            artifact_ref=artifact_ref,
            artifact=artifact,
            receipts=tuple(by_memory[memory_id]),
        )
        if artifact_invalid:
            excluded.append(
                ProvisionalRecallExclusion(
                    memory_id=str(memory_id),
                    artifact_ref=artifact_ref,
                    reason_code="artifact_invalid",
                )
            )
            continue
        record = reconciliation.record
        if (
            reconciliation.state
            not in {
                ProvisionalReconciliationState.READY,
                ProvisionalReconciliationState.EDITED,
            }
            or record is None
        ):
            excluded.append(
                ProvisionalRecallExclusion(
                    memory_id=str(memory_id),
                    artifact_ref=artifact_ref,
                    reason_code=reconciliation.diagnostic.value,
                )
            )
            continue
        if record.scope_id != active_scope_id:
            excluded.append(
                ProvisionalRecallExclusion(
                    memory_id=str(memory_id),
                    artifact_ref=artifact_ref,
                    reason_code="cross_sphere_no_allowance",
                )
            )
            continue
        score = _score(record, query_tokens)
        if score <= 0:
            continue
        candidates.append(
            ProvisionalRecallCandidate(
                record=record,
                reconciliation=reconciliation,
                score=score,
                reason_code="lexical_relevance",
            )
        )
    ranked = sorted(
        candidates,
        key=lambda item: (item.score, item.record.created_at, str(item.record.memory_id)),
        reverse=True,
    )[:k]
    return ProvisionalRecallSearch(candidates=tuple(ranked), excluded=tuple(excluded))


def activate_provisional_recall(
    candidate: ProvisionalRecallCandidate,
    *,
    consuming_authority: ConsumingAuthority,
    active_scope_id: str,
    use_right: RecallUseRight,
    activation_reason: ActivationReason,
    receipt_path: Path,
    citation_reference: str | None = None,
) -> ProvisionalGuardedRecall:
    """Apply inbound admissibility and outbound authority clamps at consumption."""

    record = candidate.record
    inbound = evaluate_admissibility(
        CandidateContext(
            artifact_id=record.artifact_ref,
            sphere=record.scope_id,
            is_memory=True,
            memory_class=record.memory_type,
            trust_archetype=TrustArchetype.MACHINE_PROPOSED,
            review_state=record.review_state,
            inferred=True,
            has_provenance=bool(record.provenance_event_ids),
        ),
        ConsumingContext(
            capability_id="agent_memory.provisional_recall",
            authority=consuming_authority,
            scope=active_scope_id,
        ),
    )
    outbound = evaluate_provisional_memory_authority(record, use_right=use_right)
    required_tier = _required_tier(consuming_authority)
    tier_sufficient = _tier_rank(inbound.admitted_tier) >= _tier_rank(required_tier)
    citation_sufficient = (
        consuming_authority is not ConsumingAuthority.PROPOSAL
        or bool((citation_reference or "").strip())
    )
    use_right_sufficient = use_right is {
        ConsumingAuthority.READ_ONLY: RecallUseRight.ACTIVATABLE,
        ConsumingAuthority.PROPOSAL: RecallUseRight.CITED_PROPOSAL,
        ConsumingAuthority.GOVERNED_EXECUTION: RecallUseRight.ACTION_AUTHORIZING,
    }[consuming_authority]
    admitted = (
        inbound.admitted
        and tier_sufficient
        and citation_sufficient
        and use_right_sufficient
        and consuming_authority is not ConsumingAuthority.GOVERNED_EXECUTION
        and outbound.allow_suggestion
        and not outbound.allow_mutation
    )
    receipt_id = uuid4().hex
    explanation = (
        _build_explanation(
            candidate,
            use_right=use_right,
            activation_reason=activation_reason,
            receipt_id=receipt_id,
            citation_reference=citation_reference,
        )
        if admitted
        else None
    )
    _emit_recall_receipt(
        receipt_path,
        receipt_id=receipt_id,
        record=record,
        inbound=inbound,
        outbound=outbound,
        consuming_authority=consuming_authority,
        use_right=use_right,
        admitted=admitted,
        citation_present=bool((citation_reference or "").strip()),
    )
    return ProvisionalGuardedRecall(
        memory_id=str(record.memory_id),
        admitted=admitted,
        may_answer=admitted and consuming_authority is ConsumingAuthority.READ_ONLY,
        may_propose=admitted and consuming_authority is ConsumingAuthority.PROPOSAL,
        may_write=False,
        admissibility_decision=inbound,
        authority_decision=outbound,
        explanation=explanation,
        receipt_id=receipt_id,
    )


def _build_explanation(
    candidate: ProvisionalRecallCandidate,
    *,
    use_right: RecallUseRight,
    activation_reason: ActivationReason,
    receipt_id: str,
    citation_reference: str | None,
) -> RecallExplanation:
    record = candidate.record
    refs = [record.artifact_ref, *(str(item) for item in record.provenance_event_ids)]
    if citation_reference:
        refs.append(citation_reference)
    return RecallExplanation(
        artifact_id=record.artifact_ref,
        title=f"Provisional memory {record.memory_id}",
        artifact_class="agentic_memory",
        artifact_type="provisional_memory",
        memory_type=record.memory_type.value,
        use_right=use_right,
        lifecycle_state=MemoryLifecycleState.PROVISIONAL,
        review_state=record.review_state,
        trust_state="provisional_low_trust_noncanonical",
        activation_reason=activation_reason,
        why_now=candidate.reason_code,
        source_provenance=SourceProvenance(
            source_refs=refs,
            generated_by=record.created_by,
        ),
        authority_limits=[
            "provisional_low_trust_noncanonical",
            "memory_is_supporting_input_not_source_of_truth",
            "explicit_citation_required_for_proposal",
            "does_not_authorize_writeback",
            "never_apply_or_tool_use",
        ],
        receipt_reference=receipt_id,
    )


def _emit_recall_receipt(
    path: Path,
    *,
    receipt_id: str,
    record: ProvisionalMemoryRecord,
    inbound: AdmissibilityDecision,
    outbound: MemoryAuthorityDecision,
    consuming_authority: ConsumingAuthority,
    use_right: RecallUseRight,
    admitted: bool,
    citation_present: bool,
) -> None:
    payload = {
        "event": PROVISIONAL_RECALL_RECEIPT_EVENT,
        "event_id": receipt_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": {
            "memory_id": str(record.memory_id),
            "artifact_ref": record.artifact_ref,
            "lifecycle_receipt_refs": [str(item) for item in record.lifecycle_receipt_refs],
            "consuming_authority": consuming_authority.value,
            "requested_use_right": use_right.value,
            "admitted": admitted,
            "admitted_tier": inbound.admitted_tier.value,
            "admissibility_reason": inbound.reason,
            "authority_blocked_reasons": list(outbound.blocked_reasons),
            "citation_present": citation_present,
            "may_write": False,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as lock_handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            with path.open("a", encoding="utf-8") as handle:
                os.chmod(path, 0o600)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _required_tier(authority: ConsumingAuthority) -> AdmissionTier:
    return {
        ConsumingAuthority.READ_ONLY: AdmissionTier.READ,
        ConsumingAuthority.PROPOSAL: AdmissionTier.CITED_PROPOSAL,
        ConsumingAuthority.GOVERNED_EXECUTION: AdmissionTier.ACTION,
    }[authority]


def _tier_rank(tier: AdmissionTier) -> int:
    return {
        AdmissionTier.NONE: 0,
        AdmissionTier.READ: 1,
        AdmissionTier.CITED_PROPOSAL: 2,
        AdmissionTier.ACTION: 3,
    }[tier]


def _tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFC", value.casefold())
    return {
        match.group(0)
        for match in _TOKEN_RE.finditer(normalized)
        if match.group(0) not in _STOPWORDS
    }


def _score(record: ProvisionalMemoryRecord, query_tokens: set[str]) -> float:
    content_tokens = _tokens(record.content)
    overlap = query_tokens & content_tokens
    return len(overlap) / max(1, len(query_tokens))


__all__ = [
    "PROVISIONAL_RECALL_RECEIPT_EVENT",
    "ProvisionalGuardedRecall",
    "ProvisionalRecallCandidate",
    "ProvisionalRecallExclusion",
    "ProvisionalRecallSearch",
    "activate_provisional_recall",
    "retrieve_relevant_provisional",
]
