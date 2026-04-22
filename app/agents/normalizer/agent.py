from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.events.types import INGEST_NORMALIZE_DONE
from app.store.object_store import ObjectStore
from app.services.audit import audit_event


AGENT = "normalizer"
_ALLOWED_ARTIFACT_KINDS = {"note", "task", "knowledge", "reference", "log"}


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---"):
        return {}, raw
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw
    end_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}, raw
    frontmatter_text = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
        if not isinstance(frontmatter, dict):
            frontmatter = {}
    except Exception:
        frontmatter = {}
    return frontmatter, body


def _resolve_artifact_kind(frontmatter: dict[str, Any], explicit_kind: str | None) -> tuple[str, list[dict[str, str]]]:
    diagnostics: list[dict[str, str]] = []
    requested = str(explicit_kind or frontmatter.get("artifact_kind") or frontmatter.get("kind") or "").strip().lower()
    if not requested:
        return "note", diagnostics
    if requested in _ALLOWED_ARTIFACT_KINDS:
        return requested, diagnostics
    diagnostics.append(
        {
            "code": "unsupported_artifact_kind",
            "requested_kind": requested,
            "fallback_kind": "note",
        }
    )
    return "note", diagnostics


def _read_file(path: str) -> tuple[str, str, dict[str, Any]]:
    """
    Return (title, body_text) from a markdown-ish file.
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw)
    lines = [ln.strip() for ln in body.splitlines()]
    title = ""
    for ln in lines:
        if ln.startswith("#"):
            cand = ln.lstrip("#").strip()
            if cand:
                title = cand
                break
        elif ln:
            title = ln
            break
    if not title:
        title = p.stem
    return title, raw, frontmatter


def normalize_file(path: str, *, trace_id: str, artifact_kind: str | None = None) -> dict[str, Any]:
    """
    Build a 'domain object' from a source file:
    - uuid
    - core6 metadata
    - payload with raw_text + source_path
    """
    title, raw_text, frontmatter = _read_file(path)
    normalized_artifact_kind, diagnostics = _resolve_artifact_kind(frontmatter, artifact_kind)

    object_uuid = str(_uuid.uuid4())

    core6 = {
        "id": object_uuid,
        "title": title,
        "review_state": "reviewed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    payload: dict[str, Any] = {
        "core6": core6,
        "raw_text": raw_text,
        "source_path": path,
        "artifact_kind": normalized_artifact_kind,
        "policy_profile_kind": normalized_artifact_kind,
        "ingest_diagnostics": diagnostics,
    }

    domain_object = {
        "uuid": object_uuid,
        "kind": "note",
        "payload": payload,
        # carry source_ref as first-class too for DB upsert
        "source_ref": path,
    }

    # best-effort audit
    audit_event(
        event=INGEST_NORMALIZE_DONE,
        object_id=object_uuid,
        agent=AGENT,
        trace_id=trace_id,
        extra={"path": path, "title": title},
    )

    return domain_object


@dataclass
class _DomainObjectShim:
    uuid: str
    kind: str
    payload: dict[str, Any]
    created_at: datetime
    source_ref: str | None


def run(path: str, *, trace_id: str, artifact_kind: str | None = None) -> dict[str, Any]:
    """
    End-to-end:
    - normalize file into domain_object
    - create shim matching ObjectStore expectations
    - save via ObjectStore (memory + DB if available)
    """
    store = ObjectStore()
    dom = normalize_file(path, trace_id=trace_id, artifact_kind=artifact_kind)

    shim = _DomainObjectShim(
        uuid=dom["uuid"],
        kind=dom["kind"],
        payload=dom["payload"],
        created_at=datetime.now(timezone.utc),
        source_ref=dom.get("source_ref") or dom["payload"].get("source_path"),
    )

    store.save_object(
        shim,
        emit_outbox=False,
        trace_id=trace_id,
    )

    out = {
        "event": INGEST_NORMALIZE_DONE,
        "object_id": dom["uuid"],
        "uuid": dom["uuid"],
        "kind": dom["kind"],
        "payload": dom["payload"],
        "source_ref": dom["source_ref"],
        "core6": dom["payload"]["core6"],
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    return out
