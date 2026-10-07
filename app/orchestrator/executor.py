from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, Iterable, Mapping, MutableMapping, Protocol, cast
from uuid import NAMESPACE_URL, uuid5

import yaml

from app.a2a.events import emit_agent_error_event, emit_agent_response_event, send_agent_request
from app.a2a.schema import AgentRequest, AgentResponse, new_error, new_response
from app.builderops.boundary import execute_builderops_mcp_tool, is_builderops_mcp_tool
from app.builderops.models import BuilderOpsValidationError
from app.domain.state_axes import normalize_promotion_payload
from app.execution.execution_request import ExecutionRequest, ExecutionResult
from app.governance.governed_write import (
    AuthorityReceipt,
    DecisionToken,
    GovernedWriteAdapter,
    GovernedWriteGrant,
    InvalidDecisionTokenError,
    MissingDecisionTokenError,
    normalize_resource_ref,
)
from app.mcp.vault_tools import VaultToolError, append_note, get_vault_root
from app.orchestrator.agents import AgentPermissionError, _normalize_agent_target, resolve_agent_config, validate_agent_permissions
from app.planner.schema import PlanMetadata, PlanStep, ToolDescriptor
from app.planner.tools import get_tool_descriptor

AgentHandler = Callable[[AgentRequest], AgentResponse]
from app.policy.enforce import assert_tool_allowed, is_policy_enforced
from app.quality import timeout_wrapper
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services.outbox import (
    JsonlOutboxCorruptionError,
    append_jsonl_record,
    read_jsonl_outbox_records,
)
from app.objects import ObjectStore
from app.events.schema import OutboxEvent
from app.write_guard import DEFAULT_WRITE_GUARD

from .events import emit_mcp_tool_call_finished, emit_mcp_tool_call_started


_GOVERNED_WRITE_ADAPTER = GovernedWriteAdapter()
_MCP_APPEND_ACTION = "mcp.vault.append_note"
_MCP_APPEND_WRITE_CLASS = "vault_mcp_append"
_MCP_APPEND_STATE_OWNER = "exe"
_AUTHORITY_RECEIPT_EVENT = "governance.authority_receipt.recorded"
_MCP_APPEND_EVENT = "mcp.vault.append_note"
_DECISION_TOKEN_FIELDS = frozenset(
    {
        "token_id",
        "decision_id",
        "action",
        "write_class",
        "actor",
        "resource",
        "issued_at",
        "valid",
        "contract_version",
    }
)
_DECISION_TOKEN_ID_PATTERN = re.compile(r"^decision_token_[0-9a-f]{32}$")
_POLICY_DECISION_ID_PATTERN = re.compile(r"^policy_decision_[0-9a-f]{32}$")
_EXECUTION_REQUEST_FIELDS = frozenset(
    {
        "side_effect",
        "actor",
        "resource",
        "adapter",
        "active_context_set",
        "decision_token",
        "effect_id",
        "dry_run",
        "preview",
        "trace_id",
        "args",
        "contract_version",
    }
)
_EXECUTION_RESULT_FIELDS = frozenset(
    {
        "request",
        "status",
        "preview_result",
        "dry_run_result",
        "effect_result",
        "rollback_available",
        "rollback_result",
        "receipt_ref",
        "trace_id",
        "contract_version",
    }
)
_AUTHORITY_RECEIPT_FIELDS = frozenset(
    {
        "receipt_id",
        "decision_token_id",
        "decision_id",
        "action",
        "write_class",
        "actor",
        "resource",
        "outcome",
        "operation",
        "adapter",
        "state_owner",
        "source_receipt_ref",
        "fallback_used",
        "recorded_at",
        "trace_id",
        "effect_id",
        "contract_version",
    }
)

# A process-local recovery hint covers the crash window in which the writer
# returned a path but the first durable receipt write failed. The canonical
# effect itself also carries this identity in frontmatter, so recovery after a
# process restart uses the vault scan below rather than this cache.
_EFFECT_PATH_HINTS: dict[str, Path] = {}
_EFFECT_ROOT_HINTS: dict[str, str | None] = {}
_EFFECT_LOCKS: dict[str, Lock] = {}
_EFFECT_LOCKS_GUARD = Lock()


@dataclass
class _EffectLocator:
    path: str


@dataclass
class _EffectReceipt:
    operation: str
    locator: _EffectLocator
    adapter: str
    trace_id: str | None = None
    fallback_used: bool = False


@dataclass(frozen=True)
class _EffectRecovery:
    path: Path
    decision_token: DecisionToken


class _EffectReconciliationConflict(RuntimeError):
    """A persisted effect identity exists with content that no longer matches."""


def _effect_identity(
    plan_id: str,
    step_id: str,
    args: Mapping[str, Any],
    *,
    vault_root: Path | str | None = None,
) -> str:
    encoded = json.dumps(dict(args), sort_keys=True, separators=(",", ":"), default=str)
    scope = str(Path(vault_root).expanduser()) if vault_root is not None else "default-vault"
    digest = hashlib.sha256(f"{scope}\0{encoded}".encode("utf-8")).hexdigest()[:24]
    return f"orchestrator:{plan_id}:{step_id}:{digest}"


def _effect_resource(args: Mapping[str, Any]) -> str:
    return normalize_resource_ref(str(args.get("title") or ""))


def _effect_note_reference(path: Path | str) -> str:
    """Return the canonical serialized note reference without changing access paths."""
    return normalize_resource_ref(str(path))


def _effect_metadata(args: Mapping[str, Any], effect_id: str) -> dict[str, Any]:
    metadata = dict(args.get("metadata") or {})
    existing = metadata.get("governed_effect_id")
    if existing is not None and str(existing) != effect_id:
        raise InvalidDecisionTokenError(
            "effect metadata is bound to a different governed effect identity"
        )
    metadata["governed_effect_id"] = effect_id
    return metadata


def _effect_metadata_with_authorization(
    args: Mapping[str, Any],
    effect_id: str,
    decision_token: DecisionToken,
) -> dict[str, Any]:
    metadata = _effect_metadata(args, effect_id)
    existing = metadata.get("governed_authorization")
    serialized = asdict(decision_token)
    if existing is not None and existing != serialized:
        raise InvalidDecisionTokenError(
            "effect metadata is bound to a different authorization provenance"
        )
    metadata["governed_authorization"] = serialized
    return metadata


