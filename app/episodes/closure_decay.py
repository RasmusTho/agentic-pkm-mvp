"""Closure-derived retrieval salience decay (ERE-06, #3181).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md``; the normative model is
``docs/adr/ADR-0058-event-horizon-closure-decay.md`` (Event Horizon decay). Salience contract hard
law (``docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md``): decay is **derived, never
persisted** and **ranking-only** -- it never touches ``evidence_role``, ``authority_state``, or
scope.

The factor is recomputed on every read from exactly two inputs (ADR-0058 §4): an artifact's
``episode_ref`` binding set and the referenced Episodes' own ``closed`` state. No dampened score,
no "decayed" stamp, no derived field is ever written back to any store -- this module contains no
write path at all, only readers of the already-durable ``episodes`` projection (DB, for the
production retrieval call site) or the vault-canonical Episode notes themselves (for the
deterministic, no-DB relevance evaluator).

MAX-over-bindings (ADR-0058 §3): an artifact is as hot as its hottest episode -- ANY binding that
is not a CONFIRMED-closed episode (an open episode, or a dangling/unresolved id -- fail-open to
visibility per the ADR) keeps the artifact at full salience. Only when EVERY referenced episode id
resolves as closed does the artifact step down.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.db.db import conn_rw
from app.domain.state_axes import normalize_maturity, normalize_review_state
from app.jobs.episodes_projection import EPISODES_TABLE

logger = logging.getLogger(__name__)

#: v1 decay curve (RQ3 -- provisional, single named constant; see
#: docs/EPISODE_RESOLUTION_ENGINE/README.md :: Provisional thresholds (RQ-E1)). ADR-0058 accepts
#: the shape (step-at-closure + floor + reinforcement resets) while leaving the curve PARAMETERS
#: (eta, tail shape, per-scope variation) owner-open research; v1 realizes the shape as a single
#: step-down factor applied the instant every referenced episode is closed. This module is the
#: single source -- nothing else literal-copies this value.
CLOSURE_DECAY_STEP_DOWN_FACTOR: float = 0.5

#: episode_ref string sentinels (schemas/_defs.schema.json :: episode_ref) -- neither carries a
#: real episode id, so neither can ever resolve to a closed binding (structurally immune, ADR-0058
#: Edge case 1's "absence of episodic origin is absence of decay").
_EPISODE_REF_SENTINELS = frozenset({"unbound", "pending"})

# ADR-0058 §2 exempt note-class gate (amended 2026-07-11): canonical knowledge artifacts stay at
# full salience even when episode-bound, because their liveness follows their OWN properties
# (ADR-0051 commitment 5: episodic -> semantic is transformation, and the transformed artifact
# carries its own standing) -- not the situation they were authored in. Without this gate, an
# evergreen note or reviewed/protected decision authored inside a meeting would be halved the
# moment that meeting closes (ADR-0058 §2's exact warning; Edge case 4). ADR-0058 §4 makes the
# exempt check short-circuit to 1.0 BEFORE any binding math.
#
# v1 keys the gate on EXISTING, already-populated bundle signals -- deliberately NOT a new
# note-class taxonomy (the concrete ADR-0055/T2 note-class table, #3131, is still unbuilt as a
# decay classification). The honest signals are the two state axes the ingest/index producers
# actually write onto every store_objects/store_vector_index payload (app/services/vault_sync.py
# via normalize_artifact_state_axes; app/services/indexer.py::handle_ingest_object_created;
# guaranteed present past app/index/artifact_metadata.py::build_indexed_unit_payload). Compared
# through the SAME canonical normalizers the rest of the system uses (app/domain/state_axes.py),
# so a legacy alias like review_state 'evergreen' -> 'reviewed' is honored:
#   - maturity     == "evergreen"              -> ADR-0058 "evergreen knowledge notes"
#   - review_state in {"reviewed","protected"} -> curated/durable products (project status +
#     reviewed derivatives); a decision promoted through the vault normalizes here
# Known honest gap (NOT invented around): the distinct "accepted decision" class carries its
# canonical marker in `authority_state == accepted`, which lives only in vault frontmatter and is
# NOT lifted onto the retrieval payload today (app/retrieval/envelope.py defaults authority_state
# to "projection"; no ingest/index producer writes it top-level, and the choke-point
# `review_state` enum has no "accepted" value). Gating on it would never match a real row, so the
# accepted-decision class rides on its normalized review_state/maturity above until #3131's
# note-class table (or an authority_state payload lift) lands -- see the PR/hand-back.
_EXEMPT_REVIEW_STATES = frozenset({"reviewed", "protected"})
_EXEMPT_MATURITIES = frozenset({"evergreen"})


def is_exempt_note_class(payload: Mapping[str, Any] | None) -> bool:
    """Whether a retrieval hit's bundle payload marks it a canonical knowledge artifact exempt
    from closure decay (ADR-0058 §2). Gated on existing, populated state-axis bundle signals only
    (see the module constants above), compared through the canonical ``app.domain.state_axes``
    normalizers -- a payload without an exempt-class marker is dampenable as normal."""
    if not isinstance(payload, Mapping):
        return False
    if normalize_review_state(payload.get("review_state")) in _EXEMPT_REVIEW_STATES:
        return True
    if normalize_maturity(payload.get("maturity")) in _EXEMPT_MATURITIES:
        return True
    return False

EPISODES_SCHEMA_MIGRATION_HINT = (
    "episodes projection schema is migration-owned: run 'alembic upgrade head' against this "
    "database. See app/alembic/versions/e0f2a9c4b7d1_ere02_episodes_projection.py."
)


class ClosureDecaySchemaMissingError(RuntimeError):
    """Raised when the ``episodes`` projection table is absent (pre-migration database)."""


def _assert_schema(conn: Any) -> None:
    """Fail-loud preflight (invariant -> producers rule, mirrors
    ``app.episodes.engine_state._assert_schema`` / ``app.episodes.assignment._assert_table_schema``):
    the ``episodes`` projection must exist before any query touches it."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (EPISODES_TABLE,))
        row = cur.fetchone()
    oid = (row.get("to_regclass") if isinstance(row, dict) else row[0]) if row else None
    if not oid:
        raise ClosureDecaySchemaMissingError(
            f"Missing table '{EPISODES_TABLE}'. {EPISODES_SCHEMA_MIGRATION_HINT}"
        )


