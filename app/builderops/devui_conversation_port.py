"""External-first, provenance-only Conversation Port contracts for devUI.

The module builds and validates immutable context artifacts, performs one
explicit adapter handoff, and validates non-authoritative dispositions. It owns
no provider discovery, credential access, persistence, workflow state, or
command execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any


CONTEXT_PACK_VERSION = "conversation-context-pack.v1"
DISPOSITION_VERSION = "conversation-disposition.v1"
MAX_PACK_LIFETIME = timedelta(hours=1)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ISSUE_STABLE_ID = re.compile(
    r"github:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*\Z"
)
_CAPABILITY_STABLE_ID = re.compile(r"[a-z][a-z0-9_.:-]{2,127}\Z")
_SUBJECT_SOURCE_TYPES = {
    "issue": {"github_issue"},
    "capability": {"owner_document"},
}
_DIALOGUE_OUTCOMES = (
    "disposition",
    "decision_brief",
    "plan",
    "inquiry",
    "workflow_route",
    "no_action",
)
_ADAPTER_STATES = {"available", "unavailable", "unsupported", "refused"}
_MANDATORY_EXCLUDES = {
    "credentials",
    "hidden_system_prompts",
    "provider_sessions",
    "broad_repository_history",
}
_FORBIDDEN_INCLUDES = _MANDATORY_EXCLUDES | {
    "*",
    "all",
    "provider_transcripts",
    "repository_history",
}
_PROVENANCE_ONLY_SOURCE_PARTS = {"session", "transcript"}


class ConversationPortContractError(ValueError):
    """Raised when Conversation Port data violates its governed boundary."""


Opener = Callable[[bytes, str], Mapping[str, Any]]


def _require_string_keys(value: Any, *, label: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ConversationPortContractError(
                    f"{label} objects require string keys"
                )
            _require_string_keys(item, label=label)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _require_string_keys(item, label=label)


def _detached(value: Any, *, label: str) -> Any:
    try:
        _require_string_keys(value, label=label)
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        encoded.encode("utf-8", errors="strict")
        return json.loads(encoded)
    except ConversationPortContractError:
        raise
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ConversationPortContractError(f"{label} must be JSON-safe") from exc


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    detached = _detached(value, label=label)
    if not isinstance(detached, dict):
        raise ConversationPortContractError(f"{label} must be an object")
    return detached


def _items(value: Any, *, label: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ConversationPortContractError(f"{label} must be a list")
    detached = _detached(list(value), label=label)
    if not isinstance(detached, list):
        raise ConversationPortContractError(f"{label} must be a list")
    return detached


def _keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    allowed: set[str],
    label: str,
) -> None:
    missing = required - set(value)
    unknown = set(value) - allowed
    if missing:
        raise ConversationPortContractError(
            f"{label} is missing field(s): {sorted(missing)}"
        )
    if unknown:
        raise ConversationPortContractError(
            f"{label} has unknown field(s): {sorted(unknown)}"
        )


def _nonempty(value: Any, *, label: str, max_length: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConversationPortContractError(f"{label} must be a non-empty string")
    if len(value) > max_length:
        raise ConversationPortContractError(f"{label} is over-broad")
    return value


def _timestamp(value: str | datetime, *, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = _nonempty(value, label=label)
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ConversationPortContractError(
                f"{label} must be an RFC3339 timestamp"
            ) from exc
    if parsed.tzinfo is None:
        raise ConversationPortContractError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _timestamp_text(value: str | datetime, *, label: str) -> str:
    return _timestamp(value, label=label).isoformat()


def _source_ref(value: Any, *, label: str) -> dict[str, Any]:
    ref = _mapping(value, label=label)
    _keys(
        ref,
        required={"source_type", "source_id", "locator"},
        allowed={
            "source_type",
            "source_id",
            "version",
            "snapshot",
            "content_hash",
            "locator",
        },
        label=label,
    )
    source_type = _nonempty(ref["source_type"], label=f"{label}.source_type")
    _nonempty(ref["source_id"], label=f"{label}.source_id")
    _nonempty(ref["locator"], label=f"{label}.locator")
    source_parts = set(re.split(r"[^a-z0-9]+", source_type.lower()))
    if source_parts & _PROVENANCE_ONLY_SOURCE_PARTS:
        raise ConversationPortContractError(
            f"{label} cannot include provider session or transcript material"
        )
    for field in ("version", "snapshot"):
        if ref.get(field) is not None:
            _nonempty(ref[field], label=f"{label}.{field}")
    digest = ref.get("content_hash")
    if digest is not None and (
        not isinstance(digest, str) or not _SHA256.fullmatch(digest)
    ):
        raise ConversationPortContractError(
            f"{label}.content_hash must be canonical SHA-256"
        )
    if not any(ref.get(field) is not None for field in ("version", "snapshot", "content_hash")):
        raise ConversationPortContractError(
            f"{label} requires an exact version, snapshot, or content hash"
        )
    return ref


def _subject_ref(value: Any) -> dict[str, Any]:
    subject = _mapping(value, label="subject_ref")
    _keys(
        subject,
        required={"kind", "stable_id", "authority_ref", "title"},
        allowed={"kind", "stable_id", "authority_ref", "title"},
        label="subject_ref",
    )
    kind = subject["kind"]
    if kind not in _SUBJECT_SOURCE_TYPES:
        raise ConversationPortContractError(
            "subject_ref must be a governed Issue or capability"
        )
    stable_id = _nonempty(subject["stable_id"], label="subject_ref.stable_id")
    _nonempty(subject["title"], label="subject_ref.title")
    authority_ref = _source_ref(
        subject["authority_ref"], label="subject_ref.authority_ref"
    )
    if kind == "capability" and authority_ref["source_type"] != "owner_document":
        raise ConversationPortContractError(
            "capability subject_ref requires owner_document authority"
        )
    if authority_ref["source_type"] not in _SUBJECT_SOURCE_TYPES[kind]:
        raise ConversationPortContractError(
            "subject_ref authority does not match its governed kind"
        )
    if kind == "issue" and (
        not _ISSUE_STABLE_ID.fullmatch(stable_id)
        or stable_id.removeprefix("github:") != authority_ref["source_id"]
    ):
        raise ConversationPortContractError(
            "Issue subject_ref requires an exact GitHub Issue identity"
        )
    if kind == "capability" and not _CAPABILITY_STABLE_ID.fullmatch(stable_id):
        raise ConversationPortContractError(
            "capability subject_ref requires a stable governed identity"
        )
    subject["authority_ref"] = authority_ref
    return subject


def _limitation(value: Any, *, label: str) -> dict[str, Any]:
    limitation = _mapping(value, label=label)
    _keys(
        limitation,
        required={"kind", "reason"},
        allowed={"kind", "reason", "source_ref", "evidence_state", "linkage"},
        label=label,
    )
    _nonempty(limitation["kind"], label=f"{label}.kind")
    _nonempty(limitation["reason"], label=f"{label}.reason")
    if limitation.get("source_ref") is not None:
        limitation["source_ref"] = _source_ref(
            limitation["source_ref"], label=f"{label}.source_ref"
        )
    for field in ("evidence_state", "linkage"):
        if limitation.get(field) is not None:
            _nonempty(limitation[field], label=f"{label}.{field}")
    return limitation


def _scope_items(value: Any, *, label: str) -> list[str]:
    items = _items(value, label=label)
    if not items or len(items) > 32:
        raise ConversationPortContractError(f"{label} is empty or over-broad")
    normalized = [_nonempty(item, label=f"{label}[{index}]", max_length=128) for index, item in enumerate(items)]
    if len(normalized) != len(set(normalized)):
        raise ConversationPortContractError(f"{label} contains duplicate or ambiguous fields")
    return normalized


def _source_refs(value: Any, *, label: str, required: bool) -> list[dict[str, Any]]:
    raw_items = _items(value, label=label)
    if len(raw_items) > 32 or (required and not raw_items):
        raise ConversationPortContractError(f"{label} is empty or over-broad")
    refs = [
        _source_ref(item, label=f"{label}[{index}]")
        for index, item in enumerate(raw_items)
    ]
    identities = [(ref["source_type"], ref["source_id"]) for ref in refs]
    if len(identities) != len(set(identities)):
        raise ConversationPortContractError(
            f"{label} contains duplicate or ambiguous sources"
        )
    return refs


def _source_state(value: Any, *, label: str) -> dict[str, Any]:
    state = _mapping(value, label=label)
    _keys(
        state,
        required={
            "source_ref",
            "freshness",
            "captured_at",
            "fresh_until",
            "read_watermark",
        },
        allowed={
            "source_ref",
            "freshness",
            "captured_at",
            "fresh_until",
            "read_watermark",
        },
        label=label,
    )
    state["source_ref"] = _source_ref(
        state["source_ref"], label=f"{label}.source_ref"
    )
    if state["freshness"] != "fresh":
        raise ConversationPortContractError(
            f"{label} is not fresh enough for external handoff"
        )
    state["captured_at"] = _timestamp_text(
        state["captured_at"], label=f"{label}.captured_at"
    )
    state["fresh_until"] = _timestamp_text(
        state["fresh_until"], label=f"{label}.fresh_until"
    )
    _nonempty(
        state["read_watermark"], label=f"{label}.read_watermark", max_length=512
    )
    return state


def _ref_identity(ref: Mapping[str, Any]) -> bytes:
    return _canonical_bytes(ref)


def _canonical_bytes(value: Any) -> bytes:
    detached = _detached(value, label="canonical value")
    return json.dumps(
        detached,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _content_hash(pack: Mapping[str, Any]) -> str:
    unsigned = dict(pack)
    unsigned.pop("content_hash", None)
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _validated_pack(value: Any, *, now: datetime) -> dict[str, Any]:
    pack = _mapping(value, label="context pack")
    required = {
        "contract_version",
        "pack_id",
        "subject_ref",
        "purpose",
        "owner_intent_ref",
        "source_refs",
        "evidence_snapshot_refs",
        "source_states",
        "scope",
        "allowed_dialogue_outcomes",
        "allowed_effects",
        "limitations",
        "created_at",
        "expires_at",
        "hash_algorithm",
        "content_hash",
    }
    _keys(pack, required=required, allowed=required, label="context pack")
    if pack["contract_version"] != CONTEXT_PACK_VERSION:
        raise ConversationPortContractError("context pack contract version is unsupported")
    _nonempty(pack["pack_id"], label="context pack.pack_id", max_length=128)
    pack["subject_ref"] = _subject_ref(pack["subject_ref"])
    _nonempty(pack["purpose"], label="context pack.purpose", max_length=1000)
    pack["owner_intent_ref"] = _source_ref(
        pack["owner_intent_ref"], label="context pack.owner_intent_ref"
    )
    pack["source_refs"] = _source_refs(
        pack["source_refs"], label="context pack.source_refs", required=True
    )
    pack["evidence_snapshot_refs"] = _source_refs(
        pack["evidence_snapshot_refs"],
        label="context pack.evidence_snapshot_refs",
        required=False,
    )
    pack["source_states"] = [
        _source_state(item, label=f"context pack.source_states[{index}]")
        for index, item in enumerate(
            _items(pack["source_states"], label="context pack.source_states")
        )
    ]
    material_refs = [
        pack["subject_ref"]["authority_ref"],
        pack["owner_intent_ref"],
        *pack["source_refs"],
        *pack["evidence_snapshot_refs"],
    ]
    expected_ref_ids = {_ref_identity(ref) for ref in material_refs}
    state_ref_ids = {
        _ref_identity(state["source_ref"]) for state in pack["source_states"]
    }
    if len(state_ref_ids) != len(pack["source_states"]):
        raise ConversationPortContractError(
            "context pack source_states contain duplicate or ambiguous sources"
        )
    if state_ref_ids != expected_ref_ids:
        raise ConversationPortContractError(
            "context pack source_states must exactly cover every material source"
        )

    scope = _mapping(pack["scope"], label="context pack.scope")
    _keys(
        scope,
        required={"includes", "excludes"},
        allowed={"includes", "excludes"},
        label="context pack.scope",
    )
    includes = _scope_items(scope["includes"], label="context pack.scope.includes")
    excludes = _scope_items(scope["excludes"], label="context pack.scope.excludes")
    if set(includes) & _FORBIDDEN_INCLUDES or set(includes) & set(excludes):
        raise ConversationPortContractError("context pack scope is over-broad or ambiguous")
    if not _MANDATORY_EXCLUDES.issubset(excludes):
        raise ConversationPortContractError(
            "context pack scope must explicitly exclude credentials, hidden prompts, sessions, and broad history"
        )
    pack["scope"] = {"includes": includes, "excludes": excludes}

    if pack["allowed_dialogue_outcomes"] != list(_DIALOGUE_OUTCOMES):
        raise ConversationPortContractError(
            "context pack dialogue outcomes must match the governed set"
        )
    if pack["allowed_effects"] != []:
        raise ConversationPortContractError("context pack cannot allow effects")
    pack["limitations"] = [
        _limitation(item, label=f"context pack.limitations[{index}]")
        for index, item in enumerate(_items(pack["limitations"], label="context pack.limitations"))
    ]

    created = _timestamp(pack["created_at"], label="context pack.created_at")
    expires = _timestamp(pack["expires_at"], label="context pack.expires_at")
    current = _timestamp(now, label="validation time")
    if expires <= created or expires - created > MAX_PACK_LIFETIME:
        raise ConversationPortContractError("context pack expiry is invalid or over-broad")
    if current < created:
        raise ConversationPortContractError("context pack is not yet fresh")
    if current >= expires:
        raise ConversationPortContractError("context pack has expired")
    for index, state in enumerate(pack["source_states"]):
        captured = _timestamp(
            state["captured_at"],
            label=f"context pack.source_states[{index}].captured_at",
        )
        fresh_until = _timestamp(
            state["fresh_until"],
            label=f"context pack.source_states[{index}].fresh_until",
        )
        if captured > created:
            raise ConversationPortContractError(
                "context pack source freshness was captured after pack creation"
            )
        if fresh_until < expires:
            raise ConversationPortContractError(
                "context pack expires after a material source freshness deadline"
            )
    pack["created_at"] = created.isoformat()
    pack["expires_at"] = expires.isoformat()
    if pack["hash_algorithm"] != "sha256":
        raise ConversationPortContractError("context pack hash algorithm is unsupported")
    digest = pack["content_hash"]
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ConversationPortContractError("context pack content hash is malformed")
    if digest != _content_hash(pack):
        raise ConversationPortContractError("context pack content hash does not match exact bytes")
    return pack


def build_context_pack(
    *,
    pack_id: str,
    subject_ref: Mapping[str, Any],
    purpose: str,
    owner_intent_ref: Mapping[str, Any],
    source_refs: Sequence[Mapping[str, Any]],
    evidence_snapshot_refs: Sequence[Mapping[str, Any]],
    source_states: Sequence[Mapping[str, Any]],
    includes: Sequence[str],
    excludes: Sequence[str],
    limitations: Sequence[Mapping[str, Any]],
    created_at: str | datetime,
    expires_at: str | datetime,
) -> dict[str, Any]:
    """Build one immutable, scope-bounded context pack."""

    created_text = _timestamp_text(created_at, label="created_at")
    expires_text = _timestamp_text(expires_at, label="expires_at")
    candidate: dict[str, Any] = {
        "contract_version": CONTEXT_PACK_VERSION,
        "pack_id": pack_id,
        "subject_ref": subject_ref,
        "purpose": purpose,
        "owner_intent_ref": owner_intent_ref,
        "source_refs": list(source_refs),
        "evidence_snapshot_refs": list(evidence_snapshot_refs),
        "source_states": list(source_states),
        "scope": {"includes": list(includes), "excludes": list(excludes)},
        "allowed_dialogue_outcomes": list(_DIALOGUE_OUTCOMES),
        "allowed_effects": [],
        "limitations": list(limitations),
        "created_at": created_text,
        "expires_at": expires_text,
        "hash_algorithm": "sha256",
    }
    candidate["content_hash"] = _content_hash(candidate)
    return _validated_pack(candidate, now=_timestamp(created_at, label="created_at"))


def canonical_context_pack_bytes(pack: Mapping[str, Any]) -> bytes:
    """Return deterministic UTF-8 JSON bytes for an already built pack."""

    return _canonical_bytes(pack)


class _DuplicateField(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateField(key)
        result[key] = value
    return result


def validate_context_pack_bytes(
    payload: bytes, *, now: datetime | None = None
) -> dict[str, Any]:
    """Validate exact canonical bytes, scope, lifetime, and content hash."""

    if not isinstance(payload, bytes):
        raise ConversationPortContractError("context pack payload must be bytes")
    try:
        text = payload.decode("utf-8", errors="strict")
        parsed = json.loads(text, object_pairs_hook=_unique_object)
    except _DuplicateField as exc:
        raise ConversationPortContractError(
            f"context pack contains duplicate field: {exc}"
        ) from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConversationPortContractError(
            "context pack must be canonical UTF-8 JSON"
        ) from exc
    if _canonical_bytes(parsed) != payload:
        raise ConversationPortContractError(
            "context pack must use canonical UTF-8 JSON"
        )
    return _validated_pack(parsed, now=now or datetime.now(timezone.utc))


def open_external_conversation(
    *,
    pack_bytes: bytes,
    expected_hash: str,
    provider: str,
    availability: str,
    reason: str,
    opener: Opener | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pass exact bytes to one explicit adapter or return an honest degradation."""

    pack = validate_context_pack_bytes(pack_bytes, now=now)
    if expected_hash != pack["content_hash"]:
        raise ConversationPortContractError("previewed context hash changed")
    provider_name = _nonempty(provider, label="provider", max_length=128)
    _nonempty(reason, label="adapter reason", max_length=1000)
    if availability not in _ADAPTER_STATES:
        raise ConversationPortContractError("adapter availability is unsupported")
    if availability != "available":
        return {
            "state": availability,
            "provider": provider_name,
            "context_hash": expected_hash,
            "reason": reason,
            "focus_usable": True,
            "authority": "provenance_only",
            "durable_effect": False,
        }
    if opener is None:
        raise ConversationPortContractError("available adapter requires an explicit opener")
    try:
        raw_result = _mapping(opener(pack_bytes, expected_hash), label="adapter result")
    except ConversationPortContractError:
        raise
    except Exception as exc:
        return {
            "state": "unavailable",
            "provider": provider_name,
            "context_hash": expected_hash,
            "reason": f"external adapter failed: {type(exc).__name__}",
            "focus_usable": True,
            "authority": "provenance_only",
            "durable_effect": False,
        }
    _keys(
        raw_result,
        required={"provider_request_id"},
        allowed={"provider_request_id", "provider_session_ref", "model", "usage"},
        label="adapter result",
    )
    request_id = _nonempty(
        raw_result["provider_request_id"],
        label="adapter result.provider_request_id",
        max_length=256,
    )
    result: dict[str, Any] = {
        "state": "opened",
        "provider": provider_name,
        "context_hash": expected_hash,
        "provider_request_id": request_id,
        "authority": "provenance_only",
        "durable_effect": False,
    }
    provenance = {
        key: raw_result[key]
        for key in ("provider_session_ref", "model", "usage")
        if key in raw_result
    }
    if provenance:
        for field in ("provider_session_ref", "model"):
            if field in provenance:
                _nonempty(
                    provenance[field],
                    label=f"adapter result.{field}",
                    max_length=512,
                )
        if "usage" in provenance:
            provenance["usage"] = _mapping(
                provenance["usage"], label="adapter result.usage"
            )
        result["provenance"] = provenance
    return result


