"""Attention view — Epic #3019 slice A16 (J6, #3036).

Enacts journey **J6** (attention view) under
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §2,
specifically the **declared bend #1**: the vault keeps the grouped daily
summary (durable); the item-level skip firehose is a **UI-only lens**,
runtime data, never an artifact of record. Grounded in the §9-k
ingestion-organ boundary from `docs/HEIMDAL/FABLE_COMPANION.md`.

This module is the **grouping + persistence layer** over the
`attention/YYYY-MM-DD.md` note spec (`ATTENTION_DAY`) that A14
(`app.heimdal.settings_notes`) already declared -- A14 only reserved the
schema slot; this module is the first thing that actually writes and reads
it for a real purpose (mirroring A17's `entity_confirm.py` relationship to
`ENTITY_REVIEW`).

Two slices, deliberately asymmetric in durability (ADR-0049 §2, Constraints
"Declared bends only"):

- **The grouped daily record** (`AttentionDaySummary`): per-day counts by
  reason and the distinct reasons seen, both **agent-authored**
  (`counts`/`reasons` fields on `ATTENTION_DAY`), plus every **human
  override** (`overrides`, human-editable). `record_attention_events` folds
  a batch of per-item skip/attend decisions into this grouped shape and
  persists it through the governed write seam
  (`app.heimdal.settings_notes.write_settings_note` ->
  `app.knowledge.write_ops.write_note_relative` ->
  `app.write_guard.DEFAULT_WRITE_GUARD`) -- the real production call site,
  never a hand-rolled file write.
- **The item-level firehose** (`iter_skip_firehose`): a pure, in-memory
  generator over the same per-item events, for a UI to render a
  moment-to-moment "skipped X because Y" stream. It performs **no vault
  write of any kind** -- not even a temp/cache file -- because it is
  declared bend #1: runtime data, not an artifact of record. No per-item row
  may become the sole durable record of an attention decision (Fitness
  rule); only the grouped summary persists.

Overrides are human-authored, never agent-authored (Constraints: "Overrides
are human-authored; counts/reasons agent-authored"). `record_override`
writes directly to the human-editable `overrides` field -- honoring a
human's steering action as intent, exactly as the human editing the note by
hand in Obsidian would -- and never touches the agent-authored
`counts`/`reasons` fields it does not own (mirrors
`settings_notes.apply_agent_update`'s complementary discipline: an agent may
never silently overwrite a human-editable field; symmetrically, this module
never lets an override write clobber the agent-authored grouped counts).

Out of scope (per the governing Issue): native-app firehose rendering (a
lens; not the record); cross-day attention analytics/rollups (v2); live
device telemetry (declared bend #2, Epic B).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from app.heimdal.settings_notes import (
    ATTENTION_DAY,
    DEFAULT_SETTINGS_DIR,
    SettingsNote,
    read_settings_note,
    write_settings_note,
)
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

ATTENTION_LOG_WRITE_ACTION = "heimdal.attention_log.write"

#: The two decisions a per-item attention event can carry. Anything else is
#: a caller bug (fail loud), not a silently-accepted third state.
DECISION_ATTENDED = "attended"
DECISION_SKIPPED = "skipped"
_VALID_DECISIONS = frozenset({DECISION_ATTENDED, DECISION_SKIPPED})


class AttentionLogError(RuntimeError):
    """Raised for attention-log contract violations."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# The per-item event: the ONLY shape the firehose is allowed to touch.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttentionEvent:
    """One item-level attention decision -- "skipped/attended X because Y".

    This is the shape both slices fold over: `iter_skip_firehose` renders it
    as ephemeral UI-only rows (never persisted); `record_attention_events`
    groups it away into day-level counts/reasons before anything touches the
    vault. No function in this module writes an `AttentionEvent` itself to
    disk -- that is the structural guarantee behind
    `test_firehose_is_ui_only_no_durable_rows`.
    """

    item_id: str
    decision: str
    reason: str
    observed_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if self.decision not in _VALID_DECISIONS:
            raise AttentionLogError(
                f"AttentionEvent.decision must be one of {sorted(_VALID_DECISIONS)}, "
                f"got {self.decision!r}"
            )
        if not self.reason.strip():
            raise AttentionLogError("AttentionEvent.reason must be non-empty")


@dataclass(frozen=True)
class FirehoseRow:
    """One UI-only lens row -- exactly what a native-app firehose panel would
    render. Deliberately a plain, non-vault-writable shape: there is no
    `write_*` function anywhere in this module that accepts a `FirehoseRow`,
    and `iter_skip_firehose` never touches `Path`/`VaultContext`/`WriteGuard`
    at all. Runtime data, not an artifact of record (ADR-0049 §2, declared
    bend #1)."""

    item_id: str
    decision: str
    reason: str
    observed_at: str


