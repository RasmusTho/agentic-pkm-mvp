"""Episode-ref assignment: stamp pending bindings on in-bounds artifacts (ERE-05, #3180).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/ASSIGN_EPISODE_REF_TO_ARTIFACTS.md``. ADR-0054 ground 1;
``docs/architecture/semantic-dimensions.md`` :: ``episode_ref``.

This is the knowledge-layer write that forced the Mimer placement: for every artifact that
originated within a proposed episode's bounds, upgrade its ``episode_ref`` from ``unbound`` to a
real (provisional) episode-id binding. Two write classes never blur (mirrors ERE-02's
``app/episodes/store.py`` two-class rule -- health-gate asserted, no human confirm, proposal
class, no governance import anywhere in this module):

- The assignment rule itself (:func:`compute_assignments`) is a PURE function over normalized
  ``ArtifactCandidate``/``EpisodeBoundsRecord`` inputs -- no I/O, fully unit-testable and
  deterministic.
- The commit path (:func:`commit_assignment_diff`) asserts ``WriteGuard.assert_writes_allowed``
  *inside the seam itself*, before any DB mutation (guard-at-seam, #2910/#2953 precedent), and
  persists to the ``episode_artifact_binding`` ledger (migration ``b7c8d9e0f1a2``) -- the audit
  PROVENANCE record (which episode, which rule, basis, confidence, when). A blocked guard means
  zero rows touched.

Bundle mutation (review-round-2 fix, Finding 1 -- the ledger alone left retrieval returning
``unbound`` forever): the ledger row is NOT the artifact's own bundle. The artifact's own bundle
lives in two places, and BOTH are upgraded, when resolvable:

- **Vault-serialized bundle** (spec point 3; the ERE-03 CANONICAL source): for a
  ``vault.activity``-sourced artifact, the underlying note's OWN frontmatter ``episode_ref`` field
  is stamped through the SAME guarded write seam ERE-02 uses
  (``app.knowledge.write_ops.write_note_from_absolute``, ADR-0055 multi-writer rules) -- health-gate
  asserted, no human confirm, proposal class. This is stamped FIRST (see the ordering note on
  :func:`commit_assignment_diff`), because it is the durable source of truth: the vault ingest
  pipeline (``app/ingest/vault_alpha.py``) now reprojects ``episode_ref`` from this frontmatter on
  every reingest, so a later body edit / cold rebuild re-derives the binding instead of dropping it
  (round-2 Finding 1 -- invariant->producers: every bundle producer carries the field).
- **DB-side bundle rows** (the reingest-stable PROJECTION): ``store_objects``/``store_vector_index``
  (``app/stores/pg.py``, KERNEL-04) each carry a ``payload`` JSONB column; retrieval
  (``app/retrieval/envelope.py`` via ``app/retrieval/hybrid.py::_load_all_docs`` ->
  ``get_vector_index().all_rows()``) reads ``payload['episode_ref']`` off ``store_vector_index``
  specifically. Both rows are updated in ONE transaction with the ledger write, via a targeted
  ``jsonb_set`` on the ``episode_ref`` key ONLY (round-2 Finding 3 -- never a read-modify-write of
  the whole ``payload`` column, so a concurrent writer's change to ``evidence_role``/
  ``authority_state``/``scope_binding``/any other key is never clobbered). The union-not-overwrite
  merge means a multi-episode (nested) artifact accumulates every binding across ticks (spec point
  1's "zero or more").

Resolution (:func:`_resolve_bundle_object_id_and_note_path`, ``app.episodes.vault_activity_stream
.resolve_bundle_target_for_outbox_row_id``): an ``artifact_ref`` is the SAME provenance-ref shape
segmentation signals carry (`heimdal.observations:<observation_id>` / `vault.activity:<outbox_row_
id>`). A ``vault.activity:<id>`` ref resolves back to the outbox event that earned it (outbox rows
are never purged) and from there to the object's ``uuid`` (the ``store_objects``/
``store_vector_index`` primary key) plus the note's own path. A ``heimdal.observations:<id>`` ref
does NOT resolve to a bundle today: raw Heimdal observations are never themselves indexed into
``store_objects``/``store_vector_index`` (HEIM-2 -- Heimdal is forbidden to do assignment, and this
codebase has no "Heimdal observation's downstream candidate" bundle-minting path yet; that is
future work, not invented here). For those refs this function still records the ledger row
(unchanged provenance-tracking behavior) but bundle mutation is a documented no-op, never a
fabricated write. ``vault_root=None`` (the default) skips bundle mutation entirely -- callers that
only care about the ledger (most of this module's own unit tests) keep working unchanged; the
production entrypoint (``app.episodes.segmenter.run_segmentation_tick``) always passes the real
vault root.

Fail-loud schema preflight (invariant -> producers rule, mirroring
``app.episodes.engine_state._assert_schema`` / ``EngineStateSchemaMissingError``): every function
that queries ``episodes`` or ``episode_artifact_binding`` asserts the table exists first, raising
:class:`EpisodeAssignmentSchemaMissingError` with a migration hint instead of a raw
``UndefinedTable`` traceback from inside a query.

Confidence floor (HEIM-6-honest, issue Scope): a ``derived_from``-anchored artifact (its signal's
``provenance_ref`` appears in the episode's own ``derived_from``) is binding-strength
(:data:`BASIS_PROVENANCE`, confidence 1.0) -- the segment was literally built FROM this signal.
A bounds-only (time-overlap) match is proposed-only (:data:`BASIS_TIME_OVERLAP`, confidence 0.5)
-- never a confident claim from a weak correlation. The ERE-01 signal contract's real per-axis
``ConfidenceScore`` block (``app.episodes.stream_registry.SignalContract``) is not threaded through
``app.episodes.segmenter.SegmentationSignal`` today (that dataclass is deliberately a lighter,
segmentation-internal content carrier, not the full ERE-01 contract) -- fabricating finer-grained
precision here than the upstream signal actually carries would itself violate HEIM-6 honesty, so
this module's confidence is the qualitative basis floor, not a borrowed per-axis score. Threading
real per-axis confidence through is a documented follow-up, not silently invented here.

Scope discipline (deny-by-default, ERE-08 pins the full posture): an artifact and an episode bind
only when they share the same ``scope`` -- this module never proposes or persists a cross-scope
binding, provenance-anchored or not.

Multi-ref (spec point 1): :func:`compute_assignments` evaluates every candidate episode
independently per artifact, so nested/overlapping episodes naturally yield multiple
``AssignmentDecision`` rows for one ``artifact_ref`` -- the doctrine's "zero or more".

Idempotency + correction (spec points 4-5): :func:`diff_assignments` is a PURE diff between the
newly computed decisions and the ledger's existing rows for the same artifacts. A decision already
recorded ``active`` with the same basis is a no-op (re-ticks never duplicate); a previously
``active`` binding no longer supported by the current decision set is corrected (``binding_state``
-> ``corrected``, ``corrected_at`` stamped) rather than deleted -- corrections carry provenance,
never silent, and the ledger row remains inspectable history.

``episode_ref`` itself never upgrades ``evidence_role``/``authority_state``/``scope_binding``
(semantic-dimensions.md :: episode_ref) -- this module has no path to any of those fields and does
not touch them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.db.db import conn_rw
from app.jobs.episodes_projection import EPISODES_TABLE
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

logger = logging.getLogger(__name__)

#: A cross-scope flow provider resolves the explicit typed ``CrossScopeFlow`` (a plain mapping, the
#: shape ``mimer_runtime.cross_scope.evaluate`` reads) for a directional crossing, or ``None`` when
#: none grants it. Production passes no provider (authoring flow grants is out of scope), so every
#: cross-scope binding is denied (ERE-08 AC4). Mirrors ``cross_scope_fusion.FlowProvider``.
CrossScopeFlowProvider = Callable[[str, str], "Mapping[str, Any] | None"]

# Distinct action string for the assignment write seam (mirrors
# app.episodes.store.EPISODE_WRITE_ACTION's per-seam-action pattern), asserted inside
# commit_assignment_diff itself -- not a caller-side helper (AC4: enforcement at the production
# seam).
EPISODE_ASSIGNMENT_WRITE_ACTION = "episodes.assign_episode_ref"

#: Single-sourced assignment-rule identifier, stamped into every ledger row's ``rule`` column so a
#: future rule revision is distinguishable from this one in the audit trail.
ASSIGNMENT_RULE: str = "ere05-bounds-and-provenance-v1"

BASIS_PROVENANCE = "provenance"
BASIS_TIME_OVERLAP = "time_overlap"
_VALID_BASES = (BASIS_PROVENANCE, BASIS_TIME_OVERLAP)

#: HEIM-6-honest confidence floor (see module docstring): provenance-anchored is binding-strength;
#: time-overlap-only is proposed-only. Named constants, never a magic number at a call site.
PROVENANCE_CONFIDENCE: float = 1.0
TIME_OVERLAP_CONFIDENCE: float = 0.5

BINDING_STATE_ACTIVE = "active"
BINDING_STATE_CORRECTED = "corrected"

BINDING_TABLE = "episode_artifact_binding"

_SCHEMA_MIGRATION_HINTS: dict[str, str] = {
    BINDING_TABLE: (
        "episode_artifact_binding schema is migration-owned: run 'alembic upgrade head' against "
        "this database. See app/alembic/versions/b7c8d9e0f1a2_ere05_episode_artifact_binding.py."
    ),
    EPISODES_TABLE: (
        "episodes schema is migration-owned: run 'alembic upgrade head' against this database. "
        "See app/jobs/episodes_projection.py."
    ),
}


class EpisodeAssignmentError(RuntimeError):
    """Raised for malformed assignment inputs."""


class EpisodeAssignmentSchemaMissingError(RuntimeError):
    """Raised when ``episodes`` or ``episode_artifact_binding`` is absent (pre-migration
    database) -- fail-loud schema preflight (invariant -> producers rule, mirrors
    ``app.episodes.engine_state.EngineStateSchemaMissingError`` / ``_assert_schema``), asserted
    before any query touches either table so a pre-migration database raises an actionable,
    migration-hinting error instead of a raw ``UndefinedTable`` traceback from inside a query."""


def _assert_table_schema(conn: Any, table: str) -> None:
    """Fail-loud preflight: ``table`` must exist before any query touches it."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table,))
        row = cur.fetchone()
    oid = (row.get("to_regclass") if isinstance(row, dict) else row[0]) if row else None
    if not oid:
        hint = _SCHEMA_MIGRATION_HINTS.get(table, f"Run 'alembic upgrade head' for '{table}'.")
        raise EpisodeAssignmentSchemaMissingError(f"Missing table '{table}'. {hint}")