def validate_conversation_disposition(
    value: Mapping[str, Any], *, expected_context_hash: str
) -> dict[str, Any]:
    """Validate provider reasoning without granting it work or command authority."""

    if not _SHA256.fullmatch(expected_context_hash):
        raise ConversationPortContractError("expected context hash is malformed")
    disposition = _mapping(value, label="conversation disposition")
    required = {
        "contract_version",
        "context_hash",
        "outcome",
        "rationale",
        "source_refs",
        "limitations",
        "provenance",
        "proposed_command",
    }
    _keys(disposition, required=required, allowed=required, label="conversation disposition")
    if disposition["contract_version"] != DISPOSITION_VERSION:
        raise ConversationPortContractError("conversation disposition version is unsupported")
    if disposition["context_hash"] != expected_context_hash:
        raise ConversationPortContractError("conversation disposition context hash changed")
    if disposition["outcome"] not in _DIALOGUE_OUTCOMES:
        raise ConversationPortContractError("conversation disposition outcome is unsupported")
    _nonempty(disposition["rationale"], label="conversation disposition.rationale")
    disposition["source_refs"] = [
        _source_ref(item, label=f"conversation disposition.source_refs[{index}]")
        for index, item in enumerate(
            _items(disposition["source_refs"], label="conversation disposition.source_refs")
        )
    ]
    disposition["limitations"] = [
        _limitation(item, label=f"conversation disposition.limitations[{index}]")
        for index, item in enumerate(
            _items(disposition["limitations"], label="conversation disposition.limitations")
        )
    ]
    provenance = _mapping(
        disposition["provenance"], label="conversation disposition.provenance"
    )
    _keys(
        provenance,
        required=set(),
        allowed={"provider", "model", "provider_session_ref", "usage"},
        label="conversation disposition.provenance",
    )
    for field in ("provider", "model", "provider_session_ref"):
        if field in provenance:
            _nonempty(
                provenance[field],
                label=f"conversation disposition.provenance.{field}",
                max_length=512,
            )
    if "usage" in provenance:
        provenance["usage"] = _mapping(
            provenance["usage"], label="conversation disposition.provenance.usage"
        )
    disposition["provenance"] = provenance

    proposed = disposition["proposed_command"]
    if proposed is not None:
        raise ConversationPortContractError(
            "typed command proposals require the FCP-04 validator"
        )
    disposition["authority"] = "provenance_only"
    disposition["durable_effect"] = False
    return disposition


