"""Mimer projector: cursor consumer -> noncanonical candidate (Epic #3019 slice A11, #3031).

The read-model that proves the Heimdal <-> Mimer seam end to end: it consumes
``heimdal.observation.published.v1`` events through the A2 per-consumer cursor
contract (``app.heimdal.publish.read_observations_for_consumer`` /
``advance_cursor_for_consumer`` -- never the log/cursor *store* modules
directly, per the issue Constraints "no direct DB imports across
boundaries") and materializes each observation as a **noncanonical**
candidate artifact entering the *existing* Mimer triage path
(``app.knowledge_acquisition.candidate_writeback``'s governed-write posture:
``requires_review: true`` / ``review_state: draft`` / ``triage_state:
captured``, written through ``app.knowledge.write_ops.write_note_relative``
behind ``WriteGuard``).

Division of labor with A3 (``app.heimdal.projector``): A3 owns the content
*quarantine* -- the neutralization primitive that renders observed content
inert as an instruction (HEIM-9/F2). This module owns the *candidate
materialization* -- turning a quarantined observation into a durable,
reviewable vault artifact carrying the full provenance chain. This module
calls A3's ``quarantine_observed_content`` directly (not
``project_observation``) because it needs the full assembled payload (
``episode_id``, ``provenance.content_identity/raw_ref/capture_chain``,
``scope_hint``, ``supersedes``/``revision_of``) that A3's envelope-shaped
``QuarantinedCandidate`` does not carry -- A3 built the seam that proves
observed content cannot become an instruction; this slice builds the seam
that proves an observation can become a reviewable candidate without
becoming canonical knowledge (HEIM-8).

Noncanonical standing (HEIM-8) is structurally fixed on every candidate this
module emits: ``requires_review=True`` and ``source_authoritative=False`` are
enforced in ``HeimdalCandidate.__post_init__`` exactly as A3's
``QuarantinedCandidate``/``QuarantinedContent`` fix them -- there is no
governed-promotion call in this module. Candidate -> canonical knowledge
rides the existing GOV xfail skeleton (out of scope, §11#11).

Provenance survival (HEIM-2): ``content_identity`` + ``raw_ref`` +
``capture_chain`` are read straight from the observation's ``provenance``
family and carried onto the candidate unchanged; ``derived_from`` is stamped
as the source ``observation_id`` so a downstream reader can always resolve a
candidate back to the exact observation it was projected from.

Fold semantics (§3.5, HEIM-1): corrections (``supersedes``) and revisions
(``revision_of``) are new, append-only events -- this module never rewrites
the log. Folding happens at projection time: for a given fold key
(``episode_id`` if present, else ``observation_id``), the batch is folded so
the highest-``sequence`` event wins (last-correction-wins, deterministic by
publication order per §3.5 rule 3) and only the winning candidate is
written. This is a projection-time fold over the read batch, not a stateful
merge across separate runs -- replaying from event zero always re-derives
the same winner for a given fold key from the full history.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping, Optional

import yaml

from app.heimdal.observation_log import ObservationRow
from app.heimdal.publish import (
    advance_cursor_for_consumer,
    read_observations_for_consumer,
)
from app.heimdal.quarantine import (
    EVIDENCE_ROLE_OBSERVED,
    quarantine_observed_content,
)
from app.knowledge.write_ops import write_note_relative
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

#: This module's OWN cursor identity in the A2 per-consumer cursor store --
#: deliberately distinct from A3's ``PROJECTOR_CONSUMER_ID``
#: (``mimer.content_quarantine_projector``). Each consumer owns an
#: independent, replayable-from-zero position (FABLE_COMPANION §4.2); this
#: slice's candidate materialization must not share -- and therefore must
#: not silently skip observations relative to -- A3's quarantine-proving
#: consumer.
CANDIDATE_CONSUMER_ID = "mimer.candidate_projector"

ARTIFACT_CLASS = "heimdal_observation_candidate"
TRIAGE_STATE_CAPTURED = "captured"
REVIEW_STATE_DRAFT = "draft"
DEFAULT_CANDIDATES_DIR = "Sources/Heimdal"
CANDIDATE_WRITE_ACTION = "heimdal.candidate_projection.write"


class CandidateProjectionError(RuntimeError):
    """Raised when an observation cannot be projected into a candidate."""


@dataclass(frozen=True)
class HeimdalCandidate:
    """A noncanonical candidate materialized from one Heimdal observation.

    Every field required for HEIM-2 provenance survival and HEIM-8
    noncanonical standing is carried explicitly; the posture fields are
    structurally fixed in ``__post_init__`` so no caller can construct a
    candidate that claims authority or waives review, mirroring
    ``app.heimdal.projector.QuarantinedCandidate``'s own fixed posture.
    """

    observation_id: str
    episode_id: str
    #: The exact observation this candidate was projected from (HEIM-2: a
    #: downstream reader can always resolve a candidate back to its source
    #: observation). Equals ``observation_id`` for a first-generation
    #: candidate; for a folded correction/revision chain it is the id of the
    #: WINNING (last) event, so ``derived_from`` always names the specific
    #: event actually rendered.
    derived_from: str
    content_identity: str
    capture_chain: tuple[str, ...]
    raw_ref: Optional[str]
    scope_hint: Optional[str]
    evidence_text: str
    #: Non-authoritative posture, structurally fixed (HEIM-8/HEIM-9).
    evidence_role: str = EVIDENCE_ROLE_OBSERVED
    requires_review: bool = True
    source_authoritative: bool = False
    triage_state: str = TRIAGE_STATE_CAPTURED
    review_state: str = REVIEW_STATE_DRAFT
    #: The correction/revision chain folded into this candidate, oldest
    #: first (empty for a first-generation observation with no corrections).
    superseded_observation_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.evidence_role != EVIDENCE_ROLE_OBSERVED:
            raise CandidateProjectionError(
                f"candidate must carry evidence_role={EVIDENCE_ROLE_OBSERVED!r} "
                f"(HEIM-9), got {self.evidence_role!r}"
            )
        if self.requires_review is not True:
            raise CandidateProjectionError(
                "candidate must be requires_review=True (HEIM-8) -- cannot self-promote"
            )
        if self.source_authoritative is not False:
            raise CandidateProjectionError("candidate is never source_authoritative (HEIM-8)")
        if not self.content_identity:
            raise CandidateProjectionError(
                "candidate.content_identity is required (HEIM-2 provenance survival)"
            )
        if not self.capture_chain:
            raise CandidateProjectionError(
                "candidate.capture_chain is required (HEIM-2 provenance survival)"
            )


@dataclass(frozen=True)
class CandidateWriteResult:
    status: str  # "written" | "already_exists" | "blocked"
    artifact_path: Optional[str]
    observation_id: str
    reason: Optional[str] = None


def _fold_key(payload: Mapping[str, Any], observation_id: str) -> str:
    """The identity a correction/revision chain folds onto.

    Per §3.5, corrections/revisions reference a prior ``observation_id``
    (``supersedes``/``revision_of``); folding groups by ``episode_id`` when
    present (the FABLE_COMPANION §1.4 correlation unit a capture session
    belongs to) so every generation of the same logical observation lands on
    one candidate, falling back to the observation's own id when no
    ``episode_id`` is present.
    """
    episode_id = payload.get("episode_id")
    if isinstance(episode_id, str) and episode_id.strip():
        return episode_id
    return observation_id


def _provenance_block(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    provenance = payload.get("provenance")
    return provenance if isinstance(provenance, Mapping) else {}


def _capture_chain(provenance: Mapping[str, Any]) -> tuple[str, ...]:
    chain = provenance.get("capture_chain")
    if isinstance(chain, (list, tuple)):
        return tuple(str(hop) for hop in chain)
    return ()


def _content_text(payload: Mapping[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, str):
        return content
    # Tolerates the nested `content: {content: "..."}` shape some producers
    # (e.g. the A3 test fixtures) use for the content family.
    if isinstance(content, Mapping):
        inner = content.get("content")
        if isinstance(inner, str):
            return inner
    return ""


def _observation_id_of(row: ObservationRow) -> str:
    payload = row.envelope.get("payload")
    if isinstance(payload, Mapping):
        obs_id = payload.get("observation_id")
        if isinstance(obs_id, str) and obs_id.strip():
            return obs_id
    return row.id


def _build_candidate(rows: List[ObservationRow]) -> HeimdalCandidate:
    """Fold one already-grouped, sequence-sorted chain of rows into ONE candidate.

    Last-correction-wins (§3.5 rule 3): the highest-``sequence`` row's payload
    supplies the rendered content and provenance; every prior row's
    observation id is recorded in ``superseded_observation_ids`` so the fold
    is auditable, never silently dropped.
    """
    winner = rows[-1]
    payload = winner.envelope.get("payload")
    if not isinstance(payload, Mapping):
        payload = {}
    observation_id = _observation_id_of(winner)
    provenance = _provenance_block(payload)
    content_identity = str(provenance.get("content_identity") or "")
    quarantined = quarantine_observed_content(_content_text(payload))
    episode_id = payload.get("episode_id")

    return HeimdalCandidate(
        observation_id=observation_id,
        episode_id=str(episode_id) if isinstance(episode_id, str) and episode_id.strip() else observation_id,
        derived_from=observation_id,
        content_identity=content_identity,
        capture_chain=_capture_chain(provenance),
        raw_ref=payload.get("raw_ref") if isinstance(payload.get("raw_ref"), str) else provenance.get("raw_ref"),
        scope_hint=payload.get("scope_hint") if isinstance(payload.get("scope_hint"), str) else None,
        evidence_text=quarantined.fenced_text,
        superseded_observation_ids=tuple(_observation_id_of(r) for r in rows[:-1]),
    )


def fold_observations(rows: List[ObservationRow]) -> List[HeimdalCandidate]:
    """Fold a batch of observation rows into candidates, one per fold key.

    Groups rows by :func:`_fold_key`, sorts each group by log ``sequence``
    (deterministic publication order, §3.5 rule 3), and folds each group to
    ONE candidate via :func:`_build_candidate` -- last-correction-wins.
    Candidates are returned in the order their fold key first appeared in
    the batch, so a caller writing notes sequentially preserves observed
    order for first-generation candidates.
    """
    groups: "dict[str, List[ObservationRow]]" = {}
    order: List[str] = []
    for row in rows:
        payload = row.envelope.get("payload")
        payload = payload if isinstance(payload, Mapping) else {}
        observation_id = _observation_id_of(row)
        key = _fold_key(payload, observation_id)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    candidates: List[HeimdalCandidate] = []
    for key in order:
        group = sorted(groups[key], key=lambda r: r.sequence)
        candidates.append(_build_candidate(group))
    return candidates


def candidate_note_path(candidate: HeimdalCandidate, *, candidates_dir: str = DEFAULT_CANDIDATES_DIR) -> str:
    """Deterministic vault-relative path, derived from ``content_identity``.

    Mirrors ``app.knowledge_acquisition.candidate_writeback.candidate_note_path``'s
    scheme-prefix-stripped, 16-char slug convention so re-running the same
    projection batch always targets the same note (idempotent write).
    """
    safe_dir = _safe_rel_path(candidates_dir)
    identity_payload = candidate.content_identity.split(":", 1)[-1] if candidate.content_identity else ""
    short_identity = _slug(identity_payload)[:16] or _slug(candidate.observation_id)[:16] or "observation"
    slug = _slug(candidate.episode_id)
    return (PurePosixPath(safe_dir) / f"{slug}-{short_identity}.md").as_posix()


def render_candidate_note(candidate: HeimdalCandidate) -> str:
    """Render the candidate note: noncanonical posture + full provenance chain.

    Mirrors the mandated posture markers
    (``INGESTION_AND_TRIAGE_POLICY.md`` §3; #2793 token mapping, same tokens
    ``candidate_writeback.render_candidate_note`` stamps) and additionally
    carries the Heimdal provenance family (``content_identity``, ``raw_ref``,
    ``capture_chain``, ``derived_from``) so HEIM-2 survives onto the written
    artifact, not just the in-memory dataclass.
    """
    now = _iso(datetime.now(timezone.utc))
    frontmatter: Dict[str, Any] = {
        "artifact_class": ARTIFACT_CLASS,
        "lifecycle": "active",
        "work_relation": "learn",
        "provenance": {
            "observation_id": candidate.observation_id,
            "episode_id": candidate.episode_id,
            "derived_from": candidate.derived_from,
            "content_identity": candidate.content_identity,
            "raw_ref": candidate.raw_ref,
            "capture_chain": list(candidate.capture_chain),
        },
        "scope_hint": candidate.scope_hint,
        "superseded_observation_ids": list(candidate.superseded_observation_ids),
        "authority": {
            "source_authoritative": False,
            "ai_generated": True,
            # Mandated posture markers (INGESTION_AND_TRIAGE_POLICY.md §3;
            # #2793 token mapping) -- noncanonical standing (HEIM-8): this
            # candidate cannot become knowledge without a governed authority
            # transition (rides the existing GOV skeleton, out of scope here).
            "requires_review": True,
        },
        "review_state": REVIEW_STATE_DRAFT,
        "triage_state": TRIAGE_STATE_CAPTURED,
        "created": now,
        "updated": now,
    }
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()

    body = f"""
