"""Fail-closed, read-only admission for personal decision history.

This adapter deliberately reuses the existing canonical identity resolver and
CAL-01 outcome-receipt reader.  It performs no retrieval, persistence,
inference, generation, scheduling, or writeback of its own.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Callable, Literal, Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from app.receipts import decision_receipt_log, outcome_receipt_log

IdentityResolver = Callable[[str], str | None]
OutcomeReader = Callable[[], list[dict[str, Any]]]
CitationResolver = Callable[[str], bool]


class DecisionIdentity(BaseModel):
    object_id: UUID
    decision_uuid: UUID


class DecisionHistoryCandidate(BaseModel):
    identity: DecisionIdentity
    object_type: str
    scope_id: str = Field(min_length=1)
    corpus: Literal["personal", "governance"]
    title: str
    excerpt: str
    citation_handle: str = Field(min_length=1)


class AdmittedDecision(BaseModel):
    object_id: UUID
    decision_uuid: UUID
    role: Literal["selected", "precedent"]
    title: str
    excerpt: str
    citation_handle: str


class AdmittedOutcome(BaseModel):
    decision_object_id: UUID
    decision_uuid: UUID
    rung_index: int
    outcome: outcome_receipt_log.OutcomeValue
    note: str | None
    created_at: datetime
    citation_handle: str


class AdmissionCoverage(BaseModel):
    status: Literal["ok", "partial", "blocked"]
    diagnostic: str
    admitted_decision_count: int = 0
    admitted_outcome_count: int = 0
    excluded_count: int = 0
    exclusions: dict[str, int] = Field(default_factory=dict)


class DecisionHistoryAdmission(BaseModel):
    decisions: list[AdmittedDecision] = Field(default_factory=list)
    outcomes: list[AdmittedOutcome] = Field(default_factory=list)
    coverage: AdmissionCoverage


def _blocked(diagnostic: str) -> DecisionHistoryAdmission:
    return DecisionHistoryAdmission(
        coverage=AdmissionCoverage(status="blocked", diagnostic=diagnostic)
    )


def _citation_resolves(resolver: CitationResolver, handle: str) -> bool:
    try:
        return bool(resolver(handle))
    except Exception:
        return False


def _resolved_uuid(
    resolver: IdentityResolver,
    object_id: UUID,
    cache: dict[UUID, str | None],
) -> str | None:
    if object_id not in cache:
        try:
            cache[object_id] = resolver(str(object_id))
        except Exception:
            cache[object_id] = None
    return cache[object_id]


def _receipt_citation(receipt: outcome_receipt_log.OutcomeReceipt) -> str:
    # CAL-01's idempotency/linkage key is (decision_uuid, rung_index). The
    # citation handle names exactly that canonical receipt; it does not resolve
    # or infer a different decision identity.
    return f"decision-outcome:{receipt.decision_uuid}:{receipt.rung_index}"


def _raw_candidate_identity(raw: object) -> DecisionIdentity | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        return DecisionIdentity.model_validate(raw.get("identity"))
    except (ValidationError, TypeError, ValueError):
        return None


def _raw_receipt_link(raw: object) -> tuple[UUID, int] | None:
    """Extract only CAL-01's canonical key from an otherwise corrupt row."""
    if not isinstance(raw, Mapping):
        return None
    try:
        decision_uuid = UUID(str(raw.get("decision_uuid")))
        rung_index = raw.get("rung_index")
        if isinstance(rung_index, bool) or not isinstance(rung_index, int) or rung_index < 0:
            return None
        return decision_uuid, rung_index
    except (TypeError, ValueError, AttributeError):
        return None


def _raw_receipt_touches_admitted(
    raw: object,
    admitted_object_ids: set[str],
    admitted_uuids: set[str],
) -> bool:
    if not isinstance(raw, Mapping):
        return False
    return (
        str(raw.get("decision_object_id") or "") in admitted_object_ids
        or str(raw.get("decision_uuid") or "") in admitted_uuids
    )


