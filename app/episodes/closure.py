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
- The ``episodes`` PROJECTION's own ``closed`` column (ERE-02, ``app.jobs.episodes_projection``) is
  what production retrieval actually reads (``app.episodes.closure_decay.read_closed_episode_ids``)
  -- it is kept current by a targeted incremental ``UPDATE`` this module issues itself
  (:func:`_sync_projection_closed`), never by the full ``rebuild_episodes_projection`` TRUNCATE+
  replay (no production caller schedules that rebuild). This is THE fix for #3181 review finding
  P1-1 ("production retrieval never observes closures"): before it, only an operator-triggered
  rebuild ever refreshed this column, so a closed episode's bound artifacts never actually decayed
  in salience at the real retrieval call site. :func:`close_episode` orders its three writes
  note -> outbox -> projection deliberately (P1-2's crash-window fix): the projection UPDATE is the
  gate that stops a candidate from being re-offered by :func:`find_closable_episodes`, so it must
  land last -- a crash between any two of the three writes leaves the episode selectable on the
  next tick, which retries the remaining (idempotent) writes to completion instead of losing them.

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

from app.db.db import COMPATIBILITY_BINDING_ID, conn_rw
from app.db.replay_projection_schema import assert_replay_projection_schema
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

#: Distinct action string (round-3 review fix) for the reconciliation branch's own DB writes
#: (outbox insert, projection UPDATE) -- deliberately NOT ``app.episodes.store.EPISODE_WRITE_ACTION``
#: ("episodes.write_note"), which names the vault-note write seam specifically and is never
#: reached on this branch. Reusing it would make a ``WritesBlockedError`` raised here report
#: ``.action == "episodes.write_note"``, misdirecting anyone debugging a blocked-write incident
#: toward the note-write seam instead of this module's own DB writes. Mirrors the per-seam-action
#: pattern ``app.episodes.assignment.EPISODE_ASSIGNMENT_WRITE_ACTION`` already establishes.
EPISODE_CLOSURE_RECONCILE_ACTION: Final[str] = "episodes.closure_reconcile"

_EPISODES_SCHEMA_MIGRATION_HINT = (
    "episodes projection schema is migration-owned: run 'alembic upgrade head' against this "
    "database. See app/alembic/versions/e0f2a9c4b7d1_ere02_episodes_projection.py."
)


class EpisodeClosureSchemaMissingError(RuntimeError):
    """Raised when the ``episodes`` projection table is absent (pre-migration database)."""


def _assert_schema(conn: Any) -> None:
    try:
        assert_replay_projection_schema(conn, EPISODES_TABLE)
    except RuntimeError as exc:
        raise EpisodeClosureSchemaMissingError(
            f"Stale table '{EPISODES_TABLE}'. {_EPISODES_SCHEMA_MIGRATION_HINT}"
        ) from exc


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
                "WHERE vault_binding_id = %s AND closed = false AND time_end IS NOT NULL",
                (COMPATIBILITY_BINDING_ID,),
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
        try:
            assert_replay_projection_schema(conn, BINDING_TABLE)
        except RuntimeError as exc:
            raise EpisodeClosureSchemaMissingError(str(exc)) from exc
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT count(*) AS n FROM {BINDING_TABLE} "
                "WHERE vault_binding_id = %s AND episode_id = %s AND binding_state = %s",
                (COMPATIBILITY_BINDING_ID, episode_id, BINDING_STATE_ACTIVE),
            )
            row = cur.fetchone()
    if row is None:
        return 0
    value = row["n"] if isinstance(row, dict) else row[0]
    return int(value or 0)


def _sync_projection_closed(episode_id: str) -> None:
    """Incrementally flip the ``episodes`` projection row's ``closed`` column (#3181 review
    fix -- production retrieval reads ``closed`` off THIS table via
    ``app.episodes.closure_decay.read_closed_episode_ids``, and nothing else keeps it current: the
    only other writer, ``app.jobs.episodes_projection.rebuild_episodes_projection``, is a full
    TRUNCATE+replay that no production caller invokes on any schedule). A targeted ``UPDATE`` --
    never a rebuild -- mirrors the incremental-update-over-rebuild discipline
    ``app.episodes.assignment.commit_assignment_diff`` already establishes for this same
    projection family (targeted ``jsonb_set``, never a read-modify-write of the whole row).

    Idempotent by construction (``SET closed = true`` twice is the same as once), so this is safe
    to call from the reconciliation path below as often as a retried tick calls it. A zero-rowcount
    result (the projection has no row for this episode -- e.g. it was truncated by a concurrent
    ``rebuild_episodes_projection`` run) is logged, not raised: the vault note (SoR) already carries
    the correct ``closed: true`` state regardless, and the next rebuild re-derives this row from it.
    """
    with conn_rw() as conn:
        _assert_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {EPISODES_TABLE} SET closed = true "
                "WHERE vault_binding_id = %s AND episode_id = %s",
                (COMPATIBILITY_BINDING_ID, episode_id),
            )
            rowcount = getattr(cur, "rowcount", None)
    if not rowcount:
        logger.warning(
            "closure: episodes projection has no row for %s -- closed-note state will not be "
            "query-visible until the next rebuild_episodes_projection() run",
            episode_id,
        )


