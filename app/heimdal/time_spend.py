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

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from app.heimdal.observation_log import ObservationRow, read_observations_from
from app.knowledge.write_ops import write_note_relative
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
    status: str  # "written" | "rebuilt" | "unchanged" | "blocked" | "no_observations"
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


def _axis_table(title: str, totals: Mapping[str, float]) -> List[str]:
    lines = [f"## {title}", "", "| Bucket | Time |", "| --- | --- |"]
    for name, seconds in _sorted_buckets(totals):
        lines.append(f"| {name} | {format_duration(seconds)} |")
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


def _is_own_projection(path: Path) -> bool:
    """Whether the existing file is this module's own derived projection.

    Anything that does not positively prove the derived posture -- a human
    note, a foreign artifact class, a note claiming authority, an
    unparseable file -- is NOT ours and must never be overwritten.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
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
) -> TimeSpendWriteResult:
    """The governed vault-write call site for one week's projection note.

    ``WriteGuard``-gated immediately before the write; a blocked write is a
    loud, item-scoped result, never a silent drop. Overwrites ONLY its own
    prior projection (rebuild = re-fold + rewrite, the note is disposable);
    any other occupant of the path blocks the write and is left untouched.
    """
    vault_root = _vault_root(vault_context)
    artifact_path = time_spend_note_path(week, time_spend_dir=time_spend_dir)
    note_path = vault_root / artifact_path

    content = render_time_spend_note(week, rollup)

    if note_path.exists() or note_path.is_symlink():
        if not _is_own_projection(note_path):
            return TimeSpendWriteResult(
                status="blocked",
                week=week,
                artifact_path=None,
                reason=(
                    f"path is occupied by a note that is not a {ARTIFACT_CLASS} "
                    f"projection; refusing to overwrite: {artifact_path}"
                ),
            )
        try:
            if note_path.read_text(encoding="utf-8") == content:
                return TimeSpendWriteResult(
                    status="unchanged", week=week, artifact_path=artifact_path
                )
        except OSError:
            pass
        status = "rebuilt"
    else:
        status = "written"

    try:
        write_guard.assert_writes_allowed(TIME_SPEND_WRITE_ACTION)
    except WritesBlockedError as exc:
        return TimeSpendWriteResult(
            status="blocked", week=week, artifact_path=None, reason=str(exc)
        )

    write_note_relative(
        artifact_path,
        content,
        vault_root=vault_root,
        action=TIME_SPEND_WRITE_ACTION,
        write_guard=write_guard,
    )
    return TimeSpendWriteResult(status=status, week=week, artifact_path=artifact_path)


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
    and writes nothing.
    """
    rollup = build_time_spend_rollup()
    targets = [week] if week is not None else list(rollup.weeks())

    results: Dict[str, TimeSpendWriteResult] = {}
    for target in targets:
        if not rollup.spans_for_week(target):
            results[target] = TimeSpendWriteResult(
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
