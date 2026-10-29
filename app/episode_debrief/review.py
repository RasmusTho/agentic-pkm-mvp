"""DEBRIEF-03: review a published debrief without deleting or promoting it.

The durable debrief note is the only source. Accept and dismiss flip the
canonical ``review_state`` axis (``draft`` -> ``reviewed`` / ``archived``); the
frontmatter flip is the commit point and the receipt is an idempotent echo.
``authority_state``, the body, the file and the Episode ``debrief_ref`` link are
never touched. Unlike EXP-4 ``decline_draft`` nothing is ever retired.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import yaml

from app.agents.panel.filters import strip_ai_panels
from app.expansion import create
from app.knowledge.write_ops import read_note_text_with_version, write_note_from_absolute
from app.services.outbox import (
    append_jsonl_outbox_event, jsonl_outbox_append_lock, read_jsonl_outbox_records,
)
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import load_frontmatter

WRITE_ACTION = "episode_debrief.review"
DEBRIEF_DIR = Path("_system/episode-debriefs")
REVIEWED_EVENT = "episode_debrief.reviewed"
DISMISSED_EVENT = "episode_debrief.dismissed"
REVIEW_EVENT_SOURCE = "episode_debrief.review"
FRESH_STATE = "draft"
# Closed STATE_AXES_CONTRACT vocabulary; no debrief-specific value is invented.
DISPOSITIONS = {"accepted": ("reviewed", REVIEWED_EVENT), "dismissed": ("archived", DISMISSED_EVENT)}
_DEBRIEF_ID = re.compile(r"\Adebrief-[0-9a-f]{64}\Z")


class DebriefReviewError(ValueError):
    """Typed refusal; the debrief and its receipts are left unchanged."""


class DebriefNotFoundError(DebriefReviewError):
    """No published debrief exists for this identity."""


class DebriefDispositionConflictError(DebriefReviewError):
    """The debrief was already disposed differently; dispositions never overwrite."""


def _review_state_span(raw: str) -> tuple[int, int, str]:
    """Locate the plain ``review_state`` scalar inside the leading frontmatter."""
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", raw, re.S)
    if match is None:
        raise DebriefReviewError("debrief frontmatter cannot be patched")
    if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(match.group(1))):
        raise DebriefReviewError("aliased debrief fields cannot be patched safely")
    document = yaml.compose(match.group(1))
    if not isinstance(document, yaml.MappingNode):
        raise DebriefReviewError("debrief frontmatter must be a mapping")
    found = [node for key, node in document.value if key.value == "review_state"]
    if len(found) != 1 or not isinstance(found[0], yaml.ScalarNode) or found[0].style is not None:
        raise DebriefReviewError("debrief review_state must be one plain scalar")
    node = found[0]
    return match.start(1) + node.start_mark.index, match.start(1) + node.end_mark.index, node.value


def _with_review_state(raw: str, value: str) -> str:
    """Replace only the review_state value, preserving every other byte."""
    start, end, _ = _review_state_span(raw)
    patched = raw[:start] + value + raw[end:]
    before, before_body = load_frontmatter(raw)
    after, after_body = load_frontmatter(patched)
    if {**before, "review_state": value} != after or before_body != after_body:
        raise DebriefReviewError("review patch attempted to change protected debrief content")
    return patched


def _debrief_path(root: Path, debrief_id: str) -> Path:
    if not _DEBRIEF_ID.match(debrief_id):
        raise DebriefNotFoundError("unknown debrief identity")
    path = root / DEBRIEF_DIR / f"{debrief_id}.md"
    # A same-vault leaf alias must not redirect the flip to another note.
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve() / DEBRIEF_DIR):
        raise DebriefReviewError("debrief path is not owned by the selected vault")
    return path


def published_debrief(path: Path) -> tuple[str, str, dict[str, Any], str] | None:
    """Return (raw, version, frontmatter, body) for a fully published debrief.

    Publication is Create's contract: a matching integrity record over the
    as-published bytes (``review_state: draft``) and a proposal receipt.
    Partially published or tampered drafts are not reviewable.
    """
    try:
        raw, version = read_note_text_with_version(path)
        fields, body = load_frontmatter(raw)
    except (OSError, UnicodeError, ValueError):
        return None
    debrief_id = path.stem
    if (fields.get("uuid") != debrief_id or fields.get("create_kind") != create.OutputKind.EPISODE_DEBRIEF.value
            or fields.get("authority_state") != "proposal"
            or not isinstance(fields.get("episode_id"), str)):
        return None
    try:
        published = _with_review_state(raw, FRESH_STATE).encode("utf-8")
        integrity = json.loads(create._draft_integrity_path(path).read_text(encoding="utf-8"))
    except (DebriefReviewError, OSError, UnicodeError, ValueError):
        return None
    if not isinstance(integrity, dict) or integrity.get("draft_id") != debrief_id or (
            integrity.get("draft_sha256") != hashlib.sha256(published).hexdigest()):
        return None
    outbox = path.parent / "outbox.jsonl"
    if not any(record.get("event") == create.CREATE_PROPOSED_EVENT
               and (record.get("payload") or {}).get("draft_id") == debrief_id
               for record in read_jsonl_outbox_records(outbox, read_only=True)):
        return None
    return raw, version, fields, body


def replay_published_metadata(path: Path, *, request_fingerprint: str, draft_id: str) -> tuple[dict[str, Any], str]:
    """DEBRIEF-02 replay over a reviewed debrief: verify the as-published bytes.

    A disposition flips one frontmatter value after publication, so synthesis
    replay checks Create integrity against the draft with review_state restored.
    """
    raw = path.read_text(encoding="utf-8")
    fields, _ = load_frontmatter(raw)
    if fields.get("review_state") == FRESH_STATE:
        retained = create._replay_draft_metadata(path, request_fingerprint=request_fingerprint, draft_id=draft_id)
        assert retained is not None
        return retained
    published = _with_review_state(raw, FRESH_STATE)
    if published_debrief(path) is None:
        raise create.CreateIdempotencyConflictError(f"reviewed debrief integrity does not match publication: {path}")
    metadata, _ = load_frontmatter(published)
    if metadata.get("request_fingerprint") != request_fingerprint:
        raise create.CreateIdempotencyConflictError(f"reviewed debrief identity/content mismatch: {path}")
    return metadata, hashlib.sha256(published.encode("utf-8")).hexdigest()


def _summary(fields: dict[str, Any], body: str, path: Path, root: Path) -> dict[str, Any]:
    title = next((line.lstrip("# ").strip() for line in body.splitlines() if line.startswith("# ")), None)
    return {
        "debrief_id": fields["uuid"], "episode_id": fields["episode_id"], "scope": fields.get("scope"),
        "title": title, "review_state": fields.get("review_state"), "authority_state": fields["authority_state"],
        "created": fields.get("created"), "draft_path": str(path.relative_to(root)),
        # The surface shows the debrief content, not machine-managed AI blocks.
        "body": strip_ai_panels(body).strip(),
    }


def list_fresh_debriefs(vault_root: Path | str) -> list[dict[str, Any]]:
    """Read-only projection of durable debrief notes still awaiting review."""
    root = Path(vault_root).expanduser().resolve(strict=True)
    directory = root / DEBRIEF_DIR
    if not directory.is_dir():
        return []
    fresh = []
    for path in sorted(directory.glob("*.md")):
        if not _DEBRIEF_ID.match(path.stem) or path.is_symlink():
            continue
        loaded = published_debrief(path)
        if loaded is not None and loaded[2].get("review_state") == FRESH_STATE:
            fresh.append(_summary(loaded[2], loaded[3], path, root))
    return sorted(fresh, key=lambda item: (str(item["created"] or ""), item["debrief_id"]), reverse=True)


def _receipt_id(debrief_id: str, disposition: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"episode-debrief-review:{debrief_id}:{disposition}"))


def _ensure_receipt(outbox: Path, event: str, receipt_id: str, payload: dict[str, Any]) -> str:
    # Deterministic id plus payload check: a re-click or a crash-recovery
    # re-entry never appends a duplicate disposition receipt.
    with jsonl_outbox_append_lock(outbox):
        existing = create._existing_receipt(outbox, event, receipt_id, _lock_held=True)
        if existing is None:
            append_jsonl_outbox_event(outbox, {
                "event": event, "event_id": receipt_id, "trace_id": uuid4().hex,
                "source": REVIEW_EVENT_SOURCE, "timestamp": create._iso(create._now()), "payload": payload,
            }, default_source=REVIEW_EVENT_SOURCE, _lock_held=True)
        elif existing.get("payload") != payload:
            raise DebriefDispositionConflictError("existing review receipt does not match this disposition")
    return f"{event}:{receipt_id}"


def review_debrief(
    debrief_id: str, disposition: str, *, vault_root: Path | str,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> dict[str, Any]:
    """Apply one explicit human disposition; never deletes, never promotes."""
    if disposition not in DISPOSITIONS:
        raise DebriefReviewError("disposition must be 'accepted' or 'dismissed'")
    target, event = DISPOSITIONS[disposition]
    write_guard.assert_writes_allowed(WRITE_ACTION)
    root = Path(vault_root).expanduser().resolve(strict=True)
    path = _debrief_path(root, debrief_id)
    with create._draft_publication_lock(path):
        loaded = published_debrief(path)
        if loaded is None:
            raise DebriefNotFoundError("no published debrief exists for this identity")
        raw, version, fields, _ = loaded
        current = fields.get("review_state")
        if current not in {FRESH_STATE, target}:
            raise DebriefDispositionConflictError(f"debrief is already {current}")
        if current == FRESH_STATE:
            write_note_from_absolute(path, _with_review_state(raw, target), vault_root=root,
                                     write_guard=write_guard, action=WRITE_ACTION, expected_version=version)
        # The only admitted transition is from draft, so the receipt is exact
        # even when it is recovered after an interrupted first click.
        payload = {"debrief_id": debrief_id, "episode_id": fields["episode_id"],
                   "prior_review_state": FRESH_STATE, "review_state": target}
        receipt = _ensure_receipt(path.parent / "outbox.jsonl", event, _receipt_id(debrief_id, disposition), payload)
    return {"debrief_id": debrief_id, "episode_id": fields["episode_id"], "review_state": target,
            "authority_state": fields["authority_state"], "receipt": receipt, "changed": current == FRESH_STATE}
