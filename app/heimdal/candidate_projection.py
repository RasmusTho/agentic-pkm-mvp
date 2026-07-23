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

# Karakeep reading-source-note extension (KMA-04, #3375). The Karakeep source
# is discriminated by ``provenance.sensor == karakeep_rest``; its published
# evidence maps to a distinct ``reading_source_note`` candidate that preserves
# one candidate per immutable ``observation_id`` (not the generic episode fold),
# under its own deterministic path. It reuses this module's governed
# WriteGuard/write call site and the one ``mimer.candidate_projector`` cursor --
# no second consumer, projector, or read path.
KARAKEEP_SENSOR = "karakeep_rest"
READING_ARTIFACT_CLASS = "reading_source_note"
DEFAULT_READING_CANDIDATES_DIR = "Sources/Reading/Karakeep"
READING_CANDIDATE_WRITE_ACTION = "heimdal.candidate_projection.write_reading"


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
    if candidate_path.exists() or candidate_path.is_symlink():
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


# ---------------------------------------------------------------------------
# Karakeep reading-source-note extension (KMA-04, #3375)
# ---------------------------------------------------------------------------


def _payload_of(row: ObservationRow) -> Mapping[str, Any]:
    payload = row.envelope.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _is_karakeep(payload: Mapping[str, Any]) -> bool:
    return _provenance_block(payload).get("sensor") == KARAKEEP_SENSOR


