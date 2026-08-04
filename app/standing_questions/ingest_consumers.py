"""Production ingest-consumer wiring for SQ-03 evidence matching (#4610).

``docs/STANDING_QUESTIONS/MATCH_EVIDENCE_TO_OPEN_QUESTIONS.md`` names exactly
three existing ingest paths whose artifacts must be checked against open
questions -- Heimdal captures (observation-log cursor, the same read path the
Episode Resolution Engine consumes through ``app/heimdal/publish.py``), KAP
candidates (``knowledge_acquisition.stage.completed`` outbox topic), and
new/edited vault notes (``ingest.vault.changed`` / ``ingest.object.created``
outbox topics). PR #4588 shipped the matcher with no caller on any of them;
this module is that wiring and nothing more: it constructs
:class:`~app.standing_questions.evidence_matching.CandidateArtifact` values
from what each consumer already holds and invokes the existing matching tick.
It adds **no** acquisition source, mutates **no** artifact, and leaves the
matching threshold and provenance semantics untouched.

Failure posture is per-path:

- The worker-handler paths (vault ingest, KA completion) are **never-crash**:
  standing-question matching is a downstream consumer of an ingest that already
  succeeded, so a matching failure logs loudly and returns ``None`` instead of
  failing (and retry-looping or dead-lettering) the ingest dispatch itself.
  Matching is idempotent per ``(question_id, artifact_ref)``, so losing one
  tick to degradation is recoverable by any later pass over the same artifact.
- The Heimdal cursor tick is **fail-loud with at-least-once delivery**: the
  cursor only advances after the tick completes, so a crashed tick re-reads the
  same observations next time (mirrors the ERE consumer contract).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Mapping

from app.events.types import (
    INGEST_OBJECT_CREATED,
    INGEST_VAULT_CHANGED,
    KNOWLEDGE_ACQUISITION_STAGE_COMPLETED,
)
from app.heimdal.observation_log import ObservationRow
from app.heimdal.publish import advance_cursor_for_consumer, read_observations_for_consumer
from app.standing_questions.evidence_matching import (
    CandidateArtifact,
    MatchTickSummary,
    match_evidence_to_open_questions,
)
from app.standing_questions.question_store import QUESTION_DIRECTORY
from app.watcher.vault_watcher import extract_context_dimensions_for_note
from app.write_guard import WritesBlockedError
from scripts.yaml_roundtrip import load_frontmatter

_LOGGER = logging.getLogger(__name__)

#: This consumer's own durable cursor over the Heimdal observation log. A new
#: consumer id starts at sequence zero and never touches another consumer's
#: position (``app/heimdal/publish.py`` contract) -- registering it here is the
#: whole "no new egress" Heimdal integration: same log, same read path as
#: ``mimer.episode_resolution_engine``, one more independent cursor.
HEIMDAL_EVIDENCE_CONSUMER_ID = "mimer.standing_questions.evidence_matching"

#: Source-stream tag for Heimdal-sourced candidates; matches the
#: ``heimdal.observations:<id>`` provenance-ref family the ERE already stamps.
HEIMDAL_SOURCE_STREAM = "heimdal.observations"

#: Scope for artifacts that resolve no scope of their own -- the same posture as
#: the ERE's ``_DEFAULT_SCOPE`` (``app/episodes/segmenter.py``): unscoped
#: artifacts land in "default" and are content-free excluded against any
#: question registered under a real scope.
DEFAULT_ARTIFACT_SCOPE = "default"

# The KA pipeline stage whose completion means a candidate note now exists
# (mirrors `_KA_CANDIDATE_STAGE` in the worker's own KA consumer): only this
# terminal stage offers an artifact to match.
_KA_CANDIDATE_STAGE = "candidate"


def _is_question_note_path(relative_path: str) -> bool:
    """True when the path is an engine-owned Question note (#4610 review).

    Question notes live in the watched vault, so every matcher append re-enters
    ingest as a new `ingest.vault.changed` event. Offering the question's own
    note back to the matcher as candidate evidence would let questions cite
    themselves, grow their own artifact text on every append, and burn one LLM
    judgment per open question per cycle. The engine's own output is never its
    own evidence.
    """
    parts = Path(relative_path).parts
    return bool(parts) and parts[0] == QUESTION_DIRECTORY


def _resolve_note_scope(
    vault_root: Path,
    relative_path: str,
    frontmatter: Mapping[str, Any] | None,
) -> str:
    """Resolve a vault note's scope, never raising.

    Uses the caller's already-parsed frontmatter when supplied; otherwise reads
    the note best-effort (a missing or malformed note yields the default scope
    -- the matcher's own resolution step will independently count it
    unresolved if the content is also gone by match time).
    """
    if frontmatter is None:
        try:
            text = (vault_root / relative_path).read_text(encoding="utf-8")
            frontmatter, _body = load_frontmatter(text)
        except Exception:
            frontmatter = {}
    dims = extract_context_dimensions_for_note(dict(frontmatter))
    scope = dims.get("scope")
    return scope if isinstance(scope, str) and scope.strip() else DEFAULT_ARTIFACT_SCOPE


def vault_note_candidate(
    *,
    vault_root: Path,
    relative_path: str,
    source_stream: str,
    frontmatter: Mapping[str, Any] | None = None,
    content: str | None = None,
) -> CandidateArtifact | None:
    """Build the candidate for one new/edited vault note.

    Returns ``None`` for engine-owned Question notes: the matcher's own writes
    re-enter ingest through the watcher, and a question must never become its
    own evidence.
    """
    if _is_question_note_path(relative_path):
        return None
    artifact_ref = f"vault://{Path(relative_path).as_posix()}"
    return CandidateArtifact(
        artifact_ref=artifact_ref,
        source_stream=source_stream,
        scope=_resolve_note_scope(vault_root, relative_path, frontmatter),
        provenance_ref=f"outbox://{source_stream}/{artifact_ref}",
        content=content,
    )


def candidate_from_ingest_object_created(
    payload: Mapping[str, Any],
    *,
    vault_root: Path,
) -> CandidateArtifact | None:
    """Candidate for one ``ingest.object.created`` event, or ``None``.

    The topic carries two producer shapes: vault-side emissions with a note
    path (resolved like the vault-changed path) and API-side ``POST /ingest``
    emissions with inline ``content`` and no vault path (resolved as an
    ``object://`` ref whose content travels with the candidate). A payload
    with neither offers nothing to match.
    """
    relative_path = payload.get("relative_path")
    if isinstance(relative_path, str) and relative_path.strip():
        return vault_note_candidate(
            vault_root=vault_root,
            relative_path=relative_path.strip(),
            source_stream=INGEST_OBJECT_CREATED,
        )
    vault_path = payload.get("vault_path") or payload.get("path")
    if isinstance(vault_path, str) and vault_path.strip():
        try:
            rel = Path(vault_path).expanduser().resolve().relative_to(vault_root.resolve())
        except (ValueError, OSError):
            rel = None
        if rel is not None:
            return vault_note_candidate(
                vault_root=vault_root,
                relative_path=rel.as_posix(),
                source_stream=INGEST_OBJECT_CREATED,
            )
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    object_id = payload.get("uuid") or payload.get("object_id")
    if not object_id:
        # A path-less, id-less producer still offers matchable content; a
        # content-hash ref keeps the idempotency fold key stable across
        # redelivery of the same payload.
        object_id = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    # POST /ingest carries no separate frontmatter field, but its content may
    # itself be a frontmattered note -- resolve scope from it so API-ingested
    # artifacts are not silently unmatchable against scoped questions.
    scope = DEFAULT_ARTIFACT_SCOPE
    try:
        content_frontmatter, _body = load_frontmatter(content)
    except Exception:
        content_frontmatter = None
    if isinstance(content_frontmatter, Mapping) and content_frontmatter:
        dims = extract_context_dimensions_for_note(dict(content_frontmatter))
        resolved = dims.get("scope")
        if isinstance(resolved, str) and resolved.strip():
            scope = resolved
    artifact_ref = f"object://{object_id}"
    return CandidateArtifact(
        artifact_ref=artifact_ref,
        source_stream=INGEST_OBJECT_CREATED,
        scope=scope,
        provenance_ref=f"outbox://{INGEST_OBJECT_CREATED}/{artifact_ref}",
        content=content,
    )


def candidate_from_ka_stage_completed(
    payload: Mapping[str, Any],
    *,
    vault_root: Path,
) -> CandidateArtifact | None:
    """Candidate for one KA ``stage.completed`` event, or ``None``.

    Only a ``candidate``-stage completion means a candidate note now exists
    (the worker's own KA consumer draws the same line); intermediate stages
    offer nothing to match. The note is read-only downstream: content resolves
    through the matcher's own vault-ref read path at match time.
    """
    if str(payload.get("stage") or "") != _KA_CANDIDATE_STAGE:
        return None
    artifact_path = payload.get("artifact_path")
    if not isinstance(artifact_path, str) or not artifact_path.strip():
        return None
    content_identity = str(payload.get("content_identity") or "")
    relative_path = artifact_path.strip()
    if _is_question_note_path(relative_path):
        return None
    return CandidateArtifact(
        artifact_ref=f"vault://{Path(relative_path).as_posix()}",
        source_stream=KNOWLEDGE_ACQUISITION_STAGE_COMPLETED,
        scope=_resolve_note_scope(vault_root, relative_path, None),
        provenance_ref=f"knowledge_acquisition:{content_identity or relative_path}",
        content=None,
    )


def candidate_from_heimdal_observation(row: ObservationRow) -> CandidateArtifact | None:
    """Candidate for one observation-log row, or ``None``.

    An observation without published ``content`` (withheld, consent-gated, or
    simply content-free) offers no text to judge and yields no candidate --
    never a fabricated one. Scope comes from the payload's own ``scope_hint``,
    the same field the ERE normalizes, defaulting like the ERE does.
    """
    payload = row.envelope.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    observation_id = payload.get("observation_id")
    if not isinstance(observation_id, str) or not observation_id.strip():
        return None
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    scope_hint = payload.get("scope_hint")
    scope = (
        scope_hint.strip()
        if isinstance(scope_hint, str) and scope_hint.strip()
        else DEFAULT_ARTIFACT_SCOPE
    )
    return CandidateArtifact(
        artifact_ref=f"heimdal://observations/{observation_id}",
        source_stream=HEIMDAL_SOURCE_STREAM,
        scope=scope,
        provenance_ref=f"heimdal.observations:{observation_id}",
        content=content,
    )


def _never_crash_match(
    candidate: CandidateArtifact | None,
    *,
    vault_root: Path,
    source: str,
    trace_id: str | None,
) -> MatchTickSummary | None:
    if candidate is None:
        return None
    try:
        return match_evidence_to_open_questions(
            vault_root=vault_root,
            candidates=[candidate],
            trace_id=trace_id,
        )
    except WritesBlockedError as exc:
        # A blocked runtime is a systemic condition, not a one-off matching
        # failure -- name it distinctly so operators can tell them apart. The
        # ingest dispatch itself still proceeds (matcher writes are the only
        # thing refused, and re-ticking is idempotent).
        _LOGGER.warning(
            "standing-question evidence matching blocked by WriteGuard for %s artifact %s: %s",
            source,
            candidate.artifact_ref,
            exc,
        )
        return None
    except Exception:
        # Loud, never silent -- but a matching failure must not fail (or
        # retry-loop) the ingest dispatch that already succeeded upstream.
        _LOGGER.exception(
            "standing-question evidence matching failed for %s artifact %s (trace_id=%s)",
            source,
            candidate.artifact_ref,
            trace_id or "-",
        )
        return None


def match_vault_note_ingest(
    *,
    vault_root: Path,
    relative_path: str,
    frontmatter: Mapping[str, Any] | None = None,
    content: str | None = None,
    trace_id: str | None = None,
) -> MatchTickSummary | None:
    """Run the matching tick for one ingested vault note (``ingest.vault.changed``).

    Never-crash production call site for the worker's vault-ingest consumer.
    """
    try:
        candidate = vault_note_candidate(
            vault_root=vault_root,
            relative_path=relative_path,
            source_stream=INGEST_VAULT_CHANGED,
            frontmatter=frontmatter,
            content=content,
        )
    except Exception:
        _LOGGER.exception(
            "standing-question candidate construction failed for vault note %s", relative_path
        )
        return None
    return _never_crash_match(
        candidate, vault_root=vault_root, source=INGEST_VAULT_CHANGED, trace_id=trace_id
    )


def match_ingest_object_created(
    payload: Mapping[str, Any],
    *,
    vault_root: Path,
    trace_id: str | None = None,
) -> MatchTickSummary | None:
    """Run the matching tick for one ``ingest.object.created`` event. Never-crash."""
    try:
        candidate = candidate_from_ingest_object_created(payload, vault_root=vault_root)
    except Exception:
        _LOGGER.exception(
            "standing-question candidate construction failed for ingest.object.created payload"
        )
        return None
    return _never_crash_match(
        candidate, vault_root=vault_root, source=INGEST_OBJECT_CREATED, trace_id=trace_id
    )


def match_ka_candidate_completion(
    payload: Mapping[str, Any],
    *,
    vault_root: Path,
    trace_id: str | None = None,
) -> MatchTickSummary | None:
    """Run the matching tick for one KA candidate-stage completion. Never-crash."""
    try:
        candidate = candidate_from_ka_stage_completed(payload, vault_root=vault_root)
    except Exception:
        _LOGGER.exception(
            "standing-question candidate construction failed for KA stage.completed payload"
        )
        return None
    return _never_crash_match(
        candidate,
        vault_root=vault_root,
        source=KNOWLEDGE_ACQUISITION_STAGE_COMPLETED,
        trace_id=trace_id,
    )


def run_heimdal_evidence_matching_tick(
    *,
    vault_root: Path | str,
    limit: int | None = None,
    trace_id: str | None = None,
) -> MatchTickSummary:
    """Consume the next unread Heimdal observations and match them (fail-loud).

    Reads forward from this consumer's own durable cursor without advancing it,
    runs one matching tick over the batch, and only then advances the cursor
    past the batch -- "durably process, then advance" per the publish-seam
    contract, so a crashed tick re-reads the same observations (at-least-once;
    the matcher's per-pair idempotency absorbs the redelivery).

    Two guards keep the cursor honest (#4610 review): a missing vault root
    fails loud (never a silently synthesized CWD-relative vault -- the same
    phantom-root hazard #2384 removed from the worker), and a vault whose
    ``questions/`` directory does not exist yet leaves the cursor untouched --
    observations are only consumed once a vault where matching can actually
    evaluate them exists.
    """
    resolved_root = Path(vault_root).expanduser().resolve()
    if not resolved_root.is_dir():
        raise FileNotFoundError(
            f"standing-question evidence tick requires an existing vault root: {resolved_root}"
        )
    rows = read_observations_for_consumer(HEIMDAL_EVIDENCE_CONSUMER_ID, limit=limit)
    candidates = [
        candidate
        for candidate in (candidate_from_heimdal_observation(row) for row in rows)
        if candidate is not None
    ]
    if candidates:
        summary = match_evidence_to_open_questions(
            vault_root=resolved_root,
            candidates=candidates,
            trace_id=trace_id,
        )
    else:
        summary = MatchTickSummary()
    if (resolved_root / QUESTION_DIRECTORY).is_dir():
        advance_cursor_for_consumer(HEIMDAL_EVIDENCE_CONSUMER_ID, rows)
    elif rows:
        _LOGGER.warning(
            "standing-question evidence tick left the cursor untouched: no %s/ directory "
            "under %s (observations remain unconsumed until questions exist)",
            QUESTION_DIRECTORY,
            resolved_root,
        )
    return summary


__all__ = [
    "DEFAULT_ARTIFACT_SCOPE",
    "HEIMDAL_EVIDENCE_CONSUMER_ID",
    "HEIMDAL_SOURCE_STREAM",
    "candidate_from_heimdal_observation",
    "candidate_from_ingest_object_created",
    "candidate_from_ka_stage_completed",
    "match_ingest_object_created",
    "match_ka_candidate_completion",
    "match_vault_note_ingest",
    "run_heimdal_evidence_matching_tick",
    "vault_note_candidate",
]
