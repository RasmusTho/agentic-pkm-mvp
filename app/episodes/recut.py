"""Human re-cut detection, silence-is-acceptance, and binding reconciliation (ERE-07, #3182).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/RESPECT_HUMAN_RECUT.md``. ADR-0051 §5; ADR-0054 §4;
ADR-0055 (writer identity / optimistic writes).

Markdown-first re-cut: editing the Episode note IS the re-cut (dyslexia-friendly -- no forms, no
path-typing). This module is the production tick (:func:`run_recut_tick`, wired into
``python -m app.cli episodes tick``) that:

1. **Detects an operator edit** (AC1) and flips ``segmentation: re-cut`` -- WRITER-IDENTITY based,
   never a content heuristic. ``app.episodes.store.write_episode_note`` is the ONLY machine writer
   of episode notes (ERE-02's guarded seam; nothing else in this codebase writes an episode note's
   own frontmatter), and every call this module makes to it immediately records the resulting
   fields as this episode's tracked baseline (:func:`_record_baseline`, persisted via
   ``app.episodes.engine_state``). On each tick, a note's CURRENT on-disk fields are compared
   against that tracked baseline: identical -> nothing external touched it since the engine's own
   last write; different -> BY CONSTRUCTION some writer other than the engine touched the file
   (Obsidian, an external sync client, a human editing directly) -- writer identity resolved by
   elimination, never
   by asking "does this diff look like an intentional edit." A note the tracked baseline has never
   seen (no engine_state entry) is, by the same logic, entirely human-authored (e.g. a split
   sibling created by hand) -- adopted as a fresh baseline, not flagged as a "re-cut" of something
   the engine never wrote in the first place.
2. **Acceptance-by-silence** (AC5): a ``proposed`` episode whose tracked baseline has gone
   unchanged for :data:`ACCEPTANCE_QUIET_WINDOW_MINUTES` (the named, single-sourced quiet-window
   constant -- see its docstring) transitions to ``accepted``, with no notification and no
   approval-loop surface (#2475) -- exactly the same silent relabel mechanism AC1 uses, just
   triggered by elapsed time instead of a detected edit. The spec's secondary trigger ("first
   post-proposal human interaction elsewhere") is a documented, deliberately-deferred refinement
   (RQ-E1-style provisional note in the module docstring, not silently dropped): the time-based
   quiet window alone is the mechanism this module implements and AC5 verifies.
3. **Machine-terminality enforcement** (AC2) lives at the PRODUCTION write seam itself
   (``app.episodes.store.write_episode_note`` -- see that module's docstring), not here: this
   module's own relabel writes always echo the CURRENT on-disk cut fields back unchanged (only
   ``segmentation`` differs), so they pass that seam's terminality check trivially by
   construction, never by a bypass.
4. **New evidence never edits a re-cut/accepted episode** (AC3): guaranteed structurally by
   ERE-04's segmenter (a closed segment's open-segment state is deleted at emission, so any later
   signal for that scope starts a brand-new open segment with a brand-new deterministic
   ``episode_id`` -- ``app.episodes.segmenter._deterministic_episode_id`` never recomputes an
   existing id for genuinely new evidence) and backstopped by AC2's write-seam guard. This module
   adds no new evidence-folding logic; it only reconciles bindings and manages the lifecycle label.
5. **Binding reconciliation** (AC4): reuses ``app.episodes.assignment``'s ERE-05 correction path
   verbatim (:func:`app.episodes.assignment.reconcile_episode_bindings` /
   :func:`app.episodes.assignment.withdraw_episode_bindings`) -- never reimplemented.
6. **Split/merge consistency** (AC6): a split shows up here as two independent events this
   module already handles -- the original note's re-cut (narrowed bounds/``derived_from``,
   reconciled) and the new sibling note's first-sight adoption (reconciled, binding whatever its
   own ``derived_from`` supports). A merge shows up as a re-cut on the surviving (widened) note
   plus a DELETION of the other note, which this module detects by diffing the tracked-baseline id
   set against the on-disk id set and withdraws every one of the deleted episode's bindings
   (:func:`app.episodes.assignment.withdraw_episode_bindings`) -- so no artifact is ever left
   actively bound to an episode_id that no longer has a note.
7. **Projection sync** (#3182 mirror of #3181 review finding P1-1,
   ``app.episodes.closure._sync_projection_closed``): :func:`_write_relabeled` echoes the note's
   CURRENT on-disk fields straight back through ``write_episode_note`` (only ``segmentation`` is
   deliberately forced), so a re-cut relabel can carry an operator's edit to ANY note-sourced
   column -- ``title``/``scope``/bounds/``parent_episode``/the list fields -- not just the label.
   The ``episodes`` PROJECTION (ERE-02, ``app.jobs.episodes_projection``) is what
   ``app.episodes.assignment.read_candidate_episodes_for_scopes`` and
   ``app.episodes.closure.find_closable_episodes`` actually read; the only other writer,
   ``rebuild_episodes_projection``, is a full TRUNCATE+replay no production caller schedules. So
   :func:`_write_relabeled` issues its own targeted incremental ``UPDATE`` (:func:`_sync_projection_row`)
   for every note-sourced column right after each relabel write -- never partial, since a partial
   sync would leave exactly this bug class alive for whichever column it omitted.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Mapping

from app.db.db import conn_rw
from app.episodes import engine_state
from app.episodes.assignment import reconcile_episode_bindings, withdraw_episode_bindings
from app.episodes.notes import EPISODE_NOTES_DIR, parse_episode_note
from app.episodes.schema import EpisodeSchemaValidationError, validate_episode_note_fields
from app.episodes.store import cut_snapshot, write_episode_note
from app.jobs.episodes_projection import EPISODES_TABLE
from app.vault.manager import iter_vault_markdown_files
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

logger = logging.getLogger(__name__)

_EPISODES_SCHEMA_MIGRATION_HINT = (
    "episodes projection schema is migration-owned: run 'alembic upgrade head' against this "
    "database. See app/alembic/versions/e0f2a9c4b7d1_ere02_episodes_projection.py."
)


class EpisodeRecutSchemaMissingError(RuntimeError):
    """Raised when the ``episodes`` projection table is absent (pre-migration database)."""


def _assert_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (EPISODES_TABLE,))
        row = cur.fetchone()
    oid = (row.get("to_regclass") if isinstance(row, dict) else row[0]) if row else None
    if not oid:
        raise EpisodeRecutSchemaMissingError(
            f"Missing table '{EPISODES_TABLE}'. {_EPISODES_SCHEMA_MIGRATION_HINT}"
        )

# ---------------------------------------------------------------------------
# Named, single-sourced quiet-window constant (AC5; RQ-E1 open research, mirrors
# app.episodes.segmenter.TIME_GAP_MINUTES's provisional-constant discipline).
# ---------------------------------------------------------------------------

#: How long a `proposed` episode's tracked baseline must go unchanged before silence is
#: treated as acceptance (spec: "a declared quiet window"). 24h -- long enough that a normal
#: day's later vault activity/re-cut window has clearly passed, short enough that a proposal
#: does not linger indeterminately. Provisional (RQ-E1), documented in
#: `docs/EPISODE_RESOLUTION_ENGINE/README.md` :: Provisional thresholds -- this module is the
#: single source; nothing else literal-copies this value. The spec's secondary trigger ("first
#: post-proposal human interaction elsewhere passes without a re-cut") is a deliberately
#: deferred refinement, not implemented here -- see module docstring point 2.
ACCEPTANCE_QUIET_WINDOW_MINUTES: Final[int] = 1440
_QUIET_WINDOW: Final[timedelta] = timedelta(minutes=ACCEPTANCE_QUIET_WINDOW_MINUTES)

_RECUT_STATE_KEY_PREFIX: Final[str] = "episode_recut_state:"

SEGMENTATION_PROPOSED = "proposed"
SEGMENTATION_ACCEPTED = "accepted"
SEGMENTATION_RECUT = "re-cut"


def _state_key(episode_id: str) -> str:
    return f"{_RECUT_STATE_KEY_PREFIX}{episode_id}"


def _iso(value: datetime) -> str:
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_fields_hash(fields: Mapping[str, Any]) -> str:
    """Writer-identity fingerprint of an episode note: the hash of ONLY its CUT fields
    (:func:`app.episodes.store.cut_snapshot` -- title/time.start/time.end/space/protagonists/goal/
    causation/parent_episode/derived_from), the exact set store.py's terminality guard freezes.

    Round-1 review Finding 2 (CONFIRMED): the engine's own lifecycle writes -- an accept-by-silence
    or re-cut relabel (``segmentation``) and an ERE-06 closure flip (``time.closed``) -- are
    DELIBERATELY EXCLUDED. Were they hashed, a non-atomic write+``set_state`` (note written, baseline
    record fails) would leave the on-disk ``segmentation`` ahead of the tracked baseline, and the
    next tick would mis-read that engine-authored label change as a human re-cut and relabel
    ``accepted -> re-cut`` with no human involved. Hashing only the human-owned cut means an
    engine relabel never changes the fingerprint, so a missed baseline write can never manufacture a
    false re-cut. Canonicalized via ``sort_keys`` so key-order alone (a YAML round-trip artifact)
    never produces a false-positive divergence.
    """
    return hashlib.sha256(
        json.dumps(cut_snapshot(fields), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class _RecutState:
    """This module's own record of the last state it either wrote or observed for one
    episode_id -- the writer-identity baseline AC1 diffs against (see module docstring).

    ``content_hash`` is the CUT-only fingerprint (:func:`compute_fields_hash`). ``segmentation``
    is the lifecycle label as of that baseline; it is READ back by the self-heal in
    :func:`run_recut_tick` (round-1 review Finding 2/3): when the cut hash matches but this
    recorded label lags the on-disk one -- the signature of an engine lifecycle write whose
    ``set_state`` baseline record failed -- the baseline is refreshed to disk WITHOUT reporting a
    re-cut. ``first_seen_at`` is the acceptance-by-silence aging clock."""

    content_hash: str
    segmentation: str
    first_seen_at: datetime

    def to_state(self) -> dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "segmentation": self.segmentation,
            "first_seen_at": _iso(self.first_seen_at),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "_RecutState":
        return cls(
            content_hash=str(value["content_hash"]),
            segmentation=str(value["segmentation"]),
            first_seen_at=_parse_dt(value["first_seen_at"]),
        )


def _load_tracked_states() -> dict[str, _RecutState]:
    raw = engine_state.all_state_with_prefix(_RECUT_STATE_KEY_PREFIX)
    out: dict[str, _RecutState] = {}
    for key, value in raw.items():
        episode_id = key[len(_RECUT_STATE_KEY_PREFIX) :]
        out[episode_id] = _RecutState.from_state(value)
    return out


def _record_baseline(episode_id: str, fields: Mapping[str, Any], *, first_seen_at: datetime) -> None:
    state = _RecutState(
        content_hash=compute_fields_hash(fields),
        segmentation=str(fields.get("segmentation")),
        first_seen_at=first_seen_at,
    )
    engine_state.set_state(_state_key(episode_id), state.to_state())


def _forget_baseline(episode_id: str) -> None:
    engine_state.delete_state(_state_key(episode_id))


# ---------------------------------------------------------------------------
# Vault scan
# ---------------------------------------------------------------------------


def _episode_bounds(fields: Mapping[str, Any]) -> tuple[datetime, datetime | None]:
    """Parse a note's ``time.start`` / ``time.end`` into instants for binding reconciliation.
    A schema-valid episode note always carries ``time.start``; ``time.end`` may be absent (an
    open episode) -> ``None``, which reconciliation treats as "cannot bounds-check, preserve"."""
    time_fields = fields.get("time") or {}
    start = _parse_dt(time_fields["start"])
    end_raw = time_fields.get("end")
    end = _parse_dt(end_raw) if end_raw else None
    return start, end


def _scan_episode_notes(vault_root: Path) -> dict[str, dict[str, Any]]:
    """Every schema-valid episode note currently on disk, keyed by ``episode_id``. Mirrors
    ``app.jobs.episodes_projection._iter_episode_notes``'s orphan-skip discipline: a malformed
    note is skipped (logged), never crashes the tick."""
    subtree = vault_root / EPISODE_NOTES_DIR
    out: dict[str, dict[str, Any]] = {}
    for path in iter_vault_markdown_files(vault_root, subtree_root=subtree):
        try:
            text = path.read_text(encoding="utf-8")
            fields = parse_episode_note(text)
            validate_episode_note_fields(fields)
        except (OSError, EpisodeSchemaValidationError) as exc:
            logger.warning("recut: skipping unreadable/invalid episode note %s: %s", path, exc)
            continue
        episode_id = fields.get("episode_id")
        if not isinstance(episode_id, str) or not episode_id:
            continue
        out[episode_id] = fields
    return out


def _sync_projection_row(episode_id: str, fields: Mapping[str, Any]) -> None:
    """Incrementally sync the ``episodes`` projection row's note-sourced columns after a relabel
    write (#3182 review fix -- ``app.episodes.assignment.read_candidate_episodes_for_scopes`` and
    ``app.episodes.closure.find_closable_episodes`` read THIS table, and nothing else keeps it
    current: the only other writer, ``app.jobs.episodes_projection.rebuild_episodes_projection``,
    is a full TRUNCATE+replay no production caller invokes on any schedule). A targeted ``UPDATE``
    -- never a rebuild -- mirrors ``app.episodes.closure._sync_projection_closed``'s
    incremental-update-over-rebuild discipline for this same projection family.

    Unlike closure's single ``closed`` column, :func:`_write_relabeled` echoes the note's FULL
    on-disk cut back through ``write_episode_note`` (see module docstring point 7), so this syncs
    every note-sourced column -- ``episode_id`` (the key) and ``note_path`` (never changes for the
    same episode_id) are the only two omitted.

    Idempotent by construction (writing the same on-disk values twice is the same as once), so
    this is safe to call on every relabel, retried tick included. A zero-rowcount result (the
    projection has no row for this episode -- e.g. truncated by a concurrent
    ``rebuild_episodes_projection`` run) is logged, not raised: the vault note (SoR) already
    carries the correct fields regardless, and the next rebuild re-derives this row from it.
    """
    time_fields = fields.get("time") or {}
    with conn_rw() as conn:
        _assert_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {EPISODES_TABLE} SET
                    scope = %s, title = %s, time_start = %s, time_end = %s, closed = %s,
                    segmentation = %s, parent_episode = %s, space = %s::jsonb,
                    protagonists = %s::jsonb, goal = %s::jsonb, causation = %s::jsonb,
                    derived_from = %s::jsonb
                WHERE episode_id = %s
                """,
                (
                    fields.get("scope"),
                    fields.get("title"),
                    time_fields.get("start"),
                    time_fields.get("end"),
                    bool(time_fields.get("closed", False)),
                    fields.get("segmentation"),
                    fields.get("parent_episode"),
                    json.dumps(fields.get("space") or []),
                    json.dumps(fields.get("protagonists") or []),
                    json.dumps(fields.get("goal") or []),
                    json.dumps(fields.get("causation") or []),
                    json.dumps(fields.get("derived_from") or []),
                    episode_id,
                ),
            )
            rowcount = getattr(cur, "rowcount", None)
    if not rowcount:
        logger.warning(
            "recut: episodes projection has no row for %s -- relabeled cut will not be "
            "query-visible until the next rebuild_episodes_projection() run",
            episode_id,
        )


