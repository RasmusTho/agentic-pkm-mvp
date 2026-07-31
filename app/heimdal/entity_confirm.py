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
from app.heimdal.entity_register import (
    LIFECYCLE_MERGED,
    MERGE_EFFECTS_COMPLETE,
    EntityRegister,
    EntityRegisterError,
)
from app.heimdal.entity_review_operation_journal import (
    STATE_EVENT_COMMITTED,
    EntityReviewOperationConflictError,
    EntityReviewOperationJournalError,
    EntityReviewOperationJournalPort,
    EntityReviewOperationSchemaMissingError,
    decision_mapping_digest,
)
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
    resolved, whether a register merge was performed, and (for merges) the
    entity-review operation the merge was journaled under (EROJ-01)."""

    queue_entry_id: str
    action: str
    merged: bool
    operation_id: str | None = None


def apply_human_review_decisions(
    vault_root: Path,
    *,
    register: EntityRegister,
    settings_dir: str = DEFAULT_SETTINGS_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    journal: EntityReviewOperationJournalPort | None = None,
) -> tuple[AppliedDecision, ...]:
    """Fold and apply each pending entry's ordered `decisions` history.

    This is the confirmation mechanism itself: reading `decisions` off disk
    IS reading the human ruling -- there is no separate "confirm" API a UI
    calls that the note lacks (Constraints: "the ruling itself is a one-line
    note edit ... the UI owns no capability the note lacks"). An iPad (or any
    other client) record is only ever a proposal-bound review signal
    (INV-EROJ-1): this Hub fold is what validates that a decision is bound to
    a displayed pending proposal and canonicalizes an approval into an
    executable operation — a client record alone is never replayed as a merge
    command.

    A `merge` decision runs the EROJ-01 restart-safe sequence (#4350):

    1. the exact human-authored decision mapping is bound into one
       deterministic operation, committed by the journal **before** the first
       register note write (`claim_operation`; a changed mapping for a
       still-active entry fails closed);
    2. the note effects are applied resumably through
       `register.ensure_merge_effects` (A1's own mechanism — reversible via
       `register.split()` (F5) — never a bespoke mutation here, and never
       re-applied when a crash already wrote them);
    3. the operation's `heimdal.register.entity.merged` event commits
       atomically with the terminal journal state in a journal-owned
       transaction (`commit_merge_event`);
    4. the queue entry may leave `pending` only after a **fresh**
       connection/transaction observes both the terminal journal state and
       the matching committed outbox row (`verify_committed_visibility`,
       INV-EROJ-3). Visibility on the writer's or a caller's own uncommitted
       transaction never authorizes the clear — that same-connection read is
       exactly how #4253 lost the merge event after the retry anchor was gone.

    Merges therefore **require** `journal`; calling with merge intent and no
    journal raises before anything is applied. A `reject` decision only
    clears the queue entry and keeps its current semantics: the register and
    journal are untouched (no identity assertion is made for a declined
    candidate). A following `undo` resets that queue entry to undecided
    before application: no register mutation occurs, `pending` remains, and
    the append-only `decisions` history is retained. A later merge/reject can
    establish a new terminal intent. Once the hub has applied a decision and
    removed the pending entry, a later undo is an idempotent no-op rather
    than a register reversal.

    Per-entry refusals (a changed decision digest, unprovable/evolved note
    effects, a failed visibility fence) leave that entry `pending` with its
    history byte-for-byte unchanged, do not block other entries, and are
    raised loudly as one aggregate `EntityConfirmError` after durable
    successes are recorded.

    Resume is keyed on the ENTRY, not on re-deriving an id from the current
    decision content: an active `event_committed` operation on a pending
    entry is an already-authorized merge whose clear was interrupted, and it
    is finished first (fence -> cleared -> entry removed, reported as the
    applied merge under its original operation id) -- the merge is
    materialised and its event committed, so it is not reversible at this
    layer. Because the documented undo boundary is defined on `pending` (the
    only surface a client observes), a ruling that folded differently while
    the entry was still pending is NEVER silently discarded: the completion
    stands, and the divergence is raised loudly, naming the finished merge
    and the ruling that was not applied (with `EntityRegister.split` as the
    reversal path). The same loud notice covers a non-merge ruling clearing
    an entry whose previously completed merge still stands. An active
    `claimed` operation blocks a `reject` from clearing that entry (the
    operation may already have register effects; ambiguity fails closed,
    INV-EROJ-6; restoring the entry's original decision resumes it cleanly)
    and makes a *changed* merge decision fail closed via the identity
    conflict. An interrupted clear whose operation already reached `cleared`
    (stop between the journal update and the note write) is finished without
    claiming a new operation, so one merge can never emit a second event
    through re-approval (partial-failure matrix row 4).

    Idempotent: a decision whose `queue_entry_id` is no longer in `pending`
    has already been applied (or never existed) and is skipped rather than
    re-merged -- re-running this function is always safe, and a re-run after
    a crash resumes each in-flight operation at its journaled state.
    """
    note = _read_review_note(vault_root, settings_dir=settings_dir)
    pending = list(note.values.get("pending") or [])
    raw_decisions = list(note.values.get("decisions") or ())
    decisions = [ReviewDecision.from_dict(d) for d in raw_decisions]

    pending_ids = {p.get("queue_entry_id") for p in pending}
    applied: list[AppliedDecision] = []
    refused: list[tuple[str, str]] = []
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

    ordered_terminals = [
        (index, effective_decision)
        for index, effective_decision in sorted(
            terminal_by_queue_id.values(), key=lambda item: item[0]
        )
        if effective_decision is not None
    ]

    if journal is None and any(d.action == "merge" for _, d in ordered_terminals):
        raise EntityConfirmError(
            "apply_human_review_decisions: a merge decision is pending but no "
            "entity-review operation journal was provided; a merge queue entry may "
            "leave 'pending' only through the committed-visibility fence "
            "(EROJ-01, INV-EROJ-3), so nothing was applied"
        )

    vault_identity = register.vault_identity

    for index, effective_decision in ordered_terminals:
        merged = False
        operation_id: str | None = None
        queue_entry_id = effective_decision.queue_entry_id
        try:
            if journal is not None:
                # Entry-keyed resume (review F1): an edited decision history
                # derives a different operation id, so the in-flight row is
                # reachable only through the entry itself.
                active = journal.find_active_operation(
                    vault_identity=vault_identity, queue_entry_id=queue_entry_id
                )
                if active is not None and active.state == STATE_EVENT_COMMITTED:
                    # An already-authorized merge whose clear was interrupted:
                    # finish it first. The merge is materialised and its event
                    # committed -- it is not reversible at this layer.
                    if not journal.verify_committed_visibility(active):
                        refused.append(
                            (
                                queue_entry_id,
                                "committed visibility was not observed on a fresh "
                                "transaction for the in-flight operation "
                                f"{active.operation_id}; the queue entry stays "
                                "pending (INV-EROJ-3)",
                            )
                        )
                        continue
                    journal.mark_cleared(active)
                    remaining_pending = [
                        p
                        for p in remaining_pending
                        if p.get("queue_entry_id") != queue_entry_id
                    ]
                    applied.append(
                        AppliedDecision(
                            queue_entry_id=queue_entry_id,
                            action="merge",
                            merged=True,
                            operation_id=active.operation_id,
                        )
                    )
                    if not (
                        effective_decision.action == "merge"
                        and effective_decision.from_id == active.from_id
                        and effective_decision.into_id == active.into_id
                    ):
                        # Round-2 review blocker on #4350: completing the
                        # committed operation is correct, but silently
                        # discarding the human's later, different ruling is
                        # not -- the journal must never appear to reinterpret
                        # a decision (INV-EROJ-1). Say exactly what stood and
                        # what was not applied.
                        later_ruling = (
                            f"merge into {effective_decision.into_id}"
                            if effective_decision.action == "merge"
                            else effective_decision.action
                        )
                        refused.append(
                            (
                                queue_entry_id,
                                "an already-committed merge operation "
                                f"{active.operation_id} ({active.from_id} -> "
                                f"{active.into_id}) was finished and its entry "
                                f"cleared; your later {later_ruling} was NOT "
                                "applied. The merge is materialised and is not "
                                "reversible at this layer -- see the undo "
                                "boundary; use EntityRegister.split to reverse it.",
                            )
                        )
                    continue
                if active is not None and effective_decision.action != "merge":
                    # Review F3: a reject must not clear an entry whose claimed
                    # operation may already have register effects -- that would
                    # silently divorce the human ruling from canonical notes.
                    refused.append(
                        (
                            queue_entry_id,
                            f"operation {active.operation_id} is still claimed for this "
                            "entry; a reject cannot clear it and the entry stays "
                            "pending (INV-EROJ-6). To recover, restore this entry's "
                            "original decision in entities/review.md (the claimed "
                            "operation then resumes cleanly), or wait for EROJ-02.",
                        )
                    )
                    continue
                if effective_decision.action != "merge":
                    # Round-2 review on #4350, cleared-window variant: the
                    # entry may clear on this ruling, but a previously
                    # completed merge that still stands must be named -- the
                    # ruling does not reverse it.
                    prior = journal.find_cleared_operation(
                        vault_identity=vault_identity, queue_entry_id=queue_entry_id
                    )
                    if prior is not None:
                        prior_source = register.get_entry(prior.from_id)
                        if (
                            prior_source is not None
                            and prior_source.lifecycle == LIFECYCLE_MERGED
                        ):
                            refused.append(
                                (
                                    queue_entry_id,
                                    f"entry cleared by {effective_decision.action}, but "
                                    f"previously completed merge operation "
                                    f"{prior.operation_id} ({prior.from_id} -> "
                                    f"{prior.into_id}) remains materialised with its "
                                    f"event committed; the {effective_decision.action} "
                                    "does not reverse it -- use EntityRegister.split "
                                    "to reverse it.",
                                )
                            )

            if effective_decision.action == "merge":
                assert (
                    effective_decision.from_id is not None
                    and effective_decision.into_id is not None
                )
                assert journal is not None  # guaranteed by the upfront check
                # Review F4 / matrix row 4: a stop between mark_cleared and
                # the note write leaves the entry visible with its operation
                # already cleared. Finishing that interrupted clear must not
                # claim a new operation -- that path emits a second event for
                # the same merge.
                cleared_twin = journal.find_cleared_operation(
                    vault_identity=vault_identity,
                    queue_entry_id=queue_entry_id,
                    from_id=effective_decision.from_id,
                    into_id=effective_decision.into_id,
                )
                if (
                    cleared_twin is not None
                    and register.merge_effect_state(
                        effective_decision.from_id, effective_decision.into_id
                    )
                    == MERGE_EFFECTS_COMPLETE
                ):
                    merged = True
                    operation_id = cleared_twin.operation_id
                else:
                    # Pre-claim validation: prove the merge is executable (or
                    # resumable) from current notes BEFORE binding an
                    # operation, so a typo'd decision never strands an active
                    # operation row.
                    register.merge_effect_state(
                        effective_decision.from_id, effective_decision.into_id
                    )
                    # 1. Operation identity commits before the first register
                    #    effect (INV-EROJ-2; a changed mapping fails closed).
                    operation = journal.claim_operation(
                        vault_identity=vault_identity,
                        queue_entry_id=queue_entry_id,
                        decision_position=index,
                        decision_digest=decision_mapping_digest(raw_decisions[index]),
                        from_id=effective_decision.from_id,
                        into_id=effective_decision.into_id,
                    )
                    # 2. Resumable note effects (skips sides a crash already
                    #    wrote).
                    register.ensure_merge_effects(
                        effective_decision.from_id, effective_decision.into_id
                    )
                    # 3. Terminal journal state + exactly one event, atomically.
                    operation = journal.commit_merge_event(operation)
                    # 4. The fence: only a fresh transaction's read of the
                    #    committed journal + outbox rows authorizes the clear.
                    if not journal.verify_committed_visibility(operation):
                        refused.append(
                            (
                                queue_entry_id,
                                "committed visibility was not observed on a fresh "
                                "transaction; the queue entry stays pending "
                                "(INV-EROJ-3)",
                            )
                        )
                        continue
                    operation = journal.mark_cleared(operation)
                    merged = True
                    operation_id = operation.operation_id
            # "reject": no register mutation -- the candidate stays
            # unresolved/ambiguous, exactly as it was before queuing. "undo"
            # never reaches this application loop because the fold represents
            # it as no intent.
        except EntityReviewOperationSchemaMissingError:
            # System misconfiguration, not a per-entry ambiguity: surface the
            # migration guidance immediately.
            raise
        except (
            EntityRegisterError,
            EntityReviewOperationConflictError,
            EntityReviewOperationJournalError,
        ) as exc:
            refused.append((queue_entry_id, str(exc)))
            continue

        remaining_pending = [
            p
            for p in remaining_pending
            if p.get("queue_entry_id") != queue_entry_id
        ]
        applied.append(
            AppliedDecision(
                queue_entry_id=queue_entry_id,
                action=effective_decision.action,
                merged=merged,
                operation_id=operation_id,
            )
        )

    if applied:
        updated_note = SettingsNote(
            spec=ENTITY_REVIEW,
            values={
                **note.values,
                "pending": remaining_pending,
                # Parsing validates and folds the supported intent fields, but
                # the persisted human-authored history is append-only. Keep
                # every original mapping byte-for-byte at the value layer so
                # forward-compatible audit fields and omitted optional fields
                # are never normalized away by application.
                "decisions": raw_decisions,
            },
        )
        write_settings_note(
            vault_root,
            updated_note,
            settings_dir=settings_dir,
            write_guard=write_guard,
            action=ENTITY_CONFIRM_WRITE_ACTION,
        )

    if refused:
        details = "; ".join(f"{queue_id}: {reason}" for queue_id, reason in refused)
        raise EntityConfirmError(
            "apply_human_review_decisions: "
            f"{len(refused)} queue entr{'y' if len(refused) == 1 else 'ies'} require "
            f"operator attention (decision history is unchanged; each item states "
            f"whether its entry stayed pending or was cleared) -- {details}"
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