def iter_skip_firehose(events: Iterable[AttentionEvent]) -> Iterator[FirehoseRow]:
    """The item-level skip firehose -- a **UI-only lens, DECLARED BEND #1**.

    Pure, in-memory, no I/O: takes the same per-item events the grouped
    summary folds over and yields one `FirehoseRow` per event, unfiltered
    and unaggregated -- the moment-to-moment "skipped X because Y" stream a
    native-app panel renders live. This function is the entire firehose
    surface; there is nothing else to call to get per-item detail, and
    nothing here persists a row. A caller wanting durable per-item history
    is asking for the wrong artifact -- the grouped daily note is the record
    (`record_attention_events`); this is explicitly not that.
    """
    for event in events:
        yield FirehoseRow(
            item_id=event.item_id,
            decision=event.decision,
            reason=event.reason,
            observed_at=event.observed_at,
        )


# ---------------------------------------------------------------------------
# The grouped daily record: attention/YYYY-MM-DD.md (A14's ATTENTION_DAY spec).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttentionDaySummary:
    """The durable, grouped shape persisted to `attention/YYYY-MM-DD.md`.

    `counts` and `reasons` are agent-authored (folded from a batch of
    `AttentionEvent`s); `overrides` is human-authored and is never populated
    by `record_attention_events` -- only `record_override` writes it, and
    only by appending, never replacing what a human already wrote.
    """

    date: str
    counts: Mapping[str, int]
    reasons: Sequence[str]
    overrides: Sequence[Mapping[str, Any]] = field(default_factory=tuple)

    def to_values(self) -> dict[str, Any]:
        return {
            "counts": dict(self.counts),
            "reasons": list(self.reasons),
            "overrides": list(self.overrides),
        }


def _read_day_note(vault_root: Path, date: str, *, settings_dir: str) -> SettingsNote:
    existing = read_settings_note(vault_root, ATTENTION_DAY, settings_dir=settings_dir, date=date)
    if existing is not None:
        return existing
    return SettingsNote(spec=ATTENTION_DAY, values={"counts": {}, "reasons": [], "overrides": []})


def fold_day_summary(date: str, events: Iterable[AttentionEvent]) -> AttentionDaySummary:
    """Group a batch of per-item events into the grouped daily shape.

    `counts` is keyed `"{decision}:{reason}"` (e.g. `"skipped:low_relevance"`)
    so a skip and an attend sharing the same reason string stay distinguishable
    in the grouped record -- the whole point of "grouped" is that it survives
    without the per-item rows, so it must retain everything a human auditing
    the day needs: how many, for which reason, of which kind. `reasons` is the
    sorted set of distinct reason strings seen that day. No `overrides` are
    produced here -- folding observed events never manufactures a human
    decision.
    """
    counter: Counter[str] = Counter()
    reasons: set[str] = set()
    for event in events:
        counter[f"{event.decision}:{event.reason}"] += 1
        reasons.add(event.reason)
    return AttentionDaySummary(
        date=date,
        counts=dict(counter),
        reasons=tuple(sorted(reasons)),
        overrides=(),
    )