# ---------------------------------------------------------------------------
# Pure data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactCandidate:
    """One in-flight artifact signal, normalized for the assignment rule.

    ``artifact_ref`` reuses the exact ``provenance_ref`` shape segmentation signals already carry
    (``heimdal.observations:<id>`` / ``vault.activity:<id>``) -- the same identity a closed
    segment's own ``derived_from`` records, so a provenance-anchored match is a literal membership
    check, never a fuzzy join.
    """

    artifact_ref: str
    scope: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.artifact_ref:
            raise EpisodeAssignmentError("ArtifactCandidate.artifact_ref must be non-empty")
        if not self.scope:
            raise EpisodeAssignmentError("ArtifactCandidate.scope must be non-empty")


@dataclass(frozen=True)
class EpisodeBoundsRecord:
    """One candidate episode's bounds + provenance, normalized for the assignment rule.

    Sourced either from THIS tick's freshly closed segments (in-memory, not yet reflected in the
    ``episodes`` PG projection) or from that projection directly (already-persisted episodes from
    a prior tick -- the source late-arriving artifacts bind against, AC7)."""

    episode_id: str
    scope: str
    start: datetime
    end: datetime | None
    derived_from: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise EpisodeAssignmentError("EpisodeBoundsRecord.episode_id must be non-empty")
        if not self.scope:
            raise EpisodeAssignmentError("EpisodeBoundsRecord.scope must be non-empty")


@dataclass(frozen=True)
class AssignmentDecision:
    """One (artifact, episode) binding the assignment rule computed."""

    artifact_ref: str
    episode_id: str
    scope: str
    basis: str
    confidence: float

    def __post_init__(self) -> None:
        if self.basis not in _VALID_BASES:
            raise EpisodeAssignmentError(
                f"AssignmentDecision.basis must be one of {_VALID_BASES}, got {self.basis!r}"
            )


# ---------------------------------------------------------------------------
# Pure assignment rule (AC1/AC2/AC3)
# ---------------------------------------------------------------------------