def _karakeep_block(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    structure = payload.get("content_structure")
    if isinstance(structure, Mapping):
        block = structure.get("karakeep")
        if isinstance(block, Mapping):
            return block
    return {}


@dataclass(frozen=True)
class ReadingSourceCandidate:
    """A ``reading_source_note`` candidate materialized from one Karakeep observation.

    Preserves one candidate per immutable ``observation_id`` (a Karakeep item
    shares ``episode_id`` across source updates, reprocesses, and tombstones, so
    the generic episode fold would collapse distinct revisions). Posture is
    structurally fixed non-authoritative/review-required (KMA-INV-1); it can
    never self-promote or overwrite a human artifact.
    """

    observation_id: str
    episode_id: str
    item_id: str
    item_kind: str
    source_url: Optional[str]
    tags: tuple[str, ...]
    content_identity: str
    raw_ref: Optional[str]
    scope_hint: Optional[str]
    sequence: Optional[int]
    supersedes: Optional[str]
    revision_of: Optional[str]
    tombstone: bool
    evidence_text: str
    requires_review: bool = True
    source_authoritative: bool = False
    review_state: str = REVIEW_STATE_DRAFT
    triage_state: str = TRIAGE_STATE_CAPTURED

    def __post_init__(self) -> None:
        if self.requires_review is not True:
            raise CandidateProjectionError(
                "reading candidate must be requires_review=True (KMA-INV-1) -- cannot self-promote"
            )
        if self.source_authoritative is not False:
            raise CandidateProjectionError("reading candidate is never source_authoritative (KMA-INV-1)")
        if not self.content_identity:
            raise CandidateProjectionError("reading candidate.content_identity is required (provenance survival)")
        if not self.item_id:
            raise CandidateProjectionError("reading candidate.item_id is required")

    @property
    def revision_prefix(self) -> str:
        """The revision discriminator, derived from the immutable observation_id.

        ``observation_id`` is ``karakeep:<item-id>:<content-hex>:<profile-hex>``;
        the content-hex uniquely identifies this revision of the item.
        """
        parts = self.observation_id.rsplit(":", 2)
        content_hex = parts[1] if len(parts) == 3 else self.content_identity.split(":", 1)[-1]
        return content_hex[:16] or "rev"

    @property
    def prior_revision(self) -> Optional[str]:
        """The prior published revision this one links to (supersede or reprocess)."""
        return self.supersedes or self.revision_of


def build_reading_candidate(row: ObservationRow) -> ReadingSourceCandidate:
    """Build one reading candidate from a Karakeep published observation row.

    Consumes only the published evidence -- no Karakeep egress, no re-attribution
    (KMA-INV-4). Observed note/highlight text is quarantined before it becomes
    candidate content (HEIM-9); a tombstone carries no live content.
    """
    payload = row.envelope.get("payload")
    if not isinstance(payload, Mapping):
        payload = {}
    observation_id = _observation_id_of(row)
    episode_id = payload.get("episode_id")
    episode = str(episode_id) if isinstance(episode_id, str) and episode_id.strip() else observation_id
    item_id = episode.split(":", 1)[1] if episode.startswith("karakeep:") else episode
    provenance = _provenance_block(payload)
    karakeep = _karakeep_block(payload)
    tombstone = bool(karakeep.get("tombstone"))
    tags_raw = karakeep.get("tags")
    tags = tuple(str(t) for t in tags_raw) if isinstance(tags_raw, (list, tuple)) else ()
    text = _content_text(payload)
    evidence = "" if tombstone or not text else quarantine_observed_content(text).fenced_text

    sequence = payload.get("sequence")
    return ReadingSourceCandidate(
        observation_id=observation_id,
        episode_id=episode,
        item_id=item_id,
        item_kind=str(karakeep.get("item_kind") or "link"),
        source_url=karakeep.get("source_url") if isinstance(karakeep.get("source_url"), str) else None,
        tags=tags,
        content_identity=str(provenance.get("content_identity") or ""),
        raw_ref=payload.get("raw_ref") if isinstance(payload.get("raw_ref"), str) else provenance.get("raw_ref"),
        scope_hint=payload.get("scope_hint") if isinstance(payload.get("scope_hint"), str) else None,
        sequence=sequence if isinstance(sequence, int) else None,
        supersedes=payload.get("supersedes") if isinstance(payload.get("supersedes"), str) else None,
        revision_of=payload.get("revision_of") if isinstance(payload.get("revision_of"), str) else None,
        tombstone=tombstone,
        evidence_text=evidence,
    )


def reading_candidate_note_path(
    candidate: ReadingSourceCandidate, *, candidates_dir: str = DEFAULT_READING_CANDIDATES_DIR
) -> str:
    """Deterministic first-write-wins path: ``Sources/Reading/Karakeep/<item-id>-<revision-prefix>.md``.

    Keyed by the immutable ``observation_id`` (via item-id + revision-prefix), so
    each revision targets a distinct path and replay of the same revision always
    targets the same path (idempotent). A source update, reprocess, or tombstone
    lands at a new path and never overwrites a prior or human-reviewed note.
    """
    safe_dir = _safe_rel_path(candidates_dir)
    return (PurePosixPath(safe_dir) / f"{_slug(candidate.item_id)}-{candidate.revision_prefix}.md").as_posix()


def render_reading_candidate_note(candidate: ReadingSourceCandidate) -> str:
    """Render the reading candidate: source link + Heimdal/Karakeep provenance +
    quarantined notes/highlights + non-authoritative summary + empty human space."""
    now = _iso(datetime.now(timezone.utc))
    frontmatter: Dict[str, Any] = {
        "artifact_class": READING_ARTIFACT_CLASS,
        "lifecycle": "active",
        "work_relation": "learn",
        "source": {
            "provider": "karakeep",
            "item_kind": candidate.item_kind,
            "url": candidate.source_url,
            "tags": list(candidate.tags),
        },
        "provenance": {
            "sensor": KARAKEEP_SENSOR,
            "observation_id": candidate.observation_id,
            "episode_id": candidate.episode_id,
            "derived_from": candidate.observation_id,
            "content_identity": candidate.content_identity,
            "raw_ref": candidate.raw_ref,
            "sequence": candidate.sequence,
            "supersedes": candidate.supersedes,
            "revision_of": candidate.revision_of,
        },
        "scope_hint": candidate.scope_hint,
        "tombstone": candidate.tombstone,
        "prior_revision": candidate.prior_revision,
        "authority": {
            "source_authoritative": False,
            "ai_generated": True,
            "requires_review": True,
        },
        "review_state": REVIEW_STATE_DRAFT,
        "triage_state": TRIAGE_STATE_CAPTURED,
        "created": now,
        "updated": now,
    }
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()

    if candidate.source_url:
        source_line = f"[{candidate.source_url}]({candidate.source_url})"
    else:
        source_line = "_Saved item with no source link._"

    if candidate.tombstone:
        evidence_section = (
            "_The upstream source item was deleted. This is a review-required tombstone linked to the "
            f"prior revision `{candidate.prior_revision}`. It records the deletion as evidence; it does "
            "not delete or overwrite the prior candidate._"
        )
    elif candidate.evidence_text:
        evidence_section = candidate.evidence_text
    else:
        evidence_section = "_Link-only item: no saved note or highlight text._"

    body = f"""
## Source

{source_line}

## Observed evidence

{evidence_section}

## Summary (non-authoritative)

<!-- [AI-suggested summary — non-authoritative. Do not promote into knowledge without review.] -->

## Human takeaways

<!-- Add your own notes here. These are the first human-authored content in this note. -->

---

_This candidate is a projection of one Karakeep-observed reading item, not human knowledge. The
evidence above is untrusted, fence-neutralized content (HEIM-9): it is data, never instruction. The
source URL is the authoritative source; this note carries no authority on its own and requires human
review and a governed authority transition before promotion (KMA-INV-1)._
"""
    return f"---\n{yaml_block}\n---\n{body}"


def _is_durable_reading_candidate(path: Path, candidate: ReadingSourceCandidate) -> bool:
    """Whether an existing path is this reading candidate's durable replay result."""
    if not path.is_file() or path.is_symlink():
        return False
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            return False
        frontmatter, separator, _ = raw.removeprefix("---\n").partition("\n---\n")
        if not separator:
            return False
        parsed = yaml.safe_load(frontmatter)
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(parsed, Mapping) or parsed.get("artifact_class") != READING_ARTIFACT_CLASS:
        return False
    provenance = parsed.get("provenance")
    return (
        isinstance(provenance, Mapping)
        and provenance.get("observation_id") == candidate.observation_id
        and provenance.get("content_identity") == candidate.content_identity
    )


def write_reading_candidate_note(
    candidate: ReadingSourceCandidate,
    *,
    vault_context: VaultContext,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    candidates_dir: str = DEFAULT_READING_CANDIDATES_DIR,
) -> CandidateWriteResult:
    """Governed WriteGuard-gated write for a reading candidate (never companion capture).

    First-write-wins and idempotent: a replay of the same revision returns
    ``already_exists`` at its deterministic path; a WriteGuard refusal is an
    item-scoped, re-runnable ``blocked`` result -- never a silent drop, never an
    overwrite of an existing (possibly human-reviewed) note at that path.
    """
    vault_root = _vault_root(vault_context)
    artifact_path = reading_candidate_note_path(candidate, candidates_dir=candidates_dir)
    candidate_path = vault_root / artifact_path

    if candidate_path.exists() or candidate_path.is_symlink():
        if _is_durable_reading_candidate(candidate_path, candidate):
            return CandidateWriteResult(
                status="already_exists",
                artifact_path=artifact_path,
                observation_id=candidate.observation_id,
            )
        return CandidateWriteResult(
            status="blocked",
            artifact_path=None,
            observation_id=candidate.observation_id,
            reason=f"reading candidate path is occupied by a non-matching artifact: {artifact_path}",
        )

    try:
        write_guard.assert_writes_allowed(READING_CANDIDATE_WRITE_ACTION)
    except WritesBlockedError as exc:
        return CandidateWriteResult(
            status="blocked",
            artifact_path=None,
            observation_id=candidate.observation_id,
            reason=str(exc),
        )

    content = render_reading_candidate_note(candidate)
    write_note_relative(artifact_path, content, vault_root=vault_root, action=READING_CANDIDATE_WRITE_ACTION)
    return CandidateWriteResult(
        status="written",
        artifact_path=artifact_path,
        observation_id=candidate.observation_id,
    )


@dataclass(frozen=True)
class _PlannedWrite:
    """One materialization unit and the log rows it durably acknowledges."""

    rows: tuple[ObservationRow, ...]
    kind: str  # "heimdal" | "karakeep"
    candidate: Any


def _plan_writes(rows: List[ObservationRow]) -> List[_PlannedWrite]:
    """Plan materialization units in earliest-row order.

    Karakeep rows (``sensor == karakeep_rest``) each become one reading
    candidate keyed by their immutable ``observation_id`` -- never folded onto a
    shared ``episode_id``. Non-Karakeep rows keep the existing episode fold
    (last-correction-wins). Units are ordered by their earliest covered log
    sequence so results and cursor advancement follow publication order.
    """
    karakeep_rows: List[ObservationRow] = []
    heimdal_rows: List[ObservationRow] = []
    for row in rows:
        (karakeep_rows if _is_karakeep(_payload_of(row)) else heimdal_rows).append(row)

    planned: List[_PlannedWrite] = []
    # Non-Karakeep rows keep the existing episode fold (last-correction-wins),
    # grouped here so each unit records the exact rows it acknowledges.
    groups: "dict[str, List[ObservationRow]]" = {}
    order: List[str] = []
    for row in heimdal_rows:
        key = _fold_key(_payload_of(row), _observation_id_of(row))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    for key in order:
        group = sorted(groups[key], key=lambda r: r.sequence)
        planned.append(_PlannedWrite(rows=tuple(group), kind="heimdal", candidate=_build_candidate(group)))
    for row in karakeep_rows:
        planned.append(_PlannedWrite(rows=(row,), kind="karakeep", candidate=build_reading_candidate(row)))

    planned.sort(key=lambda unit: min(r.sequence for r in unit.rows))
    return planned


def _durable_prefix(
    rows: List[ObservationRow], planned: List[_PlannedWrite], durable: Dict[int, bool]
) -> List[ObservationRow]:
    """The contiguous prefix of rows (by log sequence) that is safe to acknowledge.

    The acknowledgement boundary starts at the first non-durable row and is then
    lowered by any durable materialization unit that *straddles* it (a folded
    chain with rows on both sides). Every row below the final boundary belongs to
    a fully-durable, non-straddling unit, so acknowledging up to it never
    half-commits a folded chain and never consumes a row that sits beneath a
    blocked one. Because ``advance_cursor_for_consumer`` advances to
    ``max(sequence)+1`` and the batch is a contiguous read from the cursor, the
    returned prefix advances exactly to that boundary; a later successful row
    above the boundary stays unread and replays rather than being skipped
    (KMA-INV-3).
    """
    if not rows:
        return []

    unit_of: Dict[int, int] = {}
    unit_min: Dict[int, int] = {}
    unit_max: Dict[int, int] = {}
    unit_durable: Dict[int, bool] = {}
    for index, unit in enumerate(planned):
        seqs = [row.sequence for row in unit.rows]
        unit_min[index] = min(seqs)
        unit_max[index] = max(seqs)
        unit_durable[index] = all(durable.get(seq, False) for seq in seqs)
        for seq in seqs:
            unit_of[seq] = index

    ordered = sorted(rows, key=lambda r: r.sequence)
    boundary: Optional[int] = None
    for row in ordered:
        if not unit_durable[unit_of[row.sequence]]:
            boundary = row.sequence
            break
    if boundary is None:
        return ordered  # every unit durable -- acknowledge the whole batch

    changed = True
    while changed:
        changed = False
        for index, is_durable in unit_durable.items():
            if is_durable and unit_min[index] < boundary <= unit_max[index]:
                boundary = unit_min[index]
                changed = True
    return [row for row in ordered if row.sequence < boundary]


def project_pending_candidates(
    *,
    vault_context: VaultContext,
    consumer_id: str = CANDIDATE_CONSUMER_ID,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    candidates_dir: str = DEFAULT_CANDIDATES_DIR,
    reading_candidates_dir: str = DEFAULT_READING_CANDIDATES_DIR,
    limit: Optional[int] = None,
    advance: bool = True,
) -> List[CandidateWriteResult]:
    """THE production call site: cursor-consume, materialize, and advance a durable prefix.

    Reads the next unread batch for ``consumer_id`` through the A2 cursor
    contract (``read_observations_for_consumer`` -- no store/table import).
    Non-Karakeep observations fold supersede/revision chains
    (:func:`fold_observations`) and write through :func:`write_candidate_note`;
    Karakeep observations write one ``reading_source_note`` per immutable
    ``observation_id`` through :func:`write_reading_candidate_note`. Both use the
    governed WriteGuard call site and this one consumer's cursor -- no second
    consumer, projector, read path, or companion capture.

    Cursor advancement (KMA-INV-3): the consumer's own cursor advances only
    across the contiguous durable prefix of rows whose materialization returned
    ``written``/``already_exists``. A WriteGuard refusal or item-scoped failure
    stops the prefix at that row, so a later successful row is never skipped --
    it replays on the next run. Replays are safe because a prior successful write
    is ``already_exists`` at its deterministic path.
    """
    # The cursor is a durability acknowledgement: do not begin a batch unless a
    # selected, existing vault can hold its candidates. This happens before
    # writes so a restart can replay the complete unread batch safely.
    _vault_root(vault_context)
    rows = read_observations_for_consumer(consumer_id, limit=limit)
    planned = _plan_writes(rows)

    results: List[CandidateWriteResult] = []
    durable: Dict[int, bool] = {}
    for unit in planned:
        if unit.kind == "karakeep":
            result = write_reading_candidate_note(
                unit.candidate,
                vault_context=vault_context,
                write_guard=write_guard,
                candidates_dir=reading_candidates_dir,
            )
        else:
            result = write_candidate_note(
                unit.candidate,
                vault_context=vault_context,
                write_guard=write_guard,
                candidates_dir=candidates_dir,
            )
        results.append(result)
        is_durable = result.status in {"written", "already_exists"}
        for row in unit.rows:
            durable[row.sequence] = is_durable

    if advance and rows:
        prefix = _durable_prefix(rows, planned, durable)
        if prefix:
            advance_cursor_for_consumer(consumer_id, prefix)
    return results


def _vault_root(context: VaultContext) -> Path:
    if not context.is_selected:
        raise CandidateProjectionError("candidate projection requires a selected vault")
    active_vault_path = context.active_vault_path
    if active_vault_path is None:
        raise CandidateProjectionError("candidate projection requires a selected vault")
    root = Path(active_vault_path).expanduser().resolve()
    if not root.is_dir():
        raise CandidateProjectionError("candidate projection requires an existing vault directory")
    return root


def _is_durable_candidate(path: Path, candidate: HeimdalCandidate) -> bool:
    """Return whether an existing path is this candidate's durable replay result."""
    if not path.is_file() or path.is_symlink():
        return False
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            return False
        frontmatter, separator, body = raw.removeprefix("---\n").partition("\n---\n")
        if not separator:
            return False
        parsed = yaml.safe_load(frontmatter)
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(parsed, Mapping) or parsed.get("artifact_class") != ARTIFACT_CLASS:
        return False
    provenance = parsed.get("provenance")
    authority = parsed.get("authority")
    return (
        isinstance(provenance, Mapping)
        and isinstance(authority, Mapping)
        and provenance.get("observation_id") == candidate.observation_id
        and provenance.get("episode_id") == candidate.episode_id
        and provenance.get("derived_from") == candidate.derived_from
        and provenance.get("content_identity") == candidate.content_identity
        and provenance.get("raw_ref") == candidate.raw_ref
        and provenance.get("capture_chain") == list(candidate.capture_chain)
        and parsed.get("scope_hint") == candidate.scope_hint
        and parsed.get("superseded_observation_ids") == list(candidate.superseded_observation_ids)
        and parsed.get("lifecycle") == "active"
        and parsed.get("work_relation") == "learn"
        and authority.get("source_authoritative") is False
        and authority.get("ai_generated") is True
        and authority.get("requires_review") is True
        and parsed.get("review_state") == REVIEW_STATE_DRAFT
        and parsed.get("triage_state") == TRIAGE_STATE_CAPTURED
        and body.startswith(
            f"\n## Observed evidence\n\n{candidate.evidence_text}\n\n## Human takeaways\n"
        )
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
    "DEFAULT_READING_CANDIDATES_DIR",
    "KARAKEEP_SENSOR",
    "READING_ARTIFACT_CLASS",
    "READING_CANDIDATE_WRITE_ACTION",
    "REVIEW_STATE_DRAFT",
    "TRIAGE_STATE_CAPTURED",
    "CandidateProjectionError",
    "CandidateWriteResult",
    "HeimdalCandidate",
    "ReadingSourceCandidate",
    "build_reading_candidate",
    "candidate_note_path",
    "fold_observations",
    "project_pending_candidates",
    "reading_candidate_note_path",
    "render_candidate_note",
    "render_reading_candidate_note",
    "write_candidate_note",
    "write_reading_candidate_note",
]
