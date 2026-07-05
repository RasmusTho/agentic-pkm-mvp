"""Failure-to-eval capture loop (KERNEL-15, #2777).

Converts the two worst silent failures in the runtime — dead-lettered events
and misrouted intents — into permanent regression-test candidates instead of
letting them vanish into logs. Ground truth in a probabilistic system is
accumulated **adjudicated history**, not a-priori labels (audit §5.4, RQ4).

What this module does:

- On a dead-lettered outbox event whose ``reason`` is a schema-violation
  reason, :func:`draft_dead_letter_case` writes a draft eval-case artifact
  with full provenance. KERNEL-08 (event topic schema registry, #2770) is the
  eventual producer of that reason family; capture is producer-agnostic and
  does not depend on KERNEL-08 having landed.
- On an explicit ``UNKNOWN`` classification (KERNEL-07,
  ``app.components.llm.intent_classifier``), :func:`draft_unknown_classification_case`
  writes a draft ``classification_case.v1`` candidate with full provenance.

Both drafts are **companion-note-class artifacts**
(`docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`): system-owned location resolved
via ``get_vault_system_dir_rel()``, never the human writing surface, never the
DB. Drafting is WriteGuard-gated exactly like `materialize_promoted_memory`
(`app/agent_memory/materialization.py`) — a blocked write-state prevents the
draft from landing.

**No auto-promotion.** A draft is a candidate, not ground truth. Only an
explicit, recorded human decision via :func:`promote_draft` moves a draft into
the golden datasets (`docs/eval/classification_golden.yaml` for classification
cases; a topic-schema fixture for schema-violation cases). Until that decision
is recorded the draft is inert: present as a pending file, absent from any
golden dataset.

Deliberate divergence from "reuse the existing queue surface"
-------------------------------------------------------------

The KERNEL-15 spec says to *mirror* the existing memory review-queue pattern
(`app/agent_memory/review_queue.py` + `materialize_promoted_memory`). This
module mirrors its **shape** — a file-based draft, WriteGuard-gated, with an
explicit human-decision promotion step and no auto-promotion — but does **not**
reuse `MemoryCandidateReviewQueue` itself, by design. That queue is
memory-candidate-specific end to end: every entry is a
:class:`app.agent_memory.candidate.MemoryCandidate` carrying a required
``MemoryType`` cognitive class, activation-policy / working-context-recall
semantics, and a promotion path (`materialize_promoted_memory`) that writes a
``semantic_memory`` note into the agent-memory ledger. The companion API
projection (`_memory_review_candidate_projection` in
`app/api/routes/companion.py`) hard-requires ``proposed_memory_type``.

An eval-dataset case is a **distinct artifact class**: it has no cognitive
memory type, no working-context recall meaning, and its promotion target is a
golden-dataset file, not the memory ledger. Forcing it into
`MemoryCandidateReviewQueue` would mean fabricating a ``MemoryType`` and
materializing it as a memory note — a category error. So eval drafts live in
their own file-based surface (``<system_dir>/eval_drafts/`` with ``status``
frontmatter), honoring the storage-substrate rule (human-reviewable, long-lived
material belongs in notes, not the DB) without corrupting the memory ledger's
semantics.

Reviewer discoverability (a pending-eval-drafts view distinct from the memory
ledger) is delivered by :func:`list_pending_drafts` plus the
``/api/eval-drafts`` route (`app/api/routes/eval_drafts.py`, #2871). Real-traffic
population of the dead-letter draft path still waits on KERNEL-08 (#2770), the
``schema_violation`` producer — the surfacing view itself is not dormant. The
review **UI** stays out of scope (W7/W8). See the "Reviewer surfacing" note in
`docs/RUNTIME_CORRECTNESS_KERNEL/FAILURE_TO_EVAL_CAPTURE_LOOP.md`.

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/FAILURE_TO_EVAL_CAPTURE_LOOP.md
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from uuid import uuid4

import yaml

from app.knowledge.write_ops import write_note_relative
from app.vault.paths import get_vault_system_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

#: WriteGuard action name for a draft eval-case write. Mirrors the naming
#: convention of MEMORY_MATERIALIZATION_ACTION in app/agent_memory/materialization.py.
FAILURE_CAPTURE_DRAFT_ACTION = "eval.failure_capture.draft"

#: Directory (relative to the layout-aware system folder) drafts are written into.
DRAFT_DIR_NAME = "eval_drafts"

#: Draft kinds. `schema_violation` mirrors the dead-letter reason family this
#: task captures (KERNEL-08/12); `classification_case.v1` mirrors the golden-set
#: schema version (KERNEL-13, app/eval/classification.py::CASE_SCHEMA_VERSION).
DRAFT_KIND_SCHEMA_VIOLATION = "schema_violation"
DRAFT_KIND_CLASSIFICATION_CASE = "classification_case.v1"

#: The schema-violation reason family this task captures. KERNEL-08 (event
#: topic schema registry, #2770) is the eventual producer of exactly this
#: family; capture does not depend on KERNEL-08 having landed — any dead-letter
#: reason in this family is drafted regardless of producer. Matched
#: delimiter-aware (see :func:`is_schema_violation_reason`): the bare token
#: ``"schema_violation"`` or a ``"schema_violation:<detail>"`` sub-reason, never
#: an accidental substring like ``"schema_violationXYZ"``.
SCHEMA_VIOLATION_REASON = "schema_violation"

#: Review states for a draft. PENDING is the only state this module ever
#: writes on intake; PROMOTED/REJECTED are terminal states recorded only via
#: an explicit call to promote_draft/reject_draft.
DRAFT_STATUS_PENDING = "pending"
DRAFT_STATUS_PROMOTED = "promoted"
DRAFT_STATUS_REJECTED = "rejected"


class FailureCaptureError(RuntimeError):
    """Raised when a draft eval-case cannot be written or promoted."""


@dataclass(frozen=True)
class SourceEvent:
    """Provenance pointer back to the original production event."""

    topic: str
    event_id: str


@dataclass(frozen=True)
class DraftEvalCase:
    """A single drafted eval-case candidate, as written to the vault."""

    draft_id: str
    kind: str
    trace_id: str | None
    source_event: SourceEvent
    payload_snapshot: Mapping[str, Any]
    created_at: str
    status: str = DRAFT_STATUS_PENDING
    draft_path: str | None = None


def is_schema_violation_reason(reason: str | None) -> bool:
    """True when a dead-letter ``reason`` belongs to the schema-violation family.

    Delimiter-aware: matches the bare token ``"schema_violation"`` or a
    ``"schema_violation:<detail>"`` sub-reason (colon delimiter), and nothing
    else. A bare ``startswith`` would falsely capture an unrelated or
    mistyped reason such as ``"schema_violationXYZ"`` — the colon (or exact
    equality) is required so only genuine members of the family are drafted.
    """
    if not reason:
        return False
    normalized = reason.strip().lower()
    return normalized == SCHEMA_VIOLATION_REASON or normalized.startswith(
        SCHEMA_VIOLATION_REASON + ":"
    )


#: Draft-id shape as generated by :func:`_write_draft`: ``<slug>-<hex12>``,
#: where the slug alphabet is ``[a-z0-9-]``. The validator is deliberately a
#: little wider (case-insensitive alnum plus ``-``/``_``) but admits NO path
#: separators, dots, or other traversal material — a caller-controlled
#: ``draft_id`` reaches a filesystem path (e.g. via the
#: ``POST /api/eval-drafts/{draft_id}/decision`` route), so anything outside
#: this shape is refused before any path construction (py/path-injection
#: hardening, #2871).
_DRAFT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def is_valid_draft_id(draft_id: str) -> bool:
    """True when ``draft_id`` matches the shape this module generates.

    Rejects path separators, dots, empty strings, and oversized values so a
    caller-provided id can never traverse out of the ``eval_drafts/``
    directory when joined into a filesystem path.
    """
    return bool(_DRAFT_ID_RE.fullmatch(draft_id or ""))


def _drafts_dir(vault_root: Path) -> Path:
    return Path(get_vault_system_dir_rel(vault_root)) / DRAFT_DIR_NAME


def _draft_path(vault_root: Path, draft_id: str) -> Path:
    return _drafts_dir(vault_root) / f"{draft_id}.md"


def _contained_draft_abspath(vault_root: Path, draft_id: str) -> Path | None:
    """Resolve ``draft_id`` to an absolute path inside ``eval_drafts/``, or None.

    Two independent layers (validate-then-contain, the repo-precedent pattern —
    see ``app/knowledge/write_ops.py::write_note_from_absolute`` and
    ``app/api/routes/artifacts.py::_resolve_and_validate``):

    1. strict id-shape validation (:func:`is_valid_draft_id`) rejects any
       separator/dot/traversal material outright;
    2. ``os.path.realpath`` + prefix check (the CodeQL-recognized
       py/path-injection sanitizer) asserts the resolved candidate stays
       under the resolved ``eval_drafts/`` directory even in the face of
       symlinks or future id-shape drift.
    """
    if not is_valid_draft_id(draft_id):
        return None
    drafts_root = os.path.realpath(str(vault_root / _drafts_dir(vault_root)))
    candidate = os.path.realpath(str(vault_root / _draft_path(vault_root, draft_id)))
    if not candidate.startswith(drafts_root + os.sep):
        return None
    return Path(candidate)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_rel_path(value: str) -> str:
    path = PurePosixPath(value)
    if value.startswith("/") or ".." in path.parts:
        raise FailureCaptureError("draft artifact path must stay vault-relative")
    return path.as_posix()


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "case"


def _write_draft(
    *,
    vault_root: Path,
    kind: str,
    trace_id: str | None,
    source_event: SourceEvent,
    payload_snapshot: Mapping[str, Any],
    title: str,
    write_guard: WriteGuard,
) -> DraftEvalCase:
    """Shared write path for both draft kinds. WriteGuard-gated, never auto-promotes."""
    # Fail-loud, production write path: a blocked write-state must prevent the
    # draft from being written at all — asserted BEFORE any file I/O, matching
    # materialize_promoted_memory's use of DEFAULT_WRITE_GUARD.
    write_guard.assert_writes_allowed(FAILURE_CAPTURE_DRAFT_ACTION)

    draft_id = f"{_slug(kind)}-{uuid4().hex[:12]}"
    created_at = _now_iso()
    draft = DraftEvalCase(
        draft_id=draft_id,
        kind=kind,
        trace_id=trace_id,
        source_event=source_event,
        payload_snapshot=dict(payload_snapshot),
        created_at=created_at,
        status=DRAFT_STATUS_PENDING,
    )

    rel_path = _safe_rel_path(str(_draft_path(vault_root, draft_id)))
    content = _render_draft_note(draft, title=title)
    write_note_relative(rel_path, content, vault_root=vault_root)
    return DraftEvalCase(
        draft_id=draft.draft_id,
        kind=draft.kind,
        trace_id=draft.trace_id,
        source_event=draft.source_event,
        payload_snapshot=draft.payload_snapshot,
        created_at=draft.created_at,
        status=draft.status,
        draft_path=rel_path,
    )


def draft_dead_letter_case(
    *,
    vault_root: Path,
    topic: str,
    reason: str,
    event_id: str,
    payload: Mapping[str, Any],
    trace_id: str | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> DraftEvalCase | None:
    """Draft a schema-violation dead-letter as an eval-case candidate.

    Called from the production dead-letter emission sites in
    ``app.workers.outbox_worker`` (``_dead_letter_outbox_message`` /
    ``_emit_retry_dead_letter``). Only ``reason`` values in the
    schema-violation family (see :func:`is_schema_violation_reason`) produce a
    draft; any other dead-letter reason returns ``None`` — this task is
    bounded to schema-violation capture, not every dead-letter.

    Raises whatever :meth:`WriteGuard.assert_writes_allowed` raises
    (``WritesBlockedError``) when writes are currently blocked — the caller
    (worker dead-letter path) treats this as best-effort exactly like the
    audit emission it wraps.
    """
    if not is_schema_violation_reason(reason):
        return None
    source_event = SourceEvent(topic=topic, event_id=event_id)
    payload_snapshot = {
        "topic": topic,
        "reason": reason,
        "event_id": event_id,
        "payload": dict(payload),
    }
    return _write_draft(
        vault_root=vault_root,
        kind=DRAFT_KIND_SCHEMA_VIOLATION,
        trace_id=trace_id,
        source_event=source_event,
        payload_snapshot=payload_snapshot,
        title=f"Dead-letter draft: {topic} ({reason})",
        write_guard=write_guard,
    )


def draft_unknown_classification_case(
    *,
    vault_root: Path,
    utterance: str,
    surface: str = "canvas",
    note_state: str = "",
    language: str = "en",
    rationale: str | None = None,
    trace_id: str | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> DraftEvalCase:
    """Draft an UNKNOWN classification as a ``classification_case.v1`` candidate.

    Called from the caller of ``IntentClassifierCognition.classify`` when the
    result's ``intent_class`` is ``IntentClass.UNKNOWN`` (``classified=False``,
    KERNEL-07). Every UNKNOWN produces a draft — there is no reason filter here
    the way there is for dead-letters, because UNKNOWN is already the single
    explicit failure class.
    """
    event_id = trace_id or uuid4().hex
    source_event = SourceEvent(topic="chat.intent_classification", event_id=event_id)
    payload_snapshot = {
        "case_shape": DRAFT_KIND_CLASSIFICATION_CASE,
        "utterance": utterance,
        "language": language,
        "context": {"surface": surface, "note_state": note_state},
        "expected_intent": None,  # unresolved until a human adjudicates
        "rationale": rationale,
    }
    return _write_draft(
        vault_root=vault_root,
        kind=DRAFT_KIND_CLASSIFICATION_CASE,
        trace_id=trace_id,
        source_event=source_event,
        payload_snapshot=payload_snapshot,
        title=f"UNKNOWN classification draft: {utterance[:60]!r}",
        write_guard=write_guard,
    )


def _render_draft_note(draft: DraftEvalCase, *, title: str) -> str:
    frontmatter = {
        "artifact_class": "eval_draft_case",
        "draft_id": draft.draft_id,
        "kind": draft.kind,
        "status": draft.status,
        "trace_id": draft.trace_id,
        "source_event": {
            "topic": draft.source_event.topic,
            "event_id": draft.source_event.event_id,
        },
        "created_at": draft.created_at,
    }
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=True, allow_unicode=False).strip()
    payload_json = json.dumps(dict(draft.payload_snapshot), indent=2, sort_keys=True)
    return (
        f"---\n{yaml_block}\n---\n\n"
        f"# {title}\n\n"
        "This is a drafted eval-case candidate, awaiting human adjudication. "
        "It is NOT part of any golden dataset until explicitly promoted.\n\n"
        "## Provenance\n\n"
        f"- trace_id: `{draft.trace_id or '-'}`\n"
        f"- source topic: `{draft.source_event.topic}`\n"
        f"- source event id: `{draft.source_event.event_id}`\n\n"
        "## Payload snapshot\n\n"
        f"```json\n{payload_json}\n```\n"
    )


def list_pending_drafts(vault_root: Path) -> list[DraftEvalCase]:
    """List every pending eval-draft in ``<system_dir>/eval_drafts/*.md``.

    Read-only directory scan (KERNEL-15 follow-up, #2871): a discoverable
    surface distinct from the memory review queue (see the module docstring's
    "Deliberate divergence" section). Only ``status: pending`` drafts are
    returned — promoted/rejected drafts are terminal decisions and no longer
    belong in the pending review surface. Malformed or unparseable draft
    files are skipped rather than raising, matching :func:`read_draft`'s
    tolerant-read behaviour; this is a best-effort discovery surface, not a
    strict schema validator.

    Sorted by ``created_at`` (oldest first) so the oldest unreviewed failure
    surfaces first.
    """
    drafts_dir = vault_root / _drafts_dir(vault_root)
    if not drafts_dir.exists():
        return []
    pending: list[DraftEvalCase] = []
    for path in sorted(drafts_dir.glob("*.md")):
        draft = read_draft(vault_root, path.stem)
        if draft is not None and draft.status == DRAFT_STATUS_PENDING:
            pending.append(draft)
    pending.sort(key=lambda d: d.created_at)
    return pending


def read_draft(vault_root: Path, draft_id: str) -> DraftEvalCase | None:
    """Read a drafted eval-case back from its vault-relative path.

    None if missing, unparseable, or if ``draft_id`` is not a valid draft id
    (invalid ids — anything with separators, dots, or traversal material —
    are refused before any filesystem access; see
    :func:`_contained_draft_abspath`). ``draft_id`` may be caller-controlled
    (the decision API route), so containment is enforced here at the shared
    seam rather than per-caller.
    """
    path = _contained_draft_abspath(vault_root, draft_id)
    if path is None or not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    if not text.startswith("---\n"):
        return None
    try:
        _, rest = text.split("---\n", 1)
        fm_text, _ = rest.split("\n---", 1) if "\n---" in rest else (rest, "")
        fm = yaml.safe_load(fm_text) or {}
    except Exception:
        return None
    if not isinstance(fm, dict):
        return None
    try:
        payload_start = text.index("```json\n") + len("```json\n")
        payload_end = text.index("\n```", payload_start)
        payload_snapshot = json.loads(text[payload_start:payload_end])
    except Exception:
        payload_snapshot = {}
    source_event_fm = fm.get("source_event") or {}
    return DraftEvalCase(
        draft_id=str(fm.get("draft_id", draft_id)),
        kind=str(fm.get("kind", "")),
        trace_id=fm.get("trace_id"),
        source_event=SourceEvent(
            topic=str(source_event_fm.get("topic", "")),
            event_id=str(source_event_fm.get("event_id", "")),
        ),
        payload_snapshot=payload_snapshot,
        created_at=str(fm.get("created_at", "")),
        status=str(fm.get("status", DRAFT_STATUS_PENDING)),
        draft_path=str(_draft_path(vault_root, draft_id)),
    )


class PromotionDecisionError(FailureCaptureError):
    """Raised when a promote/reject call cannot be recorded truthfully."""


@dataclass(frozen=True)
class PromotionDecision:
    """An explicit, recorded human decision on a draft. The ground-truth step.

    Recording a decision does NOT itself append the case to any golden
    dataset file — it only marks the draft's status. Writing the resulting
    case into ``docs/eval/classification_golden.yaml`` (or a topic-schema
    fixture for schema-violation drafts) is a separate, explicit, reviewed doc
    change; this module never performs that write automatically.
    """

    draft_id: str
    decision: str  # "promote" | "reject"
    decided_by: str
    decided_at: str
    notes: str | None = None


_VALID_DECISIONS = {DRAFT_STATUS_PROMOTED: "promote", DRAFT_STATUS_REJECTED: "reject"}


def promote_draft(
    vault_root: Path,
    draft_id: str,
    *,
    decided_by: str,
    notes: str | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> PromotionDecision:
    """Record an explicit human PROMOTE decision on a pending draft.

    This is the only path by which a draft's status can change from
    ``pending``. It requires a non-empty ``decided_by`` (human/reviewer
    identity) — collapsing that requirement would remove the human-adjudication
    ground-truth step the whole capture loop exists to enforce.
    """
    return _decide(
        vault_root,
        draft_id,
        target_status=DRAFT_STATUS_PROMOTED,
        decided_by=decided_by,
        notes=notes,
        write_guard=write_guard,
    )


def reject_draft(
    vault_root: Path,
    draft_id: str,
    *,
    decided_by: str,
    notes: str | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> PromotionDecision:
    """Record an explicit human REJECT decision on a pending draft."""
    return _decide(
        vault_root,
        draft_id,
        target_status=DRAFT_STATUS_REJECTED,
        decided_by=decided_by,
        notes=notes,
        write_guard=write_guard,
    )


def _decide(
    vault_root: Path,
    draft_id: str,
    *,
    target_status: str,
    decided_by: str,
    notes: str | None,
    write_guard: WriteGuard,
) -> PromotionDecision:
    if not decided_by or not decided_by.strip():
        raise PromotionDecisionError("decided_by is required to record a review decision")
    draft = read_draft(vault_root, draft_id)
    if draft is None:
        raise PromotionDecisionError(f"no draft found: {draft_id}")
    if draft.status != DRAFT_STATUS_PENDING:
        raise PromotionDecisionError(f"draft already decided: {draft_id} (status={draft.status})")

    write_guard.assert_writes_allowed(FAILURE_CAPTURE_DRAFT_ACTION)
    decided_at = _now_iso()
    updated = DraftEvalCase(
        draft_id=draft.draft_id,
        kind=draft.kind,
        trace_id=draft.trace_id,
        source_event=draft.source_event,
        payload_snapshot=draft.payload_snapshot,
        created_at=draft.created_at,
        status=target_status,
        draft_path=draft.draft_path,
    )
    title = f"{_VALID_DECISIONS[target_status].capitalize()}d draft: {draft.kind}"
    content = _render_draft_note(updated, title=title)
    rel_path = draft.draft_path or _safe_rel_path(str(_draft_path(vault_root, draft_id)))
    write_note_relative(rel_path, content, vault_root=vault_root)

    return PromotionDecision(
        draft_id=draft_id,
        decision=_VALID_DECISIONS[target_status],
        decided_by=decided_by,
        decided_at=decided_at,
        notes=notes,
    )


__all__ = [
    "DRAFT_DIR_NAME",
    "DRAFT_KIND_CLASSIFICATION_CASE",
    "DRAFT_KIND_SCHEMA_VIOLATION",
    "DRAFT_STATUS_PENDING",
    "DRAFT_STATUS_PROMOTED",
    "DRAFT_STATUS_REJECTED",
    "FAILURE_CAPTURE_DRAFT_ACTION",
    "DraftEvalCase",
    "FailureCaptureError",
    "PromotionDecision",
    "PromotionDecisionError",
    "SourceEvent",
    "draft_dead_letter_case",
    "draft_unknown_classification_case",
    "is_schema_violation_reason",
    "is_valid_draft_id",
    "list_pending_drafts",
    "promote_draft",
    "read_draft",
    "reject_draft",
]