def _cross_scope_binding_allowed(
    artifact_scope: str,
    episode_scope: str,
    flow_provider: "CrossScopeFlowProvider | None",
) -> bool:
    """ERE-08 (#3183) assignment seam gate: may an artifact in ``artifact_scope`` bind to an episode
    in ``episode_scope``? Deny-by-default -- routed through ``mimer_runtime.cross_scope.evaluate``
    (via :func:`app.episodes.cross_scope_fusion.evaluate_episode_fuse`, the single ``episode_fuse``
    operation, no new authority model). Binding an artifact into a different-scope episode admits it
    into that episode's cross-scope situation, so the crossing is source=``artifact_scope`` ->
    target=``episode_scope``. Absence of an explicit flow denies ("similarity is not permission").

    Production passes NO ``flow_provider`` (authoring flow grants is out of scope), so a cross-scope
    binding is ALWAYS denied -- assignment never crosses scopes unflowed (AC4). Imported lazily to
    keep this pure module free of an import-time ``mimer_runtime`` dependency."""
    from app.episodes.cross_scope_fusion import evaluate_episode_fuse

    flow = flow_provider(artifact_scope, episode_scope) if flow_provider else None
    return bool(evaluate_episode_fuse(artifact_scope, episode_scope, flow=flow).allowed)


def compute_assignments(
    artifacts: Sequence[ArtifactCandidate],
    episodes: Sequence[EpisodeBoundsRecord],
    *,
    flow_provider: "CrossScopeFlowProvider | None" = None,
) -> list[AssignmentDecision]:
    """The pure assignment rule: which artifacts bind to which episodes, and on what basis.

    For every (artifact, episode) pair sharing the SAME ``scope`` (and, for a DIFFERENT-scope pair,
    only when an explicit ``CrossScopeFlow`` admits it via :func:`_cross_scope_binding_allowed` --
    deny-by-default, ERE-08's posture enforced here through ``mimer_runtime.cross_scope.evaluate``;
    production passes no ``flow_provider`` so a cross-scope binding is always denied, AC4):

    - provenance-anchored (AC2): ``artifact.artifact_ref in episode.derived_from`` -> binds at
      :data:`BASIS_PROVENANCE`, even when the artifact's ``observed_at`` sits outside
      ``[episode.start, episode.end]`` (an imperfect time overlap never overrides a real
      provenance anchor -- the segment was literally built from this signal).
    - time-overlap-only: ``episode.start <= artifact.observed_at <= episode.end`` (only when the
      episode carries a concrete ``end`` -- every segmentation-emitted proposal always does, see
      ``app.episodes.segmenter._emit_proposal``) -> binds at :data:`BASIS_TIME_OVERLAP`, the
      honest lower-confidence claim.
    - neither -> no binding for that pair.

    Every matching episode is evaluated independently (AC3): a nested/overlapping pair of episodes
    both covering one artifact yields two decisions (multi-ref, "zero or more" per the doctrine),
    never just the first/best match. No I/O; deterministic; safe to re-run on the same inputs
    (idempotency lives in :func:`diff_assignments`, the layer that compares against what is
    already durably recorded).
    """
    decisions: list[AssignmentDecision] = []
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        for episode in episodes:
            if artifact.scope != episode.scope and not _cross_scope_binding_allowed(
                artifact.scope, episode.scope, flow_provider
            ):
                continue
            key = (artifact.artifact_ref, episode.episode_id)
            if key in seen:
                continue
            if artifact.artifact_ref in episode.derived_from:
                decisions.append(
                    AssignmentDecision(
                        artifact_ref=artifact.artifact_ref,
                        episode_id=episode.episode_id,
                        scope=artifact.scope,
                        basis=BASIS_PROVENANCE,
                        confidence=PROVENANCE_CONFIDENCE,
                    )
                )
                seen.add(key)
            elif episode.end is not None and episode.start <= artifact.observed_at <= episode.end:
                decisions.append(
                    AssignmentDecision(
                        artifact_ref=artifact.artifact_ref,
                        episode_id=episode.episode_id,
                        scope=artifact.scope,
                        basis=BASIS_TIME_OVERLAP,
                        confidence=TIME_OVERLAP_CONFIDENCE,
                    )
                )
                seen.add(key)
    return decisions


def artifact_candidates_from_signals(signals: Iterable[Any]) -> list[ArtifactCandidate]:
    """Adapt this tick's already-normalized segmentation signals into assignment candidates.

    Duck-typed on ``.provenance_ref`` / ``.scope`` / ``.observed_at`` (the shape
    ``app.episodes.segmenter.SegmentationSignal`` already carries) so assignment reuses the SAME
    delta-window signals segmentation just folded -- "assignment runs in the tick after
    segmentation, over the same delta window" (spec point 4) -- without a second read of the
    underlying streams.
    """
    return [
        ArtifactCandidate(artifact_ref=s.provenance_ref, scope=s.scope, observed_at=s.observed_at)
        for s in signals
    ]


def episode_bounds_from_closed_segments(
    closed_segments: Iterable[Any], *, episode_id_for: Any
) -> list[EpisodeBoundsRecord]:
    """Adapt this tick's freshly closed segments into assignment episode-bounds records.

    ``episode_id_for`` is ``app.episodes.segmenter._deterministic_episode_id`` (passed in, not
    imported, to keep this module free of a segmenter dependency and avoid a private-name import
    across modules) -- the SAME start-independent id ``_emit_proposal`` mints, so an artifact bound
    against a freshly closed segment this tick and one bound against the same episode's persisted
    projection row next tick resolve to the identical ``episode_id``.
    """
    return [
        EpisodeBoundsRecord(
            episode_id=episode_id_for(closed),
            scope=closed.scope,
            start=closed.start,
            end=closed.end,
            derived_from=tuple(closed.derived_from),
        )
        for closed in closed_segments
    ]


# ---------------------------------------------------------------------------
# Pure diff (idempotency + correction, AC6)
# ---------------------------------------------------------------------------


def diff_assignments(
    existing: Mapping[tuple[str, str], Mapping[str, Any]],
    decisions: Sequence[AssignmentDecision],
) -> tuple[list[AssignmentDecision], list[tuple[str, str]]]:
    """Pure diff between newly computed ``decisions`` and the ledger's ``existing`` rows.

    ``existing`` keys on ``(artifact_ref, episode_id)`` -> a row mapping carrying at least
    ``binding_state`` and ``basis`` (the shape :func:`read_existing_bindings` returns).

    Returns ``(to_insert, to_correct)``:

    - ``to_insert``: decisions with no existing row, OR an existing row that is not currently
      ``active`` with the same ``basis`` (a corrected binding being reinstated, or a weaker basis
      being upgraded to a stronger one on new evidence) -- an idempotent re-tick of an unchanged,
      already-``active``, same-``basis`` pair produces nothing here (AC6: re-ticks don't
      duplicate).
    - ``to_correct``: ``(artifact_ref, episode_id)`` keys whose existing row is ``active`` but is
      no longer supported by ANY current decision -- a re-cut (or a bounds/derived_from change)
      invalidated a prior binding; corrected, never silently dropped.

    No I/O; deterministic; the layer :func:`commit_assignment_diff` persists.
    """
    decision_map = {(d.artifact_ref, d.episode_id): d for d in decisions}

    to_insert: list[AssignmentDecision] = []
    for key, decision in decision_map.items():
        row = existing.get(key)
        if row is None:
            to_insert.append(decision)
            continue
        if row.get("binding_state") != BINDING_STATE_ACTIVE or row.get("basis") != decision.basis:
            to_insert.append(decision)

    to_correct = [
        key
        for key, row in existing.items()
        if row.get("binding_state") == BINDING_STATE_ACTIVE and key not in decision_map
    ]
    return to_insert, to_correct