# ---------------------------------------------------------------------------
# Relabel writes -- always echo the CURRENT on-disk cut fields back unchanged, only
# `segmentation` differs, so app.episodes.store's terminality guard (AC2) passes trivially.
# ---------------------------------------------------------------------------


def _write_relabeled(
    episode_id: str,
    fields: Mapping[str, Any],
    *,
    segmentation: str,
    vault_root: Path,
    write_guard: WriteGuard,
) -> dict[str, Any]:
    time_fields = fields.get("time") or {}
    result = write_episode_note(
        title=fields["title"],
        scope=fields["scope"],
        start=time_fields["start"],
        closed=bool(time_fields.get("closed", False)),
        end=time_fields.get("end"),
        space=list(fields.get("space") or []),
        protagonists=list(fields.get("protagonists") or []),
        goal=list(fields.get("goal") or []),
        causation=list(fields.get("causation") or []),
        parent_episode=fields.get("parent_episode"),
        segmentation=segmentation,
        derived_from=list(fields.get("derived_from") or []),
        episode_id=episode_id,
        vault_root=vault_root,
        write_guard=write_guard,
    )
    # #3182 review fix (mirrors #3181 P1-1): keep the `episodes` projection current from the
    # write path itself -- see _sync_projection_row's docstring for why this must never be partial.
    _sync_projection_row(episode_id, result.fields)
    return result.fields


