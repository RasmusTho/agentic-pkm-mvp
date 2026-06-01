"""Explicit BuilderOps PromotionIntent gateway.

The gateway renders promotion proposals and records BuilderOps receipts/state
transitions. It never creates GitHub Issues, writes repo docs, opens PRs, or
mutates product/runtime authority surfaces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from app.builderops.models import (
    BuilderOpsValidationError,
    normalize_actor,
)
from app.builderops.store import SqliteBuilderOpsStore


class BuilderOpsPromotionError(BuilderOpsValidationError):
    """Raised when a PromotionIntent cannot cross the gateway."""


@dataclass(frozen=True)
class PromotionTargetSpec:
    canonical: str
    proposal_kind: str
    requires_pr: bool
    requires_human_gate: bool = True


TARGET_SPECS: dict[str, PromotionTargetSpec] = {
    "github_issue": PromotionTargetSpec(
        canonical="github_issue",
        proposal_kind="github_issue_draft",
        requires_pr=False,
    ),
    "pr_branch_proposal": PromotionTargetSpec(
        canonical="pr_branch_proposal",
        proposal_kind="pr_branch_proposal",
        requires_pr=True,
    ),
    "adr_doc_proposal": PromotionTargetSpec(
        canonical="adr_doc_proposal",
        proposal_kind="adr_doc_writeback_proposal",
        requires_pr=True,
    ),
    "owner_doc_writeback_proposal": PromotionTargetSpec(
        canonical="owner_doc_writeback_proposal",
        proposal_kind="owner_doc_writeback_proposal",
        requires_pr=True,
    ),
    "generated_projection": PromotionTargetSpec(
        canonical="generated_projection",
        proposal_kind="generated_projection_update",
        requires_pr=True,
    ),
    "discard_receipt": PromotionTargetSpec(
        canonical="discard_receipt",
        proposal_kind="discard_receipt",
        requires_pr=False,
    ),
}

TARGET_ALIASES = {
    "github": "github_issue",
    "github_issue": "github_issue",
    "issue": "github_issue",
    "pr": "pr_branch_proposal",
    "pull_request": "pr_branch_proposal",
    "branch": "pr_branch_proposal",
    "pr_branch_proposal": "pr_branch_proposal",
    "adr": "adr_doc_proposal",
    "decision_doc": "adr_doc_proposal",
    "adr_doc_proposal": "adr_doc_proposal",
    "repo_doc": "owner_doc_writeback_proposal",
    "owner_doc": "owner_doc_writeback_proposal",
    "doc_writeback": "owner_doc_writeback_proposal",
    "owner_doc_writeback_proposal": "owner_doc_writeback_proposal",
    "skill": "owner_doc_writeback_proposal",
    "agents_md": "owner_doc_writeback_proposal",
    "generated_projection": "generated_projection",
    "projection": "generated_projection",
    "discard": "discard_receipt",
    "discard_receipt": "discard_receipt",
}

FINAL_PROMOTION_STATES = frozenset({"promoted", "discarded", "superseded"})


class BuilderOpsPromotionGateway:
    """Proposal-only gateway for PromotionIntent material."""

    def __init__(self, store: SqliteBuilderOpsStore) -> None:
        self._store = store
        self._store.initialize()

    def render_proposal(self, intent_id: str) -> dict[str, Any]:
        intent = self._require_intent(intent_id)
        spec = self._target_spec(intent)
        return {
            "intent_id": intent["id"],
            "proposal_kind": spec.proposal_kind,
            "target_authority_surface": spec.canonical,
            "target_action": intent["target_action"],
            "target_ref": intent["target_ref"],
            "requires_human_gate": spec.requires_human_gate,
            "requires_pr": spec.requires_pr,
            "would_mutate_authority": False,
            "title": intent["summary"],
            "body": self._render_body(intent, spec),
            "source_refs": intent["source_refs"],
        }

    def dry_run_promotion(
        self,
        intent_id: str,
        *,
        actor: Mapping[str, Any] | str,
        idempotency_key: str,
        source_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        intent = self._require_intent(intent_id)
        proposal = self.render_proposal(intent_id)
        actor_ref = normalize_actor(actor)
        refs = source_refs if source_refs is not None else intent["source_refs"]
        receipt = self._store.append_receipt(
            summary=f"Dry-run promotion proposal for {intent['id']}",
            event_type="promotion_dry_run",
            actor=actor_ref,
            occurred_at=intent["updated_at"],
            target_refs=[
                {
                    "ref_type": "builderops_object",
                    "ref": intent["id"],
                    "authority_surface": "builderops",
                }
            ],
            action=f"dry_run_{proposal['target_authority_surface']}",
            receipt_body=(
                f"Generated {proposal['proposal_kind']} without mutating "
                f"{proposal['target_authority_surface']} authority."
            ),
            idempotency_key=idempotency_key,
            source_refs=refs,
            created_by=actor_ref,
            promotion_proposal=proposal,
        )
        return {"intent": intent, "proposal": proposal, "receipt": receipt}

    def transition_intent(
        self,
        intent_id: str,
        *,
        decision: str,
        actor: Mapping[str, Any] | str,
        lease_id: str,
        idempotency_key: str,
        rationale: str,
        source_refs: list[dict[str, Any]] | None = None,
        result_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        intent = self._require_intent(intent_id)
        normalized_decision = decision.strip().lower()
        if normalized_decision not in {"accepted", "promoted", "rejected", "discarded"}:
            raise BuilderOpsPromotionError(
                "decision must be one of: accepted, promoted, rejected, discarded"
            )
        lifecycle_state, promotion_status = _state_for_decision(normalized_decision)
        self._validate_transition(
            intent,
            normalized_decision,
            lifecycle_state=lifecycle_state,
            promotion_status=promotion_status,
        )
        if normalized_decision == "promoted" and not result_refs:
            raise BuilderOpsPromotionError(
                "promoted PromotionIntent transition requires result_refs"
            )
        proposal = self.render_proposal(intent_id)
        refs = source_refs if source_refs is not None else intent["source_refs"]
        receipt_extra: dict[str, Any] = {
            "promotion_decision": normalized_decision,
            "promotion_rationale": rationale,
            "promotion_proposal": proposal,
        }
        if result_refs:
            receipt_extra["result_refs"] = result_refs

        return self._store.transition_record_state(
            intent_id,
            actor=actor,
            lease_id=lease_id,
            idempotency_key=idempotency_key,
            source_refs=refs,
            summary=f"PromotionIntent {normalized_decision}: {intent['summary']}",
            action=f"promotion_{normalized_decision}",
            receipt_body=rationale,
            lifecycle_state=lifecycle_state,
            promotion_status=promotion_status,
            receipt_extra=receipt_extra,
        )

    def _require_intent(self, intent_id: str) -> dict[str, Any]:
        record = self._store.get_record(intent_id)
        if record is None:
            raise BuilderOpsPromotionError(f"PromotionIntent not found: {intent_id}")
        if record.get("object_type") != "PromotionIntent":
            raise BuilderOpsPromotionError(
                f"promotion gateway requires PromotionIntent, got {record.get('object_type')}"
            )
        source_refs = record.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            raise BuilderOpsPromotionError("PromotionIntent requires source_refs")
        return record

    def _target_spec(self, intent: Mapping[str, Any]) -> PromotionTargetSpec:
        raw = str(intent.get("target_authority_surface", "")).strip().lower()
        normalized = raw.replace("-", "_").replace(" ", "_")
        canonical = TARGET_ALIASES.get(normalized)
        if canonical is None:
            allowed = ", ".join(sorted(TARGET_SPECS))
            raise BuilderOpsPromotionError(
                f"unsupported promotion target_authority_surface: {raw}; allowed: {allowed}"
            )
        return TARGET_SPECS[canonical]

    def _validate_transition(
        self,
        intent: Mapping[str, Any],
        decision: str,
        *,
        lifecycle_state: str,
        promotion_status: str,
    ) -> None:
        target_state = {
            "lifecycle_state": lifecycle_state,
            "promotion_status": promotion_status,
        }
        current_state = {
            "lifecycle_state": str(intent.get("lifecycle_state", "")),
            "promotion_status": str(intent.get("promotion_status", "")),
        }
        if current_state == target_state:
            return
        lifecycle_state = str(intent.get("lifecycle_state", ""))
        promotion_status = str(intent.get("promotion_status", ""))
        if lifecycle_state in FINAL_PROMOTION_STATES or promotion_status in {
            "promoted",
            "rejected",
            "discarded",
            "superseded",
        }:
            raise BuilderOpsPromotionError(
                f"PromotionIntent is already terminal: {lifecycle_state}/{promotion_status}"
            )
        if decision == "accepted" and lifecycle_state not in {"draft", "review_pending"}:
            raise BuilderOpsPromotionError("PromotionIntent can only be accepted from draft/review_pending")
        if decision == "promoted" and lifecycle_state != "accepted":
            raise BuilderOpsPromotionError("PromotionIntent must be accepted before promoted")
        if decision in {"rejected", "discarded"} and lifecycle_state not in {
            "draft",
            "review_pending",
            "accepted",
        }:
            raise BuilderOpsPromotionError(
                f"PromotionIntent cannot be {decision} from {lifecycle_state}"
            )

    def _render_body(
        self,
        intent: Mapping[str, Any],
        spec: PromotionTargetSpec,
    ) -> str:
        if spec.canonical == "github_issue":
            return _render_github_issue_body(intent)
        if spec.canonical == "discard_receipt":
            return _render_discard_body(intent)
        return _render_repo_proposal_body(intent, spec)


def _state_for_decision(decision: str) -> tuple[str, str]:
    if decision == "accepted":
        return "accepted", "promotion_pending"
    if decision == "promoted":
        return "promoted", "promoted"
    if decision == "rejected":
        return "discarded", "rejected"
    if decision == "discarded":
        return "discarded", "discarded"
    raise BuilderOpsPromotionError(f"unsupported promotion decision: {decision}")


def _render_github_issue_body(intent: Mapping[str, Any]) -> str:
    return "\n".join([
        f"Parent: {_parent_ref(intent)}",
        "",
        "## Context",
        f"Generated from BuilderOps PromotionIntent `{intent['id']}`.",
        "",
        "## Scope",
        str(intent["intended_output"]),
        "",
        "## Source Anchors",
        *_format_source_refs(intent["source_refs"]),
        "",
        "## BuilderOps source_refs",
        _source_refs_json(intent["source_refs"]),
        "",
        "## Authority Boundary",
        "This is a GitHub Issue draft only. Creating or editing the Issue remains an explicit promotion action.",
    ])


def _render_repo_proposal_body(
    intent: Mapping[str, Any],
    spec: PromotionTargetSpec,
) -> str:
    return "\n".join([
        f"# {intent['summary']}",
        "",
        f"Proposal kind: `{spec.proposal_kind}`",
        f"Target: `{intent['target_authority_surface']}` / `{intent['target_ref']}`",
        "",
        "## Proposed Output",
        str(intent["intended_output"]),
        "",
        "## Source Anchors",
        *_format_source_refs(intent["source_refs"]),
        "",
        "## Authority Boundary",
        "This is proposal material only. Repo docs, ADRs, skills, and branches change only through the normal PR workflow.",
    ])


def _render_discard_body(intent: Mapping[str, Any]) -> str:
    return "\n".join([
        f"# Discard receipt proposal for {intent['id']}",
        "",
        "## Rationale",
        str(intent.get("promotion_rationale") or intent["intended_output"]),
        "",
        "## Source Anchors",
        *_format_source_refs(intent["source_refs"]),
        "",
        "## Authority Boundary",
        "Discarding BuilderOps material records a receipt; it does not erase source records.",
    ])


def _format_source_refs(source_refs: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for ref in source_refs:
        authority = ref.get("authority_surface")
        locator = ref.get("locator")
        suffix_parts = []
        if authority:
            suffix_parts.append(f"authority_surface={authority}")
        if locator:
            suffix_parts.append(f"locator={locator}")
        suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
        rows.append(f"- {ref['ref_type']}: {ref['ref']}{suffix}")
    return rows


def _source_refs_json(source_refs: list[dict[str, Any]]) -> str:
    return json.dumps(source_refs, ensure_ascii=False, sort_keys=True, indent=2)


def _parent_ref(intent: Mapping[str, Any]) -> str:
    for ref in intent["source_refs"]:
        if ref.get("ref_type") == "github_issue" and str(ref.get("ref", "")).startswith("#"):
            return str(ref["ref"])
    return "unknown"


__all__ = [
    "BuilderOpsPromotionError",
    "BuilderOpsPromotionGateway",
    "TARGET_SPECS",
]