def record_attention_events(
    vault_root: Path,
    date: str,
    events: Iterable[AttentionEvent],
    *,
    settings_dir: str = DEFAULT_SETTINGS_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> AttentionDaySummary:
    """Fold a batch of per-item events and persist the grouped counts/reasons
    to `attention/YYYY-MM-DD.md` -- the real production write call site.

    Writes only the agent-authored `counts`/`reasons` fields (read-merge-write,
    mirroring `settings_notes.apply_agent_update` and `entity_confirm
    .queue_for_review`): the existing note is read first and its
    human-editable `overrides` are carried forward unchanged, so a human's
    already-recorded override is never clobbered by a later agent-authored
    fold. New counts/reasons for the day REPLACE the prior agent-authored
    values (this call is the full day's fold, not an incremental delta) --
    callers that need incremental accumulation pass the full accumulated
    event set for the day, mirroring the projector's replay-from-batch
    posture rather than inventing a separate merge mechanism.
    """
    existing = _read_day_note(vault_root, date, settings_dir=settings_dir)
    summary = fold_day_summary(date, events)

    merged_values: dict[str, Any] = dict(existing.values)
    merged_values["counts"] = summary.to_values()["counts"]
    merged_values["reasons"] = summary.to_values()["reasons"]
    # overrides is human-editable -- never assigned from folded events; carry
    # forward whatever is already on disk untouched.
    merged_values.setdefault("overrides", [])

    note = SettingsNote(spec=ATTENTION_DAY, values=merged_values)
    write_settings_note(
        vault_root,
        note,
        settings_dir=settings_dir,
        write_guard=write_guard,
        action=ATTENTION_LOG_WRITE_ACTION,
        date=date,
    )
    return AttentionDaySummary(
        date=date,
        counts=merged_values["counts"],
        reasons=merged_values["reasons"],
        overrides=tuple(merged_values["overrides"]),
    )


@dataclass(frozen=True)
class AttentionOverride:
    """One human override of an agent attention decision -- the durable
    record of a human steering the agent after the fact (Constraints:
    "Overrides are human-authored ... Every override ... persists to the
    daily note"). `item_id` names the specific item being overridden so the
    override is auditable against whatever grouped count/reason produced it,
    even though the per-item row itself is never durably stored."""

    item_id: str
    original_decision: str
    overridden_decision: str
    note: str = ""
    overridden_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if self.original_decision not in _VALID_DECISIONS:
            raise AttentionLogError(
                f"AttentionOverride.original_decision must be one of "
                f"{sorted(_VALID_DECISIONS)}, got {self.original_decision!r}"
            )
        if self.overridden_decision not in _VALID_DECISIONS:
            raise AttentionLogError(
                f"AttentionOverride.overridden_decision must be one of "
                f"{sorted(_VALID_DECISIONS)}, got {self.overridden_decision!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "original_decision": self.original_decision,
            "overridden_decision": self.overridden_decision,
            "note": self.note,
            "overridden_at": self.overridden_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AttentionOverride":
        return cls(
            item_id=str(data["item_id"]),
            original_decision=str(data["original_decision"]),
            overridden_decision=str(data["overridden_decision"]),
            note=str(data.get("note", "")),
            overridden_at=str(data.get("overridden_at", _now_iso())),
        )


def record_override(
    vault_root: Path,
    date: str,
    override: AttentionOverride,
    *,
    settings_dir: str = DEFAULT_SETTINGS_DIR,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> AttentionDaySummary:
    """Persist one human override into `attention/YYYY-MM-DD.md`'s
    human-editable `overrides` field -- the durable capture of a human
    steering an agent attention decision (Scope: "every override the human
    made"; Fitness rule: "every override ... must persist to the daily
    note").

    Appends only to `overrides` (human-editable); never touches the
    agent-authored `counts`/`reasons` this module's other half owns --
    exactly the field-authority discipline `settings_notes` enforces
    structurally elsewhere (`apply_agent_update` raises if an agent tries to
    write a human-editable field; here the symmetric rule is upheld by
    construction: `record_override` never assigns `counts`/`reasons`).
    Idempotent on exact-duplicate entries: replaying the exact same override
    does not duplicate it.
    """
    existing = _read_day_note(vault_root, date, settings_dir=settings_dir)
    overrides = list(existing.values.get("overrides") or [])
    new_entry = override.to_dict()
    if new_entry not in overrides:
        overrides.append(new_entry)

    merged_values: dict[str, Any] = dict(existing.values)
    merged_values["overrides"] = overrides
    merged_values.setdefault("counts", {})
    merged_values.setdefault("reasons", [])

    note = SettingsNote(spec=ATTENTION_DAY, values=merged_values)
    write_settings_note(
        vault_root,
        note,
        settings_dir=settings_dir,
        write_guard=write_guard,
        action=ATTENTION_LOG_WRITE_ACTION,
        date=date,
    )
    return AttentionDaySummary(
        date=date,
        counts=merged_values["counts"],
        reasons=merged_values["reasons"],
        overrides=tuple(merged_values["overrides"]),
    )


def read_day_summary(
    vault_root: Path, date: str, *, settings_dir: str = DEFAULT_SETTINGS_DIR
) -> AttentionDaySummary | None:
    """Read the current grouped daily summary, or `None` if the day has no
    note yet. The whole durable record for that day -- counts, reasons, and
    every override -- is visible from this one read; there is no separate
    per-item store to consult (Fitness rule: no per-item row may become the
    sole durable record)."""
    note = read_settings_note(vault_root, ATTENTION_DAY, settings_dir=settings_dir, date=date)
    if note is None:
        return None
    return AttentionDaySummary(
        date=date,
        counts=dict(note.values.get("counts") or {}),
        reasons=tuple(note.values.get("reasons") or ()),
        overrides=tuple(note.values.get("overrides") or ()),
    )


__all__ = [
    "ATTENTION_LOG_WRITE_ACTION",
    "DECISION_ATTENDED",
    "DECISION_SKIPPED",
    "AttentionDaySummary",
    "AttentionEvent",
    "AttentionLogError",
    "AttentionOverride",
    "FirehoseRow",
    "fold_day_summary",
    "iter_skip_firehose",
    "read_day_summary",
    "record_attention_events",
    "record_override",
]