def admit_decision_history(
    *,
    selected_identities: Sequence[object],
    candidates: Sequence[object],
    current_scope_id: str,
    citation_resolver: CitationResolver,
    identity_resolver: IdentityResolver = decision_receipt_log.resolve_vault_uuid,
    outcome_reader: OutcomeReader = outcome_receipt_log.iter_outcome_receipts,
) -> DecisionHistoryAdmission:
    """Admit one selected decision plus safe current-scope precedents.

    Structural identity, corpus, and scope checks always run before title,
    excerpt, or outcome note is copied into an output model. Every returned
    content-bearing item must also pass the caller's current citation resolver.
    """

    if not isinstance(selected_identities, Sequence) or isinstance(
        selected_identities, (str, bytes)
    ):
        return _blocked("selected_identity_count_invalid")
    if len(selected_identities) != 1:
        return _blocked("selected_identity_count_invalid")
    try:
        selected = DecisionIdentity.model_validate(selected_identities[0])
    except (ValidationError, TypeError, ValueError):
        return _blocked("selected_identity_malformed")
    if not isinstance(current_scope_id, str) or not current_scope_id.strip():
        return _blocked("current_scope_invalid")

    raw_selected_alias_count = sum(_raw_candidate_identity(raw) == selected for raw in candidates)
    if raw_selected_alias_count == 0:
        return _blocked("selected_identity_stale")
    if raw_selected_alias_count != 1:
        return _blocked("selected_identity_ambiguous")

    parsed: list[DecisionHistoryCandidate] = []
    exclusions: Counter[str] = Counter()
    for raw in candidates:
        try:
            parsed.append(DecisionHistoryCandidate.model_validate(raw))
        except (ValidationError, TypeError, ValueError):
            exclusions["candidate_malformed"] += 1

    selected_matches = [item for item in parsed if item.identity == selected]
    if not selected_matches:
        return _blocked("selected_record_malformed")
    if len(selected_matches) != 1:
        return _blocked("selected_identity_ambiguous")

    identity_cache: dict[UUID, str | None] = {}
    selected_record = selected_matches[0]
    selected_uuid = _resolved_uuid(identity_resolver, selected.object_id, identity_cache)
    if selected_uuid is None:
        return _blocked("selected_identity_unavailable")
    if selected_uuid != str(selected.decision_uuid):
        return _blocked("selected_identity_stale")
    if (
        selected_record.object_type != "decision_record"
        or selected_record.corpus != "personal"
        or selected_record.scope_id != current_scope_id
    ):
        return _blocked("selected_decision_inadmissible")
    if not _citation_resolves(citation_resolver, selected_record.citation_handle):
        return _blocked("selected_citation_unresolvable")

    identity_counts = Counter(
        (item.identity.object_id, item.identity.decision_uuid) for item in parsed
    )
    admitted_records: list[tuple[DecisionHistoryCandidate, Literal["selected", "precedent"]]] = [
        (selected_record, "selected")
    ]
    for item in parsed:
        if item is selected_record:
            continue
        pair = (item.identity.object_id, item.identity.decision_uuid)
        if identity_counts[pair] > 1:
            exclusions["precedent_identity_ambiguous"] += 1
            continue
        if item.corpus == "governance":
            exclusions["governance_corpus"] += 1
            continue
        if item.object_type != "decision_record":
            exclusions["not_decision_record"] += 1
            continue
        if item.scope_id != current_scope_id:
            exclusions["scope_denied"] += 1
            continue
        canonical_uuid = _resolved_uuid(identity_resolver, item.identity.object_id, identity_cache)
        if canonical_uuid != str(item.identity.decision_uuid):
            exclusions["identity_unresolved"] += 1
            continue
        if not _citation_resolves(citation_resolver, item.citation_handle):
            exclusions["citation_unresolvable"] += 1
            continue
        admitted_records.append((item, "precedent"))

    admitted_pairs = {
        (record.identity.object_id, record.identity.decision_uuid)
        for record, _role in admitted_records
    }
    admitted_object_ids = {str(pair[0]) for pair in admitted_pairs}
    admitted_uuids = {str(pair[1]) for pair in admitted_pairs}
    exact_receipts: list[outcome_receipt_log.OutcomeReceipt] = []
    tainted_links: set[tuple[UUID, int]] = set()
    try:
        raw_receipts = outcome_reader()
    except Exception:
        raw_receipts = []
        exclusions["outcome_reader_unavailable"] += 1
    for raw in raw_receipts:
        try:
            receipt = outcome_receipt_log.OutcomeReceipt.model_validate(raw)
        except (ValidationError, TypeError, ValueError):
            if _raw_receipt_touches_admitted(raw, admitted_object_ids, admitted_uuids):
                exclusions["malformed_outcome_link"] += 1
                raw_link = _raw_receipt_link(raw)
                if raw_link is not None and str(raw_link[0]) in admitted_uuids:
                    tainted_links.add(raw_link)
            continue
        pair = (receipt.decision_object_id, receipt.decision_uuid)
        object_match = str(receipt.decision_object_id) in admitted_object_ids
        uuid_match = str(receipt.decision_uuid) in admitted_uuids
        if pair in admitted_pairs:
            exact_receipts.append(receipt)
        elif object_match or uuid_match:
            exclusions["malformed_outcome_link"] += 1
            if uuid_match:
                tainted_links.add((receipt.decision_uuid, receipt.rung_index))

    by_link: dict[tuple[UUID, int], list[outcome_receipt_log.OutcomeReceipt]] = defaultdict(list)
    for receipt in exact_receipts:
        by_link[(receipt.decision_uuid, receipt.rung_index)].append(receipt)

    admitted_outcomes: list[AdmittedOutcome] = []
    for receipt in exact_receipts:
        link = (receipt.decision_uuid, receipt.rung_index)
        if link in tainted_links:
            if by_link[link][0] is receipt:
                exclusions["conflicting_outcome_link"] += len(by_link[link])
            continue
        if len(by_link[link]) > 1:
            # Count the corrupt canonical rows once per row while admitting none.
            if by_link[link][0] is receipt:
                exclusions["duplicate_outcome_link"] += len(by_link[link])
            continue
        citation_handle = _receipt_citation(receipt)
        if not _citation_resolves(citation_resolver, citation_handle):
            exclusions["citation_unresolvable"] += 1
            continue
        admitted_outcomes.append(
            AdmittedOutcome(
                decision_object_id=receipt.decision_object_id,
                decision_uuid=receipt.decision_uuid,
                rung_index=receipt.rung_index,
                outcome=receipt.outcome,
                note=receipt.note,
                created_at=receipt.created_at,
                citation_handle=citation_handle,
            )
        )

    decisions_with_outcomes = {item.decision_uuid for item in admitted_outcomes}
    for record, _role in admitted_records:
        if record.identity.decision_uuid not in decisions_with_outcomes:
            exclusions["missing_outcome_receipt"] += 1

    decisions = [
        AdmittedDecision(
            object_id=record.identity.object_id,
            decision_uuid=record.identity.decision_uuid,
            role=role,
            title=record.title,
            excerpt=record.excerpt,
            citation_handle=record.citation_handle,
        )
        for record, role in admitted_records
    ]
    exclusion_map = dict(sorted((key, value) for key, value in exclusions.items() if value))
    status: Literal["ok", "partial", "blocked"] = "partial" if exclusion_map else "ok"
    diagnostic = "partial_history" if exclusion_map else "ok"
    return DecisionHistoryAdmission(
        decisions=decisions,
        outcomes=admitted_outcomes,
        coverage=AdmissionCoverage(
            status=status,
            diagnostic=diagnostic,
            admitted_decision_count=len(decisions),
            admitted_outcome_count=len(admitted_outcomes),
            excluded_count=sum(exclusion_map.values()),
            exclusions=exclusion_map,
        ),
    )


__all__ = [
    "AdmittedDecision",
    "AdmittedOutcome",
    "AdmissionCoverage",
    "DecisionHistoryAdmission",
    "DecisionHistoryCandidate",
    "DecisionIdentity",
    "admit_decision_history",
]