# ---------------------------------------------------------------------------
# DB-side bundle-row ledger (I/O boundary; guard-at-seam)
# ---------------------------------------------------------------------------


def read_candidate_episodes_for_scopes(scopes: Iterable[str]) -> list[EpisodeBoundsRecord]:
    """Read persisted episodes (the ``episodes`` PG projection, ERE-02) for the given scopes.

    The source late-arriving artifacts bind against (AC7): an episode closed and emitted on a
    PRIOR tick is no longer in this tick's in-memory ``closed_segments`` (its open-segment state
    was already deleted), but it IS queryable here via its projected row -- so a signal that
    arrives after its episode closed still resolves a binding without touching that episode's
    bounds.
    """
    scope_list = sorted({s for s in scopes if s})
    if not scope_list:
        return []
    placeholders = ", ".join(["%s"] * len(scope_list))
    query = (
        f"SELECT episode_id, scope, time_start, time_end, derived_from "
        f"FROM {EPISODES_TABLE} WHERE scope IN ({placeholders})"
    )
    rows: list[EpisodeBoundsRecord] = []
    with conn_rw() as conn:
        _assert_table_schema(conn, EPISODES_TABLE)
        with conn.cursor() as cur:
            cur.execute(query, tuple(scope_list))
            for r in cur.fetchall():
                if isinstance(r, dict):
                    episode_id, scope, start, end, derived_from = (
                        r["episode_id"],
                        r["scope"],
                        r["time_start"],
                        r["time_end"],
                        r["derived_from"],
                    )
                else:
                    episode_id, scope, start, end, derived_from = r
                if isinstance(derived_from, str):
                    derived_from = json.loads(derived_from)
                rows.append(
                    EpisodeBoundsRecord(
                        episode_id=str(episode_id),
                        scope=str(scope),
                        start=_as_utc(start),
                        end=_as_utc(end) if end is not None else None,
                        derived_from=tuple(str(x) for x in (derived_from or [])),
                    )
                )
    return rows


def read_existing_bindings(artifact_refs: Iterable[str]) -> dict[tuple[str, str], dict[str, Any]]:
    """Read this batch's existing ledger rows, keyed ``(artifact_ref, episode_id)``.

    Scoped to the given ``artifact_refs`` only (never a full-table scan) -- the exact set
    :func:`diff_assignments` needs to decide idempotent no-ops vs new inserts vs corrections.
    """
    ref_list = sorted({r for r in artifact_refs if r})
    if not ref_list:
        return {}
    placeholders = ", ".join(["%s"] * len(ref_list))
    query = (
        "SELECT artifact_ref, episode_id, scope, basis, confidence, binding_state, rule, "
        f"assigned_at, corrected_at FROM {BINDING_TABLE} WHERE artifact_ref IN ({placeholders})"
    )
    out: dict[tuple[str, str], dict[str, Any]] = {}
    with conn_rw() as conn:
        _assert_table_schema(conn, BINDING_TABLE)
        with conn.cursor() as cur:
            cur.execute(query, tuple(ref_list))
            for r in cur.fetchall():
                row = dict(r) if isinstance(r, dict) else {
                    "artifact_ref": r[0],
                    "episode_id": r[1],
                    "scope": r[2],
                    "basis": r[3],
                    "confidence": r[4],
                    "binding_state": r[5],
                    "rule": r[6],
                    "assigned_at": r[7],
                    "corrected_at": r[8],
                }
                out[(str(row["artifact_ref"]), str(row["episode_id"]))] = row
    return out


