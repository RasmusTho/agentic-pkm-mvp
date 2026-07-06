"""Heimdal capture-note + receipt (J0) -- the dated vault note that IS the
record of a captured memo (#3035, Epic #3019 slice A15).

Ratified by `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
:: Decision §2 (markdown-first control surface, "the UI is a lens") and
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §9-k ("Markdown holds the
record. The UI is the lens.").

This module is the durable write path this slice's Acceptance Criteria
describe: a captured memo lands as a **dated vault note** (companion-note
style, markdown + YAML frontmatter) written through the same governed seam
every other Heimdal note in this package uses
(`app.knowledge.write_ops.write_note_relative` +
`app.write_guard.DEFAULT_WRITE_GUARD`, mirroring `app.heimdal.settings_notes`
and `app.services.companion_note` -- no hand-rolled YAML;
`scripts.yaml_roundtrip.load_frontmatter`/`dump_frontmatter` does the
parsing).

Contract this module owns (issue Acceptance Criteria):

- **A dated vault note per captured memo (§9-k).** One markdown note per
  memo, at a deterministic path derived from capture date + a stable memo
  id (`_heimdal/captures/YYYY-MM-DD-<memo_id>.md`) -- Obsidian-usable, no
  native-app rendering required (Out of Scope: native-app receipt
  rendering).
- **`status:` frontmatter walks the pipeline, monotonically.** Exactly the
  three-state walk this issue fixes: ``captured`` -> ``processing`` ->
  ``in-vault``. `status:` is agent-authored (pipeline-driven, never a
  human-editable field per `app.heimdal.settings_notes`'s field-authority
  split) and every transition is validated against a single fixed forward
  order (:data:`STATUS_ORDER`) -- an attempted backward or skipped-forward
  write raises :class:`CaptureNoteStatusError` rather than silently
  clobbering the durable state. The note is updated **in place** (same
  path, same memo id) at each transition, never rewritten as a new file.
- **Self-describing without a UI (§9-k).** The note body carries the A8
  on-device transcript (`app.heimdal.asr_stage.TranscriptResult`) and the
  A9 attribution + entity mentions
  (`app.heimdal.attribution_stage.AttributionResult`) as soon as those
  stages have run -- a human opening the raw file in Obsidian sees the
  full record with no UI involved.
- **The receipt is a lens, not a capability (§9-k, ADR-0049 §2).** This
  module exposes exactly one reader function
  (:func:`build_capture_receipt`) that projects the note's *own*
  `status:` field (plus already-durable transcript/attribution presence)
  into a small read-only summary. It performs no write, resolves no
  additional state, and a caller who never calls it loses nothing the note
  itself does not already show -- removing the "receipt UI" leaves the
  note fully functional, per the issue's Constraints.

Out of scope for this slice (per governing Issue #3035): always-on/ambient
capture note shape (posture B); segment-granular multi-note-per-episode
writes (v2); the Mimer projection of the memo into a candidate (A11);
native-app receipt rendering (Obsidian-usable markdown only in v1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.heimdal.asr_stage import TranscriptResult, TranscriptSegment
from app.heimdal.attribution_stage import Attribution, AttributionResult, EntityMention
from app.knowledge.write_ops import write_note_relative
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAPTURE_NOTE_WRITE_ACTION = "heimdal.capture_note.write"
ARTIFACT_CLASS = "heimdal_capture_note"
DEFAULT_CAPTURES_DIR = "_heimdal/captures"

# The fixed, monotonic three-state walk this issue's Acceptance Criteria
# name explicitly. Index in this tuple is the state's rank -- a write must
# never move to a lower rank than the note's current on-disk status
# (STATUS_ORDER position of the target must be strictly greater, or equal
# only for an idempotent re-write of the *same* stage's output).
STATUS_CAPTURED = "captured"
STATUS_PROCESSING = "processing"
STATUS_IN_VAULT = "in-vault"
STATUS_ORDER: tuple[str, ...] = (STATUS_CAPTURED, STATUS_PROCESSING, STATUS_IN_VAULT)
_STATUS_RANK: dict[str, int] = {name: idx for idx, name in enumerate(STATUS_ORDER)}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CaptureNoteError(RuntimeError):
    """Raised for capture-note contract violations."""


class CaptureNoteStatusError(CaptureNoteError):
    """Raised when a `status:` write would move the note backward (non-monotonic).

    The durable `status:` field is pipeline-driven (agent-authored, never
    human-editable) and is the whole point of this slice's fitness rule
    ("`status:` must walk the pipeline monotonically" -- governing Issue's
    SBS Impact). A caller attempting to write a status whose rank in
    :data:`STATUS_ORDER` is lower than the note's current status hits this
    error instead of silently corrupting the durable walk.
    """


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaptureNote:
    """One capture note's parsed state -- frontmatter plus the self-describing body content.

    `memo_id` + `captured_date` together determine the note's deterministic
    vault path (:func:`capture_note_rel_path`); both are immutable for the
    lifetime of one captured memo (the note is updated in place, never
    moved/renamed as it walks `status:`).
    """

    memo_id: str
    captured_date: str  # YYYY-MM-DD, the capture-time date this note is filed under
    status: str
    updated: str
    sensor: Mapping[str, Any] = field(default_factory=dict)
    transcript_text: str | None = None
    transcript_segments: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    attributions: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    entity_mentions: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CaptureReceipt:
    """The receipt-UI projection -- a **lens** over one capture note's `status:`.

    Every field here is derived read-only from the note's own durable
    state; there is no field on this dataclass that is not already visible
    by opening the note file directly (ADR-0049 §2: "any UI is a lens with
    better ergonomics, never the sole home of a capability").
    """

    memo_id: str
    status: str
    has_transcript: bool
    has_attribution: bool
    updated: str


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def capture_note_rel_path(
    memo_id: str,
    captured_date: str,
    *,
    captures_dir: str = DEFAULT_CAPTURES_DIR,
) -> str:
    """Deterministic vault-relative path for one captured memo's dated note.

    `captured_date` must already be a ``YYYY-MM-DD`` string (callers derive
    it once, at first capture, from the capture timestamp -- this function
    does no timezone reasoning of its own). The path is stable across every
    later `status:` transition for the same `memo_id`: the note is updated
    in place, never relocated.
    """
    if not isinstance(memo_id, str) or not memo_id.strip():
        raise CaptureNoteError(f"capture_note_rel_path requires a non-empty memo_id, got {memo_id!r}")
    if not isinstance(captured_date, str) or not captured_date.strip():
        raise CaptureNoteError(
            f"capture_note_rel_path requires a non-empty captured_date, got {captured_date!r}"
        )
    return f"{captures_dir}/{captured_date}-{memo_id}.md"


# ---------------------------------------------------------------------------
# Frontmatter <-> CaptureNote
# ---------------------------------------------------------------------------


def _note_to_frontmatter(note: CaptureNote) -> dict[str, Any]:
    fm: dict[str, Any] = {
        "artifact_class": ARTIFACT_CLASS,
        "memo_id": note.memo_id,
        "captured_date": note.captured_date,
        "status": note.status,
        "updated": note.updated,
    }
    if note.sensor:
        fm["sensor"] = dict(note.sensor)
    if note.transcript_text:
        fm["transcript_text"] = note.transcript_text
    if note.transcript_segments:
        fm["transcript_segments"] = [dict(s) for s in note.transcript_segments]
    if note.attributions:
        fm["attributions"] = [dict(a) for a in note.attributions]
    if note.entity_mentions:
        fm["entity_mentions"] = [dict(m) for m in note.entity_mentions]
    return fm


def _render_body(note: CaptureNote) -> str:
    """Render the human-readable body -- the self-describing part a human
    reads directly in Obsidian, no UI required (§9-k)."""
    lines: list[str] = [f"# Captured memo {note.memo_id}", ""]
    lines.append(f"**Status:** `{note.status}`")
    lines.append("")
    if note.transcript_text:
        lines.append("## Transcript")
        lines.append("")
        lines.append(note.transcript_text)
        lines.append("")
    if note.attributions or note.entity_mentions:
        lines.append("## Attribution")
        lines.append("")
        for attribution in note.attributions:
            lines.append(
                f"- {attribution.get('role')}: resolution={attribution.get('resolution')} "
                f"basis={attribution.get('basis')}"
            )
        for mention in note.entity_mentions:
            lines.append(
                f"- mention: {mention.get('surface_form')!r} "
                f"resolution={mention.get('resolution')}"
            )
        lines.append("")
    body = "\n".join(lines).rstrip() + "\n"
    return body


def render_capture_note(note: CaptureNote) -> str:
    """Render one `CaptureNote` to its full markdown+frontmatter text."""
    fm = _note_to_frontmatter(note)
    return dump_frontmatter(fm, _render_body(note))


def parse_capture_note(text: str) -> CaptureNote:
    """Parse a capture note's frontmatter back into a `CaptureNote`.

    Uses the shared `scripts.yaml_roundtrip.load_frontmatter` parser (never
    hand-rolled YAML), mirroring `app.services.companion_note` /
    `app.heimdal.settings_notes`.
    """
    fm, _ = load_frontmatter(text)
    return CaptureNote(
        memo_id=str(fm.get("memo_id", "")),
        captured_date=str(fm.get("captured_date", "")),
        status=str(fm.get("status", STATUS_CAPTURED)),
        updated=str(fm.get("updated", "")),
        sensor=dict(fm.get("sensor") or {}),
        transcript_text=(str(fm["transcript_text"]) if fm.get("transcript_text") else None),
        transcript_segments=tuple(fm.get("transcript_segments") or ()),
        attributions=tuple(fm.get("attributions") or ()),
        entity_mentions=tuple(fm.get("entity_mentions") or ()),
    )


# ---------------------------------------------------------------------------
# Read / write -- the real production entry points
# ---------------------------------------------------------------------------


def read_capture_note(
    vault_root: Path,
    memo_id: str,
    captured_date: str,
    *,
    captures_dir: str = DEFAULT_CAPTURES_DIR,
) -> CaptureNote | None:
    """Read one captured memo's dated note. Returns `None` if it does not exist yet."""
    rel_path = capture_note_rel_path(memo_id, captured_date, captures_dir=captures_dir)
    path = vault_root / rel_path
    if not path.exists():
        return None
    return parse_capture_note(path.read_text(encoding="utf-8"))


def _assert_monotonic(current: CaptureNote | None, target_status: str) -> None:
    if target_status not in _STATUS_RANK:
        raise CaptureNoteStatusError(
            f"status {target_status!r} is not one of the fixed pipeline states {STATUS_ORDER!r}"
        )
    if current is None:
        return
    current_rank = _STATUS_RANK.get(current.status)
    if current_rank is None:
        # Unknown/legacy status on disk: refuse silently accepting a lower
        # rank against an un-ranked value rather than guessing intent.
        raise CaptureNoteStatusError(
            f"capture note {current.memo_id!r} has unrecognized on-disk status "
            f"{current.status!r}; refusing to write {target_status!r} without "
            "explicit repair"
        )
    target_rank = _STATUS_RANK[target_status]
    if target_rank < current_rank:
        raise CaptureNoteStatusError(
            f"capture note {current.memo_id!r} status walk is monotonic: "
            f"cannot move from {current.status!r} (rank {current_rank}) back to "
            f"{target_status!r} (rank {target_rank})"
        )


def write_capture_note(
    vault_root: Path,
    note: CaptureNote,
    *,
    captures_dir: str = DEFAULT_CAPTURES_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    action: str = CAPTURE_NOTE_WRITE_ACTION,
) -> CaptureNote:
    """Write one capture note through the governed vault-write seam, in place.

    Enforces the monotonic `status:` walk (:data:`STATUS_ORDER`) against
    whatever is currently on disk for this `memo_id`/`captured_date` before
    writing -- raises :class:`CaptureNoteStatusError` rather than silently
    moving the durable state backward. Uses
    `app.knowledge.write_ops.write_note_relative` (the same production write
    port `app.services.companion_note` and `app.heimdal.settings_notes`
    use), which itself asserts `write_guard.assert_writes_allowed(action)`
    before touching the filesystem.
    """
    existing = read_capture_note(vault_root, note.memo_id, note.captured_date, captures_dir=captures_dir)
    _assert_monotonic(existing, note.status)

    rel_path = capture_note_rel_path(note.memo_id, note.captured_date, captures_dir=captures_dir)
    content = render_capture_note(note)
    write_note_relative(
        rel_path,
        content,
        vault_root=vault_root,
        action=action,
        write_guard=write_guard,
    )
    return note


def record_capture(
    vault_root: Path,
    *,
    memo_id: str,
    captured_date: str,
    sensor: Mapping[str, Any] | None = None,
    captures_dir: str = DEFAULT_CAPTURES_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> CaptureNote:
    """Step 1 of the pipeline walk: write the note at `status: captured`.

    The real production call site for the capture stage (A6): as soon as a
    memo is durably admitted (`app.heimdal.capture_adapter.admit_capture_file`),
    the caller derives a stable `memo_id` (e.g. the raw record's
    `content_identity` or `raw_ref`) and calls this function so the dated
    note exists and is readable **before** ASR/attribution have run --
    per the issue's fitness rule, the note must exist and be readable
    before any UI render (UUID/UI is not a render gate).
    """
    note = CaptureNote(
        memo_id=memo_id,
        captured_date=captured_date,
        status=STATUS_CAPTURED,
        updated=_now_iso(),
        sensor=dict(sensor or {}),
    )
    return write_capture_note(vault_root, note, captures_dir=captures_dir, write_guard=write_guard)


def record_processing(
    vault_root: Path,
    *,
    memo_id: str,
    captured_date: str,
    transcript: TranscriptResult | None = None,
    captures_dir: str = DEFAULT_CAPTURES_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> CaptureNote:
    """Step 2 of the pipeline walk: advance the note to `status: processing`
    and fold in the A8 transcript (self-describing without a UI, §9-k).

    Real production call site for the ASR stage (A8): once
    `app.heimdal.asr_stage.run_asr_stage` returns a `TranscriptResult` for
    this memo's `raw_ref`, the caller passes it here so the note's body and
    frontmatter carry the on-device transcript before attribution has run.
    """
    existing = read_capture_note(vault_root, memo_id, captured_date, captures_dir=captures_dir)
    if existing is None:
        raise CaptureNoteError(
            f"record_processing: no capture note found for memo_id={memo_id!r} "
            f"captured_date={captured_date!r}; call record_capture first"
        )

    transcript_text = existing.transcript_text
    transcript_segments = existing.transcript_segments
    if transcript is not None:
        transcript_text = transcript.text
        transcript_segments = tuple(_segment_to_dict(s) for s in transcript.segments)

    note = CaptureNote(
        memo_id=memo_id,
        captured_date=captured_date,
        status=STATUS_PROCESSING,
        updated=_now_iso(),
        sensor=existing.sensor,
        transcript_text=transcript_text,
        transcript_segments=transcript_segments,
        attributions=existing.attributions,
        entity_mentions=existing.entity_mentions,
    )
    return write_capture_note(vault_root, note, captures_dir=captures_dir, write_guard=write_guard)


def record_in_vault(
    vault_root: Path,
    *,
    memo_id: str,
    captured_date: str,
    attribution: AttributionResult | None = None,
    captures_dir: str = DEFAULT_CAPTURES_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> CaptureNote:
    """Step 3 of the pipeline walk: advance the note to `status: in-vault`
    and fold in the A9 attribution + entity mentions.

    Real production call site for the attribution stage (A9) /
    publish handoff (A10): once
    `app.heimdal.attribution_stage.run_attribution_stage` has produced its
    `AttributionResult` (or the caller otherwise confirms the memo is fully
    published/projected), the caller calls this to land the note's terminal
    `in-vault` status with the attribution folded in, so the note is fully
    self-describing without the UI.
    """
    existing = read_capture_note(vault_root, memo_id, captured_date, captures_dir=captures_dir)
    if existing is None:
        raise CaptureNoteError(
            f"record_in_vault: no capture note found for memo_id={memo_id!r} "
            f"captured_date={captured_date!r}; call record_capture first"
        )

    attributions = existing.attributions
    entity_mentions = existing.entity_mentions
    if attribution is not None:
        attributions = tuple(_attribution_to_dict(a) for a in attribution.attributions)
        entity_mentions = tuple(_mention_to_dict(m) for m in attribution.entity_mentions)

    note = CaptureNote(
        memo_id=memo_id,
        captured_date=captured_date,
        status=STATUS_IN_VAULT,
        updated=_now_iso(),
        sensor=existing.sensor,
        transcript_text=existing.transcript_text,
        transcript_segments=existing.transcript_segments,
        attributions=attributions,
        entity_mentions=entity_mentions,
    )
    return write_capture_note(vault_root, note, captures_dir=captures_dir, write_guard=write_guard)


def _segment_to_dict(segment: TranscriptSegment) -> dict[str, Any]:
    return {
        "start": segment.start,
        "end": segment.end,
        "text": segment.text,
        "confidence": segment.confidence,
        "calibration": segment.calibration,
        "method": segment.method,
        "speaker_hint": segment.speaker_hint,
    }


def _attribution_to_dict(attribution: Attribution) -> dict[str, Any]:
    return {
        "mention_id": attribution.mention_id,
        "role": attribution.role,
        "resolution": attribution.resolution,
        "basis": attribution.basis,
        "confidence": attribution.confidence,
    }


def _mention_to_dict(mention: EntityMention) -> dict[str, Any]:
    return {
        "mention_id": mention.mention_id,
        "surface_form": mention.surface_form,
        "resolution": mention.resolution,
        "kind_hint": mention.kind_hint,
        "confidence": mention.confidence,
        "span": mention.span,
    }


# ---------------------------------------------------------------------------
# Receipt -- a lens over `status:`, no capability of its own
# ---------------------------------------------------------------------------


def build_capture_receipt(note: CaptureNote) -> CaptureReceipt:
    """Project a `CaptureNote` into the receipt-UI's read-only summary.

    This is the **entire** contract the receipt UI is allowed to have
    (ADR-0049 §2 / issue Constraints: "the receipt UI is a lens and owns no
    capability of its own"). It performs no write and resolves no state the
    note does not already carry -- every field here is read directly off
    `note`. A caller may build this receipt from any `CaptureNote` obtained
    via :func:`read_capture_note`; there is no code path in this module
    that lets a receipt exist without a backing note, and no code path that
    lets the receipt diverge from the note's own `status:` field.
    """
    return CaptureReceipt(
        memo_id=note.memo_id,
        status=note.status,
        has_transcript=bool(note.transcript_text),
        has_attribution=bool(note.attributions or note.entity_mentions),
        updated=note.updated,
    )


__all__ = [
    "ARTIFACT_CLASS",
    "CAPTURE_NOTE_WRITE_ACTION",
    "DEFAULT_CAPTURES_DIR",
    "STATUS_CAPTURED",
    "STATUS_IN_VAULT",
    "STATUS_ORDER",
    "STATUS_PROCESSING",
    "CaptureNote",
    "CaptureNoteError",
    "CaptureNoteStatusError",
    "CaptureReceipt",
    "build_capture_receipt",
    "capture_note_rel_path",
    "parse_capture_note",
    "read_capture_note",
    "record_capture",
    "record_in_vault",
    "record_processing",
    "render_capture_note",
    "write_capture_note",
]
