"""Episode closure detection + ``episode.closed`` emission (ERE-06, #3181).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md``. Two write classes, kept
explicit (mirrors ``app/episodes/store.py`` / ``app/episodes/assignment.py``):

- The Episode note's own ``time.closed`` flip is the SoR (ADR-0051 §3.6, ADR-0058 §1): a
  proposal-class REWRITE of the SAME note (same ``episode_id`` -> same deterministic path) through
  the SAME guarded seam ERE-02 (``app.episodes.store.write_episode_note``) already uses --
  health-gate asserted, no human confirm, no governance import in this module either. A human
  re-cut (ERE-07) always wins over this engine write (spec).
- The ``episode.closed`` outbox event is plumbing, not SoR: at-least-once, idempotency-keyed
  (``app.services.outbox.derive_idempotency_key``/``write_outbox_event``, the house KERNEL-02
  scheme), carrying ``context_dimensions`` per SSI-01. A consumer that misses it self-heals from
  the ``episodes`` projection -- this module never gates correctness on delivery.

Closure detection (AC1): an open episode (``time.closed == False``) closes when wall-clock ``now``
has moved more than :data:`EPISODE_CLOSURE_QUIESCENCE_MINUTES` past its OWN bounded ``time.end`` --
"no new in-bounds signal for the time-gap threshold" (spec), read as: once an episode's bounded
window has closed (segmentation, ERE-04) and stayed quiescent for another full threshold window,
the situation is over. This deliberately reuses wall-clock time (unlike segmentation's own
observed-signal frontier, ADR-0058 §1 explicitly permits age as a CLOSURE input, just never in the
retrieval decay math itself, see ``app/episodes/closure_decay.py``) -- a scope that never emits
another signal after an episode's bounds close must still be able to close it; a per-scope observed
frontier that never advances again would never do so (the same limitation segmentation's own
carried-over-open-segment posture accepts and explicitly defers here).

Candidates are read from EVERY open, bounded episode in the ``episodes`` projection (ERE-02) --
not scoped to this tick's touched scopes -- so a scope with zero fresh activity still closes its
stale episodes on schedule; no daemon (spec: "runs as a deterministic tick"), a caller schedules
repeated invocations the same way ``episodes tick`` already is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

from app.db.db import conn_rw
from app.episodes.assignment import BINDING_STATE_ACTIVE, BINDING_TABLE
from app.episodes.notes import parse_episode_note
from app.episodes.segmenter import TIME_GAP_MINUTES
from app.episodes.store import write_episode_note
from app.events.models import new_event
from app.events.types import EPISODE_CLOSED
from app.jobs.episodes_projection import EPISODES_TABLE
from app.services.outbox import derive_idempotency_key, write_outbox_event
from app.watcher.vault_watcher import extract_context_dimensions_for_note
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

logger = logging.getLogger(__name__)

#: Closure quiescence threshold (AC1's "named threshold constant"): SINGLE-SOURCED as the SAME
#: constant segmentation's own shift/quiescence detector already defines
#: (``app.episodes.segmenter.TIME_GAP_MINUTES``) -- "no new in-bounds signals for the time-gap
#: threshold" (spec) is literally this value; this module never redefines its own copy.
EPISODE_CLOSURE_QUIESCENCE_MINUTES: Final[int] = TIME_GAP_MINUTES
_QUIESCENCE: Final[timedelta] = timedelta(minutes=EPISODE_CLOSURE_QUIESCENCE_MINUTES)

#: Fixed content fingerprint for the closure event's idempotency key (never the computed
#: ``closed_at`` timestamp, which legitimately varies between a first attempt and a crash-retry --
#: a varying fingerprint would defeat the whole point of the idempotency key. One episode closes
#: (in the decay-triggering sense) exactly once, so one fixed fingerprint per episode is correct.
_CONTENT_FINGERPRINT: Final[str] = "episode-closed-v1"

_EPISODES_SCHEMA_MIGRATION_HINT = (
    "episodes projection schema is migration-owned: run 'alembic upgrade head' against this "
    "database. See app/alembic/versions/e0f2a9c4b7d1_ere02_episodes_projection.py."
)


class EpisodeClosureSchemaMissingError(RuntimeError):
    """Raised when the ``episodes`` projection table is absent (pre-migration database)."""


def _assert_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (EPISODES_TABLE,))
        row = cur.fetchone()
    oid = (row.get("to_regclass") if isinstance(row, dict) else row[0]) if row else None
    if not oid:
        raise EpisodeClosureSchemaMissingError(
            f"Missing table '{EPISODES_TABLE}'. {_EPISODES_SCHEMA_MIGRATION_HINT}"
        )


@dataclass(frozen=True)
class EpisodeCloseCandidate:
    """One open, bounded episode eligible for the quiescence check."""

    episode_id: str
    scope: str
    note_path: str
    time_end: datetime


@dataclass(frozen=True)
class EpisodeCloseResult:
    episode_id: str
    event_emitted: bool


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def find_closable_episodes(
    *, now: datetime | None = None, quiescence: timedelta = _QUIESCENCE
) -> list[EpisodeCloseCandidate]:
    """Every open (``closed = false``), bounded (``time_end IS NOT NULL``) episode whose bound
    ``time_end`` lies more than ``quiescence`` behind ``now`` -- across every scope, not just this
    tick's touched scopes (see module docstring)."""
    resolved_now = now or datetime.now(timezone.utc)
    out: list[EpisodeCloseCandidate] = []
    with conn_rw() as conn:
        _assert_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT episode_id, scope, time_end, note_path FROM {EPISODES_TABLE} "
                "WHERE closed = false AND time_end IS NOT NULL"
            )
            rows = cur.fetchall()
    for r in rows:
        if isinstance(r, dict):
            episode_id, scope, time_end, note_path = (
                r["episode_id"],
                r["scope"],
                r["time_end"],
                r["note_path"],
            )
        else:
            episode_id, scope, time_end, note_path = r
        time_end_dt = _as_utc(time_end)
        if resolved_now - time_end_dt > quiescence:
            out.append(
                EpisodeCloseCandidate(
                    episode_id=str(episode_id),
                    scope=str(scope),
                    note_path=str(note_path),
                    time_end=time_end_dt,
                )
            )
    return out