def close_episode(
    candidate: EpisodeCloseCandidate,
    *,
    vault_root: Path | str,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> EpisodeCloseResult | None:
    """Flip ``time.closed`` on ONE episode's note (guarded seam), sync the ``episodes``
    projection's ``closed`` column, and emit ``episode.closed``.

    ``None`` (a documented no-op, never an error) only when the note is unreadable (best-effort,
    mirrors ``app.episodes.assignment``'s treatment of a vanished vault target).

    When the note ALREADY reads ``closed: true`` -- another writer/tick beat us to it, OR this is a
    crash-recovery retry after a PRIOR call flipped the note but died before the projection sync
    and/or outbox write completed (#3181 review fix, P1 finding 2) -- the note rewrite is skipped
    (never a duplicate write) but the projection sync and outbox emission are STILL attempted: both
    are idempotent (the projection ``UPDATE`` is naturally idempotent;
    ``app.services.outbox.write_outbox_event`` dedups via ``ON CONFLICT (id) DO NOTHING`` keyed on
    the FIXED idempotency-key fingerprint, see :data:`_CONTENT_FINGERPRINT`), so a retry converges
    rather than duplicating. This turns the existing candidate-rescan (``find_closable_episodes``
    only offers a candidate while the projection still reads ``closed = false``, see
    :func:`_sync_projection_closed`) into the crash-recovery replay path: as long as the projection
    sync has not yet landed, the SAME episode keeps being offered to the next tick, which keeps
    retrying the outbox write and the projection sync until both land -- no event or projection
    update is permanently lost to a crash between the note write and these two follow-up writes.
    ``event_emitted`` on the returned result reflects whether THIS call's outbox insert was the one
    that actually landed (``write_outbox_event``'s non-empty return) vs. a deduped retry.

    Guard placement (review-round-2 fix): the reconciliation branch below performs two real DB
    writes (outbox insert, projection UPDATE) even when the note rewrite itself is skipped, so it
    cannot rely on ``write_episode_note``'s own internal guard check as an implicit proxy gate
    (that only covered the whole function while every write path funneled through it). The guard
    is asserted explicitly on ONLY that branch -- not unconditionally at the top of the function --
    for two reasons: (1) the "unreadable note is always a silent no-op, never an error" contract
    above must hold regardless of write-health state (an unconditional top-of-function assert would
    turn a read-only diagnostic no-op into an uncaught ``WritesBlockedError``, and
    ``run_closure_tick``'s candidate loop has no per-candidate try/except, so that would abort every
    later candidate in the same tick too); (2) ``write_guard.assert_writes_allowed`` evaluates
    ``DEFAULT_CONTRACT`` (DB ping, outbox-tail read, object-store count, index diagnosis --
    genuinely not cheap), and the fresh-close branch already pays that cost once inside
    ``write_episode_note``'s own guard-at-seam check, so asserting it again unconditionally here
    would double per-closure health-evaluation cost across every quiesced episode a tick processes.
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
    already_closed = bool(time_fields.get("closed", False))

    if already_closed:
        # Nothing else on this branch funnels through write_episode_note, so nothing else would
        # ever assert the guard before the outbox/projection writes below -- assert it here,
        # exactly once, only for this branch (see the guard-placement note above). Uses this
        # module's OWN action string, not the vault-note seam's, since no note write happens here.
        write_guard.assert_writes_allowed(EPISODE_CLOSURE_RECONCILE_ACTION)
    else:
        # Guard-at-seam (mirrors ERE-02/05): write_episode_note asserts
        # write_guard.assert_writes_allowed(app.episodes.store.EPISODE_WRITE_ACTION) itself, before
        # any filesystem mutation. Re-write the SAME note (same episode_id -> same deterministic
        # path) with every other field preserved verbatim and only `closed` flipped -- a
        # proposal-class rewrite, never a new note, never a governed transition (no governance
        # import anywhere in this module).
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
    # Outbox BEFORE projection sync (deliberate ordering, #3181 review fix): the projection
    # UPDATE is what stops `find_closable_episodes` from re-offering this candidate, so it must be
    # the LAST write. A crash after the outbox insert but before the projection sync still leaves
    # this episode selectable on the next tick, which retries the (now-deduped) outbox write and
    # completes the projection sync -- the durable retry path outbox-first-then-gate requires.
    inserted_id = write_outbox_event(
        event,
        idempotency_key=idempotency_key,
        required_db=True,
    )
    _sync_projection_closed(candidate.episode_id)
    return EpisodeCloseResult(episode_id=candidate.episode_id, event_emitted=bool(inserted_id))


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
    "EPISODE_CLOSURE_RECONCILE_ACTION",
    "EpisodeClosureSchemaMissingError",
    "EpisodeCloseCandidate",
    "EpisodeCloseResult",
    "close_episode",
    "find_closable_episodes",
    "run_closure_tick",
]
