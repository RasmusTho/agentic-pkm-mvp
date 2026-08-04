"""Heimdal time-spend projection: rebuildable markdown rollup over screen spans.

SCREEN-05 (#3345), specified by
`docs/HEIMDAL_SCREEN_STREAM/PROJECT_TIME_SPEND_ANALYSIS.md`. The third
downstream track from the screen stream: "analysis of what I spend my time
on". Screen span observations (SCREEN-02, `app.heimdal.screen_derivation`)
carry a real ``observed_at_start``/``observed_at_end`` window, the frontmost
app, entity mentions, and a scope tag -- everything needed to answer "where
did my time go?" without any manual tracking.

Design contract (issue Acceptance Criteria + MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT):

- **Derived, rebuildable, never authority.** The rollup is a disposable lens
  over the observation log. Every fold starts from event zero
  (:func:`app.heimdal.observation_log.read_observations_from` at sequence 0)
  -- there is deliberately NO consumer cursor and NO incremental state, so a
  "rebuild" and an "incremental update" are the same deterministic re-fold
  and can never drift apart. The rendered markdown carries no wall-clock
  timestamp and no counter that the observations themselves do not imply:
  same observations in, byte-identical projection out.
- **Per-span identity, not per-episode.** Spans fold by ``observation_id``
  (last revision wins by log ``sequence``; a winner named in another
  winner's ``supersedes``/``revision_of`` chain is dropped as corrected).
  This deliberately does NOT reuse the candidate projector's ``episode_id``
  fold (`app.heimdal.candidate_projection.fold_observations`): known defect
  ``KD-FBDBDAD4C052`` records that the episode fold collapses distinct
  spans sharing one ``episode_id``, under-reporting distinct activities.
  Reading the log directly with per-span identity is that defect's
  documented workaround, and the reason this module never goes through the
  candidate notes.
- **Idle/locked gaps are excluded by construction.** The capture client
  never samples idle/locked time (SCREEN-01), so gaps between spans simply
  do not appear in any span window. The rollup sums span durations; it never
  interpolates between spans. Per DERIVE_ACTIVITY_OBSERVATIONS.md, SCREEN-02
  ships no max-gap bound, so this module makes no bounded-gap assumption
  either -- a long coalesced span is summed exactly as published.
- **Governed write, derived class, never over a human note.** The weekly
  markdown note (``heimdal/time-spend/YYYY-Www.md``) is written through
  ``WriteGuard`` + ``app.knowledge.write_ops.write_note_relative`` with the
  derived posture (``requires_review: true``, ``source_authoritative:
  false``, ``ai_generated: true``). An existing note at the target path is
  overwritten ONLY when its frontmatter proves it is this module's own
  derived projection; anything else (a human note, a foreign artifact, an
  unparseable file) blocks the write loudly and leaves the file untouched.
  Both write paths are race-safe (#4609): replacing an existing owned
  projection is a compare-and-swap against the exact bytes the ownership
  check read (``expected_version``, VMW-01), so a human edit landing between
  check and write stages a conflict artifact and blocks instead of being
  overwritten; creating an absent target is atomic no-clobber
  (``create_candidate_note_once``), so a note created in that window
  likewise blocks the projection, never the human.
- **Observed labels are quarantined before materialization (HEIM-9).**
  Screen-derived bucket labels (frontmost app, scope, project entity surface
  forms) are observed content -- untrusted, potentially instruction-shaped.
  Before any label is interpolated into vault markdown it passes through
  A3's sole quarantine path (``app.heimdal.quarantine``): neutralized
  (homoglyph fold, zero-width strip, fence-breakout defang, sentinel strip)
  and then markdown-table-escaped (pipes, newlines) so it can neither read
  as a directive downstream nor corrupt the note's table structure. The raw
  text survives only as visible, inert evidence.
- **Stale weekly notes are cleared, not left lying (#4609 P2).** When a
  rebuild's fold no longer targets a week (its last span was superseded or
  revised into another week), an existing note at that week's path that
  provably IS this module's own projection is rewritten to the empty
  projection through the same guarded CAS path -- it must not keep reporting
  retracted time. Anything not provably ours (human notes, foreign
  artifacts, week-named or not) is never touched by the cleanup.

Attribution choices (deterministic, documented rather than configurable):

- A span's whole duration lands on the day/week of its ``observed_at_start``
  (spans are short coalesced windows; splitting across midnight would add
  complexity without changing the answer materially).
- The **project** axis reads entity mentions with ``kind_hint == "project"``;
  a span mentioning several projects contributes its full duration to each
  (a lens over attention, not a partition -- per-project sums may exceed
  wall clock and the note says so). Spans with no project mention land on
  ``(none)``.
- The **scope** axis prefers the span dimension ``scope`` and falls back to
  the payload ``scope_hint``.

Named seams (not built here, per the source doc steps 3-4): the companion-UI
lens is a later reader over these same notes/rollups, and the episode-level
rollup (time per meeting/build/trip) is a future enrichment keyed on
``episode_ref`` once ERE (SCREEN-04) lands -- this module ships fully from
observations alone and does not depend on ERE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from app.heimdal.observation_log import ObservationRow, read_observations_from
from app.heimdal.quarantine import quarantine_observed_content
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.write_ops import (
    create_candidate_note_once,
    read_note_text_with_version,
    write_note_relative,
)
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

#: The observation topic and modality this projection folds. Values mirror
#: `app.heimdal.screen_derivation` (OBSERVATION_TOPIC / modality="screen");
#: kept as local constants so the projection does not import the derivation
#: stage's local-vision runtime dependencies just to read the log.
SCREEN_OBSERVATION_TOPIC = "heimdal.observation.published"
SCREEN_MODALITY = "screen"

ARTIFACT_CLASS = "time_spend_projection"
PROJECTION_CONSUMER = "heimdal.time_spend"
DEFAULT_TIME_SPEND_DIR = "heimdal/time-spend"
TIME_SPEND_WRITE_ACTION = "heimdal.time_spend.write"

#: Bucket labels for spans missing an axis value. Parenthesized so they can
#: never collide with a real slug/app/scope surface form.
UNKNOWN_BUCKET = "(unknown)"
NO_PROJECT_BUCKET = "(none)"


class TimeSpendProjectionError(RuntimeError):
    """Raised when the time-spend projection cannot run at all."""


@dataclass(frozen=True)
class TimeSpendSpan:
    """One folded screen span, reduced to the rollup axes."""

    observation_id: str
    sequence: int
    app: str
    scope: str
    projects: Tuple[str, ...]
    day: str  # YYYY-MM-DD (UTC date of observed_at_start)
    week: str  # ISO week label, e.g. 2026-W28
    duration_seconds: float


@dataclass(frozen=True)
class TimeSpendRollup:
    """The deterministic fold result over one observation stream read."""

    spans: Tuple[TimeSpendSpan, ...]
    #: Screen-span log rows considered (including revisions that later folded
    #: away) -- the "rebuilt_from" provenance count.
    source_row_count: int

    def weeks(self) -> Tuple[str, ...]:
        return tuple(sorted({span.week for span in self.spans}))

    def spans_for_week(self, week: str) -> Tuple[TimeSpendSpan, ...]:
        return tuple(span for span in self.spans if span.week == week)


@dataclass(frozen=True)
class TimeSpendWriteResult:
    # "written" | "rebuilt" | "unchanged" | "blocked" | "no_observations" | "cleared"
    status: str
    week: str
    artifact_path: Optional[str]
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Folding: observation rows -> spans -> rollup
# ---------------------------------------------------------------------------


def _payload_of(row: ObservationRow) -> Mapping[str, Any]:
    payload = row.envelope.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _as_moment(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso_week_label(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _is_screen_span(row: ObservationRow, payload: Mapping[str, Any]) -> bool:
    if row.topic != SCREEN_OBSERVATION_TOPIC:
        return False
    return payload.get("modality") == SCREEN_MODALITY


def _span_dimensions(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    structure = payload.get("content_structure")
    if not isinstance(structure, Mapping):
        return {}
    span = structure.get("span")
    if not isinstance(span, Mapping):
        return {}
    dimensions = span.get("dimensions")
    return dimensions if isinstance(dimensions, Mapping) else {}


def _projects_of(payload: Mapping[str, Any]) -> Tuple[str, ...]:
    mentions = payload.get("entity_mentions")
    if not isinstance(mentions, Sequence) or isinstance(mentions, (str, bytes)):
        return (NO_PROJECT_BUCKET,)
    projects = {
        str(mention.get("surface_form")).strip()
        for mention in mentions
        if isinstance(mention, Mapping)
        and mention.get("kind_hint") == "project"
        and str(mention.get("surface_form") or "").strip()
    }
    if not projects:
        return (NO_PROJECT_BUCKET,)
    return tuple(sorted(projects))


def _build_span(row: ObservationRow, payload: Mapping[str, Any]) -> Optional[TimeSpendSpan]:
    start = _as_moment(payload.get("observed_at_start"))
    end = _as_moment(payload.get("observed_at_end"))
    if start is None or end is None:
        # The publisher (INV-SCREEN-B) refuses incomplete windows; a row
        # without one is not a span observation and cannot carry duration.
        return None
    duration = (end - start).total_seconds()
    if duration < 0:
        # Cannot be published by screen_derivation (backwards windows are
        # refused); fold defensively rather than corrupt the sums.
        return None
    dimensions = _span_dimensions(payload)
    app = str(dimensions.get("app") or "").strip() or UNKNOWN_BUCKET
    scope = (
        str(dimensions.get("scope") or "").strip()
        or str(payload.get("scope_hint") or "").strip()
        or UNKNOWN_BUCKET
    )
    observation_id = str(payload.get("observation_id") or "").strip() or row.id
    start_day = (start.astimezone(timezone.utc) if start.tzinfo else start).date()
    return TimeSpendSpan(
        observation_id=observation_id,
        sequence=row.sequence,
        app=app,
        scope=scope,
        projects=_projects_of(payload),
        day=start_day.isoformat(),
        week=_iso_week_label(start_day),
        duration_seconds=duration,
    )


def fold_time_spend(rows: Sequence[ObservationRow]) -> TimeSpendRollup:
    """Fold observation rows into the time-spend rollup, deterministically.

    Pure function of ``rows``: filters to screen spans, groups by
    ``observation_id`` (per-span identity -- see the module docstring on
    ``KD-FBDBDAD4C052``), lets the highest log ``sequence`` win within a
    group (a revision republish of the same evidence), then drops winners
    named in any other winner's ``supersedes``/``revision_of`` chain
    (corrections). Output order is fixed by log sequence, so every
    downstream sum runs in one deterministic order.
    """
    screen_rows: List[Tuple[ObservationRow, Mapping[str, Any]]] = []
    for row in rows:
        payload = _payload_of(row)
        if _is_screen_span(row, payload):
            screen_rows.append((row, payload))

    winners: Dict[str, Tuple[ObservationRow, Mapping[str, Any]]] = {}
    for row, payload in screen_rows:
        observation_id = str(payload.get("observation_id") or "").strip() or row.id
        current = winners.get(observation_id)
        if current is None or row.sequence > current[0].sequence:
            winners[observation_id] = (row, payload)

    corrected: set[str] = set()
    for row, payload in winners.values():
        for field_name in ("supersedes", "revision_of"):
            target = payload.get(field_name)
            if isinstance(target, str) and target.strip():
                corrected.add(target.strip())

    spans: List[TimeSpendSpan] = []
    for observation_id, (row, payload) in winners.items():
        if observation_id in corrected:
            continue
        span = _build_span(row, payload)
        if span is not None:
            spans.append(span)
    spans.sort(key=lambda span: span.sequence)

    return TimeSpendRollup(spans=tuple(spans), source_row_count=len(screen_rows))


# ---------------------------------------------------------------------------
# Aggregation + rendering
# ---------------------------------------------------------------------------


def _sum_by(spans: Sequence[TimeSpendSpan], axis: str) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for span in spans:
        if axis == "project":
            for project in span.projects:
                totals[project] = totals.get(project, 0.0) + span.duration_seconds
            continue
        key: str = getattr(span, axis)
        totals[key] = totals.get(key, 0.0) + span.duration_seconds
    return totals


def rollup_axes(
    spans: Sequence[TimeSpendSpan],
) -> Dict[str, Dict[str, float]]:
    """All five contract axes over the given spans (seconds per bucket)."""
    return {
        "by_app": _sum_by(spans, "app"),
        "by_project": _sum_by(spans, "project"),
        "by_scope": _sum_by(spans, "scope"),
        "by_day": _sum_by(spans, "day"),
        "by_week": _sum_by(spans, "week"),
    }


def format_duration(seconds: float) -> str:
    """Deterministic human duration: 6h12m / 5m / 5m30s / 45s / 0s."""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s" if secs else f"{minutes}m"
    return f"{secs}s"


def _sorted_buckets(totals: Mapping[str, float]) -> List[Tuple[str, float]]:
    # Largest first; name breaks ties so the ordering is total.
    return sorted(totals.items(), key=lambda item: (-item[1], item[0]))


def _quarantined_table_label(label: str) -> str:
    """Neutralize an observation-derived label and escape markdown table syntax.

    Bucket labels on the app/project/scope axes are screen-derived observed
    content -- untrusted by HEIM-9. Routing them through A3's sole quarantine
    path (``quarantine_observed_content``; the ``neutralized_text`` form is
    the one for structured renderers that supply their own framing) makes
    instruction-shaped text, fence breakouts, zero-width smuggling, and forged
    quarantine sentinels inert while keeping the text visible as evidence.
    On top of neutralization this escapes the *table* structure the renderer
    itself supplies: newlines/whitespace runs collapse to one space (a label
    can never start a new markdown block or row) and ``\\``/``|`` are escaped
    (a label can never terminate its cell). Pure function -- determinism of
    the rendered note (AC2) is preserved. Two distinct raw labels may collapse
    to one visible form; they still render as separate rows in deterministic
    order. A label that neutralizes to nothing renders as ``(unknown)``.
    """
    neutralized = quarantine_observed_content(label).neutralized_text
    collapsed = " ".join(neutralized.split())
    escaped = collapsed.replace("\\", "\\\\").replace("|", "\\|")
    return escaped or UNKNOWN_BUCKET


def _axis_table(title: str, totals: Mapping[str, float]) -> List[str]:
    lines = [f"## {title}", "", "| Bucket | Time |", "| --- | --- |"]
    for name, seconds in _sorted_buckets(totals):
        lines.append(f"| {_quarantined_table_label(name)} | {format_duration(seconds)} |")
    lines.append("")
    return lines


def time_spend_note_path(week: str, *, time_spend_dir: str = DEFAULT_TIME_SPEND_DIR) -> str:
    safe_dir = PurePosixPath(time_spend_dir.strip().strip("/"))
    if any(part in ("..", "") for part in safe_dir.parts):
        raise TimeSpendProjectionError(f"invalid time-spend directory: {time_spend_dir!r}")
    return (safe_dir / f"{week}.md").as_posix()


def render_time_spend_note(week: str, rollup: TimeSpendRollup) -> str:
    """Render one week's markdown projection note.

    Deterministic by construction: every value comes from the folded
    observations (no wall-clock stamp, no run counter), buckets sort by
    (duration desc, name asc), and days sort ascending -- same observations
    in, byte-identical note out (AC2).
    """
    spans = rollup.spans_for_week(week)
    axes = rollup_axes(spans)
    total_seconds = sum(span.duration_seconds for span in spans)

    frontmatter: Dict[str, Any] = {
        "artifact_class": ARTIFACT_CLASS,
        "lifecycle": "active",
        "work_relation": "learn",
        "projection": {
            "consumer": PROJECTION_CONSUMER,
            "week": week,
            "span_count": len(spans),
            "rebuilt_from": rollup.source_row_count,
            "source": "heimdal.observation.published (modality=screen)",
        },
        "authority": {
            "source_authoritative": False,
            "ai_generated": True,
            "requires_review": True,
        },
        "review_state": "draft",
        "rebuildable": True,
    }
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()

    lines: List[str] = [
        f"# Time spent -- {week}",
        "",
        f"Total observed screen time: **{format_duration(total_seconds)}** across "
        f"{len(spans)} span(s), folded from {rollup.source_row_count} observation row(s). "
        "Idle/locked time is excluded by construction (never sampled).",
        "",
    ]
    lines.extend(_axis_table("By app", axes["by_app"]))
    lines.extend(_axis_table("By project", axes["by_project"]))
    lines.extend(_axis_table("By scope", axes["by_scope"]))
    lines.extend(_axis_table("By day", dict(sorted(axes["by_day"].items()))))
    lines.extend(
        [
            "---",
            "",
            "_This note is a derived, rebuildable projection over the Heimdal screen "
            "observation stream -- a lens, never authority. It holds no state the "
            "observations do not; regenerate it any time with "
            f"`python -m app.cli heimdal time-spend --rebuild --week {week}`. "
            "A span mentioning several projects counts fully toward each, so "
            "per-project sums may exceed wall clock._",
        ]
    )
    body = "\n".join(lines)
    return f"---\n{yaml_block}\n---\n\n{body}\n"


# ---------------------------------------------------------------------------
# Governed write
# ---------------------------------------------------------------------------


def _vault_root(context: VaultContext) -> Path:
    if not context.is_selected or context.active_vault_path is None:
        raise TimeSpendProjectionError("time-spend projection requires a selected vault")
    root = Path(context.active_vault_path).expanduser().resolve()
    if not root.is_dir():
        raise TimeSpendProjectionError(
            "time-spend projection requires an existing vault directory"
        )
    return root


def _is_own_projection(text: str) -> bool:
    """Whether the existing note text is this module's own derived projection.

    Anything that does not positively prove the derived posture -- a human
    note, a foreign artifact class, a note claiming authority, an
    unparseable file -- is NOT ours and must never be overwritten. Takes the
    already-read text (not a path) so the caller can prove ownership, compare
    for changes, and compare-and-swap against ONE consistent byte snapshot --
    a re-read here would reopen the check/write race this closes (#4609).
    """
    if not text.startswith("---\n"):
        return False
    end = text.find("\n---", 4)
    if end < 0:
        return False
    try:
        frontmatter = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return False
    if not isinstance(frontmatter, Mapping):
        return False
    if frontmatter.get("artifact_class") != ARTIFACT_CLASS:
        return False
    authority = frontmatter.get("authority")
    return (
        isinstance(authority, Mapping)
        and authority.get("ai_generated") is True
        and authority.get("source_authoritative") is False
        and authority.get("requires_review") is True
    )


def write_time_spend_note(
    week: str,
    rollup: TimeSpendRollup,
    *,
    vault_context: VaultContext,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    time_spend_dir: str = DEFAULT_TIME_SPEND_DIR,
    replace_only: bool = False,
) -> TimeSpendWriteResult:
    """The governed vault-write call site for one week's projection note.

    ``WriteGuard``-gated at the write seam; a blocked write is a loud,
    item-scoped result, never a silent drop. Overwrites ONLY its own prior
    projection (rebuild = re-fold + rewrite, the note is disposable); any
    other occupant of the path blocks the write and is left untouched.

    Race-safe by construction (#4609): the ownership proof, the unchanged
    comparison, and the write expectation all come from ONE byte snapshot,
    and the replacement is a compare-and-swap against exactly those bytes
    (``expected_version``) -- a human edit landing after the snapshot makes
    the write refuse (the racing bytes stay canonical; the projection's
    proposal is staged as a conflict artifact by the VMW-01 port). An absent
    target is created atomically no-clobber, so a note created in the
    check/write window equally blocks the projection, never the human.

    ``replace_only=True`` (the stale-week cleanup caller) additionally
    refuses to CREATE: an absent target returns ``no_observations`` instead
    of materializing a note -- cleanup may only rewrite something that
    already exists, never conjure a file a human just deleted.
    """
    vault_root = _vault_root(vault_context)
    artifact_path = time_spend_note_path(week, time_spend_dir=time_spend_dir)
    note_path = vault_root / artifact_path

    content = render_time_spend_note(week, rollup)

    if note_path.exists() or note_path.is_symlink():
        try:
            existing_text, expected_version = read_note_text_with_version(note_path)
        except (OSError, UnicodeDecodeError):
            # An occupant we cannot even read is not provably ours: hands off.
            return TimeSpendWriteResult(
                status="blocked",
                week=week,
                artifact_path=None,
                reason=(
                    f"path is occupied by an unreadable file; refusing to "
                    f"overwrite: {artifact_path}"
                ),
            )
        if not _is_own_projection(existing_text):
            return TimeSpendWriteResult(
                status="blocked",
                week=week,
                artifact_path=None,
                reason=(
                    f"path is occupied by a note that is not a {ARTIFACT_CLASS} "
                    f"projection; refusing to overwrite: {artifact_path}"
                ),
            )
        if existing_text == content:
            return TimeSpendWriteResult(
                status="unchanged", week=week, artifact_path=artifact_path
            )
        try:
            write_note_relative(
                artifact_path,
                content,
                vault_root=vault_root,
                action=TIME_SPEND_WRITE_ACTION,
                write_guard=write_guard,
                expected_version=expected_version,
                writer_identity=PROJECTION_CONSUMER,
            )
        except WritesBlockedError as exc:
            return TimeSpendWriteResult(
                status="blocked", week=week, artifact_path=None, reason=str(exc)
            )
        except KnowledgeWriteConflict as exc:
            return TimeSpendWriteResult(
                status="blocked",
                week=week,
                artifact_path=None,
                reason=(
                    f"target changed concurrently; refusing to overwrite: "
                    f"{artifact_path} ({exc})"
                ),
            )
        return TimeSpendWriteResult(status="rebuilt", week=week, artifact_path=artifact_path)

    if replace_only:
        return TimeSpendWriteResult(
            status="no_observations", week=week, artifact_path=None
        )

    try:
        outcome = create_candidate_note_once(
            artifact_path,
            content,
            vault_root=vault_root,
            action=TIME_SPEND_WRITE_ACTION,
            write_guard=write_guard,
        )
    except WritesBlockedError as exc:
        return TimeSpendWriteResult(
            status="blocked", week=week, artifact_path=None, reason=str(exc)
        )
    except (OSError, ValueError) as exc:
        # E.g. a non-regular file (directory, symlink, FIFO) won the create
        # race, or the target name failed the primitive's path validation.
        # Same posture as the rewrite branch: a loud, item-scoped 'blocked'
        # result, never an exception that destroys the sibling weeks' receipt.
        return TimeSpendWriteResult(
            status="blocked",
            week=week,
            artifact_path=None,
            reason=(
                f"could not create projection note atomically; refusing: "
                f"{artifact_path} ({exc})"
            ),
        )
    if outcome == "already_exists":
        return TimeSpendWriteResult(
            status="blocked",
            week=week,
            artifact_path=None,
            reason=(
                f"target was created concurrently; refusing to clobber: "
                f"{artifact_path}"
            ),
        )
    return TimeSpendWriteResult(status="written", week=week, artifact_path=artifact_path)


#: Filename stem shape of a weekly projection note (ISO week label). Only
#: files with this stem are ever *candidates* for stale-week cleanup; the
#: ownership proof in :func:`_clear_stale_week_note` remains the actual gate.
_WEEK_STEM_RE = re.compile(r"^\d{4}-W\d{2}$")


def _clear_stale_week_note(
    week: str,
    rollup: TimeSpendRollup,
    *,
    vault_context: VaultContext,
    write_guard: WriteGuard,
    time_spend_dir: str,
) -> Optional[TimeSpendWriteResult]:
    """Clear one owned weekly note the current fold no longer targets (#4609 P2).

    Returns ``None`` when there is nothing owned to clear -- the target is
    absent, unreadable, or not provably this module's own projection (a human
    note is NEVER touched, deleted, or reported on by cleanup). Otherwise the
    note is rewritten to the week's empty projection (span_count 0, all
    tables empty) through :func:`write_time_spend_note` in ``replace_only``
    mode, i.e. through the same ownership re-proof + compare-and-swap guards
    as any other rewrite, and with creation refused -- a note a human deletes
    between this check and the rewrite stays deleted (``None``), it is not
    conjured back as an empty projection. An "emptied" note stays a legible,
    regenerable projection artifact; this module deliberately has no delete
    primitive.
    """
    vault_root = _vault_root(vault_context)
    note_path = vault_root / time_spend_note_path(week, time_spend_dir=time_spend_dir)
    if not (note_path.exists() or note_path.is_symlink()):
        return None
    try:
        existing_text, _version = read_note_text_with_version(note_path)
    except (OSError, UnicodeDecodeError):
        return None
    if not _is_own_projection(existing_text):
        return None
    result = write_time_spend_note(
        week,
        rollup,
        vault_context=vault_context,
        write_guard=write_guard,
        time_spend_dir=time_spend_dir,
        replace_only=True,
    )
    if result.status == "no_observations":
        # The owned note vanished between the ownership proof and the
        # rewrite: there is nothing left to clear, and cleanup never creates.
        return None
    if result.status == "rebuilt":
        return replace(result, status="cleared")
    return result


def _stale_week_candidates(
    vault_root: Path,
    *,
    time_spend_dir: str,
    active_weeks: set[str],
) -> Tuple[str, ...]:
    """Week labels with an existing note file that the current fold skips.

    Purely a filename scan (deterministic, sorted): every ``<dir>/<week>.md``
    whose stem is week-shaped and not in ``active_weeks``. Ownership is NOT
    decided here -- :func:`_clear_stale_week_note` proves it per file, so a
    human note named like a week is listed as a candidate but never touched.
    """
    safe_dir = PurePosixPath(time_spend_dir.strip().strip("/"))
    dir_path = vault_root / safe_dir
    if not dir_path.is_dir():
        return ()
    stems = []
    for entry in sorted(dir_path.glob("*.md")):
        stem = entry.name[: -len(".md")]
        if _WEEK_STEM_RE.match(stem) and stem not in active_weeks:
            stems.append(stem)
    return tuple(stems)


# ---------------------------------------------------------------------------
# Entrypoints: fold-from-zero rebuild
# ---------------------------------------------------------------------------


def build_time_spend_rollup() -> TimeSpendRollup:
    """Fold the full observation stream from event zero.

    No cursor, no cache: the projection is stateless by design so a rebuild
    can never disagree with an incremental update (they are the same fold).
    """
    return fold_time_spend(read_observations_from(0))


def rebuild_time_spend(
    *,
    vault_context: VaultContext,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    week: Optional[str] = None,
    time_spend_dir: str = DEFAULT_TIME_SPEND_DIR,
) -> Dict[str, Any]:
    """Re-fold the observation stream and (re)write the weekly markdown notes.

    The production rebuild entrypoint (`heimdal time-spend --rebuild`).
    Writes one note per ISO week present in the folded spans, or only
    ``week`` when given. Returns a receipt mapping each targeted week to its
    write status; a week with no observations reports ``no_observations``
    and writes nothing NEW -- but a week that still has an existing note
    provably owned by this module is *cleared* to the empty projection
    (status ``cleared``; #4609 P2), so a note whose spans were revised into
    another week cannot keep reporting retracted time. A full rebuild
    (``week=None``) additionally scans the projection directory for owned
    week notes the fold no longer targets and clears those the same way.
    Cleanup never touches, deletes, or reports on notes that are not
    provably this module's own projection.
    """
    rollup = build_time_spend_rollup()
    active_weeks = set(rollup.weeks())
    targets = [week] if week is not None else sorted(active_weeks)

    results: Dict[str, TimeSpendWriteResult] = {}
    for target in targets:
        if not rollup.spans_for_week(target):
            cleared = _clear_stale_week_note(
                target,
                rollup,
                vault_context=vault_context,
                write_guard=write_guard,
                time_spend_dir=time_spend_dir,
            )
            results[target] = cleared or TimeSpendWriteResult(
                status="no_observations", week=target, artifact_path=None
            )
            continue
        results[target] = write_time_spend_note(
            target,
            rollup,
            vault_context=vault_context,
            write_guard=write_guard,
            time_spend_dir=time_spend_dir,
        )

    if week is None:
        for stale in _stale_week_candidates(
            _vault_root(vault_context),
            time_spend_dir=time_spend_dir,
            active_weeks=active_weeks,
        ):
            if stale in results:
                continue
            cleared = _clear_stale_week_note(
                stale,
                rollup,
                vault_context=vault_context,
                write_guard=write_guard,
                time_spend_dir=time_spend_dir,
            )
            if cleared is not None:
                results[stale] = cleared

    return {
        "rebuilt_from": rollup.source_row_count,
        "span_count": len(rollup.spans),
        "weeks": {
            target: {
                "status": result.status,
                "artifact_path": result.artifact_path,
                "reason": result.reason,
            }
            for target, result in results.items()
        },
    }


def time_spend_summary(week: Optional[str] = None) -> Dict[str, Any]:
    """Read-only JSON summary of the rollup (the ``--json`` CLI surface)."""
    rollup = build_time_spend_rollup()
    spans: Sequence[TimeSpendSpan]
    if week is not None:
        spans = rollup.spans_for_week(week)
    else:
        spans = rollup.spans
    axes = rollup_axes(spans)
    formatted = {
        axis: {
            name: format_duration(seconds)
            for name, seconds in _sorted_buckets(totals)
        }
        for axis, totals in axes.items()
    }
    return {
        "week": week,
        "span_count": len(spans),
        "rebuilt_from": rollup.source_row_count,
        **formatted,
    }


__all__ = [
    "ARTIFACT_CLASS",
    "DEFAULT_TIME_SPEND_DIR",
    "NO_PROJECT_BUCKET",
    "PROJECTION_CONSUMER",
    "SCREEN_MODALITY",
    "SCREEN_OBSERVATION_TOPIC",
    "TIME_SPEND_WRITE_ACTION",
    "TimeSpendProjectionError",
    "TimeSpendRollup",
    "TimeSpendSpan",
    "TimeSpendWriteResult",
    "UNKNOWN_BUCKET",
    "build_time_spend_rollup",
    "fold_time_spend",
    "format_duration",
    "rebuild_time_spend",
    "render_time_spend_note",
    "rollup_axes",
    "time_spend_note_path",
    "time_spend_summary",
    "write_time_spend_note",
]
