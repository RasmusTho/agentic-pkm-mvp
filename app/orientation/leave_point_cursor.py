from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

import yaml

from app.api.routes.artifacts import _content_hash, _extract_title
from app.chat.canvas_writer import _split_frontmatter

LEAVE_POINT_EVENT_TYPE = "workspace.leave_point.captured.v1"
LEAVE_POINT_CURSOR_VERSION = 1
DEFAULT_TTL = timedelta(hours=72)
MAX_TTL = timedelta(days=7)

ALLOWED_SOURCE_KINDS = {"artifact_activation", "canvas_session", "session_end"}
ALLOWED_CAPTURE_REASONS = {"artifact_focus", "artifact_interaction", "session_end"}
ALLOWED_CURSOR_FIELDS = {
    "cursor_version",
    "event_type",
    "vault_id",
    "channel",
    "artifact_uuid",
    "captured_at",
    "expires_at",
    "last_session_id",
    "trace_id",
    "source_ref",
    "content_hash_at_capture",
    "capture_reason",
}
ALLOWED_SOURCE_REF_FIELDS = {"kind", "ref_id"}


@dataclass(frozen=True)
class LeavePointArtifactRef:
    artifact_uuid: str | None
    logical_ref: str | None
    title: str | None


@dataclass(frozen=True)
class LeavePointSourceRef:
    kind: str | None
    trace_id: str | None