def resolve_episode_ids(episode_ref: Any) -> tuple[str, ...]:
    """Normalize a payload's ``episode_ref`` value to the tuple of real episode ids it carries.

    ``'unbound'``/``'pending'`` and anything malformed (not a list, or a list of non-strings)
    normalize to ``()`` -- honest, never a fabricated id (mirrors
    ``app.retrieval.envelope._episode_ref_from_payload``'s conservative-fallback posture, but this
    reader never needs to CHOOSE a fallback value -- an empty binding set is exactly "no episode
    input to the decay math").
    """
    if isinstance(episode_ref, str):
        # Every string value is a sentinel ('unbound'/'pending') or, if malformed, still not a
        # real id list -- either way there is no episode id to extract.
        return ()
    if isinstance(episode_ref, (list, tuple)):
        return tuple(x for x in episode_ref if isinstance(x, str) and x)
    return ()


def derive_closure_salience(
    episode_ref: Any,
    closed_episode_ids: Iterable[str] | Mapping[str, Any],
    *,
    exempt_note_class: bool = False,
) -> tuple[float, dict[str, Any]]:
    """The pure decay derivation (ADR-0058 §2/§3): ``(factor, salience_metadata)``.

    ``closed_episode_ids`` is the CONFIRMED-closed subset of episode ids (from whichever reader the
    caller used -- DB projection or vault notes); anything not in it is treated as open-or-unknown,
    which the MAX rule below resolves to full salience (fail-open, never fail-closed).

    - ``exempt_note_class`` (ADR-0058 §2 gate) -> ``(1.0, {})`` -- a canonical knowledge artifact
      (accepted decision / evergreen knowledge note; see :func:`is_exempt_note_class`) stays at
      full salience even when every binding is closed. Checked FIRST, short-circuiting before any
      binding math (ADR-0058 §4).
    - No episode binding (``unbound``/``pending``/malformed) -> ``(1.0, {})`` -- structurally
      immune, no salience key at all (an open-episode or unbound artifact "carries none", per the
      spec's AC2).
    - At least one binding NOT confirmed closed (open, or a dangling/unresolved id) -> ``(1.0,
      {})`` -- MAX-over-bindings: one open situation keeps the whole artifact hot.
    - Every binding confirmed closed -> ``(CLOSURE_DECAY_STEP_DOWN_FACTOR, {"episode_closure":
      {closed: True, factor, closed_episode_refs}})`` -- the step-down, with per-hit metadata so
      every consumer can see why (ADR-0058's "same honesty posture as provenance/temporal_validity").
    """
    if exempt_note_class:
        return 1.0, {}
    ids = resolve_episode_ids(episode_ref)
    if not ids:
        return 1.0, {}
    closed_set = set(closed_episode_ids)
    if any(episode_id not in closed_set for episode_id in ids):
        return 1.0, {}
    return CLOSURE_DECAY_STEP_DOWN_FACTOR, {
        "episode_closure": {
            "closed": True,
            "factor": CLOSURE_DECAY_STEP_DOWN_FACTOR,
            "closed_episode_refs": sorted(set(ids)),
        }
    }


