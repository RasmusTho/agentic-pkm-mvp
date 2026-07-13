"""Guarded write seam for Episode notes (ERE-02; ADR-0051 OD-1/OD-2; #2910 guard-at-seam
precedent).

Two write classes are kept explicit and are never blurred (INV-ERE-B):

- Every write -- regardless of ``segmentation`` -- goes through the same guarded knowledge-write
  seam (``app.knowledge.write_ops.write_note_relative``), action ``episodes.write_note``. That
  function asserts ``WriteGuard.assert_writes_allowed(action)`` *inside the port itself*, before
  any path resolution or filesystem mutation (guard-at-seam), so a blocked write is atomic --
  zero bytes touched -- regardless of caller. This is the health/fail-closed gate every
  vault-write seam must assert.
- ``segmentation: proposed`` is a low-trust opt-out proposal (ADR-0051 §5): it never goes through
  ``app.governance.governed_write`` (no ``PolicyDecision`` / ``DecisionToken`` / ``AuthorityReceipt``).
  Canonical standing for an episode arrives via silent acceptance or human re-cut (ERE-07), not a
  governed transition -- so this module has no governance import at all, by construction, not just
  by convention.

Machine-terminality of the cut (ERE-07, #3182; ``docs/EPISODE_RESOLUTION_ENGINE/RESPECT_HUMAN_RECUT.md``
AC2): once an episode note's on-disk ``segmentation`` is ``accepted`` or ``re-cut``, this seam
refuses any write that would change the note's cut -- ``title``, ``time.start``, ``time.end``,
``space``, ``protagonists``, ``goal``, ``causation``, ``parent_episode``, ``derived_from`` -- and
raises :class:`EpisodeCutTerminalError` BEFORE any filesystem mutation (guard-at-seam ordering,
mirroring the ``WriteGuard`` check below it). Two fields are deliberately exempt from this freeze:
``segmentation`` itself (the exact field a legitimate re-cut-detection/silence-acceptance relabel
changes -- see ``app.episodes.recut``) and ``time.closed`` (ERE-06's closure-decay tick may still
flip it on an otherwise-terminal episode; spec: "the engine may append ... closure flips per ERE-06
... but never mutate the five dimensions or the cut itself"). A legitimate relabel always echoes
the CURRENT on-disk cut fields back unchanged (only ``segmentation`` differs), so it passes this
check trivially; an attempt to mutate the cut of an already-terminal episode (e.g. new evidence
trying to widen/edit it instead of becoming its own new proposal, AC3) is rejected here, not by a
convention callers must remember.

When an existing note has a human-authored Markdown body, rewrites preserve that body while
updating validated frontmatter. The generated canonical body remains replaceable so derived
headings can follow legitimate engine relabels without fabricating a human edit.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.episodes.ids import mint_episode_id, validate_fused_episode_id
from app.episodes.notes import (
    episode_note_rel_path,
    parse_episode_note_document,
    render_episode_note,
)
from app.episodes.schema import validate_episode_note_fields
from app.knowledge.contracts import WriteReceipt
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.write_ops import write_note_relative
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

logger = logging.getLogger(__name__)

# Distinct action string for the episode write seam (mirrors the
# knowledge.write_note / memory.materialize per-seam-action pattern), asserted by
# write_note_relative itself -- not a caller-side helper (AC2: enforcement lives at the
# production seam).
EPISODE_WRITE_ACTION = "episodes.write_note"

_ALLOWED_SEGMENTATIONS = ("proposed", "accepted", "re-cut")

#: Segmentation values that make an episode note's cut machine-terminal (ERE-07 AC2).
TERMINAL_SEGMENTATIONS: frozenset[str] = frozenset({"accepted", "re-cut"})


class EpisodeStoreError(ValueError):
    """Raised when an episode note write is rejected before reaching the write seam."""


class EpisodeCutTerminalError(EpisodeStoreError):
    """AC2 (enforcement): raised when a write would mutate the cut of an episode note whose
    on-disk ``segmentation`` is already ``accepted``/``re-cut``. Checked before any filesystem
    mutation -- the note is left byte-for-byte untouched. New evidence that would otherwise
    reshape a terminal episode must become a NEW proposed episode instead (never an edit of the
    human's cut, ERE-07 AC3)."""


def cut_snapshot(fields: Mapping[str, Any]) -> dict[str, Any]:
    """The subset of ``fields`` considered "the cut" -- everything a terminal episode's write
    seam freezes, and the SINGLE SOURCE OF TRUTH for "what a human owns" (ERE-07). The
    terminality guard below freezes exactly these fields against machine mutation, and
    ``app.episodes.recut.compute_fields_hash`` fingerprints exactly these fields for
    writer-identity detection -- so an engine-only lifecycle relabel (``segmentation``) or an
    ERE-06 closure flip (``time.closed``), both deliberately EXCLUDED here, can never trip a
    false re-cut detection (round-1 review Finding 2). Keep the two in lockstep by importing this
    function, never by re-listing the fields."""
    time_fields = fields.get("time") or {}
    return {
        "title": fields.get("title"),
        "time.start": time_fields.get("start"),
        "time.end": time_fields.get("end"),
        "space": list(fields.get("space") or []),
        "protagonists": list(fields.get("protagonists") or []),
        "goal": list(fields.get("goal") or []),
        "causation": list(fields.get("causation") or []),
        "parent_episode": fields.get("parent_episode"),
        "derived_from": list(fields.get("derived_from") or []),
    }


def _read_existing_episode_note(rel_path: str, vault_root: Path | str) -> str | None:
    """Best-effort read of the CURRENT on-disk text at ``rel_path``, or ``None`` when no note
    exists there yet (a brand-new episode_id, never terminal). Reads the filesystem directly
    (mirrors ``app.episodes.segmenter._emit_proposal``'s existence check) rather than through the
    knowledge port -- this is a read-only pre-write check, not itself a guarded mutation.

    Returning the raw text (not just parsed fields) lets the caller both apply the
    machine-terminality freeze and compute the ``expected_version`` the shared knowledge-write
    seam (#3450) requires before overwriting a REWRITTEN-classified episode note."""
    note_path = Path(vault_root) / rel_path
    if not note_path.exists():
        return None
    try:
        return note_path.read_text(encoding="utf-8")
    except OSError:
        return None


@dataclass(frozen=True)
class EpisodeWriteResult:
    """Result of a guarded episode-note write. Deliberately carries only a
    ``WriteReceipt`` -- never a ``DecisionToken``/``AuthorityReceipt`` -- so a proposal-class
    write is structurally incapable of looking like a governed mutation (AC3)."""

    receipt: WriteReceipt
    episode_id: str
    fields: dict[str, Any]


def write_episode_note(
    *,
    title: str,
    scope: str,
    start: str,
    closed: bool = False,
    end: str | None = None,
    space: list[str] | None = None,
    protagonists: list[str] | None = None,
    goal: list[str] | None = None,
    causation: list[str] | None = None,
    parent_episode: str | None = None,
    segmentation: str = "proposed",
    derived_from: list[str] | None = None,
    episode_id: str | None = None,
    vault_root: Path | str,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    preserve_existing_body: bool | None = None,
    expected_existing_version: str | None = None,
) -> EpisodeWriteResult:
    """Write a vault-canonical episode note through the guarded seam.

    ``episode_id`` defaults to a freshly minted fused id (``ep-<uuid>``, disjoint-by-construction
    from Heimdal's per-session id space); an explicit ``episode_id`` is still validated against
    the same disjointness rule (AC4) so no caller can smuggle a raw Heimdal session id through.

    ``preserve_existing_body`` is normally auto-detected. Re-cut reconciliation may pass an
    explicit decision from its prior baseline, which is the only reliable way to distinguish an
    untouched old generated body from a simultaneous frontmatter-and-body human edit.
    ``expected_existing_version`` carries the scan-time version into this seam so that decision
    cannot overwrite a concurrent editor save between scan and write.
    """
    if segmentation not in _ALLOWED_SEGMENTATIONS:
        raise EpisodeStoreError(
            f"segmentation must be one of {_ALLOWED_SEGMENTATIONS}, got {segmentation!r}"
        )

    derived = list(derived_from or [])
    eid = episode_id if episode_id is not None else mint_episode_id()
    validate_fused_episode_id(eid, derived_from=derived)

    fields: dict[str, Any] = {
        "episode_id": eid,
        "scope": scope,
        "title": title,
        "time": {"start": start, "closed": closed, **({"end": end} if end else {})},
        "space": list(space or []),
        "protagonists": list(protagonists or []),
        "goal": list(goal or []),
        "causation": list(causation or []),
        "parent_episode": parent_episode,
        "segmentation": segmentation,
        "derived_from": derived,
    }
    # Schema validation (AC1) happens before the write seam is even reached -- a
    # malformed note is rejected with zero filesystem mutation, same as a blocked guard.
    validate_episode_note_fields(fields)

    rel_path = episode_note_rel_path(eid)

    # Machine-terminality (ERE-07 AC2), checked BEFORE any filesystem mutation, mirroring the
    # WriteGuard ordering below: an existing note whose on-disk segmentation is already
    # accepted/re-cut has its cut frozen against machine mutation. A relabel that only changes
    # `segmentation` (echoing every cut field back unchanged) passes trivially; an attempted cut
    # mutation is rejected here and the note is left byte-for-byte untouched.
    existing_text = _read_existing_episode_note(rel_path, vault_root)
    current_version = (
        hashlib.sha256(existing_text.encode("utf-8")).hexdigest()
        if existing_text is not None
        else None
    )
    if (
        expected_existing_version is not None
        and current_version != expected_existing_version
    ):
        raise KnowledgeWriteConflict(
            f"version mismatch for episode note {rel_path}: scan-time content changed or vanished"
        )
    existing_fields: dict[str, Any] | None = None
    preserved_body: str | None = None
    if existing_text is not None:
        existing_fields, existing_body = parse_episode_note_document(existing_text)
        _, canonical_body = parse_episode_note_document(render_episode_note(existing_fields))
        should_preserve_body = (
            existing_body != canonical_body
            if preserve_existing_body is None
            else preserve_existing_body
        )
        if should_preserve_body:
            # The markdown body has diverged from the generated template, so it belongs to the
            # human edit surface. Every machine rewrite carries its content through unchanged
            # instead of regenerating the canned body over it. A still-canonical body
            # is regenerated from the new fields so derived headings remain current.
            preserved_body = existing_body
    if existing_fields is not None and existing_fields.get("segmentation") in TERMINAL_SEGMENTATIONS:
        if cut_snapshot(existing_fields) != cut_snapshot(fields):
            logger.warning(
                "episodes.store: rejected machine mutation of terminal cut for episode_id=%s "
                "(existing segmentation=%s) -- note left untouched; new evidence must become a "
                "new proposed episode instead (ERE-07 AC3)",
                eid,
                existing_fields.get("segmentation"),
            )
            raise EpisodeCutTerminalError(
                f"episode {eid!r} is segmentation={existing_fields.get('segmentation')!r} "
                "(machine-terminal); the write seam refuses to mutate its cut."
            )

    content = render_episode_note(fields, body=preserved_body)

    # Guard-at-seam (#2910 precedent): write_note_relative asserts
    # write_guard.assert_writes_allowed(EPISODE_WRITE_ACTION) itself, before any path
    # resolution or filesystem mutation -- this call IS the production seam AC2 verifies,
    # not a caller-side check that could be bypassed by a different call path. No
    # governance import anywhere in this module: a proposal-class write reaches only this
    # seam and produces only a WriteReceipt (AC3).
    # Shared knowledge-write seam (#3450): an episode note is REWRITTEN-classified, so a
    # rewrite of an existing note requires the ``expected_version`` of the bytes we read
    # above -- otherwise the seam refuses the write as a would-be silent overwrite. A
    # brand-new episode note (``existing_text is None``) needs no version.
    expected_version = (
        expected_existing_version
        if expected_existing_version is not None
        else current_version
    )
    receipt = write_note_relative(
        rel_path,
        content,
        vault_root=vault_root,
        action=EPISODE_WRITE_ACTION,
        write_guard=write_guard,
        expected_version=expected_version,
    )
    return EpisodeWriteResult(receipt=receipt, episode_id=eid, fields=fields)


__all__ = [
    "EPISODE_WRITE_ACTION",
    "TERMINAL_SEGMENTATIONS",
    "EpisodeCutTerminalError",
    "EpisodeStoreError",
    "EpisodeWriteResult",
    "cut_snapshot",
    "write_episode_note",
]