@dataclass(frozen=True)
class LeavePointProjection:
    status: Literal["absent", "present", "stale", "artifact_missing", "degraded"]
    artifact_ref: LeavePointArtifactRef
    captured_at: str | None
    last_session_id: str | None
    authority_role: Literal["operational_trace_pointer", "derived_runtime_projection"]
    source_ref: LeavePointSourceRef


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _db_path() -> Path:
    configured = os.getenv("LEAVE_POINT_TRACE_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(os.getenv("RUNTIME_TRACE_DIR", "runtime/orientation")).expanduser() / "leave_point_trace.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_point_trace_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            vault_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            artifact_uuid TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_leave_point_trace_scope
        ON leave_point_trace_events(vault_id, channel, captured_at, id)
        """
    )
    conn.commit()
    return conn


def _safe_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_ref_id(value: str) -> str:
    candidate = PurePosixPath(value)
    if not value or value.startswith("/") or ".." in candidate.parts:
        raise ValueError("source_ref.ref_id must not be an absolute or escaping path")
    return candidate.as_posix()


def _frontmatter(body: str) -> dict[str, Any]:
    frontmatter, _ = _split_frontmatter(body)
    if frontmatter is None:
        return {}
    try:
        parsed = yaml.safe_load(frontmatter) or {}
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _artifact_metadata(path: Path, vault_root: Path) -> tuple[str | None, str, str, str]:
    body = path.read_text(encoding="utf-8")
    frontmatter = _frontmatter(body)
    artifact_uuid = _safe_str(frontmatter.get("uuid") or frontmatter.get("id"))
    logical_ref = path.relative_to(vault_root).as_posix()
    title = _extract_title(body, fallback=path.stem)
    return artifact_uuid, logical_ref, title, _content_hash(body)


def find_artifact_by_uuid(vault_root: Path, artifact_uuid: str) -> tuple[str, str, str] | None:
    if not vault_root.exists():
        return None
    for path in vault_root.rglob("*.md"):
        if not path.is_file():
            continue
        try:
            resolved_uuid, logical_ref, title, content_hash = _artifact_metadata(path, vault_root)
        except Exception:
            continue
        if resolved_uuid == artifact_uuid:
            return logical_ref, title, content_hash
    return None


def capture_leave_point_cursor(
    *,
    vault_id: str,
    channel: str,
    artifact_uuid: str,
    source_kind: Literal["artifact_activation", "canvas_session", "session_end"],
    source_ref_id: str,
    capture_reason: Literal["artifact_focus", "artifact_interaction", "session_end"],
    last_session_id: str | None = None,
    trace_id: str | None = None,
    content_hash_at_capture: str | None = None,
    captured_at: datetime | None = None,
    ttl: timedelta = DEFAULT_TTL,
) -> dict[str, Any]:
    if source_kind not in ALLOWED_SOURCE_KINDS:
        raise ValueError("invalid leave-point source kind")
    if capture_reason not in ALLOWED_CAPTURE_REASONS:
        raise ValueError("invalid leave-point capture reason")
    artifact_uuid = _safe_str(artifact_uuid) or ""
    vault_id = _safe_str(vault_id) or ""
    channel = _safe_str(channel) or ""
    resolved_trace_id = _safe_str(trace_id) or uuid4().hex
    if not artifact_uuid or not vault_id or not channel or not resolved_trace_id:
        raise ValueError("vault_id, channel, artifact_uuid, and trace_id are required")
    if ttl <= timedelta(0) or ttl > MAX_TTL:
        raise ValueError("leave-point cursor TTL must be positive and at most 7 days")

    captured = captured_at or _now()
    event = {
        "cursor_version": LEAVE_POINT_CURSOR_VERSION,
        "event_type": LEAVE_POINT_EVENT_TYPE,
        "vault_id": vault_id,
        "channel": channel,
        "artifact_uuid": artifact_uuid,
        "captured_at": _iso(captured),
        "expires_at": _iso(captured + ttl),
        "last_session_id": _safe_str(last_session_id),
        "trace_id": resolved_trace_id,
        "source_ref": {
            "kind": source_kind,
            "ref_id": _safe_ref_id(source_ref_id),
        },
        "content_hash_at_capture": _safe_str(content_hash_at_capture),
        "capture_reason": capture_reason,
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO leave_point_trace_events (
                event_type, vault_id, channel, artifact_uuid, captured_at, trace_id, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                LEAVE_POINT_EVENT_TYPE,
                vault_id,
                channel,
                artifact_uuid,
                event["captured_at"],
                resolved_trace_id,
                json.dumps(event, sort_keys=True, separators=(",", ":")),
            ),
        )
        conn.commit()
    return event


def _valid_cursor_event(payload: Any, *, vault_id: str, channel: str, now: datetime) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if set(payload) - ALLOWED_CURSOR_FIELDS:
        return None
    source_ref = payload.get("source_ref")
    if not isinstance(source_ref, dict) or set(source_ref) - ALLOWED_SOURCE_REF_FIELDS:
        return None
    if payload.get("cursor_version") != LEAVE_POINT_CURSOR_VERSION:
        return None
    if payload.get("event_type") != LEAVE_POINT_EVENT_TYPE:
        return None
    if payload.get("vault_id") != vault_id or payload.get("channel") != channel:
        return None
    if not _safe_str(payload.get("artifact_uuid")) or not _safe_str(payload.get("trace_id")):
        return None
    if source_ref.get("kind") not in ALLOWED_SOURCE_KINDS or not _safe_str(source_ref.get("ref_id")):
        return None
    if payload.get("capture_reason") not in ALLOWED_CAPTURE_REASONS:
        return None
    captured_at = _parse_iso(payload.get("captured_at"))
    expires_at = _parse_iso(payload.get("expires_at"))
    if captured_at is None or expires_at is None or expires_at <= now:
        return None
    if expires_at - captured_at > MAX_TTL:
        return None
    return payload


def _projection(
    *,
    status: Literal["absent", "present", "stale", "artifact_missing", "degraded"],
    artifact_uuid: str | None = None,
    logical_ref: str | None = None,
    title: str | None = None,
    captured_at: str | None = None,
    last_session_id: str | None = None,
    authority_role: Literal["operational_trace_pointer", "derived_runtime_projection"],
    source_kind: str | None = None,
    trace_id: str | None = None,
) -> LeavePointProjection:
    return LeavePointProjection(
        status=status,
        artifact_ref=LeavePointArtifactRef(
            artifact_uuid=artifact_uuid,
            logical_ref=logical_ref,
            title=title,
        ),
        captured_at=captured_at,
        last_session_id=last_session_id,
        authority_role=authority_role,
        source_ref=LeavePointSourceRef(kind=source_kind, trace_id=trace_id),
    )


def latest_leave_point_projection(
    *,
    vault_id: str,
    channel: str,
    vault_root: Path,
    derived_label: str | None = None,
    derived_at: str | None = None,
) -> LeavePointProjection:
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT payload
                FROM leave_point_trace_events
                WHERE vault_id = ? AND channel = ?
                ORDER BY captured_at DESC, id DESC
                LIMIT 20
                """,
                (vault_id, channel),
            ).fetchall()
    except Exception:
        rows = []

    now = _now()
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except Exception:
            continue
        event = _valid_cursor_event(payload, vault_id=vault_id, channel=channel, now=now)
        if event is None:
            continue
        artifact_uuid = str(event["artifact_uuid"])
        source_ref = event["source_ref"]
        artifact = find_artifact_by_uuid(vault_root, artifact_uuid)
        if artifact is None:
            return _projection(
                status="artifact_missing",
                artifact_uuid=artifact_uuid,
                captured_at=event["captured_at"],
                last_session_id=event.get("last_session_id"),
                authority_role="operational_trace_pointer",
                source_kind=source_ref.get("kind"),
                trace_id=event.get("trace_id"),
            )
        logical_ref, title, current_hash = artifact
        captured_hash = event.get("content_hash_at_capture")
        if captured_hash and captured_hash != current_hash:
            return _projection(
                status="stale",
                artifact_uuid=artifact_uuid,
                logical_ref=logical_ref,
                title=title,
                captured_at=event["captured_at"],
                last_session_id=event.get("last_session_id"),
                authority_role="operational_trace_pointer",
                source_kind=source_ref.get("kind"),
                trace_id=event.get("trace_id"),
            )
        return _projection(
            status="present",
            artifact_uuid=artifact_uuid,
            logical_ref=logical_ref,
            title=title,
            captured_at=event["captured_at"],
            last_session_id=event.get("last_session_id"),
            authority_role="operational_trace_pointer",
            source_kind=source_ref.get("kind"),
            trace_id=event.get("trace_id"),
        )

    return _projection(
        status="absent",
        title=derived_label,
        captured_at=derived_at,
        authority_role="derived_runtime_projection",
        source_kind=None,
        trace_id=None,
    )


def append_raw_leave_point_trace(payload: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO leave_point_trace_events (
                event_type, vault_id, channel, artifact_uuid, captured_at, trace_id, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("corrupt", "unknown", "unknown", "unknown", _iso(_now()), "corrupt", payload),
        )
        conn.commit()


def clear_leave_point_trace() -> None:
    path = _db_path()
    if path.exists():
        path.unlink()


__all__ = [
    "ALLOWED_CURSOR_FIELDS",
    "ALLOWED_SOURCE_REF_FIELDS",
    "DEFAULT_TTL",
    "LEAVE_POINT_EVENT_TYPE",
    "LeavePointProjection",
    "append_raw_leave_point_trace",
    "capture_leave_point_cursor",
    "clear_leave_point_trace",
    "latest_leave_point_projection",
]