def read_closed_episode_ids(episode_ids: Iterable[str]) -> set[str]:
    """DB-backed reader (the production ``retrieve()`` call site): which of ``episode_ids`` are
    currently ``closed`` per the rebuildable ``episodes`` projection (ERE-02).

    Derived FROM the projection, never itself persisted anywhere -- a fresh query on every call,
    same posture as any other retrieval-time signal read. An id absent from the result (never
    existed, or is open) is simply not in the returned set -- callers never distinguish the two,
    which is exactly the fail-open posture ADR-0058 requires for a dangling reference.
    """
    ids = sorted({e for e in episode_ids if e})
    if not ids:
        return set()
    placeholders = ", ".join(["%s"] * len(ids))
    query = (
        f"SELECT episode_id FROM {EPISODES_TABLE} WHERE closed = true AND episode_id IN ({placeholders})"
    )
    out: set[str] = set()
    with conn_rw() as conn:
        _assert_schema(conn)
        with conn.cursor() as cur:
            cur.execute(query, tuple(ids))
            for row in cur.fetchall():
                value = row["episode_id"] if isinstance(row, dict) else row[0]
                out.add(str(value))
    return out


def read_closed_episode_ids_from_vault(episode_ids: Iterable[str], *, vault_root: Path | str) -> set[str]:
    """Vault-native reader (the deterministic relevance evaluator's own no-external-source
    constraint, CRE-03): read each candidate Episode note's OWN frontmatter ``time.closed``
    directly -- no DB round-trip.

    Best-effort, never raises: a missing, unreadable, or malformed note is skipped (not counted as
    closed) -- the same fail-open posture as the DB reader above, just resolved against the
    vault-canonical source instead of its projection.
    """
    from app.episodes.notes import episode_note_rel_path, parse_episode_note

    root = Path(vault_root)
    out: set[str] = set()
    for episode_id in {e for e in episode_ids if e}:
        note_path = root / episode_note_rel_path(episode_id)
        try:
            text = note_path.read_text(encoding="utf-8")
            fields = parse_episode_note(text)
        except OSError:
            continue
        except Exception:
            logger.warning(
                "closure_decay: could not parse episode note %s -- treating as open (fail-open)",
                note_path,
                exc_info=True,
            )
            continue
        time_fields = fields.get("time") or {}
        if isinstance(time_fields, Mapping) and bool(time_fields.get("closed", False)):
            out.add(episode_id)
    return out


__all__ = [
    "CLOSURE_DECAY_STEP_DOWN_FACTOR",
    "ClosureDecaySchemaMissingError",
    "derive_closure_salience",
    "is_exempt_note_class",
    "read_closed_episode_ids",
    "read_closed_episode_ids_from_vault",
    "resolve_episode_ids",
]