def read_existing_bindings_for_episodes(
    episode_ids: Iterable[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Read every ``active``/``corrected`` ledger row for the given ``episode_id``s, keyed
    ``(artifact_ref, episode_id)`` -- the SAME shape :func:`read_existing_bindings` returns.

    Finding 3 (AC6 correction reachability): :func:`read_existing_bindings` alone only ever sees
    THIS tick's signal ``artifact_ref``s, so a binding recorded on a PRIOR tick for an artifact
    that does not re-appear as a signal this tick (the common case -- a re-cut invalidates a
    binding without re-delivering the original signal) is invisible to :func:`diff_assignments`,
    and its ``to_correct`` detection (an ``active`` row no longer supported by any current
    decision) can never fire. Callers merge this function's result into the map fed to
    :func:`diff_assignments` for every episode touched this tick (fresh closures + persisted
    candidates for the touched scopes) so a stale binding is reconciled even when its artifact
    never resurfaces as a signal.
    """
    episode_list = sorted({e for e in episode_ids if e})
    if not episode_list:
        return {}
    placeholders = ", ".join(["%s"] * len(episode_list))
    query = (
        "SELECT artifact_ref, episode_id, scope, basis, confidence, binding_state, rule, "
        f"assigned_at, corrected_at FROM {BINDING_TABLE} WHERE episode_id IN ({placeholders})"
    )
    out: dict[tuple[str, str], dict[str, Any]] = {}
    with conn_rw() as conn:
        _assert_table_schema(conn, BINDING_TABLE)
        with conn.cursor() as cur:
            cur.execute(query, tuple(episode_list))
            for r in cur.fetchall():
                row = dict(r) if isinstance(r, dict) else {
                    "artifact_ref": r[0],
                    "episode_id": r[1],
                    "scope": r[2],
                    "basis": r[3],
                    "confidence": r[4],
                    "binding_state": r[5],
                    "rule": r[6],
                    "assigned_at": r[7],
                    "corrected_at": r[8],
                }
                out[(str(row["artifact_ref"]), str(row["episode_id"]))] = row
    return out


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Bundle-mutation targets (Finding 1): artifact_ref -> the real bundle to mutate
# ---------------------------------------------------------------------------

_VAULT_ACTIVITY_PREFIX = "vault.activity:"


def _resolve_bundle_object_id_and_note_path(
    artifact_ref: str, *, vault_root: Path | str | None
) -> tuple[str | None, Path | None]:
    """Resolve ``artifact_ref`` to its bundle-mutation target, or ``(None, None)`` when none
    exists (see module docstring's Bundle mutation / Resolution sections).

    ``vault_root=None`` short-circuits to ``(None, None)`` unconditionally -- callers that pass no
    vault root get ledger-only behavior (backward compatible with every pre-Finding-1 caller).
    Only ``vault.activity:<outbox_row_id>`` refs resolve today; ``heimdal.observations:<id>`` (and
    any future, unrecognized prefix) intentionally returns ``(None, None)`` -- no fabricated
    bundle target.
    """
    if not vault_root or not artifact_ref.startswith(_VAULT_ACTIVITY_PREFIX):
        return None, None
    row_id = artifact_ref[len(_VAULT_ACTIVITY_PREFIX) :]
    if not row_id:
        return None, None
    from app.episodes.vault_activity_stream import resolve_bundle_target_for_outbox_row_id

    try:
        return resolve_bundle_target_for_outbox_row_id(row_id, vault_root=Path(vault_root))
    except Exception:
        # Best-effort (mirrors resolve_activity_dimensions): a purged/malformed outbox row must
        # never fail the whole tick's ledger commit -- bundle mutation is skipped for this ref.
        logger.warning(
            "assignment: bundle target resolution failed for artifact_ref=%s -- skipping bundle "
            "mutation (ledger row still recorded)",
            artifact_ref,
            exc_info=True,
        )
        return None, None


def _merged_episode_ref(existing: Any, episode_ids: Iterable[str]) -> list[str]:
    """Union (never overwrite) the bundle's current ``episode_ref`` with ``episode_ids``.

    ``existing`` is whatever the payload's ``episode_ref`` key currently holds -- a non-empty list
    of ids contributes its members; ``'unbound'``/``'pending'``/missing/anything else contributes
    nothing (the honest starting point is empty, never a fabricated id). Sorted for a
    deterministic, diff-friendly payload.
    """
    current: set[str] = set()
    if isinstance(existing, (list, tuple)):
        current = {str(x) for x in existing if isinstance(x, str) and x}
    current.update(str(e) for e in episode_ids if e)
    return sorted(current)


def _read_bundle_payload(cur: Any, table: str, object_id: str) -> dict[str, Any] | None:
    cur.execute(f"SELECT payload FROM {table} WHERE object_id = %s::uuid", (object_id,))
    row = cur.fetchone()
    if row is None:
        return None
    payload = row["payload"] if isinstance(row, dict) else row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return dict(payload or {})


def _jsonb_set_episode_ref(cur: Any, table: str, object_id: str, value: str | list[str]) -> None:
    """Set ONLY the ``episode_ref`` key on ``object_id``'s payload via ``jsonb_set`` (round-2
    Finding 3): a targeted single-key update, never a read-modify-write of the whole ``payload``
    column, so a concurrent writer's change to a DIFFERENT key (``evidence_role``/
    ``authority_state``/``scope_binding``/...) between our read and our write is never clobbered.
    Both ``store_objects`` and ``store_vector_index`` carry a ``jsonb payload`` column (KERNEL-04,
    ``app/stores/pg.py``), so the same statement applies to both. ``updated_at`` still advances so
    the ``store_vector_index.generation()`` token moves and the retrieval cache re-derives."""
    cur.execute(
        f"UPDATE {table} SET "
        f"payload = jsonb_set(coalesce(payload, '{{}}'::jsonb), '{{episode_ref}}', %s::jsonb), "
        f"updated_at = now() WHERE object_id = %s::uuid",
        (json.dumps(value), object_id),
    )


def _apply_bundle_episode_ref_insert(cur: Any, object_id: str, episode_ids: Sequence[str]) -> None:
    """Upgrade ``object_id``'s DB-side bundle rows' ``episode_ref`` (union, never overwrite).

    Reads the current ``episode_ref`` value to compute the union, then writes ONLY that key back
    via ``jsonb_set`` (:func:`_jsonb_set_episode_ref`) -- every other payload key
    (``evidence_role``, ``authority_state``, ``scope_binding``, ``kind``, embeddings, ...) is left
    exactly as any concurrent writer has it, never round-tripped through this seam. A row absent
    from one or both tables (e.g. not yet embedded) is silently skipped for that table -- never an
    error, since not every object_id necessarily has a vector-index row yet.
    """
    for table in ("store_objects", "store_vector_index"):
        payload = _read_bundle_payload(cur, table, object_id)
        if payload is None:
            continue
        _jsonb_set_episode_ref(
            cur, table, object_id, _merged_episode_ref(payload.get("episode_ref"), episode_ids)
        )


def _apply_bundle_episode_ref_correction(cur: Any, object_id: str, episode_id: str) -> None:
    """Remove ``episode_id`` from ``object_id``'s DB-side bundle rows' ``episode_ref`` (Finding 3:
    a correction is an ordinary bundle update too, not just a ledger-row flip), again via a
    targeted ``jsonb_set`` on only that key.

    An empty result reverts to the honest ``'unbound'`` sentinel (never an empty array -- the
    schema requires ``episode_ref`` arrays to be non-empty, ``schemas/_defs.schema.json``).
    """
    for table in ("store_objects", "store_vector_index"):
        payload = _read_bundle_payload(cur, table, object_id)
        if payload is None:
            continue
        remaining = [
            e for e in _merged_episode_ref(payload.get("episode_ref"), ()) if e != episode_id
        ]
        _jsonb_set_episode_ref(cur, table, object_id, remaining if remaining else "unbound")


def _transform_note_frontmatter_episode_ref(
    note_path: Path,
    transform: "Callable[[Any], str | list[str]]",
    *,
    vault_root: Path,
    write_guard: WriteGuard,
) -> None:
    """Read-modify-write the vault note's OWN frontmatter ``episode_ref`` through the guarded
    write seam (spec point 3's "vault-serialized artifacts" half of bundle mutation).

    ``transform(existing_episode_ref) -> new_episode_ref`` computes the new value; shared by the
    insert (union-merge) and correction (removal) call sites, mirroring the DB-side
    :func:`_apply_bundle_episode_ref_insert` / :func:`_apply_bundle_episode_ref_correction` pair.
    Read failures (deleted/unreadable note) are best-effort skipped -- never fail the whole tick's
    commit over one missing file; a guard-blocked WRITE, by contrast, is NOT swallowed here
    (:func:`app.knowledge.write_ops.write_note_from_absolute` raises ``WritesBlockedError``, which
    must propagate -- AC4's guard-at-seam enforcement).
    """
    from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning(
            "assignment: could not read vault note %s for episode_ref stamping -- skipping "
            "(ledger row still recorded)",
            note_path,
        )
        return
    frontmatter, body = load_frontmatter(text)
    frontmatter["episode_ref"] = transform(frontmatter.get("episode_ref"))
    new_text = dump_frontmatter(frontmatter, body)

    from app.knowledge.write_ops import write_note_from_absolute

    write_note_from_absolute(
        note_path,
        new_text,
        vault_root=vault_root,
        action=EPISODE_ASSIGNMENT_WRITE_ACTION,
        write_guard=write_guard,
    )


def _stamp_note_frontmatter_episode_ref_insert(
    note_path: Path, episode_ids: Sequence[str], *, vault_root: Path, write_guard: WriteGuard
) -> None:
    """Union-merge ``episode_ids`` into the note's frontmatter ``episode_ref`` (never overwrite)."""
    _transform_note_frontmatter_episode_ref(
        note_path,
        lambda existing: _merged_episode_ref(existing, episode_ids),
        vault_root=vault_root,
        write_guard=write_guard,
    )


def _stamp_note_frontmatter_episode_ref_correction(
    note_path: Path, episode_id: str, *, vault_root: Path, write_guard: WriteGuard
) -> None:
    """Remove ``episode_id`` from the note's frontmatter ``episode_ref`` (Finding 3: a correction
    is an ordinary bundle update on the vault-serialized bundle too, not just the ledger row)."""

    def _remove(existing: Any) -> str | list[str]:
        remaining = [e for e in _merged_episode_ref(existing, ()) if e != episode_id]
        return remaining if remaining else "unbound"

    _transform_note_frontmatter_episode_ref(
        note_path, _remove, vault_root=vault_root, write_guard=write_guard
    )


def commit_assignment_diff(
    to_insert: Sequence[AssignmentDecision],
    to_correct: Sequence[tuple[str, str]],
    *,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    vault_root: Path | str | None = None,
) -> dict[str, int]:
    """Guarded commit of an assignment diff: the ``episode_artifact_binding`` ledger row AND (when
    ``vault_root`` is given and the artifact resolves to one) the artifact's REAL bundle -- the
    DB-side ``store_objects``/``store_vector_index`` payload rows and, for a vault-serialized
    artifact, the note's own frontmatter (Finding 1; see module docstring's Bundle mutation
    section).

    Guard-at-seam (AC4): ``write_guard.assert_writes_allowed`` is asserted FIRST, before any write
    -- a blocked guard means zero rows/bytes touched, mirroring
    ``app.episodes.store.write_episode_note``'s guard-at-seam discipline. Proposal class: this
    function never imports ``app.governance.governed_write`` and never constructs a
    ``DecisionToken``/``AuthorityReceipt`` -- a `pending` binding structurally cannot carry one.

    **Ordering (round-2 Finding 2 -- vault-canonical first, then the DB projection).** The vault
    note's own frontmatter is the ERE-03 canonical source of ``episode_ref``; the DB payload is a
    reingest-stable projection of it (``app/ingest/vault_alpha.py`` now reprojects it on every
    reingest). So this seam stamps the vault frontmatter FIRST (Phase A), and only if every stamp
    succeeds does it open the DB transaction and commit the ledger + payload projection (Phase B).
    A frontmatter write failure (``WritesBlockedError`` from a guard that flipped, or a real write
    ``OSError``) therefore raises BEFORE any DB commit -- a clean tick retry, never a committed
    ledger row sitting in front of an un-stamped note (which would make every future
    :func:`diff_assignments` treat the binding as satisfied and never repair it). Conversely a DB
    failure AFTER a successful frontmatter stamp leaves the ledger empty, so the next tick simply
    re-computes the same decision and idempotently re-stamps (union-merge is a no-op on an
    already-stamped note) -- recoverable, not fire-and-forget. A genuinely missing/unreadable note
    (deleted between resolution and stamp) is best-effort skipped inside the stamp helper -- its
    ledger row still commits, so a vanished artifact never wedges the whole tick.

    Each insert is an UPSERT (``ON CONFLICT (artifact_ref, episode_id) DO UPDATE``) so a
    reinstated/upgraded decision (:func:`diff_assignments`) overwrites its own prior row rather
    than colliding; each correction flips ``binding_state`` to ``corrected`` and stamps
    ``corrected_at`` without deleting the row (provenance survives the correction). The ledger rows
    and both DB-side bundle-payload ``jsonb_set`` updates run inside ONE Postgres transaction
    (commit-or-nothing for this tick's whole diff).

    ``vault_root=None`` (the default) skips ALL bundle mutation -- ledger-only, backward compatible
    with every pre-Finding-1 caller/test that only cares about the ledger.
    """
    write_guard.assert_writes_allowed(EPISODE_ASSIGNMENT_WRITE_ACTION)

    if not to_insert and not to_correct:
        return {"pending": 0, "corrected": 0}

    # Phase A -- resolve every artifact_ref to its bundle target (read-only) and stamp the
    # vault-canonical frontmatter FIRST. Any stamp WRITE failure raises here, before Phase B opens
    # a transaction, so the ledger is never committed ahead of an un-stamped note (Finding 2).
    insert_object_ids: list[str | None] = []
    for decision in to_insert:
        object_id, note_path = _resolve_bundle_object_id_and_note_path(
            decision.artifact_ref, vault_root=vault_root
        )
        insert_object_ids.append(object_id)
        if note_path is not None:
            _stamp_note_frontmatter_episode_ref_insert(
                note_path, [decision.episode_id], vault_root=Path(vault_root), write_guard=write_guard  # type: ignore[arg-type]
            )
    correct_object_ids: list[str | None] = []
    for artifact_ref, episode_id in to_correct:
        object_id, note_path = _resolve_bundle_object_id_and_note_path(
            artifact_ref, vault_root=vault_root
        )
        correct_object_ids.append(object_id)
        if note_path is not None:
            _stamp_note_frontmatter_episode_ref_correction(
                note_path, episode_id, vault_root=Path(vault_root), write_guard=write_guard  # type: ignore[arg-type]
            )

    # Phase B -- ledger + DB payload projection in ONE transaction (commit-or-nothing). Reached
    # only after every canonical frontmatter stamp succeeded.
    with conn_rw() as conn:
        _assert_table_schema(conn, BINDING_TABLE)
        with conn.cursor() as cur:
            for decision, object_id in zip(to_insert, insert_object_ids):
                if object_id is not None:
                    _apply_bundle_episode_ref_insert(cur, object_id, [decision.episode_id])
                cur.execute(
                    f"""
                    INSERT INTO {BINDING_TABLE} (
                        artifact_ref, episode_id, scope, basis, confidence, binding_state,
                        rule, assigned_at, corrected_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, now(), NULL)
                    ON CONFLICT (artifact_ref, episode_id) DO UPDATE SET
                        scope = EXCLUDED.scope,
                        basis = EXCLUDED.basis,
                        confidence = EXCLUDED.confidence,
                        binding_state = %s,
                        rule = EXCLUDED.rule,
                        assigned_at = now(),
                        corrected_at = NULL
                    """,
                    (
                        decision.artifact_ref,
                        decision.episode_id,
                        decision.scope,
                        decision.basis,
                        decision.confidence,
                        BINDING_STATE_ACTIVE,
                        ASSIGNMENT_RULE,
                        BINDING_STATE_ACTIVE,
                    ),
                )
            for (artifact_ref, episode_id), object_id in zip(to_correct, correct_object_ids):
                if object_id is not None:
                    _apply_bundle_episode_ref_correction(cur, object_id, episode_id)
                cur.execute(
                    f"""
                    UPDATE {BINDING_TABLE}
                    SET binding_state = %s, corrected_at = now()
                    WHERE artifact_ref = %s AND episode_id = %s
                    """,
                    (BINDING_STATE_CORRECTED, artifact_ref, episode_id),
                )

    return {"pending": len(to_insert), "corrected": len(to_correct)}


# ---------------------------------------------------------------------------
# ERE-07 (#3182) binding reconciliation: reused verbatim by app.episodes.recut, never
# reimplemented -- "binding reconciliation via the ERE-05 correction path" (issue Scope).
# ---------------------------------------------------------------------------


def _resolve_artifact_observed_at(artifact_ref: str, *, vault_root: Path | str | None) -> datetime | None:
    """Best-effort recovery of an artifact's ``observed_at`` for a time-overlap RE-VERIFICATION
    (ERE-07 reconciliation). Returns ``None`` -- meaning "cannot re-verify, so PRESERVE the
    binding, never destroy it" -- whenever the instant is not cheaply recoverable.

    Only ``vault.activity:<outbox_row_id>`` refs resolve today: the outbox row's payload carries
    the watcher-observed ``mtime`` (the SAME observation time
    ``app.episodes.segmenter._signal_from_vault_activity_row`` folds). A ``heimdal.observations:<id>``
    ref is NOT cheaply resolvable by id (the append-only observation log is keyed by sequence, not
    observation_id) -- so it returns ``None`` and its time-overlap binding is preserved here and
    left to the normal segmentation/assignment tick's own bounds-correction over live signals
    (HEIM-6 honest: never fabricate an instant this function does not actually have). ``vault_root``
    ``None`` short-circuits to ``None`` (ledger-only callers)."""
    if not vault_root or not artifact_ref.startswith(_VAULT_ACTIVITY_PREFIX):
        return None
    row_id = artifact_ref[len(_VAULT_ACTIVITY_PREFIX) :]
    if not row_id:
        return None
    try:
        with conn_rw() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM outbox WHERE id = %s::uuid", (row_id,))
                row = cur.fetchone()
    except Exception:
        return None
    if row is None:
        return None
    payload = row["payload"] if isinstance(row, dict) else row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    mtime = (payload or {}).get("mtime")
    if isinstance(mtime, bool) or mtime is None:
        return None
    try:
        if isinstance(mtime, (int, float)):
            seconds = float(mtime)
        else:
            text = str(mtime).strip()
            try:
                seconds = float(text)
            except ValueError:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        if seconds <= 0:
            return None
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _resolve_artifact_scope(artifact_ref: str, *, vault_root: Path | str | None) -> str | None:
    """Best-effort recovery of an artifact's TRUE scope for the ERE-08 (#3183) cross-scope gate
    (Finding 1). Returns ``None`` -- meaning "scope not cheaply determinable" -- whenever it cannot
    be resolved.

    Only ``vault.activity:<outbox_row_id>`` refs resolve today: they own a durable bundle (the note
    behind the never-purged outbox row) whose frontmatter scope IS the artifact's real scope
    (:func:`app.episodes.vault_activity_stream.resolve_scope_for_outbox_row_id`, the SAME scope
    segmentation assigns). This is the ref shape whose bundle a cross-scope binding would actually
    write ``episode_ref`` into -- so resolving it is what lets the gate deny a genuinely foreign-
    scope provenance rebinding. A ``heimdal.observations:<id>`` ref returns ``None``: its scope is
    not cheaply resolvable (the append-only log is keyed by sequence, not observation_id) AND it has
    no downstream bundle (:func:`_resolve_bundle_object_id_and_note_path` returns ``(None, None)``
    for it), so it can never carry a cross-scope ``episode_ref`` bundle write -- there is nothing to
    leak. ``vault_root=None`` short-circuits to ``None`` (ledger-only callers)."""
    if not vault_root or not artifact_ref.startswith(_VAULT_ACTIVITY_PREFIX):
        return None
    row_id = artifact_ref[len(_VAULT_ACTIVITY_PREFIX) :]
    if not row_id:
        return None
    from app.episodes.vault_activity_stream import resolve_scope_for_outbox_row_id

    try:
        return resolve_scope_for_outbox_row_id(row_id, vault_root=Path(vault_root))
    except Exception:
        return None


def reconcile_episode_bindings(
    episode_id: str,
    *,
    scope: str,
    start: datetime,
    end: datetime | None,
    derived_from: Iterable[str],
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    vault_root: Path | str | None = None,
    flow_provider: "CrossScopeFlowProvider | None" = None,
) -> dict[str, int]:
    """ERE-07 binding reconciliation for a re-cut or newly-adopted episode note.

    PRESERVES every still-valid binding and corrects ONLY the ones the re-cut genuinely
    invalidated -- the ERE-05 correction path (:func:`diff_assignments` /
    :func:`commit_assignment_diff`), reused verbatim. It recomputes the CURRENT correct binding
    set for the episode against its (post-edit) bounds+scope via :func:`compute_assignments`, so
    BOTH provenance AND still-in-bounds time-overlap bindings are re-supplied to
    :func:`diff_assignments` and therefore survive (a re-tick of an unchanged, still-valid binding
    is a no-op). Only a binding whose artifact is now out-of-bounds / wrong-scope produces no
    current decision and is corrected.

    Round-1 review Finding 1 (CRITICAL): the prior implementation re-supplied ONLY
    provenance decisions, so every existing time-overlap binding looked unsupported to
    :func:`diff_assignments` and was destroyed on every reconcile -- and because
    ``app.episodes.recut.run_recut_tick`` runs immediately after segmentation in the same
    ``episodes tick``, a freshly-proposed episode's brand-new time-overlap bindings were wiped in
    the SAME tick. This version never unbinds a binding merely because it is not provenance-based.

    Reconstruction of the candidate set:

    - Every current ``derived_from`` ref becomes a PROVENANCE candidate (``compute_assignments``
      matches provenance by plain membership, independent of ``observed_at`` -- the stand-in
      instant is irrelevant on that branch).
    - Every existing ACTIVE time-overlap binding (not already covered by ``derived_from``) is
      re-verified against the current bounds: its artifact's ``observed_at`` is recovered
      best-effort (:func:`_resolve_artifact_observed_at`). Resolvable + concrete ``end`` present ->
      fed through ``compute_assignments`` (kept iff still in ``[start, end]`` and same scope,
      corrected otherwise). Unresolvable, or a note without a concrete ``end`` -> PRESERVED
      (re-supplied unchanged) rather than destroyed; those fall back to the normal tick's own
      bounds-correction over live signals (HEIM-6 honest -- never destroy a binding this function
      cannot prove invalid).
    """
    existing = read_existing_bindings_for_episodes([episode_id])
    derived_from_set = {ref for ref in derived_from if ref}
    episode = EpisodeBoundsRecord(
        episode_id=episode_id, scope=scope, start=start, end=end, derived_from=tuple(sorted(derived_from_set))
    )

    # ERE-08 (#3183) Finding 1 -- CRITICAL cross-scope gate bypass, fixed: do NOT force each
    # provenance candidate's scope to the EPISODE's scope. A ``derived_from`` ref read back from a
    # (human- or sync-edited) note's frontmatter could be a FOREIGN-scope artifact_ref; forcing it
    # to the episode scope made ``compute_assignments``' cross-scope check structurally always-False,
    # so a foreign ref bound BASIS_PROVENANCE with no gate and ``commit_assignment_diff`` wrote the
    # (foreign-scope) ``episode_ref`` into that artifact's OWN bundle -- a real cross-scope write.
    # Now each ref carries its TRUE, resolved scope (:func:`_resolve_artifact_scope`); a ref whose
    # true scope differs from the episode's is routed through the same cross-scope gate as every
    # other binding (deny-by-default via ``compute_assignments(..., flow_provider=...)`` below), so
    # an unflowed foreign provenance ref produces NO decision and ``diff_assignments`` corrects any
    # previously-leaked binding. An unresolvable scope (``None`` -- a heimdal ref with no bundle to
    # leak into, or a purged row) falls back to the episode scope: it preserves legitimate same-scope
    # provenance across a re-cut (never destroy a valid binding, ERE-07 round-1 Finding 1) and can
    # carry no cross-scope bundle write regardless.
    candidates: list[ArtifactCandidate] = [
        ArtifactCandidate(
            artifact_ref=ref,
            scope=_resolve_artifact_scope(ref, vault_root=vault_root) or scope,
            observed_at=start,
        )
        for ref in sorted(derived_from_set)
    ]
    preserved: list[AssignmentDecision] = []
    for (artifact_ref, ep_id), row in existing.items():
        if ep_id != episode_id or row.get("binding_state") != BINDING_STATE_ACTIVE:
            continue
        if artifact_ref in derived_from_set:
            # Covered by the provenance candidate above -- never also preserve/re-verify it as
            # time-overlap (avoids two conflicting decisions for one (artifact, episode) key).
            continue
        if row.get("basis") != BASIS_TIME_OVERLAP:
            continue
        row_scope = str(row.get("scope") or scope)
        if row_scope != scope:
            # Cross-scope deny-by-default: a re-cut that changed the episode's scope leaves this
            # binding recorded under the old scope. Scope mismatch is a DEFINITIVE signal (unlike
            # bounds we cannot re-verify), so do NOT preserve it -- omitting it from `decisions`
            # lets diff_assignments correct (withdraw) the now-cross-scope binding. ERE-08 owns the
            # full cross-scope posture; this branch must not silently re-supply a cross-scope ref.
            continue
        observed_at = _resolve_artifact_observed_at(artifact_ref, vault_root=vault_root)
        if end is None or observed_at is None:
            # Cannot re-verify bounds -> preserve the (same-scope) binding rather than destroy it.
            preserved.append(
                AssignmentDecision(
                    artifact_ref=artifact_ref,
                    episode_id=episode_id,
                    scope=row_scope,
                    basis=BASIS_TIME_OVERLAP,
                    confidence=TIME_OVERLAP_CONFIDENCE,
                )
            )
        else:
            candidates.append(
                ArtifactCandidate(artifact_ref=artifact_ref, scope=row_scope, observed_at=observed_at)
            )

    decisions = compute_assignments(candidates, [episode], flow_provider=flow_provider) + preserved
    to_insert, to_correct = diff_assignments(existing, decisions)
    return commit_assignment_diff(to_insert, to_correct, write_guard=write_guard, vault_root=vault_root)


def withdraw_episode_bindings(
    episode_id: str,
    *,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    vault_root: Path | str | None = None,
) -> dict[str, int]:
    """ERE-07 merge-deletion reconciliation: an episode note that no longer exists on disk (the
    human deleted it as half of a merge) can no longer support ANY binding -- correct every one
    of its currently-active ledger rows (never silently dropped; provenance survives the
    correction, mirroring every other :func:`commit_assignment_diff` correction in this module)."""
    existing = read_existing_bindings_for_episodes([episode_id])
    to_correct = [
        key for key, row in existing.items() if row.get("binding_state") == BINDING_STATE_ACTIVE
    ]
    return commit_assignment_diff([], to_correct, write_guard=write_guard, vault_root=vault_root)


__all__ = [
    "ASSIGNMENT_RULE",
    "BASIS_PROVENANCE",
    "BASIS_TIME_OVERLAP",
    "BINDING_STATE_ACTIVE",
    "BINDING_STATE_CORRECTED",
    "BINDING_TABLE",
    "EPISODE_ASSIGNMENT_WRITE_ACTION",
    "PROVENANCE_CONFIDENCE",
    "TIME_OVERLAP_CONFIDENCE",
    "ArtifactCandidate",
    "AssignmentDecision",
    "EpisodeAssignmentError",
    "EpisodeAssignmentSchemaMissingError",
    "EpisodeBoundsRecord",
    "artifact_candidates_from_signals",
    "commit_assignment_diff",
    "compute_assignments",
    "diff_assignments",
    "episode_bounds_from_closed_segments",
    "read_candidate_episodes_for_scopes",
    "read_existing_bindings",
    "read_existing_bindings_for_episodes",
    "reconcile_episode_bindings",
    "withdraw_episode_bindings",
]
