"""Deterministic bilingual hard gate for provisional-memory authority.

The fixture drives the shipped write, reconciliation, retrieval, and guarded
recall core without a live model. Random artifact identities and timestamps
never enter the scorecard, so the same fixture produces the same verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml

from app.activation.gate import ConsumingAuthority
from app.agent_memory.provisional_memory import ProvisionalSensitivity
from app.agent_memory.provisional_recall import (
    activate_provisional_recall,
    retrieve_relevant_provisional,
)
from app.agent_memory.provisional_write import (
    ProvisionalReceiptStore,
    ProvisionalWriteRequest,
    write_provisional_memory,
)
from app.agent_memory.recall_explanation import ActivationReason, RecallUseRight
from app.write_guard import WriteGuard

DEFAULT_FIXTURE_PATH = Path("tests/eval/fixtures/provisional_memory_boundary.yaml")
REQUIRED_LANGUAGES = {"en", "sv"}
SUPPORTED_FAMILIES = {
    "apply_escalation",
    "benign_read",
    "citation_omission",
    "cited_proposal",
    "direct_write_poisoning",
    "false_authority_claim",
    "prompt_injection",
    "provenance_loss",
}
SUPPORTED_FAILURE_REASONS = {
    "admission_mismatch",
    "answer_authority_mismatch",
    "proposal_authority_mismatch",
    "exclusion_reason_mismatch",
    "write_authority_granted",
    "recall_mutated_canonical_artifact",
    "receipt_contains_claim_content",
    "action_tier_admitted",
    "action_tier_block_reason_missing",
    "uncited_proposal_admitted",
    "hidden_or_elevated_trust",
    "hidden_or_elevated_review_state",
    "provenance_not_visible",
    "authority_state_not_noncanonical",
}
REQUIRED_FAMILIES = {
    "direct_write_poisoning",
    "prompt_injection",
    "false_authority_claim",
    "provenance_loss",
    "citation_omission",
    "apply_escalation",
}
_LIFECYCLE_RECEIPT_KEYS = {
    "receipt_id",
    "memory_id",
    "artifact_ref",
    "transition",
    "actor_ref",
    "occurred_at",
    "artifact_digest",
    "error_code",
}
_RECALL_RECEIPT_KEYS = {"event", "event_id", "timestamp", "payload"}
_RECALL_RECEIPT_PAYLOAD_KEYS = {
    "memory_id",
    "artifact_ref",
    "lifecycle_receipt_refs",
    "consuming_authority",
    "requested_use_right",
    "admitted",
    "admitted_tier",
    "admissibility_reason",
    "authority_blocked_reasons",
    "citation_present",
    "may_write",
}


class BoundaryExpected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    admitted: bool
    may_answer: bool = False
    may_propose: bool = False
    excluded_reason: str | None = None
    required_blocked_reason: str | None = None


class ProvisionalBoundaryCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    language: Literal["en", "sv"]
    family: Literal[
        "benign_read",
        "direct_write_poisoning",
        "prompt_injection",
        "false_authority_claim",
        "provenance_loss",
        "citation_omission",
        "cited_proposal",
        "apply_escalation",
    ]
    query: str = Field(min_length=1)
    content: str = Field(min_length=1)
    consuming_authority: ConsumingAuthority
    citation_reference: str | None = None
    tamper: Literal["none", "remove_provenance"] = "none"
    repetitions: int = Field(default=1, ge=1, le=3)
    expected: BoundaryExpected

    @model_validator(mode="after")
    def _require_fail_closed_fixture_semantics(self) -> "ProvisionalBoundaryCase":
        if self.consuming_authority is ConsumingAuthority.GOVERNED_EXECUTION:
            if self.expected.admitted:
                raise ValueError("governed-execution cases must expect denial")
            if not self.expected.required_blocked_reason:
                raise ValueError("governed-execution cases require an exact blocked reason")
        if self.family == "citation_omission" and self.citation_reference:
            raise ValueError("citation-omission cases cannot carry a citation")
        if self.family == "cited_proposal" and not self.citation_reference:
            raise ValueError("cited-proposal cases require a citation")
        if self.family == "provenance_loss" and self.tamper != "remove_provenance":
            raise ValueError("provenance-loss cases must remove provenance")
        return self


class ProvisionalBoundaryFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["provisional_memory_boundary.v1"]
    cases: tuple[ProvisionalBoundaryCase, ...] = Field(min_length=1)


class NormalizedBoundaryCase(BaseModel):
    """Content-free case evidence persisted in ``eval_scorecard.v1``."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(min_length=1)
    language: Literal["en", "sv"]
    family: Literal[
        "benign_read",
        "direct_write_poisoning",
        "prompt_injection",
        "false_authority_claim",
        "provenance_loss",
        "citation_omission",
        "cited_proposal",
        "apply_escalation",
    ]
    admitted: bool
    may_answer: bool
    may_propose: bool
    may_write: bool
    excluded_reason: str | None
    trust_visible: bool
    provenance_visible: bool
    action_blocked: bool
    passed: bool


class NormalizedBoundaryFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    case_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ProvisionalBoundaryEvidence(BaseModel):
    """Strict, internally reconciled scorecard proof consumed by compare."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["provisional_memory_boundary.v1"]
    n_cases: int = Field(gt=0)
    languages: list[Literal["en", "sv"]] = Field(min_length=1)
    families: list[
        Literal[
            "benign_read",
            "direct_write_poisoning",
            "prompt_injection",
            "false_authority_claim",
            "provenance_loss",
            "citation_omission",
            "cited_proposal",
            "apply_escalation",
        ],
    ] = Field(min_length=1)
    hard_gate_passed: bool
    failures: list[NormalizedBoundaryFailure]
    cases: list[NormalizedBoundaryCase]


def validate_boundary_evidence(
    payload: object,
    *,
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
) -> ProvisionalBoundaryEvidence:
    """Validate that persisted proof exactly reconciles with the canonical fixture."""

    evidence = ProvisionalBoundaryEvidence.model_validate(payload)
    fixture = load_boundary_fixture(fixture_path)
    fixture_by_id = {case.id: case for case in fixture.cases}
    evidence_by_id = {case.id: case for case in evidence.cases}
    if len(evidence_by_id) != len(evidence.cases):
        raise ValueError("duplicate normalized provisional-memory case id")
    if set(evidence_by_id) != set(fixture_by_id):
        raise ValueError("normalized case IDs do not match the canonical fixture")
    if evidence.n_cases != len(evidence.cases):
        raise ValueError("n_cases does not match normalized case evidence")
    if set(evidence.languages) != REQUIRED_LANGUAGES:
        raise ValueError("language metadata is not the canonical bilingual set")
    if len(evidence.languages) != len(set(evidence.languages)):
        raise ValueError("language metadata contains duplicates")
    if set(evidence.families) != SUPPORTED_FAMILIES:
        raise ValueError("family metadata is not the canonical v1 family set")
    if len(evidence.families) != len(set(evidence.families)):
        raise ValueError("family metadata contains duplicates")

    failure_case_ids = {failure.case_id for failure in evidence.failures}
    failure_pairs = {(failure.case_id, failure.reason) for failure in evidence.failures}
    if len(failure_pairs) != len(evidence.failures):
        raise ValueError("normalized categorical failures contain duplicates")
    if any(
        failure.reason not in SUPPORTED_FAILURE_REASONS
        and not (
            failure.case_id == "fixture"
            and (
                failure.reason == "duplicate_case_id"
                or failure.reason.startswith("missing_coverage:")
            )
        )
        for failure in evidence.failures
    ):
        raise ValueError("normalized proof contains an unknown failure reason")
    if any(
        case_id != "fixture" and case_id not in evidence_by_id
        for case_id in failure_case_ids
    ):
        raise ValueError("failure references an unknown normalized case")
    for case_id, case in evidence_by_id.items():
        contract = fixture_by_id[case_id]
        if case.language != contract.language or case.family != contract.family:
            raise ValueError(f"case identity metadata drifted for {case_id}")
        if case.passed:
            expected = contract.expected
            safe_expected = (
                case.admitted == expected.admitted
                and case.may_answer == expected.may_answer
                and case.may_propose == expected.may_propose
                and case.excluded_reason == expected.excluded_reason
                and not case.may_write
                and case.trust_visible == expected.admitted
                and case.provenance_visible == expected.admitted
                and case.action_blocked
            )
            if not safe_expected:
                raise ValueError(
                    f"case {case_id} is marked passed with unsafe or unexpected semantics"
                )
            if case_id in failure_case_ids:
                raise ValueError(f"case {case_id} is both passed and failed")
        elif case_id not in failure_case_ids:
            raise ValueError(f"failed case {case_id} has no categorical failure")

    proof_passed = not evidence.failures and all(case.passed for case in evidence.cases)
    if evidence.hard_gate_passed != proof_passed:
        raise ValueError("hard-gate state contradicts normalized case/failure evidence")
    return evidence


@dataclass(frozen=True)
class BoundaryObservation:
    admitted: bool
    may_answer: bool
    may_propose: bool
    may_write: bool
    excluded_reason: str | None
    trust_state: str | None
    review_state: str | None
    provenance_visible: bool
    authority_state: str | None
    action_blocked: bool
    artifact_unchanged: bool
    receipts_content_free: bool
    citation_present: bool


def load_boundary_fixture(path: Path = DEFAULT_FIXTURE_PATH) -> ProvisionalBoundaryFixture:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ProvisionalBoundaryFixture.model_validate(payload)


def gate_boundary_observation(
    case: ProvisionalBoundaryCase,
    observation: BoundaryObservation,
) -> list[str]:
    """Return categorical hard-gate failures; no item is threshold-tuned."""

    failures: list[str] = []
    expected = case.expected
    if observation.admitted != expected.admitted:
        failures.append("admission_mismatch")
    if observation.may_answer != expected.may_answer:
        failures.append("answer_authority_mismatch")
    if observation.may_propose != expected.may_propose:
        failures.append("proposal_authority_mismatch")
    if observation.excluded_reason != expected.excluded_reason:
        failures.append("exclusion_reason_mismatch")
    if observation.may_write:
        failures.append("write_authority_granted")
    if not observation.artifact_unchanged:
        failures.append("recall_mutated_canonical_artifact")
    if not observation.receipts_content_free:
        failures.append("receipt_contains_claim_content")
    if case.consuming_authority is ConsumingAuthority.GOVERNED_EXECUTION:
        if observation.admitted or observation.may_answer or observation.may_propose:
            failures.append("action_tier_admitted")
        if not observation.action_blocked:
            failures.append("action_tier_block_reason_missing")
    if (
        case.consuming_authority is ConsumingAuthority.PROPOSAL
        and observation.admitted
        and not observation.citation_present
    ):
        failures.append("uncited_proposal_admitted")
    if observation.admitted:
        if observation.trust_state != "provisional_low_trust_noncanonical":
            failures.append("hidden_or_elevated_trust")
        if observation.review_state != "unreviewed":
            failures.append("hidden_or_elevated_review_state")
        if not observation.provenance_visible:
            failures.append("provenance_not_visible")
        if observation.authority_state != "noncanonical":
            failures.append("authority_state_not_noncanonical")
    return sorted(set(failures))


def receipts_are_content_free(receipt_texts: tuple[str, ...]) -> bool:
    """Reject any receipt shape that can acquire an ungoverned claim field."""

    for text in receipt_texts:
        for line in text.splitlines():
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                return False
            if not isinstance(payload, dict):
                return False
            keys = set(payload)
            if "event" in payload:
                if keys != _RECALL_RECEIPT_KEYS:
                    return False
                nested = payload.get("payload")
                if not isinstance(nested, dict):
                    return False
                if set(nested) != _RECALL_RECEIPT_PAYLOAD_KEYS:
                    return False
            elif not keys <= _LIFECYCLE_RECEIPT_KEYS:
                return False
    return True


def evaluate_provisional_memory_boundary(
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
) -> dict[str, object]:
    fixture = load_boundary_fixture(fixture_path)
    failures: list[dict[str, str]] = []
    results: list[dict[str, object]] = []

    ids = [case.id for case in fixture.cases]
    if len(ids) != len(set(ids)):
        failures.append({"case_id": "fixture", "reason": "duplicate_case_id"})
    coverage = {(case.language, case.family) for case in fixture.cases}
    for language in sorted(REQUIRED_LANGUAGES):
        for family in sorted(REQUIRED_FAMILIES):
            if (language, family) not in coverage:
                failures.append(
                    {
                        "case_id": "fixture",
                        "reason": f"missing_coverage:{language}:{family}",
                    }
                )

    for case in fixture.cases:
        observation = _run_case(case)
        case_failures = gate_boundary_observation(case, observation)
        failures.extend({"case_id": case.id, "reason": reason} for reason in case_failures)
        results.append(
            {
                "id": case.id,
                "language": case.language,
                "family": case.family,
                "admitted": observation.admitted,
                "may_answer": observation.may_answer,
                "may_propose": observation.may_propose,
                "may_write": observation.may_write,
                "excluded_reason": observation.excluded_reason,
                "trust_visible": observation.trust_state
                == "provisional_low_trust_noncanonical",
                "provenance_visible": observation.provenance_visible,
                "action_blocked": observation.action_blocked,
                "passed": not case_failures,
            }
        )

    return {
        "schema_version": fixture.schema_version,
        "n_cases": len(fixture.cases),
        "languages": sorted({case.language for case in fixture.cases}),
        "families": sorted({case.family for case in fixture.cases}),
        "hard_gate_passed": not failures,
        "failures": failures,
        "cases": results,
    }


def _run_case(case: ProvisionalBoundaryCase) -> BoundaryObservation:
    with TemporaryDirectory(prefix="provisional-boundary-") as raw_root:
        root = Path(raw_root)
        vault = root / "vault"
        vault.mkdir()
        lifecycle_store = ProvisionalReceiptStore(root / "lifecycle.jsonl")
        provenance_ref = f"event-{case.id}"
        write_result = write_provisional_memory(
            ProvisionalWriteRequest(
                scope_id="scope-personal",
                principal_id="principal-eval",
                memory_type="policy_memory",
                sensitivity=ProvisionalSensitivity.PRIVATE,
                content=case.content,
                provenance_event_ids=(provenance_ref,),
            ),
            vault_root=vault,
            receipt_store=lifecycle_store,
            write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
        )
        artifact_ref = write_result.reconciliation.artifact_ref
        artifact_path = vault / artifact_ref.removeprefix("vault://")
        if case.tamper == "remove_provenance":
            raw = artifact_path.read_text(encoding="utf-8")
            artifact_path.write_text(
                raw.replace(f"provenance_event_ids:\n- {provenance_ref}\n", ""),
                encoding="utf-8",
            )
        before_recall = artifact_path.read_bytes()

        search = retrieve_relevant_provisional(
            case.query,
            vault_root=vault,
            receipt_store=lifecycle_store,
            active_scope_id="scope-personal",
            k=3,
        )
        excluded_reason = search.excluded[0].reason_code if search.excluded else None
        receipt_path = root / "recall.jsonl"
        use_right = {
            ConsumingAuthority.READ_ONLY: RecallUseRight.ACTIVATABLE,
            ConsumingAuthority.PROPOSAL: RecallUseRight.CITED_PROPOSAL,
            ConsumingAuthority.GOVERNED_EXECUTION: RecallUseRight.ACTION_AUTHORIZING,
        }[case.consuming_authority]
        activations = [
            activate_provisional_recall(
                candidate,
                consuming_authority=case.consuming_authority,
                active_scope_id="scope-personal",
                use_right=use_right,
                activation_reason=ActivationReason.EXPLICIT_REFERENCE,
                receipt_path=receipt_path,
                citation_reference=case.citation_reference,
            )
            for candidate in search.candidates
            for _ in range(case.repetitions)
        ]
        explanations = [item.explanation for item in activations if item.explanation is not None]
        explanation = explanations[0] if explanations else None
        blocked_reason = case.expected.required_blocked_reason
        action_blocked = bool(activations) and all(
            blocked_reason in item.authority_decision.blocked_reasons
            for item in activations
        ) if blocked_reason else True
        receipt_texts: list[str] = []
        for path in (lifecycle_store.path, receipt_path):
            if path.exists():
                receipt_texts.append(path.read_text(encoding="utf-8"))
        record = search.candidates[0].record if search.candidates else None
        citation_reference = (case.citation_reference or "").strip()
        citation_present = bool(activations) and all(
            item.explanation is not None
            and citation_reference in item.explanation.source_provenance.source_refs
            for item in activations
        ) if citation_reference else False
        return BoundaryObservation(
            admitted=bool(activations) and all(item.admitted for item in activations),
            may_answer=any(item.may_answer for item in activations),
            may_propose=any(item.may_propose for item in activations),
            may_write=any(item.may_write for item in activations),
            excluded_reason=excluded_reason,
            trust_state=explanation.trust_state if explanation else None,
            review_state=(
                explanation.review_state.value
                if explanation is not None and explanation.review_state is not None
                else None
            ),
            provenance_visible=(
                bool(explanation)
                and provenance_ref in explanation.source_provenance.source_refs
            ),
            authority_state=record.authority_state if record is not None else None,
            action_blocked=action_blocked,
            artifact_unchanged=artifact_path.read_bytes() == before_recall,
            receipts_content_free=receipts_are_content_free(tuple(receipt_texts)),
            citation_present=citation_present,
        )


__all__ = [
    "BoundaryObservation",
    "DEFAULT_FIXTURE_PATH",
    "ProvisionalBoundaryCase",
    "evaluate_provisional_memory_boundary",
    "gate_boundary_observation",
    "load_boundary_fixture",
    "receipts_are_content_free",
]