def _has_configured_vault_root(settings: Mapping[str, Any] | None) -> bool:
    if settings:
        if any(settings.get(key) for key in ("vault_root", "root", "path")):
            return True
        nested = settings.get("vault")
        if isinstance(nested, Mapping) and any(nested.get(key) for key in ("root", "path")):
            return True
    return any(os.getenv(name) for name in ("MCP_VAULT_ROOT", "VAULT_DIR", "VAULT_ROOT"))


def _resolve_effect_vault_root(settings: Mapping[str, Any] | None) -> Path | None:
    """Resolve the exact root that the production writer will use.

    Some legacy tests replace the writer and intentionally omit a vault root;
    preserving ``None`` for that seam keeps their mock path additive. Whenever
    a real configuration exists, resolve it once and pass the canonical root
    into the writer and recovery scan so a restart cannot scan a different
    default root than the append used.
    """
    if not _has_configured_vault_root(settings):
        return None
    return get_vault_root(settings).expanduser().resolve()


def _effect_lock(effect_id: str, vault_root: Path | str | None) -> Lock:
    root = str(Path(vault_root).expanduser().resolve()) if vault_root is not None else "unresolved"
    key = f"{root}\0{effect_id}"
    with _EFFECT_LOCKS_GUARD:
        return _EFFECT_LOCKS.setdefault(key, Lock())


def _expected_effect_tags(args: Mapping[str, Any]) -> list[str]:
    return [tag for tag in (args.get("tags") or []) if isinstance(tag, str) and tag.strip()]


