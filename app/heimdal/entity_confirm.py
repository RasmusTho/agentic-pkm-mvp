"""Entity confirmation surface — Epic #3019 slice A17 (JE, #3037).

Enacts journey **JE** (entity confirmation) under
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §2
(markdown-first, UI is a lens), grounded in the §9-k ingestion-organ boundary
from `docs/HEIMDAL/FABLE_COMPANION.md` (entity resolution is Mimer's;
identity is knowledge; the register is markdown-built; merges must be
reversible — red-team F5).

This module is the **routing + confirmation layer** over two things that
already exist and are NOT reimplemented here:

- **A9** (`app.heimdal.attribution_stage`) produces `EntityMention` values
  carrying the register's three-state `resolution` (`resolved` / `ambiguous`
  / `unresolved`) and a `confidence` in `[0, 1]`.
- **A1** (`app.heimdal.entity_register`) owns canonical identity: `resolve`,
  `merge`, `split` (reversible, F5), `resolve_redirects`. This module never
  reimplements register mechanics; it only calls them.
- **A14** (`app.heimdal.settings_notes`) already declares the
  `entities/review.md` note spec (`ENTITY_REVIEW`) with `pending`
  (agent-authored) and `decisions` (human-editable) fields. This module is
  the first thing that actually *writes and reads* that note for a real
  purpose — A14 only reserved the schema slot.

Score-banded routing (research precedent in
`docs/HEIMDAL/ENTITY_IDENTIFICATION_RESEARCH.md`: Reltio auto-merges >=0.9,
human-reviews 0.6-0.9; Salesforce ~0.8; Dynamics >0.9 — "a ready template for
our auto-link-vs-confirm-queue threshold"):

- **>= HIGH_THRESHOLD** (default 0.9): **auto-link**, no human step. The
  mention's resolution is already a register ref (`ResolvedRef` via A9); this
  band simply confirms no further action is needed -- the register already
  did the linking. `route_mention` reports `AUTO_LINK` and this module
  performs no additional write.
- **[LOW_THRESHOLD, HIGH_THRESHOLD)** (default 0.6-0.9): **mid-band** --
  surfaced as a queued entry in `entities/review.md`'s agent-authored
  `pending` field for human confirmation. This is genuinely uncertain
  territory (`AmbiguousCandidates`, or a low-confidence `ResolvedRef`): the
  register found *something* but did not warrant auto-linking.
  `route_mention` reports `QUEUE_FOR_REVIEW`; `queue_for_review` performs the
  write.
- **< LOW_THRESHOLD** (or `UnresolvedProvisional`, no candidate at all):
  **no routing action** -- nothing to confirm yet (a fresh provisional
  entity was just minted; recurrence, not confirmation, is what will
  eventually surface it). `route_mention` reports `NO_ACTION`.

**The ruling is a one-line note edit, not a UI-only capability** (Constraints:
"the ruling itself is a one-line note edit in `entities/review.md`; the UI
owns no capability the note lacks"): `apply_human_review_decisions` reads
whatever a human (or an agent proposing on the human's behalf) wrote into
`decisions` -- `merge`, `reject`, or the pre-application compensating action
`undo` -- and folds the ordered entries for each pending queue item before
performing the corresponding register mutation. A **merge** decision calls
`register.merge(from_id, into_id)` directly (A1's mechanism, never
reimplemented): it writes
`merged_into` on the source note AND `merged_from` on the target note (the
redirect's target-side complement) -- both are the note edit. Every
confirmed merge stays reversible via `register.split()` (F5) -- this module
adds no separate un-merge mechanism, it is the same `split()` A1 already
ships. A **reject** decision removes the entry from
`pending` without touching the register at all (the candidate stays
`ambiguous`/`unresolved`, no identity assertion is made). An **undo**
following either decision while the entry remains pending cancels that
proposed intent: the full decision history and pending entry remain, and no
register mutation occurs. It never reverses an already-materialized merge.

The side-by-side candidate compare a native-app UI might render is a plain
ergonomic lens over exactly this data (`pending` entries carry both
candidate entity_ids and their labels) -- this module owns the note; it does
not render or require a UI.

Out of scope (per the governing Issue): register internals (A1); native-app
compare rendering (a lens); voiceprint/diarization attribution (v2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.heimdal.attribution_stage import RESOLUTION_UNRESOLVED, EntityMention
from app.heimdal.entity_register import EntityRegister
from app.heimdal.settings_notes import (
    DEFAULT_SETTINGS_DIR,
    ENTITY_REVIEW,
    SettingsNote,
    read_settings_note,
    write_settings_note,
)
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# ---------------------------------------------------------------------------
# Score bands (Constraints: "Score-banded routing"; research precedent —
# ENTITY_IDENTIFICATION_RESEARCH.md's Reltio/Salesforce/Dynamics survey).
# ---------------------------------------------------------------------------

#: Above this confidence, a mention auto-links: no human step (Reltio-like
#: >=0.9 auto-merge precedent). The register's own `resolve()` already
#: performed the link; this threshold only decides whether the routing layer
#: leaves it alone (AUTO_LINK) or escalates it to review.
HIGH_THRESHOLD = 0.9

#: Below this confidence (or no candidate at all), there is nothing concrete
#: enough to put in front of a human yet -- a fresh provisional mint, not a
#: reviewable candidate.
LOW_THRESHOLD = 0.6

ENTITY_CONFIRM_WRITE_ACTION = "heimdal.entity_confirm.write"


class EntityConfirmError(RuntimeError):
    """Raised for entity-confirmation routing/queue contract violations."""


class RoutingDecision(str, Enum):
    """Score-banded routing outcome for one resolved entity mention."""

    AUTO_LINK = "auto_link"
    QUEUE_FOR_REVIEW = "queue_for_review"
    NO_ACTION = "no_action"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Routing: map a mention's (resolution, confidence) onto a band.
# ---------------------------------------------------------------------------


def _mention_confidence(mention: EntityMention) -> float | None:
    return mention.confidence


def route_mention(
    mention: EntityMention,
    *,
    high_threshold: float = HIGH_THRESHOLD,
    low_threshold: float = LOW_THRESHOLD,
) -> RoutingDecision:
    """Decide the score band for one already-resolved `EntityMention`.

    Never re-resolves and never mutates the register -- this is pure
    classification over what A9's `resolve_extracted_mentions` already
    produced. `resolution="unresolved"` (a fresh `UnresolvedProvisional`,
    A1's `mint_provisional`) always routes `NO_ACTION`: there is no candidate
    to confirm, only a new provisional identity that recurrence may later
    surface as ambiguous/resolved.
    """
    if mention.resolution == RESOLUTION_UNRESOLVED:
        return RoutingDecision.NO_ACTION

    confidence = _mention_confidence(mention)
    if confidence is None:
        # No score at all (e.g. an ambiguous result with no candidates) --
        # never silently auto-link without a number; treat as unrouteable.
        return RoutingDecision.NO_ACTION

    if confidence >= high_threshold:
        return RoutingDecision.AUTO_LINK
    if confidence >= low_threshold:
        return RoutingDecision.QUEUE_FOR_REVIEW
    return RoutingDecision.NO_ACTION


# ---------------------------------------------------------------------------
# Mid-band queue: entities/review.md (A14's ENTITY_REVIEW spec).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewQueueEntry:
    """One `pending` entry in `entities/review.md` -- a mid-band mention
    awaiting human confirmation. `queue_entry_id` is the stable key a human
    (or an agent proposing on the human's behalf) references from
    `decisions` when ruling on it."""

    queue_entry_id: str
    mention_id: str
    surface_form: str
    resolution: str
    confidence: float
    candidate_entity_ids: tuple[str, ...] = field(default_factory=tuple)
    queued_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_entry_id": self.queue_entry_id,
            "mention_id": self.mention_id,
            "surface_form": self.surface_form,
            "resolution": self.resolution,
            "confidence": self.confidence,
            "candidate_entity_ids": list(self.candidate_entity_ids),
            "queued_at": self.queued_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewQueueEntry":
        return cls(
            queue_entry_id=str(data["queue_entry_id"]),
            mention_id=str(data.get("mention_id", "")),
            surface_form=str(data.get("surface_form", "")),
            resolution=str(data.get("resolution", "")),
            confidence=float(data.get("confidence", 0.0)),
            candidate_entity_ids=tuple(data.get("candidate_entity_ids") or ()),
            queued_at=str(data.get("queued_at", _now_iso())),
        )


def _read_review_note(vault_root: Path, *, settings_dir: str) -> SettingsNote:
    existing = read_settings_note(vault_root, ENTITY_REVIEW, settings_dir=settings_dir)
    if existing is not None:
        return existing
    return SettingsNote(spec=ENTITY_REVIEW, values={"pending": [], "decisions": []})


def queue_for_review(
    vault_root: Path,
    mention: EntityMention,
    *,
    candidate_entity_ids: Sequence[str] = (),
    settings_dir: str = DEFAULT_SETTINGS_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> ReviewQueueEntry:
    """Route a mid-band mention into the `entities/review.md` queue
    (Scope: "The mid-band -> surfaced as a review-queue note at
    `entities/review.md` for human confirmation").

    Writes only the agent-authored `pending` field (via the same
    read-merge-write discipline `apply_agent_update` uses) -- never touches
    the human-editable `decisions` field, so a pending human ruling already
    on disk is never clobbered by a new mid-band arrival.
    """
    confidence = mention.confidence
    if confidence is None:
        raise EntityConfirmError(
            f"queue_for_review: mention {mention.mention_id!r} has no confidence score"
        )

    entry = ReviewQueueEntry(
        queue_entry_id=f"review:{mention.mention_id}",
        mention_id=mention.mention_id,
        surface_form=mention.surface_form,
        resolution=mention.resolution,
        confidence=confidence,
        candidate_entity_ids=tuple(candidate_entity_ids),
    )

    note = _read_review_note(vault_root, settings_dir=settings_dir)
    pending = list(note.values.get("pending") or [])
    # Idempotent: re-queuing the same mention_id replaces its stale entry
    # rather than duplicating it (a stage re-run is a revision, not a rewrite
    # -- mirrors attribution_stage's own append-only-but-idempotent posture).
    pending = [p for p in pending if p.get("queue_entry_id") != entry.queue_entry_id]
    pending.append(entry.to_dict())

    updated_note = SettingsNote(
        spec=ENTITY_REVIEW,
        values={**note.values, "pending": pending},
    )
    write_settings_note(
        vault_root,
        updated_note,
        settings_dir=settings_dir,
        write_guard=write_guard,
        action=ENTITY_CONFIRM_WRITE_ACTION,
    )
    return entry


def pending_review_entries(
    vault_root: Path, *, settings_dir: str = DEFAULT_SETTINGS_DIR
) -> tuple[ReviewQueueEntry, ...]:
    """Read the current `pending` queue off `entities/review.md`."""
    note = read_settings_note(vault_root, ENTITY_REVIEW, settings_dir=settings_dir)
    if note is None:
        return ()
    return tuple(ReviewQueueEntry.from_dict(p) for p in (note.values.get("pending") or ()))


# ---------------------------------------------------------------------------
# The human ruling: a one-line note edit, not a UI-only capability.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewDecision:
    """One `decisions` entry a human (or an agent proposing on the human's
    behalf) writes into `entities/review.md`. `action` is `"merge"`,
    `"reject"`, or the compensating `"undo"`. Merge/reject propose the two
    outcomes a human confirmation over a queued candidate can produce
    (confirm identity, or decline to assert one); undo cancels the current
    proposal only while the queue entry is still pending. This is the whole
    ruling: a side-by-side compare UI is a lens over the SAME
    `queue_entry_id` + `into_id` a human could type by hand."""

    queue_entry_id: str
    action: str  # "merge" | "reject" | "undo"
    from_id: str | None = None
    into_id: str | None = None
    decided_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if self.action not in ("merge", "reject", "undo"):
            raise EntityConfirmError(
                "ReviewDecision.action must be 'merge', 'reject', or 'undo', "
                f"got {self.action!r}"
            )
        if self.action == "merge" and (not self.from_id or not self.into_id):
            raise EntityConfirmError("ReviewDecision(action='merge') requires from_id and into_id")
        if self.action == "undo" and (self.from_id is not None or self.into_id is not None):
            raise EntityConfirmError(
                "ReviewDecision(action='undo') compensates by queue_entry_id only"
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "queue_entry_id": self.queue_entry_id,
            "action": self.action,
            "decided_at": self.decided_at,
        }
        if self.from_id is not None:
            data["from_id"] = self.from_id
        if self.into_id is not None:
            data["into_id"] = self.into_id
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewDecision":
        return cls(
            queue_entry_id=str(data["queue_entry_id"]),
            action=str(data["action"]),
            from_id=data.get("from_id"),
            into_id=data.get("into_id"),
            decided_at=str(data.get("decided_at", _now_iso())),
        )


@dataclass(frozen=True)
class AppliedDecision:
    """Result of applying one `ReviewDecision`: which queue entry it
    resolved and whether a register merge was performed."""

    queue_entry_id: str
    action: str
    merged: bool


def apply_human_review_decisions(
    vault_root: Path,
    *,
    register: EntityRegister,
    settings_dir: str = DEFAULT_SETTINGS_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> tuple[AppliedDecision, ...]:
    """Fold and apply each pending entry's ordered `decisions` history.

    This is the confirmation mechanism itself: reading `decisions` off disk
    IS reading the human ruling -- there is no separate "confirm" API a UI
    calls that the note lacks (Constraints: "the ruling itself is a one-line
    note edit ... the UI owns no capability the note lacks"). A `merge`
    decision calls `register.merge(from_id, into_id)` -- A1's own mechanism,
    reversible via `register.split()` (F5) -- never a bespoke mutation here.
    A `reject` decision only clears the queue entry; the register is
    untouched (no identity assertion is made for a declined candidate).
    A following `undo` resets that queue entry to undecided before
    application: no register mutation occurs, `pending` remains, and the
    append-only `decisions` history is retained. A later merge/reject can
    establish a new terminal intent. Once the hub has applied a decision and
    removed the pending entry, a later undo is an idempotent no-op rather
    than a register reversal.

    Idempotent: a decision whose `queue_entry_id` is no longer in `pending`
    has already been applied (or never existed) and is skipped rather than
    re-merged -- re-running this function is always safe.
    """
    note = _read_review_note(vault_root, settings_dir=settings_dir)
    pending = list(note.values.get("pending") or [])
    decisions = [ReviewDecision.from_dict(d) for d in (note.values.get("decisions") or ())]

    pending_ids = {p.get("queue_entry_id") for p in pending}
    applied: list[AppliedDecision] = []
    remaining_pending = list(pending)

    # Fold every pending queue entry to its final pre-application intent.
    # An undo deliberately resets to None instead of resurrecting an older
    # proposal: the client returns to an explicitly undecided state.
    terminal_by_queue_id: dict[str, tuple[int, ReviewDecision | None]] = {}
    for index, decision in enumerate(decisions):
        if decision.queue_entry_id not in pending_ids:
            continue
        terminal_by_queue_id[decision.queue_entry_id] = (
            index,
            None if decision.action == "undo" else decision,
        )

    for _, effective_decision in sorted(
        terminal_by_queue_id.values(), key=lambda item: item[0]
    ):
        if effective_decision is None:
            continue
        merged = False
        if effective_decision.action == "merge":
            assert (
                effective_decision.from_id is not None
                and effective_decision.into_id is not None
            )
            register.merge(effective_decision.from_id, effective_decision.into_id)
            merged = True
        # "reject": no register mutation -- the candidate stays unresolved/
        # ambiguous, exactly as it was before queuing. "undo" never reaches
        # this application loop because the fold represents it as no intent.

        remaining_pending = [
            p
            for p in remaining_pending
            if p.get("queue_entry_id") != effective_decision.queue_entry_id
        ]
        applied.append(
            AppliedDecision(
                queue_entry_id=effective_decision.queue_entry_id,
                action=effective_decision.action,
                merged=merged,
            )
        )

    if applied:
        updated_note = SettingsNote(
            spec=ENTITY_REVIEW,
            values={**note.values, "pending": remaining_pending, "decisions": [d.to_dict() for d in decisions]},
        )
        write_settings_note(
            vault_root,
            updated_note,
            settings_dir=settings_dir,
            write_guard=write_guard,
            action=ENTITY_CONFIRM_WRITE_ACTION,
        )

    return tuple(applied)


__all__ = [
    "AppliedDecision",
    "ENTITY_CONFIRM_WRITE_ACTION",
    "EntityConfirmError",
    "HIGH_THRESHOLD",
    "LOW_THRESHOLD",
    "ReviewDecision",
    "ReviewQueueEntry",
    "RoutingDecision",
    "apply_human_review_decisions",
    "pending_review_entries",
    "queue_for_review",
    "route_mention",
]
