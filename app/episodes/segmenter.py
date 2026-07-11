"""Episode segmenter entrypoint + two-stream five-dimension segmentation core
(ERE-01, #3176 stub; body ERE-04, #3179).

:func:`run_segmenter_stub` / :func:`enumerate_consumable_streams` remain the
enforced call-site contract from ERE-01: the engine enumerates its stream
sources **only** via ``app.episodes.stream_registry`` -- never a hardcoded
list -- and an attempt to consume an unregistered or non-`live` stream_id is
rejected at this call site (AC4, shared with ERE-01 AC5, now exercised
against the real segmenter body below via :func:`run_segmentation_tick`).

Segmentation design (spec ``docs/EPISODE_RESOLUTION_ENGINE/TWO_STREAM_SEGMENTATION_CORE.md``,
ADR-0051 commitment 2, ADR-0054 §3):

- :func:`fold_signals_into_segments` is the PURE core: given a batch of
  normalized :class:`SegmentationSignal` and the currently-open segment per
  scope (AC7: partitioned per-scope, never cross-scope fused), it walks each
  scope's signals in ``observed_at`` order, closes a segment whenever
  :func:`detect_shift` fires a boundary, and also closes any segment gone
  stale purely from elapsed wall-clock time (the >45min-silence rule) even
  absent a new triggering signal. No I/O, no vault, no DB -- fully
  unit-testable and deterministic, so it is also the module's idempotency
  guarantee under at-least-once redelivery (AC2): re-folding a signal whose
  ``signal_id`` an open segment already recorded is a no-op.
- :func:`run_segmentation_tick` is the production, I/O-performing entrypoint
  (``python -m app.cli episodes tick``): reads new signals from each *live*
  registered stream since its own durable cursor, calls the pure fold, emits
  a ``segmentation: proposed`` Episode note per closed segment (AC5, via
  ``app.episodes.store.write_episode_note`` -- the ERE-02 guarded seam),
  persists updated open-segment state, and ONLY THEN advances each stream's
  cursor -- a crash before that point means the next tick reprocesses the
  same batch, deduped by fold-by-key plus a deterministic ``episode_id`` per
  closed segment (a retried emission never double-writes a note, AC2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from app.episodes import engine_state
from app.episodes.ids import EPISODE_ID_PREFIX
from app.episodes.notes import episode_note_rel_path
from app.episodes.store import write_episode_note
from app.episodes.stream_registry import (
    STATUS_LIVE,
    StreamRegistry,
    StreamRegistryEntry,
    UnregisteredStreamError,
    load_registry,
)
from app.episodes.vault_activity_stream import (
    VAULT_ACTIVITY_STREAM_ID,
    VaultActivityRow,
    advance_vault_activity_cursor,
    read_vault_activity_for_consumer,
    resolve_activity_dimensions,
)
from app.heimdal.observation_log import ObservationRow
from app.heimdal.publish import advance_cursor_for_consumer, read_observations_for_consumer
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard


def enumerate_consumable_streams(
    stream_ids: Sequence[str] | None = None,
    *,
    registry: StreamRegistry | None = None,
) -> tuple[StreamRegistryEntry, ...]:
    """The segmenter's one legal way to learn which streams to consume.

    - With no ``stream_ids``: returns every ``live`` registry entry
      (registry-driven enumeration, never a hardcoded source list).
    - With explicit ``stream_ids``: resolves each one through the registry
      and raises :class:`UnregisteredStreamError` for any id that is not a
      registered ``live`` stream -- the entrypoint never silently consumes
      an unregistered or non-live source.
    """
    reg = registry if registry is not None else load_registry()
    if stream_ids is None:
        return reg.live_entries()

    resolved: list[StreamRegistryEntry] = []
    for stream_id in stream_ids:
        entry = reg.get(stream_id)
        if entry is None:
            raise UnregisteredStreamError(
                f"segmenter entrypoint: stream_id {stream_id!r} is not in the stream registry"
            )
        if entry.status != STATUS_LIVE:
            raise UnregisteredStreamError(
                f"segmenter entrypoint: stream_id {stream_id!r} is status={entry.status!r}, not live -- "
                "the engine may not consume a non-live registry entry"
            )
        resolved.append(entry)
    return tuple(resolved)


def run_segmenter_stub(
    *,
    stream_ids: Sequence[str] | None = None,
    registry: StreamRegistry | None = None,
) -> tuple[StreamRegistryEntry, ...]:
    """Stub production entrypoint (ERE-04 fills in real segmentation logic).

    Enumerates its consumers strictly via :func:`enumerate_consumable_streams`
    -- this is the call site AC5 asserts against.
    """
    return enumerate_consumable_streams(stream_ids, registry=registry)


# ---------------------------------------------------------------------------
# Named, single-sourced, provisional constants (AC6; RQ-E1 open research).
# Over-segmentation is preferred over under-segmentation (spec): merging a
# wrongly-split episode is a cheap human re-cut; splitting a wrongly-fused
# one is costlier. Every threshold here is deliberately conservative and
# documented as provisional in `docs/EPISODE_RESOLUTION_ENGINE/README.md`
# :: Provisional thresholds (RQ-E1) (AC6 doc writeback) -- this module is the
# single source; nothing else literal-copies these values.
# ---------------------------------------------------------------------------

#: Heimdal per-consumer cursor id AND this engine's own vault-activity
#: cursor id (issue Scope: "cursor consumer id `mimer.episode_resolution_engine`").
#: One logical consumer identity, two independent durable cursor rows (the
#: Heimdal `heimdal_observation_cursor` table keyed by this id; the
#: `episode_engine_state` `cursor:vault.activity:<id>` row) -- never shared
#: state, never cross-affecting each other's position.
CONSUMER_ID: Final[str] = "mimer.episode_resolution_engine"

HEIMDAL_STREAM_ID: Final[str] = "heimdal.observations"

#: Time-gap dimension (ADR-0051 commitment 2): no signal for this long closes
#: the open segment window, with or without a new triggering signal.
TIME_GAP_MINUTES: Final[int] = 45
_TIME_GAP: Final[timedelta] = timedelta(minutes=TIME_GAP_MINUTES)

#: Goal-shift dimension: a signal's goal/project binding set that is
#: completely disjoint from the open segment's accumulated goal set is a
#: shift -- conservative (requires BOTH sides non-empty; absence of goal
#: evidence on either side is never treated as a shift).
GOAL_SHIFT_DETECTION_ENABLED: Final[bool] = True

#: Protagonist-shift dimension: a signal's resolved-attribution protagonist
#: set that is completely disjoint from the open segment's accumulated
#: protagonist set is a shift -- same conservative both-sides-non-empty bar.
PROTAGONIST_SHIFT_DETECTION_ENABLED: Final[bool] = True

#: Causal-break dimension (v1): an explicit Heimdal `supersedes` marker on
#: the observation payload is treated as a discontinuity.
CAUSAL_BREAK_DETECTION_ENABLED: Final[bool] = True

#: Place-shift dimension: absent in v1 by design (spec) -- unfed until a
#: calendar/location stream lands (ERE-09/ERE-10). Never contributes a
#: shift; kept named here so its absence is a documented decision, not a
#: silent omission.
PLACE_SHIFT_DETECTION_ENABLED: Final[bool] = False

#: Fixed, arbitrary namespace UUID for deterministic per-segment episode ids
#: (see :func:`_deterministic_episode_id`). Never reused for anything else.
_EPISODE_ID_NAMESPACE: Final[uuid.UUID] = uuid.UUID("6f1d9a3a-8c3e-4f7a-9b1a-8f9d2e6c4a11")

_OPEN_SEGMENT_KEY_PREFIX: Final[str] = "open_segment:"

_DEFAULT_SCOPE: Final[str] = "default"


# ---------------------------------------------------------------------------
# Normalized signal + open/closed segment state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentationSignal:
    """One stream's contribution to the segmenter, normalized to the shape
    :func:`fold_signals_into_segments` needs. Distinct from
    ``app.episodes.stream_registry.SignalContract`` (that dataclass is the
    ERE-01 declared *confidence* contract, not a content carrier) -- this is
    the segmentation-internal content shape adapted from each real stream."""

    stream_id: str
    #: Unique within `stream_id`; the fold-by-key idempotency unit (AC2).
    signal_id: str
    observed_at: datetime
    #: AC7: signals lacking scope context resolve to `_DEFAULT_SCOPE`, never
    #: `None` -- so an unscoped signal partitions into its own segment,
    #: never silently cross-fused with a scoped one.
    scope: str
    provenance_ref: str
    protagonists: tuple[str, ...] = ()
    goal: tuple[str, ...] = ()
    #: ADR-0054 seam: Heimdal's per-session boundary hint.
    heimdal_session_id: str | None = None
    causal_break: bool = False


@dataclass(frozen=True)
class OpenSegment:
    scope: str
    start: datetime
    last_signal_at: datetime
    heimdal_session_id: str | None = None
    protagonists: frozenset[str] = frozenset()
    goal: frozenset[str] = frozenset()
    derived_from: tuple[str, ...] = ()
    #: Every `signal_id` already folded into this segment -- the idempotency
    #: ledger that makes re-folding a redelivered signal a no-op (AC2).
    signal_ids: frozenset[str] = frozenset()

    def to_state(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "start": _iso(self.start),
            "last_signal_at": _iso(self.last_signal_at),
            "heimdal_session_id": self.heimdal_session_id,
            "protagonists": sorted(self.protagonists),
            "goal": sorted(self.goal),
            "derived_from": list(self.derived_from),
            "signal_ids": sorted(self.signal_ids),
        }

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "OpenSegment":
        return cls(
            scope=str(state["scope"]),
            start=_parse_dt(state["start"]),
            last_signal_at=_parse_dt(state["last_signal_at"]),
            heimdal_session_id=state.get("heimdal_session_id"),
            protagonists=frozenset(state.get("protagonists") or []),
            goal=frozenset(state.get("goal") or []),
            derived_from=tuple(state.get("derived_from") or []),
            signal_ids=frozenset(state.get("signal_ids") or []),
        )


@dataclass(frozen=True)
class ClosedSegment:
    scope: str
    start: datetime
    end: datetime
    heimdal_session_id: str | None
    protagonists: tuple[str, ...]
    goal: tuple[str, ...]
    derived_from: tuple[str, ...]


def _parse_dt(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(value: datetime) -> str:
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Five-dimension shift detection (ADR-0051 commitment 2)
# ---------------------------------------------------------------------------


def _goal_shift(open_segment: OpenSegment, signal: SegmentationSignal) -> bool:
    if not GOAL_SHIFT_DETECTION_ENABLED:
        return False
    if not open_segment.goal or not signal.goal:
        return False
    return open_segment.goal.isdisjoint(signal.goal)


def _protagonist_shift(open_segment: OpenSegment, signal: SegmentationSignal) -> bool:
    if not PROTAGONIST_SHIFT_DETECTION_ENABLED:
        return False
    if not open_segment.protagonists or not signal.protagonists:
        return False
    return open_segment.protagonists.isdisjoint(signal.protagonists)


def _causal_break(signal: SegmentationSignal) -> bool:
    return CAUSAL_BREAK_DETECTION_ENABLED and signal.causal_break


def detect_shift(open_segment: OpenSegment, signal: SegmentationSignal, *, now: datetime) -> bool:
    """Whether `signal` should close `open_segment` and start a new one.

    Order matters (AC3 first): a signal continuing the open segment's own
    bound Heimdal session ALWAYS extends -- one session never spans two
    proposed episodes (ADR-0054 seam), so no other dimension may split it.
    Only once the session-hint check does not apply do the remaining four
    dimensions run (place is unfed in v1, see `PLACE_SHIFT_DETECTION_ENABLED`).
    """
    if signal.heimdal_session_id is not None and signal.heimdal_session_id == open_segment.heimdal_session_id:
        return False
    if signal.observed_at - open_segment.last_signal_at > _TIME_GAP:
        return True
    if _goal_shift(open_segment, signal):
        return True
    if _protagonist_shift(open_segment, signal):
        return True
    if _causal_break(signal):
        return True
    return False


def _new_open_segment(signal: SegmentationSignal) -> OpenSegment:
    return OpenSegment(
        scope=signal.scope,
        start=signal.observed_at,
        last_signal_at=signal.observed_at,
        heimdal_session_id=signal.heimdal_session_id,
        protagonists=frozenset(signal.protagonists),
        goal=frozenset(signal.goal),
        derived_from=(signal.provenance_ref,),
        signal_ids=frozenset({signal.signal_id}),
    )


def _extend_open_segment(open_segment: OpenSegment, signal: SegmentationSignal) -> OpenSegment:
    if signal.signal_id in open_segment.signal_ids:
        # Idempotent fold (AC2): this exact signal already contributed to
        # this open segment (at-least-once redelivery before the cursor
        # advanced) -- a no-op, never a duplicate contribution.
        return open_segment
    derived_from = open_segment.derived_from
    if signal.provenance_ref not in derived_from:
        derived_from = derived_from + (signal.provenance_ref,)
    return replace(
        open_segment,
        last_signal_at=max(open_segment.last_signal_at, signal.observed_at),
        heimdal_session_id=open_segment.heimdal_session_id or signal.heimdal_session_id,
        protagonists=open_segment.protagonists | frozenset(signal.protagonists),
        goal=open_segment.goal | frozenset(signal.goal),
        derived_from=derived_from,
        signal_ids=open_segment.signal_ids | frozenset({signal.signal_id}),
    )


def _close(open_segment: OpenSegment) -> ClosedSegment:
    return ClosedSegment(
        scope=open_segment.scope,
        start=open_segment.start,
        end=open_segment.last_signal_at,
        heimdal_session_id=open_segment.heimdal_session_id,
        protagonists=tuple(sorted(open_segment.protagonists)),
        goal=tuple(sorted(open_segment.goal)),
        derived_from=open_segment.derived_from,
    )


def fold_signals_into_segments(
    signals: Sequence[SegmentationSignal],
    *,
    open_segments: Mapping[str, OpenSegment] | None = None,
    now: datetime,
) -> tuple[dict[str, OpenSegment], list[ClosedSegment]]:
    """Pure core (AC1/AC2/AC3/AC7): fold `signals` into per-scope open segments.

    Partitions `signals` by `scope` (AC7 -- never cross-scope fused; an
    unscoped signal already resolved to `_DEFAULT_SCOPE` by its stream
    adapter), walks each scope's signals in `observed_at` order against that
    scope's carried-over open segment (continuity across ticks via the
    `open_segments` argument), and closes a segment whenever
    :func:`detect_shift` fires. After the signal walk, also closes any
    open segment (touched this tick or not) whose `last_signal_at` is more
    than `TIME_GAP_MINUTES` stale relative to `now` -- the pure >45min-
    silence rule, needing no triggering signal. No I/O; deterministic;
    idempotent under a redelivered/overlapping `signals` batch (duplicate
    `signal_id`s are no-ops, see :func:`_extend_open_segment`).
    """
    working: dict[str, OpenSegment] = dict(open_segments or {})
    closed: list[ClosedSegment] = []

    by_scope: dict[str, list[SegmentationSignal]] = {}
    for signal in signals:
        by_scope.setdefault(signal.scope, []).append(signal)

    for scope, scope_signals in by_scope.items():
        ordered = sorted(scope_signals, key=lambda s: s.observed_at)
        current = working.get(scope)
        for signal in ordered:
            if current is None:
                current = _new_open_segment(signal)
                continue
            if detect_shift(current, signal, now=now):
                closed.append(_close(current))
                current = _new_open_segment(signal)
            else:
                current = _extend_open_segment(current, signal)
        if current is not None:
            working[scope] = current

    for scope, current in list(working.items()):
        if now - current.last_signal_at > _TIME_GAP:
            closed.append(_close(current))
            del working[scope]

    return working, closed


# ---------------------------------------------------------------------------
# Real stream adapters -- normalize each live stream's raw rows to SegmentationSignal
# ---------------------------------------------------------------------------


def _observation_id_of(row: ObservationRow, payload: Mapping[str, Any]) -> str:
    obs_id = payload.get("observation_id")
    if isinstance(obs_id, str) and obs_id.strip():
        return obs_id
    return row.id


def _signal_from_heimdal_row(row: ObservationRow) -> SegmentationSignal:
    payload = row.envelope.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    observation_id = _observation_id_of(row, payload)

    observed_at_raw = payload.get("observed_at_start")
    observed_at = _parse_dt(observed_at_raw) if observed_at_raw else row.created_at

    scope_hint = payload.get("scope_hint")
    scope = scope_hint.strip() if isinstance(scope_hint, str) and scope_hint.strip() else _DEFAULT_SCOPE

    session_id = payload.get("episode_id")
    session_id = session_id if isinstance(session_id, str) and session_id.strip() else None

    protagonists = tuple(
        sorted(
            {
                str(a["mention_id"])
                for a in (payload.get("attributions") or [])
                if isinstance(a, Mapping) and a.get("resolution") == "resolved" and a.get("mention_id")
            }
        )
    )

    supersedes = payload.get("supersedes")
    causal_break = isinstance(supersedes, str) and bool(supersedes.strip())

    return SegmentationSignal(
        stream_id=HEIMDAL_STREAM_ID,
        signal_id=observation_id,
        observed_at=observed_at,
        scope=scope,
        provenance_ref=f"heimdal.observations:{observation_id}",
        protagonists=protagonists,
        goal=(),
        heimdal_session_id=session_id,
        causal_break=causal_break,
    )


def _signal_from_vault_activity_row(row: VaultActivityRow, *, vault_root: Path) -> SegmentationSignal:
    dims = resolve_activity_dimensions(row, vault_root=vault_root)
    scope_raw = dims.get("scope")
    scope = scope_raw.strip() if isinstance(scope_raw, str) and scope_raw.strip() else _DEFAULT_SCOPE
    spheres = dims.get("sphere_memberships") or []
    # Provisional goal-dimension proxy for vault activity (no explicit
    # project/area field exists on `extract_context_dimensions_for_note`
    # yet): sphere membership is the closest available goal/context binding.
    goal = tuple(sorted({str(s) for s in spheres if str(s).strip()}))

    created_at = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)

    return SegmentationSignal(
        stream_id=VAULT_ACTIVITY_STREAM_ID,
        signal_id=row.id,
        observed_at=created_at,
        scope=scope,
        provenance_ref=f"vault.activity:{row.id}",
        protagonists=(),
        goal=goal,
        heimdal_session_id=None,
        causal_break=False,
    )


# ---------------------------------------------------------------------------
# Emission (AC5) + production tick entrypoint
# ---------------------------------------------------------------------------


def _deterministic_episode_id(closed: ClosedSegment) -> str:
    """A stable `episode_id` derived from the closed segment's own identity.

    A retried emission (crash between note-write and cursor-advance, INV-
    ERE-F) always mints the SAME id for the SAME segment, so the
    existence-check in :func:`_emit_proposal` makes the write path
    idempotent under redelivery independent of cursor-advance timing (AC2).
    """
    basis = "|".join((closed.scope, _iso(closed.start), closed.derived_from[0] if closed.derived_from else ""))
    return f"{EPISODE_ID_PREFIX}{uuid.uuid5(_EPISODE_ID_NAMESPACE, basis)}"


def _emit_proposal(
    closed: ClosedSegment,
    *,
    vault_root: Path,
    write_guard: WriteGuard,
) -> str | None:
    episode_id = _deterministic_episode_id(closed)
    rel_path = episode_note_rel_path(episode_id)
    if (Path(vault_root) / rel_path).exists():
        # Idempotent under redelivery (AC2): this exact segment was already
        # proposed by an earlier tick -- never double-propose.
        return None

    title = f"Proposed episode -- {closed.scope} -- {_iso(closed.start)}"
    result = write_episode_note(
        title=title,
        scope=closed.scope,
        start=_iso(closed.start),
        end=_iso(closed.end),
        # Segmentation only ever proposes a bounded window; the lifecycle
        # `closed` flag (event-triggered decay) is ERE-06's job, explicitly
        # out of scope here.
        closed=False,
        protagonists=list(closed.protagonists),
        goal=list(closed.goal),
        derived_from=list(closed.derived_from),
        segmentation="proposed",
        episode_id=episode_id,
        vault_root=vault_root,
        write_guard=write_guard,
    )
    return result.episode_id


def run_segmentation_tick(
    *,
    vault_root: Path | str,
    registry: StreamRegistry | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    consumer_id: str = CONSUMER_ID,
    now: datetime | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """THE production entrypoint (``python -m app.cli episodes tick``).

    Enumerates consumers strictly through the registry (AC4, via
    :func:`enumerate_consumable_streams` -- never a hardcoded source list),
    reads new signals since each live stream's own durable cursor, folds
    them per-scope into open segments (:func:`fold_signals_into_segments`),
    emits a proposal per closed segment, persists updated open-segment
    state, and ONLY THEN advances each stream's cursor.
    """
    tick_now = now if now is not None else datetime.now(timezone.utc)
    root = Path(vault_root)
    live_streams = {entry.stream_id for entry in enumerate_consumable_streams(registry=registry)}

    consumed: dict[str, int] = {}
    signals: list[SegmentationSignal] = []
    heimdal_rows: list[ObservationRow] = []
    vault_rows: list[VaultActivityRow] = []

    if HEIMDAL_STREAM_ID in live_streams:
        heimdal_rows = read_observations_for_consumer(consumer_id, limit=limit)
        consumed[HEIMDAL_STREAM_ID] = len(heimdal_rows)
        signals.extend(_signal_from_heimdal_row(row) for row in heimdal_rows)

    if VAULT_ACTIVITY_STREAM_ID in live_streams:
        vault_rows = read_vault_activity_for_consumer(consumer_id, limit=limit)
        consumed[VAULT_ACTIVITY_STREAM_ID] = len(vault_rows)
        signals.extend(_signal_from_vault_activity_row(row, vault_root=root) for row in vault_rows)

    open_state = engine_state.all_state_with_prefix(_OPEN_SEGMENT_KEY_PREFIX)
    open_segments = {
        key[len(_OPEN_SEGMENT_KEY_PREFIX) :]: OpenSegment.from_state(value) for key, value in open_state.items()
    }

    updated_open, closed_segments = fold_signals_into_segments(signals, open_segments=open_segments, now=tick_now)

    proposed_ids: list[str] = []
    for closed in closed_segments:
        episode_id = _emit_proposal(closed, vault_root=root, write_guard=write_guard)
        if episode_id is not None:
            proposed_ids.append(episode_id)

    for scope, segment in updated_open.items():
        engine_state.set_state(f"{_OPEN_SEGMENT_KEY_PREFIX}{scope}", segment.to_state())
    closed_scopes = {c.scope for c in closed_segments} - set(updated_open)
    for scope in closed_scopes:
        engine_state.delete_state(f"{_OPEN_SEGMENT_KEY_PREFIX}{scope}")

    # Advance cursors LAST (INV-ERE-F): a crash before this point means the
    # next tick re-reads the same batch, deduped by fold-by-key
    # (signal_ids already recorded on the open segment) plus the
    # deterministic episode id (an already-written note is never re-emitted).
    if heimdal_rows:
        advance_cursor_for_consumer(consumer_id, heimdal_rows)
    if vault_rows:
        advance_vault_activity_cursor(consumer_id, vault_rows)

    return {
        "consumed": consumed,
        "proposed": proposed_ids,
        "open_segments": len(updated_open),
    }


__all__ = [
    "CAUSAL_BREAK_DETECTION_ENABLED",
    "CONSUMER_ID",
    "GOAL_SHIFT_DETECTION_ENABLED",
    "HEIMDAL_STREAM_ID",
    "PLACE_SHIFT_DETECTION_ENABLED",
    "PROTAGONIST_SHIFT_DETECTION_ENABLED",
    "TIME_GAP_MINUTES",
    "ClosedSegment",
    "OpenSegment",
    "SegmentationSignal",
    "detect_shift",
    "enumerate_consumable_streams",
    "fold_signals_into_segments",
    "run_segmentation_tick",
    "run_segmenter_stub",
]