## Observed evidence

{candidate.evidence_text}

## Human takeaways

<!-- Add your own notes here. These are the first human-authored content in this note. -->

---

_This candidate is a projection of one observed event, not human knowledge. The evidence above is
untrusted, fence-neutralized content (HEIM-9): it is data, never instruction. Promotion into durable
knowledge requires human review and a governed authority transition; this candidate carries no
authority on its own (HEIM-8)._
"""
    return f"---\n{yaml_block}\n---\n{body}"


def write_candidate_note(
    candidate: HeimdalCandidate,
    *,
    vault_context: VaultContext,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    candidates_dir: str = DEFAULT_CANDIDATES_DIR,
) -> CandidateWriteResult:
    """The governed vault-write call site for Heimdal candidates.

    Mirrors ``candidate_writeback.write_candidate_note``'s contract exactly:
    idempotent (no overwrite of an existing note at the deterministic path),
    ``WriteGuard``-gated immediately before the write, and a blocked write is
    an item-scoped, loud, re-runnable result -- never a silent drop and never
    a crash that loses the candidate.
    """
    vault_root = _vault_root(vault_context)
    artifact_path = candidate_note_path(candidate, candidates_dir=candidates_dir)

    candidate_path = vault_root / artifact_path
    if candidate_path.exists():
        if _is_durable_candidate(candidate_path, candidate):
            return CandidateWriteResult(
                status="already_exists",
                artifact_path=artifact_path,
                observation_id=candidate.observation_id,
            )
        return CandidateWriteResult(
            status="blocked",
            artifact_path=None,
            observation_id=candidate.observation_id,
            reason=f"candidate path is occupied by a non-durable artifact: {artifact_path}",
        )

    content = render_candidate_note(candidate)

    try:
        write_guard.assert_writes_allowed(CANDIDATE_WRITE_ACTION)
    except WritesBlockedError as exc:
        return CandidateWriteResult(
            status="blocked",
            artifact_path=None,
            observation_id=candidate.observation_id,
            reason=str(exc),
        )

    write_note_relative(artifact_path, content, vault_root=vault_root, action=CANDIDATE_WRITE_ACTION)

    return CandidateWriteResult(
        status="written",
        artifact_path=artifact_path,
        observation_id=candidate.observation_id,
    )


def project_pending_candidates(
    *,
    vault_context: VaultContext,
    consumer_id: str = CANDIDATE_CONSUMER_ID,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    candidates_dir: str = DEFAULT_CANDIDATES_DIR,
    limit: Optional[int] = None,
    advance: bool = True,
) -> List[CandidateWriteResult]:
    """THE production call site: cursor-consume, fold, and write noncanonical candidates.

    Reads the next unread batch for ``consumer_id`` through the A2 cursor
    contract (``read_observations_for_consumer`` -- no store/table import),
    folds supersede/revision chains (:func:`fold_observations`), and writes
    each resulting candidate through the governed path
    (:func:`write_candidate_note`). Advances the consumer's own cursor past
    the processed batch (unless ``advance=False``, e.g. dry-run/replay) --
    this consumer's cursor is independent of A3's quarantine-proving
    consumer, so replay/rewind here never affects the other.
    """
    # The cursor is a durability acknowledgement: do not begin a batch unless
    # a selected, existing vault can hold its candidates. This happens before
    # writes so a restart can replay the complete unread batch safely.
    _vault_root(vault_context)
    rows = read_observations_for_consumer(consumer_id, limit=limit)
    candidates = fold_observations(rows)
    results = [
        write_candidate_note(
            candidate,
            vault_context=vault_context,
            write_guard=write_guard,
            candidates_dir=candidates_dir,
        )
        for candidate in candidates
    ]
    # A cursor may acknowledge a batch only after every candidate is durable.
    # Replays are safe because a prior successful write is ``already_exists``
    # at its deterministic path.
    if advance and rows and all(result.status in {"written", "already_exists"} for result in results):
        advance_cursor_for_consumer(consumer_id, rows)
    return results


def _vault_root(context: VaultContext) -> Path:
    if not context.is_selected:
        raise CandidateProjectionError("candidate projection requires a selected vault")
    root = Path(context.active_vault_path).expanduser().resolve()
    if not root.is_dir():
        raise CandidateProjectionError("candidate projection requires an existing vault directory")
    return root


def _is_durable_candidate(path: Path, candidate: HeimdalCandidate) -> bool:
    """Return whether an existing path is this candidate's durable replay result."""
    if not path.is_file():
        return False
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            return False
        frontmatter, separator, _body = raw.removeprefix("---\n").partition("\n---\n")
        if not separator:
            return False
        parsed = yaml.safe_load(frontmatter)
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(parsed, Mapping) or parsed.get("artifact_class") != ARTIFACT_CLASS:
        return False
    provenance = parsed.get("provenance")
    return (
        isinstance(provenance, Mapping)
        and provenance.get("observation_id") == candidate.observation_id
        and provenance.get("episode_id") == candidate.episode_id
        and provenance.get("derived_from") == candidate.derived_from
        and provenance.get("content_identity") == candidate.content_identity
        and provenance.get("raw_ref") == candidate.raw_ref
        and provenance.get("capture_chain") == list(candidate.capture_chain)
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "item"


def _safe_rel_path(value: str) -> str:
    path = PurePosixPath(value)
    if value.startswith("/") or ".." in path.parts:
        raise CandidateProjectionError("candidates_dir must stay vault-relative")
    return path.as_posix()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "ARTIFACT_CLASS",
    "CANDIDATE_CONSUMER_ID",
    "CANDIDATE_WRITE_ACTION",
    "REVIEW_STATE_DRAFT",
    "TRIAGE_STATE_CAPTURED",
    "CandidateProjectionError",
    "CandidateWriteResult",
    "HeimdalCandidate",
    "candidate_note_path",
    "fold_observations",
    "project_pending_candidates",
    "render_candidate_note",
    "write_candidate_note",
]