# ---------------------------------------------------------------------------
# Production tick entrypoint
# ---------------------------------------------------------------------------


def run_recut_tick(
    *,
    vault_root: Path | str,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    now: datetime | None = None,
) -> dict[str, Any]:
    """THE production entrypoint (wired into ``python -m app.cli episodes tick``).

    One deterministic pass: scans every episode note currently on disk, detects operator edits
    (AC1), applies acceptance-by-silence (AC5), reconciles bindings for anything that changed or
    is newly adopted (AC4), and withdraws bindings for any previously-tracked episode whose note
    has been deleted (AC6 merge-deletion side). Not a daemon, mirrors
    ``app.episodes.segmenter.run_segmentation_tick``'s scheduling posture.
    """
    root = Path(vault_root)
    moment = now if now is not None else datetime.now(timezone.utc)

    tracked = _load_tracked_states()
    on_disk = _scan_episode_notes(root)

    recut_detected: list[str] = []
    accepted: list[str] = []
    bindings_pending = 0
    bindings_corrected = 0

    # Merge-deletion side (AC6): a previously-tracked episode with no note on disk anymore.
    for missing_id in sorted(set(tracked) - set(on_disk)):
        result = withdraw_episode_bindings(missing_id, write_guard=write_guard, vault_root=root)
        bindings_corrected += result.get("corrected", 0)
        _forget_baseline(missing_id)
        logger.info("recut: episode %s note deleted -- withdrew its active bindings", missing_id)

    for episode_id, fields in on_disk.items():
        state = tracked.get(episode_id)
        segmentation = str(fields.get("segmentation"))

        def _reconcile(current_fields: Mapping[str, Any]) -> None:
            nonlocal bindings_pending, bindings_corrected
            start, end = _episode_bounds(current_fields)
            result = reconcile_episode_bindings(
                episode_id,
                scope=current_fields["scope"],
                start=start,
                end=end,
                derived_from=current_fields.get("derived_from") or [],
                write_guard=write_guard,
                vault_root=root,
            )
            bindings_pending += result.get("pending", 0)
            bindings_corrected += result.get("corrected", 0)

        if state is None:
            # First sight: either a note the engine itself just wrote earlier this same tick
            # invocation (no prior baseline recorded yet) or an entirely human-authored note
            # (e.g. a split sibling). No prior engine-recorded state exists to diff against, so
            # there is nothing to judge as a re-cut here -- adopt it as the new baseline (AC1
            # writer-identity: a note never seen before has no engine writer identity to
            # contradict; and an on-disk TERMINAL note with an absent baseline is likewise NOT a
            # re-cut -- the terminality guard already froze its cut, round-1 Finding 2 self-heal)
            # and reconcile whatever bindings its own derived_from + bounds support (AC4, also the
            # split/merge "re-bound to the sibling" case, AC6).
            _record_baseline(episode_id, fields, first_seen_at=moment)
            _reconcile(fields)
            continue

        current_hash = compute_fields_hash(fields)
        if current_hash != state.content_hash:
            # Writer-identity by elimination (AC1, see module docstring point 1): the engine is
            # the sole known machine writer of episode notes and always re-baselines on its own
            # successful writes, and the fingerprint covers ONLY the human-owned CUT (never the
            # engine's own segmentation/closed lifecycle writes, Finding 2) -- so a divergence is,
            # by construction, a human edit of the cut. Reported as detected regardless of whether
            # the segmentation LABEL itself still needs to change -- a further hand-edit of an
            # already-`re-cut` note (e.g. a merge widening bounds after an earlier split) is still
            # a real re-cut event worth reconciling bindings for, even though the label was already
            # terminal.
            recut_detected.append(episode_id)
            if segmentation != SEGMENTATION_RECUT:
                fields = _write_relabeled(
                    episode_id,
                    fields,
                    segmentation=SEGMENTATION_RECUT,
                    vault_root=root,
                    write_guard=write_guard,
                )
                logger.info("recut: operator edit detected for episode %s -- segmentation=re-cut", episode_id)
            else:
                logger.info(
                    "recut: further operator edit detected for already-re-cut episode %s", episode_id
                )
            _record_baseline(episode_id, fields, first_seen_at=moment)
            _reconcile(fields)
            continue

        # Cut unchanged since the engine's own last recorded write.
        if state.segmentation != segmentation:
            # Self-heal (round-1 review Finding 2/3): the tracked baseline's lifecycle label lags
            # the on-disk one while the CUT hash matches -- the exact signature of a non-atomic
            # engine lifecycle write (note written, then `set_state` failed), NOT a human re-cut.
            # Refresh the baseline to the on-disk truth without relabeling or reporting a re-cut,
            # preserving the acceptance-by-silence aging clock. This makes writer-identity
            # detection self-correcting: a missed baseline write can never manufacture a false
            # re-cut on a later tick.
            _record_baseline(episode_id, fields, first_seen_at=state.first_seen_at)
            logger.info(
                "recut: self-healed stale baseline label for episode %s (baseline=%s, on-disk=%s)",
                episode_id,
                state.segmentation,
                segmentation,
            )
            continue

        # Acceptance-by-silence (AC5) applies only to a still-`proposed` episode whose baseline
        # has aged past the quiet window.
        if segmentation == SEGMENTATION_PROPOSED and (moment - state.first_seen_at) >= _QUIET_WINDOW:
            new_fields = _write_relabeled(
                episode_id,
                fields,
                segmentation=SEGMENTATION_ACCEPTED,
                vault_root=root,
                write_guard=write_guard,
            )
            accepted.append(episode_id)
            _record_baseline(episode_id, new_fields, first_seen_at=state.first_seen_at)
            logger.info("recut: silence-is-acceptance for episode %s -- segmentation=accepted", episode_id)

    return {
        "recut_detected": recut_detected,
        "accepted": accepted,
        "bindings_pending": bindings_pending,
        "bindings_corrected": bindings_corrected,
    }


__all__ = [
    "ACCEPTANCE_QUIET_WINDOW_MINUTES",
    "EpisodeRecutSchemaMissingError",
    "SEGMENTATION_ACCEPTED",
    "SEGMENTATION_PROPOSED",
    "SEGMENTATION_RECUT",
    "compute_fields_hash",
    "run_recut_tick",
]