def _count_active_bound_artifacts(episode_id: str) -> int:
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT count(*) AS n FROM {BINDING_TABLE} WHERE episode_id = %s AND binding_state = %s",
                (episode_id, BINDING_STATE_ACTIVE),
            )
            row = cur.fetchone()
    if row is None:
        return 0
    value = row["n"] if isinstance(row, dict) else row[0]
    return int(value or 0)


def close_episode(
    candidate: EpisodeCloseCandidate,
    *,
    vault_root: Path | str,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> EpisodeCloseResult | None:
    """Flip ``time.closed`` on ONE episode's note (guarded seam) and emit ``episode.closed``.

    ``None`` (a documented no-op, never an error) when the note is unreadable (best-effort, mirrors
    ``app.episodes.assignment``'s treatment of a vanished vault target) or the note ALREADY reads
    ``closed: true`` -- idempotent under redelivery/retry (AC1: "closes once"): a second call
    against an already-closed episode never re-writes the note and never re-derives a NEW
    idempotency key from a fresh ``closed_at`` (the key's fingerprint is fixed, see
    :data:`_CONTENT_FINGERPRINT`), so a retried tick converges rather than duplicating.
    """
    root = Path(vault_root)
    note_abs = root / candidate.note_path
    try:
        text = note_abs.read_text(encoding="utf-8")
    except OSError:
        logger.warning(
            "closure: could not read episode note %s for candidate %s -- skipping (no-op)",
            note_abs,
            candidate.episode_id,
        )
        return None

    fields = parse_episode_note(text)
    time_fields = dict(fields.get("time") or {})
    if bool(time_fields.get("closed", False)):
        # Already closed -- another writer/tick beat us to it, or this candidate is stale
        # (the caller's own SELECT already filtered `closed = false`, but nothing prevents two
        # closure ticks racing between read and write). No-op, never a duplicate write/event.
        return None

    # Guard-at-seam (mirrors ERE-02/05): write_episode_note asserts
    # write_guard.assert_writes_allowed(EPISODE_WRITE_ACTION) itself, before any filesystem
    # mutation. Re-write the SAME note (same episode_id -> same deterministic path) with every
    # other field preserved verbatim and only `closed` flipped -- a proposal-class rewrite, never a
    # new note, never a governed transition (no governance import anywhere in this module).
    write_episode_note(
        title=str(fields.get("title") or ""),
        scope=str(fields.get("scope") or candidate.scope),
        start=str(time_fields.get("start") or ""),
        closed=True,
        end=time_fields.get("end"),
        space=list(fields.get("space") or []),
        protagonists=list(fields.get("protagonists") or []),
        goal=list(fields.get("goal") or []),
        causation=list(fields.get("causation") or []),
        parent_episode=fields.get("parent_episode"),
        segmentation=str(fields.get("segmentation") or "proposed"),
        derived_from=list(fields.get("derived_from") or []),
        episode_id=candidate.episode_id,
        vault_root=root,
        write_guard=write_guard,
    )

    closed_at = datetime.now(timezone.utc).isoformat()
    bound_artifact_count = _count_active_bound_artifacts(candidate.episode_id)
    # SSI-01 context_dimensions: reuse the SAME extractor every other outbox producer in this
    # engine already uses (app.watcher.vault_watcher.extract_context_dimensions_for_note), fed the
    # episode note's own frontmatter fields (it carries `scope`, matching `_resolve_note_scope`).
    context_dimensions = extract_context_dimensions_for_note(fields)
    payload = {
        "episode_id": candidate.episode_id,
        "closed_at": closed_at,
        "scope": candidate.scope,
        "bound_artifact_count": bound_artifact_count,
    }
    idempotency_key = derive_idempotency_key(EPISODE_CLOSED, candidate.episode_id, _CONTENT_FINGERPRINT)
    event = new_event(
        event_type=EPISODE_CLOSED,
        payload=payload,
        context_dimensions=context_dimensions,
        source="episodes.closure",
    )
    write_outbox_event(event, idempotency_key=idempotency_key)
    return EpisodeCloseResult(episode_id=candidate.episode_id, event_emitted=True)


def run_closure_tick(
    *,
    vault_root: Path | str,
    now: datetime | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> dict[str, Any]:
    """The production closure entrypoint -- extends ``episodes tick``
    (:func:`app.episodes.segmenter.run_segmentation_tick` calls this after assignment).

    Returns ``{"closed": [episode_id, ...], "events_emitted": n}`` (spec's "Concretely" shape).
    """
    root = Path(vault_root)
    candidates = find_closable_episodes(now=now)
    closed_ids: list[str] = []
    events_emitted = 0
    for candidate in candidates:
        result = close_episode(candidate, vault_root=root, write_guard=write_guard)
        if result is not None:
            closed_ids.append(result.episode_id)
            if result.event_emitted:
                events_emitted += 1
    return {"closed": closed_ids, "events_emitted": events_emitted}


__all__ = [
    "EPISODE_CLOSURE_QUIESCENCE_MINUTES",
    "EpisodeClosureSchemaMissingError",
    "EpisodeCloseCandidate",
    "EpisodeCloseResult",
    "close_episode",
    "find_closable_episodes",
    "run_closure_tick",
]
