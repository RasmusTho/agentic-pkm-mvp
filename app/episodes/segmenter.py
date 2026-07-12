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
  scope's signals in ``observed_at`` order and closes a segment whenever
  :func:`detect_shift` fires a boundary. Quiescence (the >45min-silence rule)
  is measured against a PER-SCOPE READ-POSITION frontier, never wall-clock
  and never a cross-scope/cross-stream frontier: a segment in scope X closes
  on quiescence only when scope X's OWN read position (the max ``observed_at``
  START instant consumed for that scope, ``frontiers``: scope -> that
  instant) has moved more than the gap past that segment's last signal. The
  frontier keys on ``observed_at`` (where the next signal STARTED), NOT
  ``observed_until`` (a signal's content-span END): one signal with a long
  observed window must not push the frontier past a nested, later-started
  segment in the same scope and quiesce-close it. A sibling scope's later
  signal in the same batch can therefore never close another scope's
  just-created segment (the AC7 per-scope-isolation principle applied to
  closure). This also keeps one Heimdal session from ever spanning two
  proposals (AC3): a session continuing always *extends* via
  :func:`detect_shift`'s session-hint branch, and only a genuinely
  later-started observation in that session's own scope advances its frontier
  -- and by then that observation has already folded in and moved
  ``last_signal_at`` forward with it. (``observed_until`` remains
  authoritative for ``last_signal_at`` and emitted bounds -- only the closure
  read-position keys on ``observed_at``.) No I/O, no vault, no DB --
  fully unit-testable and deterministic, so it is also the module's
  idempotency guarantee under at-least-once redelivery (AC2): re-folding a
  signal whose ``signal_id`` an open segment already recorded is a no-op.
  Closure is deliberately conservative: a scope with no signal this tick has
  no frontier entry and its carried-over segment simply stays open, deferred
  to ERE-06 (which owns real closure detection, explicitly out of scope for
  ERE-04) -- keeping a segment open too long is the safe side.
- :func:`run_segmentation_tick` is the production, I/O-performing entrypoint
  (``python -m app.cli episodes tick``): reads new signals from each *live*
  registered stream since its own durable cursor, builds this tick's
  per-scope read-position frontier (max ``observed_at`` per scope) from the
  consumed signals, calls the pure fold,
  emits a ``segmentation: proposed`` Episode note per closed segment (AC5, via
  ``app.episodes.store.write_episode_note`` -- the ERE-02 guarded seam),
  persists updated open-segment state, advances each stream's cursor, and
  ONLY THEN deletes closed-segment state -- a crash at any point means the
  next tick reprocesses/reconverges, deduped by fold-by-key (retained
  ``signal_ids`` ledgers) plus a deterministic, START-INDEPENDENT
  ``episode_id`` per closed segment (a retried emission never double-writes
  a note, AC2 / INV-ERE-F), even when only ONE of the two cursors advanced
  before the crash.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from app.episodes import engine_state
from app.episodes.assignment import (
    artifact_candidates_from_signals,
    commit_assignment_diff,
    compute_assignments,
    diff_assignments,
    episode_bounds_from_closed_segments,
    read_candidate_episodes_for_scopes,
    read_existing_bindings,
)
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

logger = logging.getLogger(__name__)


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

# The four *_DETECTION_ENABLED constants below are COMPILE-TIME DOCUMENTATION
# of which shift dimensions are active in v1, not runtime flags -- there is
# deliberately no env/settings toggle path (RQ-E1 tuning happens as code
# change against this single source, never as drifting runtime config).

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
    #: Bitemporal end of the observation window (HEIM-10), when the source
    #: carries one (e.g. a voice observation spanning 09:00-09:30). Extends
    #: the segment's `last_signal_at` so emitted bounds cover the whole
    #: observed window, not just its start.
    observed_at_end: datetime | None = None
    protagonists: tuple[str, ...] = ()
    goal: tuple[str, ...] = ()
    #: ADR-0054 seam: Heimdal's per-session boundary hint.
    heimdal_session_id: str | None = None
    causal_break: bool = False

    @property
    def observed_until(self) -> datetime:
        """The latest observed instant this signal evidences."""
        if self.observed_at_end is not None and self.observed_at_end > self.observed_at:
            return self.observed_at_end
        return self.observed_at


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


def _disjoint_set_shift(enabled: bool, open_set: frozenset[str], signal_set: frozenset[str]) -> bool:
    """Shared shape of the goal- and protagonist-shift dimensions: a shift
    fires only when detection is enabled AND both sides carry evidence AND
    the sets are completely disjoint -- absence of evidence on either side
    is never treated as a shift (conservative bar; the next set-valued
    dimension in this family reuses this helper instead of a third copy)."""
    if not enabled:
        return False
    if not open_set or not signal_set:
        return False
    return open_set.isdisjoint(signal_set)


def _causal_break(signal: SegmentationSignal) -> bool:
    return CAUSAL_BREAK_DETECTION_ENABLED and signal.causal_break


def detect_shift(open_segment: OpenSegment, signal: SegmentationSignal) -> bool:
    """Whether `signal` should close `open_segment` and start a new one.

    Order matters (AC3 first): a signal continuing the open segment's own
    bound Heimdal session ALWAYS extends -- one session never spans two
    proposed episodes (ADR-0054 seam), so no other dimension may split it.
    Only once the session-hint check does not apply do the remaining four
    dimensions run (place is unfed in v1, see `PLACE_SHIFT_DETECTION_ENABLED`).
    All comparisons are observed-time; wall-clock never enters shift detection.
    """
    if signal.heimdal_session_id is not None and signal.heimdal_session_id == open_segment.heimdal_session_id:
        return False
    if signal.observed_at - open_segment.last_signal_at > _TIME_GAP:
        return True
    if _disjoint_set_shift(GOAL_SHIFT_DETECTION_ENABLED, open_segment.goal, frozenset(signal.goal)):
        return True
    if _disjoint_set_shift(
        PROTAGONIST_SHIFT_DETECTION_ENABLED, open_segment.protagonists, frozenset(signal.protagonists)
    ):
        return True
    if _causal_break(signal):
        return True
    return False


def _new_open_segment(signal: SegmentationSignal) -> OpenSegment:
    return OpenSegment(
        scope=signal.scope,
        start=signal.observed_at,
        last_signal_at=signal.observed_until,
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
        # Bitemporal bounds cover EVERY folded signal: a late-delivered
        # signal with an earlier observed_at (the two stream cursors are
        # independent, so cross-stream arrival order is not observed order)
        # widens `start` downward -- time.start must never postdate a signal
        # in the segment's own derived_from (AC1).
        start=min(open_segment.start, signal.observed_at),
        last_signal_at=max(open_segment.last_signal_at, signal.observed_until),
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
    frontiers: Mapping[str, datetime] | None = None,
) -> tuple[dict[str, OpenSegment], list[ClosedSegment]]:
    """Pure core (AC1/AC2/AC3/AC7): fold `signals` into per-scope open segments.

    Partitions `signals` by `scope` (AC7 -- never cross-scope fused; an
    unscoped signal already resolved to `_DEFAULT_SCOPE` by its stream
    adapter), walks each scope's signals in `observed_at` order against that
    scope's carried-over open segment (continuity across ticks via the
    `open_segments` argument), and closes a segment whenever
    :func:`detect_shift` fires.

    After the signal walk, also closes any open segment (touched this tick
    or not) that has gone quiescent AGAINST ITS OWN SCOPE'S FRONTIER: its
    `last_signal_at` lies more than `TIME_GAP_MINUTES` behind the observed
    head of its own scope (`frontiers`: scope -> max observed instant
    consumed for that scope). The frontier is per-SCOPE, never per-stream and
    never cross-scope: a sibling scope's progress can never close another
    scope's segment (AC7 per-scope isolation applied to closure), and one
    Heimdal session -- always within a single scope -- can never be split
    across two proposals by a sibling's frontier (AC3). Wall-clock never
    closes a segment, and a scope with no frontier entry (no signal this
    tick) stays open -- conservative; ERE-06 owns real closure detection.

    No I/O; deterministic; idempotent under a redelivered/overlapping
    `signals` batch (duplicate `signal_id`s are no-ops, see
    :func:`_extend_open_segment`).
    """
    working: dict[str, OpenSegment] = dict(open_segments or {})
    closed: list[ClosedSegment] = []
    frontier_map: Mapping[str, datetime] = frontiers or {}

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
            if detect_shift(current, signal):
                closed.append(_close(current))
                current = _new_open_segment(signal)
            else:
                current = _extend_open_segment(current, signal)
        if current is not None:
            working[scope] = current

    for scope, current in list(working.items()):
        # Quiescence is judged ONLY against this segment's own scope frontier
        # (per-scope isolation): a sibling scope moving on says nothing about
        # whether this scope's own later signals are still in flight.
        frontier = frontier_map.get(scope)
        if frontier is not None and frontier - current.last_signal_at > _TIME_GAP:
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


def _epoch_seconds_to_dt(seconds: float) -> datetime | None:
    """Convert epoch seconds to a UTC datetime, ``None`` if not a usable
    instant. An epoch <= 0 (e.g. an ``mtime=0`` sentinel) is treated as
    ABSENT, not dated to 1970 -- a 1970 instant would drag a segment's
    `start` backward through the out-of-order min()-widening. NaN/inf/
    out-of-range values raise inside ``fromtimestamp`` and are caught here so
    a malformed mtime skips fail-loud instead of crashing the whole tick."""
    if seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _parse_observation_time(value: Any) -> datetime | None:
    """Parse a payload observation-time value: epoch seconds (the watcher's
    `mtime` float) or an ISO-8601 string. A purely-numeric string is treated
    as epoch seconds by design (the watcher may serialize `mtime` as a
    string), NOT as a bare year. ``None`` when absent/unparseable/invalid --
    the caller skips the signal fail-loud (count + log), never substitutes
    emission time, and a malformed numeric value never crashes the tick."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _epoch_seconds_to_dt(float(value))
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            seconds = float(text)
        except ValueError:
            try:
                return _parse_dt(text)
            except ValueError:
                return None
        return _epoch_seconds_to_dt(seconds)
    return None


def _signal_from_heimdal_row(row: ObservationRow) -> SegmentationSignal | None:
    """Normalize one observation-log row, or ``None`` when it carries no
    observation time (bounds come from ``observed_at``, NEVER emission time --
    a row without ``observed_at_start`` is skipped fail-loud, not silently
    stamped with the log row's insert time; the publish contract makes this
    unreachable for schema-validated observations)."""
    payload = row.envelope.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    observation_id = _observation_id_of(row, payload)

    observed_at = _parse_observation_time(payload.get("observed_at_start"))
    if observed_at is None:
        logger.warning(
            "segmentation: skipping heimdal observation without observed_at_start "
            "(observation_id=%s log_row=%s) -- bounds are never emission time",
            observation_id,
            row.id,
        )
        return None
    observed_at_end = _parse_observation_time(payload.get("observed_at_end"))

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
        observed_at_end=observed_at_end,
        scope=scope,
        provenance_ref=f"heimdal.observations:{observation_id}",
        protagonists=protagonists,
        goal=(),
        heimdal_session_id=session_id,
        causal_break=causal_break,
    )


def _signal_from_vault_activity_row(row: VaultActivityRow, *, vault_root: Path) -> SegmentationSignal | None:
    """Normalize one vault-activity outbox row, or ``None`` when it carries no
    observation time. The payload's ``mtime`` (the watcher's observed file
    change time) is the observation time; the outbox row's ``created_at`` is
    emission/enqueue time and is NEVER substituted -- a delayed or backfilled
    scan must not shift episode bounds to enqueue time (spec: bounds from
    ``observed_at``, never emission time). Rows without a usable ``mtime``
    (e.g. `ingest.object.created`/`deleted` payloads, which do not carry one
    today) are skipped fail-loud (count + log)."""
    observed_at = _parse_observation_time(row.payload.get("mtime"))
    if observed_at is None:
        logger.warning(
            "segmentation: skipping vault-activity row without observation time "
            "(topic=%s outbox_row=%s) -- bounds are never emission time",
            row.topic,
            row.id,
        )
        return None

    dims = resolve_activity_dimensions(row, vault_root=vault_root)
    scope_raw = dims.get("scope")
    scope = scope_raw.strip() if isinstance(scope_raw, str) and scope_raw.strip() else _DEFAULT_SCOPE
    spheres = dims.get("sphere_memberships") or []
    # Provisional goal-dimension proxy for vault activity (no explicit
    # project/area field exists on `extract_context_dimensions_for_note`
    # yet): sphere membership is the closest available goal/context binding.
    goal = tuple(sorted({str(s) for s in spheres if str(s).strip()}))

    return SegmentationSignal(
        stream_id=VAULT_ACTIVITY_STREAM_ID,
        signal_id=row.id,
        observed_at=observed_at,
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
    """A stable `episode_id` derived from the closed segment's STABLE identity.

    Keyed on ``scope | derived_from[0]`` -- the scope plus the provenance_ref
    of the FIRST signal ever folded into the segment. That first ref is
    append-only-stable: out-of-order widening only ever moves `start`
    downward and appends to `derived_from`, so it never mutates
    ``derived_from[0]``. The id is therefore START-INDEPENDENT: a resurrected
    stale segment (the documented crash-residual) whose `start` later widens
    still mints the SAME id, so the existence-check in :func:`_emit_proposal`
    keeps the write path idempotent under redelivery independent of both
    cursor-advance timing AND start-widening (AC2 / INV-ERE-F). Two distinct
    same-scope segments always differ in their first-folded provenance_ref, so
    they can never collide. `derived_from` is non-empty in practice (a segment
    is always created from a signal carrying a non-empty provenance_ref); the
    empty fallback is defensive only.
    """
    basis = "|".join((closed.scope, closed.derived_from[0] if closed.derived_from else ""))
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
    limit: int | None = None,
) -> dict[str, Any]:
    """THE production entrypoint (``python -m app.cli episodes tick``).

    Enumerates consumers strictly through the registry (AC4, via
    :func:`enumerate_consumable_streams` -- never a hardcoded source list),
    reads new signals since each live stream's own durable cursor, folds
    them per-scope into open segments (:func:`fold_signals_into_segments`,
    quiescence measured against this tick's PER-SCOPE read-position frontier
    (max observed_at per scope -- never wall-clock, never cross-scope, never
    a signal's observed_until span end), and emits a proposal per closed
    segment. A scope with no signal this tick has no frontier entry, so its
    carried-over segment stays open and is deferred to ERE-06 (closure
    detection is out of scope for ERE-04).

    Crash-safe ordering (INV-ERE-F): emit -> assign -> persist open state ->
    advance cursors -> delete closed-segment state LAST. A crash between the
    two cursor advances replays only one stream, but the closed segment's
    retained ``signal_ids`` ledger dedups the replayed rows and the
    deterministic, start-independent episode id skips the already-written
    note -- the tick reconverges instead of double-proposing.

    Assignment (ERE-05, #3180) runs AFTER segmentation, over the SAME
    delta-window ``signals`` this tick already folded (no second stream
    read): every signal is a candidate artifact, matched against both this
    tick's freshly closed segments (in-memory -- not yet reflected in the
    ``episodes`` PG projection) and already-persisted episodes for the
    touched scopes (the source late-arriving artifacts bind against without
    re-cutting bounds, AC7). See ``app.episodes.assignment`` for the rule.
    """
    root = Path(vault_root)
    live_streams = {entry.stream_id for entry in enumerate_consumable_streams(registry=registry)}

    consumed: dict[str, int] = {}
    skipped_no_observation_time: dict[str, int] = {}
    signals: list[SegmentationSignal] = []
    heimdal_rows: list[ObservationRow] = []
    vault_rows: list[VaultActivityRow] = []

    if HEIMDAL_STREAM_ID in live_streams:
        heimdal_rows = read_observations_for_consumer(consumer_id, limit=limit)
        consumed[HEIMDAL_STREAM_ID] = len(heimdal_rows)
        for h_row in heimdal_rows:
            signal = _signal_from_heimdal_row(h_row)
            if signal is None:
                skipped_no_observation_time[HEIMDAL_STREAM_ID] = (
                    skipped_no_observation_time.get(HEIMDAL_STREAM_ID, 0) + 1
                )
            else:
                signals.append(signal)

    if VAULT_ACTIVITY_STREAM_ID in live_streams:
        vault_rows = read_vault_activity_for_consumer(consumer_id, limit=limit)
        consumed[VAULT_ACTIVITY_STREAM_ID] = len(vault_rows)
        for v_row in vault_rows:
            signal = _signal_from_vault_activity_row(v_row, vault_root=root)
            if signal is None:
                skipped_no_observation_time[VAULT_ACTIVITY_STREAM_ID] = (
                    skipped_no_observation_time.get(VAULT_ACTIVITY_STREAM_ID, 0) + 1
                )
            else:
                signals.append(signal)

    open_state = engine_state.all_state_with_prefix(_OPEN_SEGMENT_KEY_PREFIX)
    open_segments = {
        key[len(_OPEN_SEGMENT_KEY_PREFIX) :]: OpenSegment.from_state(value) for key, value in open_state.items()
    }

    # Per-scope READ-POSITION frontier for THIS tick: scope -> max
    # `observed_at` (the START of the latest signal consumed for that scope),
    # never `observed_until` (a signal's content-span END). The frontier
    # answers "how far has this scope's read position advanced" -- i.e. up to
    # what start instant have we observed signals -- so a single signal whose
    # observed window merely spans far into the future (a long
    # observed_at_end) must NOT push the frontier past a nested, later-started
    # segment created in the same tick and quiesce-close it (that would split
    # one session across two proposals, the within-scope form of the AC3 bug).
    # observed_until stays authoritative for `last_signal_at` and segment
    # bounds (:func:`_extend_open_segment` / :func:`_close`); it is only the
    # closure read-position that keys on observed_at. Never wall-clock, never
    # enqueue time, never cross-scope: a sibling scope's later signal can never
    # close another scope's segment (AC7 isolation applied to closure), and a
    # scope with no signal this tick has no entry, so its carried-over segment
    # stays open (deferred to ERE-06). Computed fresh per tick, not carried
    # durably -- per-scope-from-this-batch is sufficient, so there is no
    # stream-watermark row family to persist.
    scope_frontiers: dict[str, datetime] = {}
    for signal in signals:
        current = scope_frontiers.get(signal.scope)
        if current is None or signal.observed_at > current:
            scope_frontiers[signal.scope] = signal.observed_at

    updated_open, closed_segments = fold_signals_into_segments(
        signals, open_segments=open_segments, frontiers=scope_frontiers
    )

    proposed_ids: list[str] = []
    for closed in closed_segments:
        episode_id = _emit_proposal(closed, vault_root=root, write_guard=write_guard)
        if episode_id is not None:
            proposed_ids.append(episode_id)

    # ERE-05 assignment: same delta-window signals, run strictly after segmentation/emission.
    # A tick with no signals at all has nothing to assign (never touches the ledger or the DB).
    assignment_summary = {"pending": 0, "corrected": 0}
    if signals:
        artifacts = artifact_candidates_from_signals(signals)
        fresh_episodes = episode_bounds_from_closed_segments(
            closed_segments, episode_id_for=_deterministic_episode_id
        )
        touched_scopes = {a.scope for a in artifacts}
        persisted_episodes = read_candidate_episodes_for_scopes(touched_scopes)
        # This tick's freshly closed segments are authoritative over any (should-be-identical)
        # stale projection row for the same id -- the projection is a rebuildable index that has
        # not yet been refreshed with this tick's own emissions.
        episodes_by_id = {e.episode_id: e for e in persisted_episodes}
        episodes_by_id.update({e.episode_id: e for e in fresh_episodes})
        decisions = compute_assignments(artifacts, list(episodes_by_id.values()))
        existing_bindings = read_existing_bindings({a.artifact_ref for a in artifacts})
        to_insert, to_correct = diff_assignments(existing_bindings, decisions)
        assignment_summary = commit_assignment_diff(to_insert, to_correct, write_guard=write_guard)

    for scope, segment in updated_open.items():
        engine_state.set_state(f"{_OPEN_SEGMENT_KEY_PREFIX}{scope}", segment.to_state())

    # Advance cursors only after proposals and open state are durable; delete
    # closed-segment state LAST. A crash between the two advances leaves the
    # closed segment's signal_ids ledger in place, so the one-stream replay
    # on the next tick folds to no-ops and the deterministic, start-independent
    # episode id skips the existing note (never a second partial proposal --
    # widening the resurrected segment's start on replay does not change its
    # id, so the "never a duplicate" guarantee holds).
    # Known residual (documented, accepted): a crash in the narrow window
    # between the final cursor advance and the closed-state delete leaves an
    # already-emitted segment's state loadable for one more tick; a genuinely
    # NEW in-gap signal for that scope would extend it and be skipped at
    # re-emission (its ref missing from one proposal's derived_from) -- an
    # under-enrichment, never a duplicate or a lost note. ERE-07's re-cut
    # path is the human correction for any mis-bounded proposal.
    if heimdal_rows:
        advance_cursor_for_consumer(consumer_id, heimdal_rows)
    if vault_rows:
        advance_vault_activity_cursor(consumer_id, vault_rows)

    closed_scopes = {c.scope for c in closed_segments} - set(updated_open)
    for scope in closed_scopes:
        engine_state.delete_state(f"{_OPEN_SEGMENT_KEY_PREFIX}{scope}")

    return {
        "consumed": consumed,
        "skipped_no_observation_time": skipped_no_observation_time,
        "proposed": proposed_ids,
        "open_segments": len(updated_open),
        "assigned": assignment_summary,
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
