"""Exact, nonvisual Start/Hold proposal projection for the sanctioned inquiry.

This module performs no I/O. Current material and permission are supplied by the
authenticated admission owner, never inferred from browser or model text.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from app.builderops.devui_conversation_port import (
    canonical_context_pack_bytes,
    validate_context_pack_bytes,
)

WORKFLOW_REF = ".codex/skills/start-model-inquiry/SKILL.md"
COMMAND_VERSION = "typed-command-proposal.v1"
OPERATION_VERSION = "operation-reservation.v1"
OPERATION_VERBS = [
    "--operation-capabilities",
    "--operation-reserve-stdin",
    "--operation-attempt-stdin",
    "--approved-operation-stdin",
    "--operation-readback-stdin",
]
PERMITTED_EFFECTS = [
    "invoke_sanctioned_inquiry_once",
    "model_inquiry_artifacts",
    "workflow_owned_lock_and_staging",
]
NON_EFFECTS = [
    "github",
    "repository",
    "branch",
    "worktree",
    "pull_request",
    "delivery_run",
    "ckm_authority",
    "provider_session_authority",
    "task",
    "product_vault",
    "owner_acceptance",
]
RECEIPT_FIELDS = ["inquiry_id", "final_state", "terminal_receipt_id", "human_readable_report"]
INVALIDATIONS = [
    "question",
    "subject",
    "context_pack",
    "sources",
    "workflow",
    "destination",
    "permission",
    "authority_epoch",
    "policy",
    "configuration",
    "capability",
    "expiry",
]
REFUSALS = [
    "unauthenticated",
    "permission_unavailable",
    "stale_or_changed",
    "expired",
    "workflow_unavailable",
    "binding_conflict",
    "reconciliation_needed",
]
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}\Z")
_MATERIAL_FIELDS = {
    "repository",
    "issue_number",
    "issue_body_hash",
    "acceptance_criteria_hash",
    "question",
    "context_pack",
    "workflow",
    "destination",
    "policy",
    "configuration",
    "capability",
}


class CommandContractError(ValueError):
    """The exact preview cannot authorize this operation."""


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _text(value: Any, label: str, *, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > limit:
        raise CommandContractError(f"{label} must be bounded nonempty text")
    return value


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise CommandContractError(f"{label} must be SHA-256")
    return value


def _time(value: Any) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise CommandContractError("absolute timestamp required") from exc


def _material(value: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    if set(value) != _MATERIAL_FIELDS:
        raise CommandContractError("complete exact material fields required")
    material = json.loads(json.dumps(value, allow_nan=False))
    repository = material["repository"]
    if (
        not isinstance(repository, str)
        or not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", repository)
        or any(part in {".", ".."} for part in repository.split("/"))
    ):
        raise CommandContractError("canonical repository required")
    _text(material["question"], "question", limit=16384)
    pack = validate_context_pack_bytes(
        canonical_context_pack_bytes(material["context_pack"]), now=now
    )
    subject = pack["subject_ref"]
    issue = material["issue_number"]
    if subject["kind"] == "issue":
        if (
            type(issue) is not int
            or issue < 1
            or subject["stable_id"].lower() != f"github:{repository}#{issue}"
        ):
            raise CommandContractError("exact addressed Issue required")
        _hash(material["issue_body_hash"], "Issue body")
        _hash(material["acceptance_criteria_hash"], "acceptance criteria")
    elif (
        issue is not None
        or material["issue_body_hash"] is not None
        or material["acceptance_criteria_hash"] is not None
    ):
        raise CommandContractError("pre-ticket Issue fields must be explicitly null")
    for name in ("workflow", "policy", "configuration", "capability"):
        binding = material[name]
        fields = (
            {"version", "content_hash"}
            if name == "workflow"
            else {"ref", "version", "content_hash"}
        )
        if not isinstance(binding, dict) or set(binding) != fields:
            raise CommandContractError(f"exact {name} binding required")
        for key, item in binding.items():
            _hash(item, name) if key == "content_hash" else _text(item, name)
    if material["destination"] != {
        "identity": "Tailscale_macmini",
        "revision": "operation-reservation.v1",
    }:
        raise CommandContractError("sanctioned operation-aware destination required")
    return material


def build_command_proposal(
    *,
    approval_id: str,
    material: Mapping[str, Any],
    owner_principal: str,
    permission_ref: str,
    permission_version: str,
    authority_epoch: int,
    now: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    """Build the complete proposal; its hash is evidence, not owner approval."""
    try:
        current = _material(material, _time(now))
        if not isinstance(approval_id, str) or not _ID.fullmatch(approval_id):
            raise CommandContractError("bounded approval id required")
        for name, permission_value in (
            ("owner principal", owner_principal),
            ("permission reference", permission_ref),
            ("permission version", permission_version),
        ):
            _text(permission_value, name, limit=256)
        if type(authority_epoch) is not int or authority_epoch < 1:
            raise CommandContractError("authority epoch required")
        created, expiry = _time(now), _time(expires_at)
        pack = current["context_pack"]
        if not created < expiry <= min(created + timedelta(hours=1), _time(pack["expires_at"])):
            raise CommandContractError("expiry must be bounded by the context pack")
        destination = {
            **current["destination"],
            "workflow_ref": WORKFLOW_REF,
            "entrypoint": WORKFLOW_REF,
            "contract_version": current["workflow"]["version"],
            "workflow_hash": current["workflow"]["content_hash"],
        }
        value: dict[str, Any] = {
            "contract_version": COMMAND_VERSION,
            "proposal_id": approval_id,
            "command_type": "start_model_inquiry",
            "repository": current["repository"],
            "subject_ref": pack["subject_ref"],
            "issue_number": current["issue_number"],
            "issue_body_hash": current["issue_body_hash"],
            "acceptance_criteria_hash": current["acceptance_criteria_hash"],
            "exact_inputs": [
                {
                    "name": "question",
                    "text": current["question"],
                    "content_hash": hashlib.sha256(current["question"].encode("utf-8")).hexdigest(),
                }
            ],
            "context_pack_ref": {"pack_id": pack["pack_id"], "content_hash": pack["content_hash"]},
            "source_refs": pack["source_states"],
            "limitations": pack["limitations"],
            "destination": destination,
            "side_effects": PERMITTED_EFFECTS.copy(),
            "explicit_non_effects": NON_EFFECTS.copy(),
            "policy": current["policy"],
            "configuration": current["configuration"],
            "capability": current["capability"],
            "approval_rule": {
                "actor": "authenticated_owner",
                "mode": "start_hold",
                "authenticated_principal_ref": owner_principal,
                "permission_ref": permission_ref,
                "permission_version": permission_version,
                "authority_epoch": authority_epoch,
                "binds": [
                    "authenticated_principal_ref",
                    "proposal_hash",
                    "context_pack_hash",
                    "input_hashes",
                    "source_versions",
                    "expires_at",
                ],
            },
            "freshness": {
                "created_at": created.isoformat(),
                "expires_at": expiry.isoformat(),
                "invalidation_conditions": INVALIDATIONS.copy(),
            },
            "expected_receipt": {
                "schema_ref": "model-inquiry terminal launcher response",
                "required_fields": RECEIPT_FIELDS.copy(),
            },
            "refusal_conditions": REFUSALS.copy(),
        }
        value["operation_key"] = canonical_hash(
            {
                "repository": current["repository"],
                "approval_id": approval_id,
                "operation_type": "start_model_inquiry",
                "destination": destination["identity"],
                "workflow_ref": WORKFLOW_REF,
            }
        )
        value["inquiry_id"] = f"inq_operation_{value['operation_key']}"
        value["proposal_hash"] = canonical_hash(value)
        return value
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise CommandContractError(str(exc)) from exc


def approval_manifest(
    proposal: Mapping[str, Any], material: Mapping[str, Any], *, approved_at: datetime
) -> dict[str, Any]:
    """Immutable admission content; only the authenticated service may persist it."""
    value = {
        "approval_id": proposal["proposal_id"],
        "inquiry_id": proposal["inquiry_id"],
        "owner_principal": proposal["approval_rule"]["authenticated_principal_ref"],
        "approved_at": _time(approved_at).isoformat(),
        "approval_receipt_ref": f"builderops:record:{proposal['repository']}:inquiry-approval:{proposal['proposal_id']}",
        "proposal": dict(proposal),
        "material": dict(material),
    }
    result = {**value, "approval_manifest_hash": canonical_hash(value)}
    # Leave space for the finite receipt envelope and bounded readback framing.
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 240000:
        raise CommandContractError("approval exceeds the bounded operation transport")
    return result


def validate_approval_identity(approval: Mapping[str, Any]) -> dict[str, Any]:
    """Validate identity, never permission. The service authenticates every verb."""
    try:
        expected = approval_manifest(
            approval["proposal"], approval["material"], approved_at=_time(approval["approved_at"])
        )
        proposal = approval["proposal"]
        key = canonical_hash(
            {
                "repository": proposal["repository"],
                "approval_id": proposal["proposal_id"],
                "operation_type": "start_model_inquiry",
                "destination": "Tailscale_macmini",
                "workflow_ref": WORKFLOW_REF,
            }
        )
        if (
            canonical_hash(approval) != canonical_hash(expected)
            or proposal["operation_key"] != key
            or proposal["inquiry_id"] != f"inq_operation_{key}"
            or proposal["proposal_hash"]
            != canonical_hash({k: v for k, v in proposal.items() if k != "proposal_hash"})
            or proposal["command_type"] != "start_model_inquiry"
        ):
            raise CommandContractError("approval binding conflicts")
        return expected
    except (KeyError, TypeError, ValueError) as exc:
        raise CommandContractError("invalid exact approval binding") from exc


def model_inquiry_design_fixtures(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Nonvisual state handoff over an exact preview; never an action adapter."""
    if proposal.get("proposal_hash") != canonical_hash(
        {key: item for key, item in proposal.items() if key != "proposal_hash"}
    ):
        raise CommandContractError("exact preview required for design handoff")
    common = {
        "visual_geometry": "unspecified",
        "owner_acceptance": False,
        "stop_support": "unsupported",
        "operation_key": proposal["operation_key"],
        "inquiry_id": proposal["inquiry_id"],
    }
    states: dict[str, dict[str, Any]] = {
        "exact_preview": {"proposal": dict(proposal), "start_available": True},
        "start": {
            "requires": "authenticated_exact_owner_confirmation",
            "effects": PERMITTED_EFFECTS.copy(),
        },
        "hold": {"state": "held", "effects": []},
        "stale": {"start_available": False, "reason": "stale_or_changed"},
        "terminal": {
            "state": "terminal",
            "required_receipt_fields": RECEIPT_FIELDS.copy(),
            "requires": "authenticated_destination_terminal_readback",
        },
        "ambiguous": {
            "state": "ambiguous",
            "automatic_relaunch": False,
            "workflow_cleanup": "preserved_for_reconciliation",
        },
        "workflow_unavailable": {
            "state": "workflow_unavailable",
            "start_available": False,
            "reservation_permitted": False,
        },
    }
    return {name: {**common, **item} for name, item in states.items()}


def validate_command_proposal(
    value: Mapping[str, Any],
    *,
    current_material: Mapping[str, Any],
    owner_principal: str,
    permission_ref: str,
    permission_version: str,
    authority_epoch: int,
    now: datetime,
) -> dict[str, Any]:
    """Rebuild against fresh source-owned material and compare every field."""
    try:
        created = _time(value["freshness"]["created_at"])
        expiry = _time(value["freshness"]["expires_at"])
        if not created <= _time(now) < expiry:
            raise CommandContractError("preview expired or not yet valid")
        _material(current_material, _time(now))
        expected = build_command_proposal(
            approval_id=value["proposal_id"],
            material=current_material,
            owner_principal=owner_principal,
            permission_ref=permission_ref,
            permission_version=permission_version,
            authority_epoch=authority_epoch,
            now=created,
            expires_at=expiry,
        )
        if canonical_hash(value) != canonical_hash(expected):
            raise CommandContractError("preview material is stale or changed")
        return expected
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise CommandContractError(str(exc)) from exc