def conversation_port_design_fixtures(
    pack: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return nonvisual state fixtures for the later governed design handoff."""

    candidate = _mapping(pack, label="context pack fixture")
    digest = candidate.get("content_hash")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ConversationPortContractError("fixture requires an exact context hash")
    common = {"context_hash": digest, "visual_geometry": "unspecified"}
    return {
        "exact_hash": {**common, "port_state": "available", "start_available": False},
        "no_action": {
            **common,
            "port_state": "available",
            "outcome": "no_action",
            "start_available": False,
        },
        "unavailable": {
            **common,
            "port_state": "unavailable",
            "focus_usable": True,
            "start_available": False,
        },
        "unsupported": {
            **common,
            "port_state": "unsupported",
            "focus_usable": True,
            "start_available": False,
        },
        "stale": {
            **common,
            "port_state": "stale",
            "freshness": "stale",
            "start_available": False,
        },
        "unlinked": {
            **common,
            "port_state": "available",
            "linkage": "unlinked",
            "start_available": False,
        },
    }


__all__ = [
    "CONTEXT_PACK_VERSION",
    "DISPOSITION_VERSION",
    "MAX_PACK_LIFETIME",
    "ConversationPortContractError",
    "build_context_pack",
    "canonical_context_pack_bytes",
    "conversation_port_design_fixtures",
    "open_external_conversation",
    "validate_context_pack_bytes",
    "validate_conversation_disposition",
]