def _parse_writer_note(text: str) -> tuple[dict[str, Any], str] | None:
    """Parse the exact line-delimited format emitted by ``append_note``.

    Splitting on the delimiter substring loses titles containing ``---`` and
    stripping the body loses intentional leading blank lines. Delimiter lines
    are structural; all bytes after the closing line remain part of the body.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0] not in {"---\n", "---\r\n"}:
        return None
    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip("\r\n") == "---" and line.strip() == "---"
        ),
        None,
    )
    if closing_index is None:
        return None
    try:
        frontmatter = yaml.safe_load("".join(lines[1:closing_index])) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(frontmatter, dict):
        return None
    return frontmatter, "".join(lines[closing_index + 1 :])


def _decision_token_from_metadata(
    metadata: Mapping[str, Any],
    *,
    action: str,
    write_class: str,
    actor: str,
    resource: str,
) -> DecisionToken | None:
    raw = metadata.get("governed_authorization")
    if not isinstance(raw, Mapping):
        return None
    token = _validated_decision_token(raw)
    if token is None:
        return None
    try:
        _GOVERNED_WRITE_ADAPTER.validate_decision_token(
            decision_token=token,
            action=action,
            write_class=write_class,
            actor=actor,
            resource=resource,
        )
    except (TypeError, ValueError, InvalidDecisionTokenError, MissingDecisionTokenError):
        return None
    return token


def _validated_decision_token(raw: Mapping[str, Any]) -> DecisionToken | None:
    """Reconstruct only a token that has the complete generated GOV schema."""
    if set(raw) != _DECISION_TOKEN_FIELDS:
        return None
    if raw.get("valid") is not True:
        return None
    string_fields = _DECISION_TOKEN_FIELDS - {"valid"}
    if any(type(raw.get(field)) is not str or not raw[field] for field in string_fields):
        return None
    token_id = cast(str, raw["token_id"])
    decision_id = cast(str, raw["decision_id"])
    if not _DECISION_TOKEN_ID_PATTERN.fullmatch(token_id):
        return None
    if not _POLICY_DECISION_ID_PATTERN.fullmatch(decision_id):
        return None
    if raw["contract_version"] != "governed_write_protocol.v0":
        return None
    issued_at = cast(str, raw["issued_at"])
    try:
        parsed_issued_at = datetime.fromisoformat(
            issued_at[:-1] + "+00:00" if issued_at.endswith("Z") else issued_at
        )
    except ValueError:
        return None
    if parsed_issued_at.tzinfo is None or parsed_issued_at.utcoffset() != timedelta(0):
        return None
    try:
        return DecisionToken(**dict(raw))
    except (TypeError, ValueError):
        return None


def _effect_note_evidence(
    path: Path,
    *,
    effect_id: str,
    args: Mapping[str, Any],
    actor: str,
    vault_root: Path,
    known_path: bool = False,
) -> tuple[str, DecisionToken | None]:
    """Accept only a writer-shaped note with exact causal content.

    A marker in body text is not evidence: the frontmatter metadata, title,
    tags, body, and vault-relative destination must all match the request that
    produced this stable effect identity.
    """
    try:
        candidate = path.expanduser().resolve(strict=True)
        root = vault_root.expanduser().resolve()
        candidate_stat = candidate.stat()
        if candidate.parent != root / "_mcp" or not stat.S_ISREG(candidate_stat.st_mode):
            return "unverifiable", None
        parsed = _parse_writer_note(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return "unverifiable", None
    if parsed is None:
        return "unverifiable", None
    frontmatter, body = parsed
    raw_metadata = frontmatter.get("metadata")
    if not isinstance(raw_metadata, Mapping):
        return ("identity_conflict", None) if known_path else ("none", None)
    candidate_effect_id = raw_metadata.get("governed_effect_id")
    if candidate_effect_id is None:
        return ("identity_conflict", None) if known_path else ("none", None)
    if candidate_effect_id != effect_id:
        return "identity_conflict", None
    original_token = _decision_token_from_metadata(
        raw_metadata,
        action=_MCP_APPEND_ACTION,
        write_class=_MCP_APPEND_WRITE_CLASS,
        actor=actor,
        resource=_effect_resource(args),
    )
    if original_token is None:
        return "conflict", None
    expected_metadata = _effect_metadata(args, effect_id)
    actual_metadata = dict(raw_metadata)
    actual_metadata.pop("governed_authorization", None)
    if actual_metadata != expected_metadata:
        return "conflict", original_token
    if frontmatter.get("title") != str(args.get("title") or "").strip():
        return "conflict", original_token
    expected_tags = _expected_effect_tags(args)
    actual_tags = frontmatter.get("tags")
    if expected_tags:
        if actual_tags != expected_tags:
            return "conflict", original_token
    elif actual_tags not in (None, []):
        return "conflict", original_token
    expected_body = f"\n{str(args.get('body') or '').rstrip()}\n"
    if body != expected_body:
        return "conflict", original_token
    return "match", original_token


def _effect_path_from_vault(
    effect_id: str,
    vault_root: Path | str | None,
    args: Mapping[str, Any],
    actor: str,
) -> _EffectRecovery | None:
    hint = _EFFECT_PATH_HINTS.get(effect_id)
    if hint is not None:
        current_root = str(Path(vault_root).expanduser().resolve()) if vault_root is not None else None
        if (
            _EFFECT_ROOT_HINTS.get(effect_id) == current_root
            and vault_root is not None
        ):
            evidence, decision_token = _effect_note_evidence(
                hint,
                effect_id=effect_id,
                args=args,
                actor=actor,
                vault_root=Path(vault_root),
                known_path=True,
            )
            if evidence == "conflict":
                raise _EffectReconciliationConflict(
                    f"persisted effect {effect_id} conflicts with its original content"
                )
            if evidence == "unverifiable":
                raise _EffectReconciliationConflict(
                    f"persisted effect {effect_id} cannot be read or parsed for recovery"
                )
            if evidence == "identity_conflict":
                raise _EffectReconciliationConflict(
                    f"persisted effect {effect_id} has conflicting identity in its hinted path"
                )
            if evidence == "match" and decision_token is not None:
                return _EffectRecovery(path=hint, decision_token=decision_token)
    if vault_root is None:
        return None
    root = Path(vault_root).expanduser().resolve()
    mcp_dir = root / "_mcp"
    try:
        with os.scandir(mcp_dir) as entries:
            candidates = sorted(
                (mcp_dir / entry.name for entry in entries if entry.name.endswith(".md")),
                key=lambda candidate: candidate.name,
            )
    except FileNotFoundError:
        candidates = []
    except OSError as exc:
        raise _EffectReconciliationConflict(
            f"vault inventory cannot be enumerated while recovering {effect_id}"
        ) from exc
    match: _EffectRecovery | None = None
    for candidate in candidates:
        evidence, decision_token = _effect_note_evidence(
            candidate,
            effect_id=effect_id,
            args=args,
            actor=actor,
            vault_root=root,
        )
        if evidence == "conflict":
            raise _EffectReconciliationConflict(
                f"persisted effect {effect_id} conflicts with its original content"
            )
        if evidence == "unverifiable":
            raise _EffectReconciliationConflict(
                f"vault evidence cannot be read or parsed while recovering {effect_id}"
            )
        if evidence == "identity_conflict":
            continue
        if evidence == "match" and decision_token is not None:
            match = _EffectRecovery(path=candidate, decision_token=decision_token)
    return match


def _validate_persisted_authority_payload(
    effect_id: str,
    event_id: str,
    payload: Any,
    *,
    args: Mapping[str, Any],
    actor: str,
    resource: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _EffectReconciliationConflict(
            f"durable authority receipt for {effect_id} has no valid payload"
        )
    if set(payload) != {
        "effect_id",
        "execution_result",
        "decision_token",
        "retry_decision_token",
        "authority_receipt",
    }:
        raise _EffectReconciliationConflict(
            f"durable authority receipt for {effect_id} has incomplete payload linkage"
        )
    if payload.get("effect_id") != effect_id or event_id != _event_id(effect_id, "authority_receipt"):
        raise _EffectReconciliationConflict(
            f"durable authority receipt for {effect_id} has inconsistent identity"
        )
    execution_result = payload.get("execution_result")
    if (
        not isinstance(execution_result, dict)
        or set(execution_result) != _EXECUTION_RESULT_FIELDS
        or execution_result.get("status") != "succeeded"
        or execution_result.get("contract_version") != "execution_request.v0"
    ):
        raise _EffectReconciliationConflict(
            f"durable authority receipt for {effect_id} has no succeeded EXE result"
        )
    effect_result = execution_result.get("effect_result")
    if (
        not isinstance(effect_result, dict)
        or set(effect_result) != {"status", "note_path"}
        or effect_result.get("status") != "ok"
        or not isinstance(effect_result.get("note_path"), str)
        or not effect_result["note_path"]
        or _effect_note_reference(effect_result["note_path"]) != effect_result["note_path"]
    ):
        raise _EffectReconciliationConflict(
            f"durable authority receipt for {effect_id} has no valid effect result"
        )
    execution_request = execution_result.get("request")
    decision_token = payload.get("decision_token")
    expected_request_args: dict[str, Any]
    try:
        original_token = (
            _validated_decision_token(decision_token)
            if isinstance(decision_token, dict)
            else None
        )
        if original_token is None:
            raise ValueError("missing DecisionToken")
        expected_request_args = dict(args)
        expected_request_args["metadata"] = _effect_metadata_with_authorization(
            args,
            effect_id,
            original_token,
        )
    except (TypeError, ValueError, InvalidDecisionTokenError):
        expected_request_args = {}
    if (
        not isinstance(execution_request, dict)
        or set(execution_request) != _EXECUTION_REQUEST_FIELDS
        or execution_request.get("contract_version") != "execution_request.v0"
        or execution_request.get("effect_id") != effect_id
        or execution_request.get("side_effect") != _MCP_APPEND_ACTION
        or execution_request.get("adapter") != _MCP_APPEND_ACTION
        or execution_request.get("actor") != actor
        or execution_request.get("resource") != resource
        or not isinstance(decision_token, dict)
        or set(decision_token) != _DECISION_TOKEN_FIELDS
        or decision_token.get("valid") is not True
        or decision_token.get("action") != _MCP_APPEND_ACTION
        or decision_token.get("write_class") != _MCP_APPEND_WRITE_CLASS
        or decision_token.get("actor") != actor
        or decision_token.get("resource") != resource
        or decision_token.get("contract_version") != "governed_write_protocol.v0"
        or execution_request.get("decision_token") != decision_token
        or not expected_request_args
        or execution_request.get("args") != expected_request_args
    ):
        raise _EffectReconciliationConflict(
            f"durable authority receipt for {effect_id} has invalid authorization provenance"
        )
    receipt_ref = execution_result.get("receipt_ref")
    expected_receipt_ref = f"{_MCP_APPEND_ACTION}:{effect_result['note_path']}"
    if (
        receipt_ref != expected_receipt_ref
        or execution_result.get("trace_id") != execution_request.get("trace_id")
        or execution_result.get("preview_result") is not None
        or execution_result.get("dry_run_result") is not None
        or execution_result.get("rollback_available") is not False
        or execution_result.get("rollback_result") is not None
    ):
        raise _EffectReconciliationConflict(
            f"durable authority receipt for {effect_id} has inconsistent EXE linkage"
        )
    authority_receipt = payload.get("authority_receipt")
    if (
        not isinstance(authority_receipt, dict)
        or set(authority_receipt) != _AUTHORITY_RECEIPT_FIELDS
        or not isinstance(authority_receipt.get("receipt_id"), str)
        or not authority_receipt.get("receipt_id")
        or authority_receipt.get("effect_id") != effect_id
        or authority_receipt.get("outcome") != "applied"
        or authority_receipt.get("decision_token_id") != decision_token.get("token_id")
        or authority_receipt.get("decision_id") != decision_token.get("decision_id")
        or authority_receipt.get("action") != decision_token.get("action")
        or authority_receipt.get("write_class") != decision_token.get("write_class")
        or authority_receipt.get("actor") != actor
        or authority_receipt.get("resource") != resource
        or authority_receipt.get("operation") != "append_note"
        or authority_receipt.get("adapter") != _MCP_APPEND_ACTION
        or authority_receipt.get("state_owner") != _MCP_APPEND_STATE_OWNER
        or authority_receipt.get("source_receipt_ref")
        != f"{_MCP_APPEND_ACTION}:append_note:{effect_result['note_path']}"
        or not isinstance(authority_receipt.get("fallback_used"), bool)
        or not isinstance(authority_receipt.get("recorded_at"), str)
        or not authority_receipt.get("recorded_at")
        or authority_receipt.get("trace_id") != execution_result.get("trace_id")
        or authority_receipt.get("contract_version") != "governed_write_protocol.v0"
    ):
        raise _EffectReconciliationConflict(
            f"durable authority receipt for {effect_id} is missing or inconsistent"
        )
    retry_token = payload.get("retry_decision_token")
    if retry_token is not None and (
        not isinstance(retry_token, dict)
        or set(retry_token) != _DECISION_TOKEN_FIELDS
        or retry_token.get("valid") is not True
        or retry_token.get("token_id") == decision_token.get("token_id")
        or retry_token.get("action") != _MCP_APPEND_ACTION
        or retry_token.get("write_class") != _MCP_APPEND_WRITE_CLASS
        or retry_token.get("actor") != actor
        or retry_token.get("resource") != resource
    ):
        raise _EffectReconciliationConflict(
            f"durable authority receipt for {effect_id} has invalid retry authorization"
        )
    return payload


def _persisted_authority_receipt(
    effect_id: str,
    outbox_path: Path,
    *,
    args: Mapping[str, Any],
    actor: str,
    resource: str,
) -> dict[str, Any] | None:
    try:
        records = read_jsonl_outbox_records(outbox_path, read_only=True)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, JsonlOutboxCorruptionError) as exc:
        raise _EffectReconciliationConflict(
            f"durable outbox receipt cannot be read while recovering {effect_id}"
        ) from exc
    expected_event_id = _event_id(effect_id, "authority_receipt")
    matched: dict[str, Any] | None = None
    for record in records:
        if not isinstance(record, dict):
            continue
        event_id = record.get("event_id")
        payload = record.get("payload")
        payload_effect_id = payload.get("effect_id") if isinstance(payload, dict) else None
        known_receipt = event_id == expected_event_id or (
            record.get("event") == _AUTHORITY_RECEIPT_EVENT
            and payload_effect_id == effect_id
        )
        if not known_receipt:
            continue
        if record.get("event") != _AUTHORITY_RECEIPT_EVENT:
            raise _EffectReconciliationConflict(
                f"known authority receipt event for {effect_id} has an unexpected event type"
            )
        validated = _validate_persisted_authority_payload(
            effect_id,
            str(event_id),
            payload,
            args=args,
            actor=actor,
            resource=resource,
        )
        if matched is not None and validated != matched:
            raise _EffectReconciliationConflict(
                f"known authority receipt events for {effect_id} disagree"
            )
        matched = validated
    return matched


def _persisted_notification(
    effect_id: str,
    outbox_path: Path,
    *,
    effect_result: Mapping[str, Any],
    authority_receipt: Any,
) -> bool:
    try:
        records = read_jsonl_outbox_records(outbox_path, read_only=True)
    except FileNotFoundError as exc:
        raise _EffectReconciliationConflict(
            f"durable outbox notification cannot be read while recovering {effect_id}"
        ) from exc
    except (OSError, ValueError, JsonlOutboxCorruptionError) as exc:
        raise _EffectReconciliationConflict(
            f"durable outbox notification cannot be read while recovering {effect_id}"
        ) from exc
    expected_event_id = _event_id(effect_id, "notification")
    expected_note_path = effect_result.get("note_path")
    if (
        not isinstance(expected_note_path, str)
        or not expected_note_path
        or not isinstance(authority_receipt, dict)
    ):
        raise _EffectReconciliationConflict(
            f"durable notification linkage is unavailable while recovering {effect_id}"
        )
    matched = False
    for record in records:
        if not isinstance(record, dict):
            continue
        event_id = record.get("event_id")
        payload = record.get("payload")
        payload_effect_id = payload.get("effect_id") if isinstance(payload, dict) else None
        known_notification = event_id == expected_event_id or (
            record.get("event") == _MCP_APPEND_EVENT and payload_effect_id == effect_id
        )
        if not known_notification:
            continue
        if record.get("event") != _MCP_APPEND_EVENT or event_id != expected_event_id:
            raise _EffectReconciliationConflict(
                f"known notification event for {effect_id} has inconsistent identity"
            )
        if (
            not isinstance(payload, dict)
            or set(payload) != {"effect_id", "note_path", "authority_receipt"}
            or payload.get("effect_id") != effect_id
            or payload.get("note_path") != expected_note_path
            or payload.get("authority_receipt") != authority_receipt
        ):
            raise _EffectReconciliationConflict(
                f"known notification event for {effect_id} has inconsistent linkage"
            )
        matched = True
    return matched


def _event_id(effect_id: str, stage: str) -> str:
    return uuid5(NAMESPACE_URL, f"{effect_id}:{stage}").hex


def _governed_write_payload(
    grant: GovernedWriteGrant,
    authority_receipt: AuthorityReceipt,
) -> dict[str, Any]:
    return {
        "policy_decision": asdict(grant.policy_decision),
        "decision_token": asdict(grant.decision_token),
        "authority_receipt": asdict(authority_receipt),
    }


def _flag_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return False
        return normalized in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


def _resolve_outbox_path() -> Path:
    return Path(INDEX_OUTBOX_PATH)


def _write_outbox_events(outbox_path: Path, events: Iterable[Any]) -> None:
    for event in events:
        if hasattr(event, "model_dump"):
            payload = event.model_dump(mode="json")
        elif isinstance(event, dict):
            payload = dict(event)
        else:
            continue
        append_jsonl_record(outbox_path, payload, require_event_id=True)


class StepExecutionError(Exception):
    """Raised when a plan step cannot be executed."""

    def __init__(self, message: str, *, error_type: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass
class StepContext:
    plan_id: str
    object_id: str | None
    trace_id: str | None
    metadata: PlanMetadata
    results: MutableMapping[str, Dict[str, Any]] = field(default_factory=dict)
    governed_write_grants: MutableMapping[str, GovernedWriteGrant] = field(default_factory=dict)
    flow_id: str | None = None
    event_type: str | None = None
    tool_settings: Mapping[str, Any] | None = None
    budget_state: MutableMapping[str, int] | None = None
    agent_id: str | None = None
    scope: str | None = None
    sphere_memberships: list[str] = field(default_factory=list)
    situated_identity: str | None = None


class PlanExecutor(Protocol):
    def execute_step(self, step: PlanStep, context: StepContext) -> Dict[str, Any]:
        ...


class MockPlanExecutor(PlanExecutor):
    """Deterministic executor used in CI and development."""

    _TYPE_MAP: Dict[str, tuple[type, ...]] = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "array": (list, tuple),
        "object": (dict,),
    }

    def __init__(self, handlers: Dict[str, AgentHandler] | None = None) -> None:
        self._handlers: Dict[str, AgentHandler] = dict(handlers or {})

    def register_handler(self, agent_name: str, handler: AgentHandler) -> None:
        """Register an in-process handler for a supported agent recipient."""
        self._handlers[_normalize_agent_target(agent_name)] = handler

    def execute_step(self, step: PlanStep, context: StepContext) -> Dict[str, Any]:
        if step.kind == "agent_call":
            return self._execute_agent_call(step, context)
        if step.kind == "tool_call":
            return self._execute_tool_call(step, context)
        if step.kind == "decision":
            return {"decision": step.description, "depends_on": list(step.depends_on)}
        if step.kind == "note":
            return {"note": step.description}
        raise StepExecutionError(f"unsupported step kind '{step.kind}'", error_type="invalid_step_kind")

    def _execute_agent_call(self, step: PlanStep, context: StepContext) -> Dict[str, Any]:
        agent_name = step.agent or "unknown-agent"
        config = resolve_agent_config(agent_name, flow_id=context.flow_id, event_type=context.event_type)
        if config:
            try:
                validate_agent_permissions(config, flow_id=context.flow_id, event_type=context.event_type)
            except AgentPermissionError as exc:
                raise StepExecutionError(f"Agent permission denied: {exc}", error_type="agent_permission") from exc
        request = send_agent_request(
            sender="orchestrator.runtime",
            recipient=agent_name,
            intent=step.intent,
            payload={
                "plan_id": context.plan_id,
                "step_id": step.id,
                "object_id": context.object_id,
                "description": step.description,
            },
            metadata={"plan": context.metadata.model_dump(), "step": step.metadata},
            correlation_id=step.id,
            trace_id=context.trace_id,
            object_id=context.object_id,
        )
        normalized = _normalize_agent_target(agent_name)
        handler = self._handlers.get(normalized) or self._handlers.get(agent_name)
        if handler is None:
            error = new_error(
                sender="orchestrator.runtime",
                recipient=agent_name,
                error_type="not_implemented",
                error_message=f"{agent_name} has no registered handler.",
                correlation_id=str(request.id),
                trace_id=context.trace_id,
            )
            emit_agent_error_event(error, object_id=context.object_id)
            raise StepExecutionError(
                f"{agent_name} has no registered handler",
                error_type="not_implemented",
            )
        try:
            response = handler(request)
        except Exception as exc:
            error = new_error(
                sender="orchestrator.runtime",
                recipient=agent_name,
                error_type="handler_error",
                error_message=str(exc),
                correlation_id=str(request.id),
                trace_id=context.trace_id,
            )
            emit_agent_error_event(error, object_id=context.object_id)
            raise StepExecutionError(str(exc), error_type="handler_error") from exc
        emit_agent_response_event(response, object_id=context.object_id)
        return {
            "agent": agent_name,
            "request_id": str(request.id),
            "response": response.model_dump(mode="json"),
        }

    def _execute_tool_call(self, step: PlanStep, context: StepContext) -> Dict[str, Any]:
        if not step.tool:
            raise StepExecutionError("tool_call step missing tool name", error_type="invalid_tool")
        descriptor = get_tool_descriptor(step.tool)
        if descriptor is None:
            raise StepExecutionError(f"unknown MCP tool '{step.tool}'", error_type="invalid_tool")
        agent_id = context.agent_id
        if is_policy_enforced() and not agent_id:
            raise StepExecutionError("policy: missing agent_id in StepContext", error_type="policy_denied")
        try:
            assert_tool_allowed(agent_id, descriptor.name)
        except PermissionError as exc:
            raise StepExecutionError(str(exc), error_type="policy_denied") from exc
        args = dict(step.tool_args or {})
        if (
            descriptor.name == "mcp.vault.append_note"
            and "content" in args
            and "body" not in args
        ):
            args["body"] = args["content"]
        self._validate_tool_args(args, descriptor.allowed_args)
        self._validate_required_args(args, descriptor.schema.get("required", []))
        emit_mcp_tool_call_started(
            plan_id=context.plan_id,
            step_id=step.id,
            tool_name=descriptor.name,
            object_id=context.object_id,
            trace_id=context.trace_id,
        )
        budget = context.budget_state if context.budget_state is not None else {}
        settings = context.tool_settings or {}
        max_tool_calls = None
        if "max_tool_calls" in settings:
            try:
                max_tool_calls = int(settings["max_tool_calls"])
            except Exception:
                max_tool_calls = None
        tool_calls = int(budget.get("tool_calls", 0))
        if max_tool_calls is not None and tool_calls >= max_tool_calls:
            raise StepExecutionError("tool call budget exhausted", error_type="budget_exhausted")
        budget["tool_calls"] = tool_calls + 1
        timeout_value = None
        if "tool_timeout_seconds" in settings:
            try:
                timeout_value = float(settings["tool_timeout_seconds"])
            except Exception:
                timeout_value = None
        try:
            result_payload = self._invoke_tool(
                descriptor, args, context, timeout_value, step_id=step.id
            )
        except (FutureTimeoutError, TimeoutError) as exc:
            raise StepExecutionError("tool call timed out", error_type="tool_timeout") from exc
        emit_mcp_tool_call_finished(
            plan_id=context.plan_id,
            step_id=step.id,
            tool_name=descriptor.name,
            result=result_payload,
            object_id=context.object_id,
            trace_id=context.trace_id,
        )
        return {"tool": descriptor.name, "result": result_payload}

    def _invoke_tool(
        self,
        descriptor: ToolDescriptor,
        args: Mapping[str, Any],
        context: StepContext,
        timeout_secs: float | None,
        *,
        step_id: str | None = None,
    ) -> Dict[str, Any]:
        def call() -> Dict[str, Any]:
            if descriptor.kind == "internal":
                return self._run_internal_tool(descriptor.name, args, context)
            if self._should_use_real_tool(descriptor.name, context):
                if is_builderops_mcp_tool(descriptor.name):
                    return self._run_builderops_tool(descriptor.name, args, context)
                return self._run_vault_append(args, context, step_id=step_id)
            return dict(descriptor.mock_result or {"status": "ok"})

        if timeout_secs is not None:
            return timeout_wrapper(call, timeout_secs)
        return call()

    def _run_internal_tool(self, name: str, args: Mapping[str, Any], context: StepContext) -> Dict[str, Any]:
        if name == "internal.ingest_external":
            try:
                from app.ingest.external import ingest_external_folder

                root = Path(args["root_dir"])
                summary = ingest_external_folder(root, limit=args.get("limit"))
                return {"status": "ok", "summary": asdict(summary)}
            except Exception as exc:
                raise StepExecutionError(f"external ingest failed: {exc}", error_type="internal_tool_error") from exc
        if name == "promotion.emit_intent":
            try:
                return _run_promotion_intent(args, context)
            except Exception as exc:
                raise StepExecutionError(f"promotion intent failed: {exc}", error_type="internal_tool_error") from exc
        raise StepExecutionError(f"unsupported internal tool '{name}'", error_type="invalid_tool")

    def _validate_tool_args(self, args: Mapping[str, Any], allowed_args: Mapping[str, str]) -> None:
        for arg_name, arg_type in allowed_args.items():
            if arg_name not in args:
                continue
            expected_types = tuple(
                expected_type
                for candidate in arg_type.split("|")
                for expected_type in self._TYPE_MAP.get(candidate, tuple())
            )
            if not isinstance(args[arg_name], expected_types):
                raise StepExecutionError(
                    f"argument '{arg_name}' must be of type {arg_type}", error_type="invalid_tool_args"
                )

    def _validate_required_args(self, args: Mapping[str, Any], required_args: Iterable[str]) -> None:
        for arg in required_args:
            if arg not in args:
                raise StepExecutionError(f"missing required argument '{arg}'", error_type="invalid_tool_args")

    def _should_use_real_tool(self, tool_name: str, context: StepContext) -> bool:
        if tool_name != "mcp.vault.append_note" and not is_builderops_mcp_tool(tool_name):
            return False
        settings = context.tool_settings or {}
        allowlist = settings.get("allowed_mcp_tools")
        if is_builderops_mcp_tool(tool_name):
            enable_flag = settings.get("mcp_builderops_enable")
        else:
            enable_flag = settings.get("mcp_vault_enable")
            if enable_flag is None:
                enable_flag = settings.get("mcp.enable")
        if allowlist is None:
            return _flag_enabled(enable_flag)
        try:
            return tool_name in allowlist and _flag_enabled(enable_flag)
        except Exception:
            return False

    def _run_builderops_tool(
        self,
        tool_name: str,
        args: Mapping[str, Any],
        context: StepContext,
    ) -> Dict[str, Any]:
        try:
            return execute_builderops_mcp_tool(
                tool_name=tool_name,
                tool_args=args,
                settings=context.tool_settings,
            )
        except BuilderOpsValidationError as exc:
            raise StepExecutionError(
                f"BuilderOps tool failed: {exc}",
                error_type="mcp_tool_error",
            ) from exc

    def _run_vault_append(
        self,
        args: Mapping[str, Any],
        context: StepContext,
        *,
        step_id: str | None = None,
    ) -> Dict[str, Any]:
        """Run the one governed real-tool append path.

        The authority step issues the GOV grant and places it in the shared
        execution context. This method validates that grant again immediately
        before the writer, then records the EXE result and GOV AuthorityReceipt
        as separate durable outbox stages. A stable effect identity and the
        identity marker in the note's metadata make the append retryable without
        repeating a completed writer call.
        """
        actor = context.agent_id or "orchestrator.runtime"
        resource = _effect_resource(args)
        grant = context.governed_write_grants.get(step_id or "")
        try:
            token = _GOVERNED_WRITE_ADAPTER.validate_decision_token(
                decision_token=grant.decision_token if grant else None,
                action=_MCP_APPEND_ACTION,
                write_class=_MCP_APPEND_WRITE_CLASS,
                actor=actor,
                resource=resource,
            )
        except (InvalidDecisionTokenError, MissingDecisionTokenError) as exc:
            raise StepExecutionError(
                f"GOV refused mcp.vault.append_note: {exc}",
                error_type="policy_denied",
            ) from exc

        try:
            vault_root = _resolve_effect_vault_root(context.tool_settings)
        except VaultToolError as exc:
            raise StepExecutionError(
                f"vault root could not be resolved: {exc}",
                error_type="mcp_tool_error",
            )
        effect_id = _effect_identity(
            context.plan_id,
            step_id or "mcp.vault.append_note",
            args,
            vault_root=vault_root,
        )
        with _effect_lock(effect_id, vault_root):
            return self._run_vault_append_locked(
                args=args,
                context=context,
                actor=actor,
                resource=resource,
                token=token,
                grant=grant,
                effect_id=effect_id,
                vault_root=vault_root,
            )

    def _run_vault_append_locked(
        self,
        *,
        args: Mapping[str, Any],
        context: StepContext,
        actor: str,
        resource: str,
        token: DecisionToken,
        grant: GovernedWriteGrant | None,
        effect_id: str,
        vault_root: Path | None,
    ) -> Dict[str, Any]:
        outbox_path = _resolve_outbox_path()
        try:
            persisted = _persisted_authority_receipt(
                effect_id,
                outbox_path,
                args=args,
                actor=actor,
                resource=resource,
            )
        except _EffectReconciliationConflict as exc:
            raise StepExecutionError(
                f"effect reconciliation is indeterminate: {exc}",
                error_type="effect_reconciliation_conflict",
            ) from exc
        if persisted is not None:
            execution_payload = persisted.get("execution_result")
            if not isinstance(execution_payload, dict):
                raise StepExecutionError(
                    "durable AuthorityReceipt has no factual EXE receipt",
                    error_type="receipt_missing",
                )
            effect_result = execution_payload.get("effect_result")
            if not isinstance(effect_result, dict):
                raise StepExecutionError(
                    "durable AuthorityReceipt has no factual effect result",
                    error_type="receipt_missing",
                )
            try:
                notification_persisted = _persisted_notification(
                    effect_id,
                    outbox_path,
                    effect_result=effect_result,
                    authority_receipt=persisted.get("authority_receipt"),
                )
            except _EffectReconciliationConflict as exc:
                raise StepExecutionError(
                    f"effect reconciliation is indeterminate: {exc}",
                    error_type="effect_reconciliation_conflict",
                ) from exc
            if not notification_persisted:
                self._persist_append_notification(
                    effect_id=effect_id,
                    effect_result=effect_result,
                    authority_receipt=persisted.get("authority_receipt"),
                    trace_id=context.trace_id,
                )
            return {
                **effect_result,
                "receipt_ref": execution_payload.get("receipt_ref"),
                "effect_id": effect_id,
                "authority_receipt": persisted.get("authority_receipt"),
                "decision_token": persisted.get("decision_token"),
                "retry_decision_token": persisted.get("retry_decision_token"),
            }

        try:
            recovery = _effect_path_from_vault(effect_id, vault_root, args, actor)
        except _EffectReconciliationConflict as exc:
            raise StepExecutionError(
                f"effect reconciliation is indeterminate: {exc}",
                error_type="effect_reconciliation_conflict",
            ) from exc
        authorization_token = recovery.decision_token if recovery else token
        retry_token = token if recovery and token.token_id != authorization_token.token_id else None
        request_args = dict(args)
        request_args["metadata"] = _effect_metadata_with_authorization(
            args,
            effect_id,
            authorization_token,
        )
        execution_request = ExecutionRequest(
            side_effect=_MCP_APPEND_ACTION,
            actor=actor,
            resource=resource,
            adapter=_MCP_APPEND_ACTION,
            decision_token=authorization_token,
            effect_id=effect_id,
            trace_id=context.trace_id,
            args=request_args,
        )

        note_path = recovery.path if recovery else None
        try:
            if note_path is None:
                note_path = append_note(
                    title=str(args.get("title") or "").strip(),
                    body=str(args.get("body") or ""),
                    tags=args.get("tags") or [],
                    metadata=request_args["metadata"],
                    vault_root=vault_root,
                )
                _EFFECT_PATH_HINTS[effect_id] = Path(note_path)
                _EFFECT_ROOT_HINTS[effect_id] = (
                    str(Path(vault_root).expanduser().resolve()) if vault_root is not None else None
                )
            note_reference = _effect_note_reference(note_path)
            effect_result = {"status": "ok", "note_path": note_reference}
            effect_receipt = _EffectReceipt(
                operation="append_note",
                locator=_EffectLocator(path=note_reference),
                adapter=_MCP_APPEND_ACTION,
                trace_id=context.trace_id,
            )
            authority_receipt = _GOVERNED_WRITE_ADAPTER.record_authority_receipt(
                decision_token=authorization_token,
                mutation_receipt=cast(Any, effect_receipt),
                state_owner=_MCP_APPEND_STATE_OWNER,
                trace_id=context.trace_id,
                resource=resource,
                effect_id=effect_id,
            )
            execution_result = ExecutionResult(
                request=execution_request,
                status="succeeded",
                effect_result=effect_result,
                receipt_ref=f"{_MCP_APPEND_ACTION}:{note_reference}",
                trace_id=context.trace_id,
            )
            self._persist_authority_receipt(
                effect_id=effect_id,
                execution_result=execution_result,
                grant=grant,
                authority_receipt=authority_receipt,
                trace_id=context.trace_id,
            )
            self._persist_append_notification(
                effect_id=effect_id,
                effect_result=effect_result,
                authority_receipt=authority_receipt,
                trace_id=context.trace_id,
            )
            _EFFECT_PATH_HINTS.pop(effect_id, None)
            _EFFECT_ROOT_HINTS.pop(effect_id, None)
            return {
                **effect_result,
                "receipt_ref": execution_result.receipt_ref,
                "effect_id": effect_id,
                "authority_receipt": asdict(authority_receipt),
                "decision_token": asdict(authorization_token),
                **(
                    {"retry_decision_token": asdict(retry_token)}
                    if retry_token is not None
                    else {}
                ),
            }
        except VaultToolError as exc:
            ExecutionResult(
                request=execution_request,
                status="failed",
                effect_result={"error": str(exc)},
                trace_id=context.trace_id,
            )
            raise StepExecutionError(f"vault append failed: {exc}", error_type="mcp_tool_error") from exc

    def _persist_authority_receipt(
        self,
        *,
        effect_id: str,
        execution_result: ExecutionResult,
        grant: GovernedWriteGrant | None,
        authority_receipt: AuthorityReceipt,
        trace_id: str | None,
    ) -> None:
        payload = {
            "effect_id": effect_id,
            "execution_result": asdict(execution_result),
            "decision_token": (
                asdict(execution_result.request.decision_token)
                if execution_result.request.decision_token
                else None
            ),
            "retry_decision_token": (
                asdict(grant.decision_token)
                if grant
                and execution_result.request.decision_token
                and grant.decision_token.token_id
                != execution_result.request.decision_token.token_id
                else None
            ),
            "authority_receipt": asdict(authority_receipt),
        }
        event = OutboxEvent(
            event=_AUTHORITY_RECEIPT_EVENT,
            event_id=_event_id(effect_id, "authority_receipt"),
            trace_id=trace_id or effect_id,
            source="orchestrator.runtime",
            payload=payload,
        )
        _write_outbox_events(_resolve_outbox_path(), [event])

    def _persist_append_notification(
        self,
        *,
        effect_id: str,
        effect_result: Mapping[str, Any],
        authority_receipt: Mapping[str, Any] | AuthorityReceipt | None,
        trace_id: str | None,
    ) -> None:
        if isinstance(authority_receipt, AuthorityReceipt):
            authority_payload: Mapping[str, Any] | None = asdict(authority_receipt)
        else:
            authority_payload = authority_receipt
        event = OutboxEvent(
            event=_MCP_APPEND_EVENT,
            event_id=_event_id(effect_id, "notification"),
            trace_id=trace_id or effect_id,
            source="orchestrator.runtime",
            payload={
                "effect_id": effect_id,
                "note_path": effect_result.get("note_path"),
                "authority_receipt": authority_payload,
            },
        )
        _write_outbox_events(_resolve_outbox_path(), [event])


def execute_plan_step(
    executor: PlanExecutor,
    step: PlanStep,
    context: StepContext,
) -> Dict[str, Any]:
    """Execute the bounded authority and receipt steps for structural vault appends.

    Admission verifies these step references against the concrete append step. The
    authority check repeats the same policy and WriteGuard used by append execution;
    it is a runtime check, not authority conferred by plan metadata. The receipt step
    returns the completed executor result itself so a caller-authored declaration can
    never mint or substitute a receipt.
    """
    if (
        step.step_class == "authority_check"
        and step.kind == "decision"
        and step.tool == "mcp.vault.append_note"
        and isinstance(step.metadata.get("append_effect_step_id"), str)
    ):
        if is_policy_enforced() and not context.agent_id:
            raise StepExecutionError(
                "policy: missing agent_id in StepContext",
                error_type="policy_denied",
            )
        try:
            assert_tool_allowed(context.agent_id, "mcp.vault.append_note")
        except PermissionError as exc:
            raise StepExecutionError(str(exc), error_type="policy_denied") from exc
        resource = _effect_resource(step.tool_args or {})
        if not resource:
            raise StepExecutionError(
                "mcp.vault.append_note authority check requires a target title",
                error_type="invalid_tool_args",
            )
        try:
            grant = _GOVERNED_WRITE_ADAPTER.issue_decision_token(
                write_guard=DEFAULT_WRITE_GUARD,
                action=_MCP_APPEND_ACTION,
                write_class=_MCP_APPEND_WRITE_CLASS,
                actor=context.agent_id or "orchestrator.runtime",
                resource=resource,
            )
        except Exception as exc:
            raise StepExecutionError(
                f"WriteGuard blocked mcp.vault.append_note: {exc}",
                error_type="write_guard_denied",
            ) from exc
        effect_step_id = str(step.metadata["append_effect_step_id"])
        context.governed_write_grants[effect_step_id] = grant
        return {
            "status": "allowed",
            "tool": "mcp.vault.append_note",
            "governed_write": {
                "policy_decision": asdict(grant.policy_decision),
                "decision_token": asdict(grant.decision_token),
            },
        }

    receipt_from_step = step.metadata.get("receipt_from_step")
    if (
        step.step_class == "receipt"
        and step.kind == "note"
        and isinstance(receipt_from_step, str)
    ):
        execution_result = context.results.get(receipt_from_step)
        if not isinstance(execution_result, dict):
            raise StepExecutionError(
                f"receipt source step '{receipt_from_step}' has no executor result",
                error_type="receipt_missing",
            )
        result_payload = execution_result.get("result")
        receipt_ref = (
            result_payload.get("receipt_ref")
            if isinstance(result_payload, dict)
            else None
        )
        return {
            "result_step_id": receipt_from_step,
            "receipt_ref": receipt_ref,
            "execution_result": execution_result,
        }

    return executor.execute_step(step, context)


def _run_promotion_intent(args: Mapping[str, Any], context: StepContext) -> Dict[str, Any]:
    note_uuid = str(args.get("note_uuid") or "")
    note_info: Dict[str, Any] = {"uuid": note_uuid}
    try:
        obj = ObjectStore().get_object(note_uuid)
    except Exception:
        obj = None
    if obj:
        if getattr(obj, "source_ref", None):
            note_info["path"] = str(obj.source_ref)
        if isinstance(getattr(obj, "payload", None), dict):
            origin = obj.payload.get("origin")
            if origin:
                note_info["origin"] = origin

    action_id = str(args.get("action_id") or "")
    payload: Dict[str, Any] = {
        "note": note_info,
        "action": {"id": action_id, "label": str(args.get("action_label") or action_id or "")},
    }
    downstream_event = args.get("downstream_event")
    if downstream_event:
        payload["action"]["downstream_event"] = str(downstream_event)
    instruction = args.get("instruction")
    if instruction:
        payload["instruction"] = str(instruction)
    payload = normalize_promotion_payload(
        {
            **payload,
            "maturity": args.get("target_maturity") or args.get("maturity"),
            "review_state": args.get("review_state"),
        }
    )

    event_kwargs = {
        "event": "promote.intent.created",
        "source": "orchestrator.runtime",
        "payload": payload,
    }
    if context.trace_id:
        event_kwargs["trace_id"] = context.trace_id
    promote_event = OutboxEvent(**event_kwargs)
    _write_outbox_events(_resolve_outbox_path(), [promote_event])
    return {"status": "ok", "event": promote_event.model_dump(mode="json")}


__all__ = [
    "AgentHandler",
    "PlanExecutor",
    "StepContext",
    "StepExecutionError",
    "MockPlanExecutor",
    "execute_plan_step",
]
