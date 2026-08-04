"""Match new ingest artifacts against open Question notes (SQ-03).

This module is the production matching entrypoint named by
``docs/STANDING_QUESTIONS/MATCH_EVIDENCE_TO_OPEN_QUESTIONS.md``. It consumes
artifacts that already flowed through the existing ingest paths (Heimdal
captures, KAP candidates, new/edited vault notes) and, for each
``(open question, candidate artifact)`` pair that clears a cheap deterministic
prefilter, asks a **fenced** schema-constrained completion whether the artifact
is evidence for the question.

Three disciplines carry the whole task and are enforced here rather than left to
callers:

- **The source artifact is never written to** (INV-SQ-B). The candidate capture,
  KAP candidate, or note is opened read-only to build the association prompt and
  is never opened for write on any code path — attach, below-threshold,
  degraded, or excluded. Only the *question* side gains state, through the SQ-01
  guarded seam (:class:`~app.standing_questions.question_store.QuestionStore`).
  This is the one deliberate asymmetry against the Episode Resolution Engine's
  ``episode_ref`` pattern, which stamps the artifact's own bundle.
- **Scope is hard** (mirroring ``docs/MIMER_CAPABILITY_HARDENING/
  EXPANSION_CONNECT_AND_CREATE.md :: 1.2``). A cross-scope pair is excluded
  *before* the artifact's content is resolved, so no span of another scope can
  reach the model, the log, or the evidence trail — a content-free denial. No
  ``CrossScopeFlow`` grant class exists for this relation; cross-scope evidence
  is capability-level out of scope, not deferred.
- **LLM cognition, deterministic gate.** The model judges relatedness; code
  decides attachment. A schema-validation failure or degraded backend yields no
  link (``UNKNOWN``-equivalent per ``docs/RUNTIME_CORRECTNESS_KERNEL/
  STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md``), never a fabricated or
  default-attached one, and a quoted span that is not verbatim in the artifact
  is refused rather than stored as a paraphrase.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from app.components.llm.constrained import (
    CompletionFn,
    ConstrainedCompletionError,
    constrained_completion,
    register_schema,
)
from app.standing_questions.projection import (
    QuestionsDirectoryMissingError,
    iter_question_notes,
)
from jsonschema import ValidationError

from app.knowledge.errors import KnowledgeWriteConflict
from app.standing_questions.question_store import (
    QUESTION_DIRECTORY,
    QuestionNoteRoundTripError,
    QuestionNotOpenError,
    QuestionStore,
)

_LOGGER = logging.getLogger(__name__)

VAULT_REF_PREFIX = "vault://"


class ConfidenceClass(str, Enum):
    """The association's uncertainty band, ranked by :data:`CONFIDENCE_CLASS_RANK`.

    Deliberately a closed set: the deterministic gate can only rank classes it
    knows, so a class the model invents is a schema violation (no link), never an
    unranked value that falls through the floor comparison.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: Total order the threshold gate compares against. Kept next to the enum so a new
#: class cannot be added without giving it a rank.
CONFIDENCE_CLASS_RANK: dict[ConfidenceClass, int] = {
    ConfidenceClass.LOW: 0,
    ConfidenceClass.MEDIUM: 1,
    ConfidenceClass.HIGH: 2,
}

#: **RQ-SQ2 — provisional.** The deterministic floor an association's confidence
#: class must clear before a link attaches at all. This is the single source for
#: that threshold; nothing else in the codebase may hard-code an attach cutoff.
#: Starting posture is conservative per ``docs/STANDING_QUESTIONS/README.md ::
#: Provisional thresholds (RQ-SQ1, RQ-SQ2)`` — under-attaching is preferred,
#: because a missed link can still be found by a later, stronger-evidence pass
#: while a wrongly attached one pollutes an evidence trail a human must then
#: mentally discount. It is a tuning value to revisit once live data accumulates,
#: not a pre-code gate.
EVIDENCE_ATTACH_CONFIDENCE_FLOOR = ConfidenceClass.HIGH

#: Registered schema for the fenced association judgment. ``relation_label`` is
#: judged and logged but not persisted: the Question note's ``evidence`` entry
#: shape is owned by SQ-01's ``schemas/question-note.schema.json`` and this task
#: does not widen it.
EVIDENCE_ASSOCIATION_SCHEMA_REF = "standing_questions.evidence_association.v1"

_EVIDENCE_ASSOCIATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "related": {"type": "boolean"},
        "confidence_class": {"enum": [member.value for member in ConfidenceClass]},
        "relation_label": {"type": ["string", "null"]},
        "supporting_span": {"type": "string"},
    },
    "required": ["related", "confidence_class", "supporting_span"],
}

register_schema(EVIDENCE_ASSOCIATION_SCHEMA_REF, _EVIDENCE_ASSOCIATION_SCHEMA)

_SYSTEM_PROMPT = (
    "You judge whether one artifact is evidence bearing on one open question. "
    "You see only the question and the artifact; judge nothing else and assume "
    "nothing about their origin. Return ONLY a JSON object, no commentary:\n"
    '{"related": <true|false>, "confidence_class": "<low|medium|high>", '
    '"relation_label": "<short phrase or null>", "supporting_span": "<verbatim '
    'quote from the artifact, or empty string>"}\n\n'
    "Rules:\n"
    "- supporting_span must be copied verbatim from the artifact text. Never "
    "paraphrase, translate, summarise, or repair it; a span that is not present "
    "byte-for-byte in the artifact is rejected and the artifact is not linked.\n"
    "- related: true only when the artifact bears on answering this question, "
    "not merely when it shares vocabulary with it.\n"
    "- confidence_class states your uncertainty about that judgment: high only "
    "when the span itself makes the bearing plain."
)


@dataclass(frozen=True)
class CandidateArtifact:
    """One artifact from an existing ingest path, offered for matching.

    This task adds no acquisition source: callers are the existing consumers
    (Heimdal observation-log cursor, ``knowledge_acquisition.stage.completed``,
    ``ingest.vault.changed`` / ``ingest.object.created``) and supply what they
    already hold.

    ``content`` is optional. A ``vault://`` ref is resolved read-only against the
    vault root when content is not supplied inline; any other ref scheme must
    carry its content, because this module has no other read path and will never
    invent one.
    """

    artifact_ref: str
    source_stream: str
    scope: str
    provenance_ref: str
    content: str | None = None


@dataclass(frozen=True)
class EvidenceAssociation:
    """A validated association judgment. Carries no authority by itself."""

    related: bool
    confidence_class: ConfidenceClass
    supporting_span: str
    relation_label: str | None = None

    def clears_threshold(self) -> bool:
        return (
            CONFIDENCE_CLASS_RANK[self.confidence_class]
            >= CONFIDENCE_CLASS_RANK[EVIDENCE_ATTACH_CONFIDENCE_FLOOR]
        )


@dataclass(frozen=True)
class MatchTickSummary:
    """Legible outcome counts for one matching tick.

    Every pair the tick saw lands in exactly one bucket, so a link that did not
    attach always has a named reason rather than disappearing silently.
    """

    evaluated_pairs: int = 0
    attached: int = 0
    unrelated: int = 0
    below_threshold: int = 0
    unverifiable_span: int = 0
    duplicate_basis: int = 0
    degraded: int = 0
    excluded_cross_scope: int = 0
    excluded_non_open: int = 0
    unresolved_artifact: int = 0
    #: Pairs whose guarded append was refused or failed AFTER a qualifying
    #: match: a human-edit write conflict (CAS), a round-trip refusal, or a
    #: question note that disappeared/corrupted mid-tick. Never silent, never
    #: fatal to the tick. Re-offerable sources (vault notes, KA candidates)
    #: retry naturally on their next event; the Heimdal cursor path does NOT
    #: re-deliver once its cursor advances past the batch, so a refused
    #: Heimdal-sourced pair is a logged, counted loss.
    append_refused: int = 0


@dataclass
class _Counters:
    counts: dict[str, int] = field(default_factory=dict)

    def bump(self, name: str, amount: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount

    def summary(self) -> MatchTickSummary:
        return MatchTickSummary(**self.counts)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _open_questions(vault_root: Path, counters: _Counters) -> list[dict[str, Any]]:
    """Return every ``open`` Question note, counting the terminal ones skipped.

    A missing ``questions/`` directory is an empty tick rather than an error:
    matching is a read-only consumer, so the projection's fail-loud posture — which
    exists to stop a TRUNCATE from wiping a live projection — has nothing to protect
    here.
    """
    try:
        notes = iter_question_notes(vault_root)
    except QuestionsDirectoryMissingError:
        return []
    open_notes: list[dict[str, Any]] = []
    for _source_path, note in notes:
        if note["status"] == "open":
            open_notes.append(note)
        else:
            # INV-SQ-F: answered/closed are terminal for the engine. Only a human
            # editing status back to `open` resumes matching.
            counters.bump("excluded_non_open")
    return open_notes


def _resolve_content(vault_root: Path, candidate: CandidateArtifact) -> str | None:
    """Read the artifact's text. Read-only by construction — there is no write path.

    Returns ``None`` when the artifact cannot be resolved (for example a note
    deleted between the ingest event and this tick), which yields no link.
    """
    if candidate.content is not None:
        return candidate.content
    if not candidate.artifact_ref.startswith(VAULT_REF_PREFIX):
        _LOGGER.warning(
            "Standing Questions matching cannot resolve artifact ref without inline content: %s",
            candidate.artifact_ref,
        )
        return None
    relative = candidate.artifact_ref[len(VAULT_REF_PREFIX) :]
    # Defense in depth against question self-citation (#4610 review): the
    # production candidate builders already exclude engine-owned Question
    # notes, but any future caller constructing a CandidateArtifact directly
    # must not be able to route a question back into its own evidence trail.
    if PurePosixPath(relative).parts[:1] == (QUESTION_DIRECTORY,):
        _LOGGER.warning(
            "Standing Questions matching refused engine-owned question note as candidate: %s",
            candidate.artifact_ref,
        )
        return None
    path = (vault_root / relative).resolve()
    if not path.is_relative_to(vault_root) or not path.is_file():
        _LOGGER.warning(
            "Standing Questions matching skipped unresolvable artifact: %s",
            candidate.artifact_ref,
        )
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # #4610 P2: a note deleted (or otherwise made unreadable) between the
        # `is_file()` check above and this read is a normal race for
        # asynchronously consumed ingest events. It is an unresolved no-link
        # result for THIS candidate only -- never an aborted tick for the rest.
        _LOGGER.warning(
            "Standing Questions matching skipped artifact that disappeared before read: %s (%s)",
            candidate.artifact_ref,
            exc,
        )
        return None


def _build_user_prompt(question_text: str, artifact_text: str) -> str:
    """Fence the completion: the model sees the question and the artifact, nothing else.

    No question id, scope, status, existing evidence, or sibling artifact is ever
    included, so the judgment cannot be steered by state the model has no business
    reasoning about.
    """
    return (
        f"Open question:\n{question_text.strip()}\n\n"
        f"Artifact text:\n{artifact_text.strip()}"
    )


def judge_association(
    *,
    question_text: str,
    artifact_text: str,
    complete: CompletionFn | None = None,
    trace_id: str | None = None,
) -> EvidenceAssociation | None:
    """Run the fenced association judgment, or return ``None`` when degraded.

    ``None`` is this task's ``UNKNOWN``: a provider failure or any completion that
    does not validate against :data:`EVIDENCE_ASSOCIATION_SCHEMA_REF` yields no
    judgment at all, which the caller can only turn into "no link".
    """
    try:
        payload = constrained_completion(
            EVIDENCE_ASSOCIATION_SCHEMA_REF,
            system=_SYSTEM_PROMPT,
            user=_build_user_prompt(question_text, artifact_text),
            task_kind="decide",
            trace_id=trace_id,
            complete=complete,
        )
    except ConstrainedCompletionError as exc:
        # Fail-loud observability: without this a backend outage is
        # indistinguishable from "nothing matched today".
        _LOGGER.warning(
            "evidence association degraded to no-link (schema_ref=%s trace_id=%s): %s",
            EVIDENCE_ASSOCIATION_SCHEMA_REF,
            trace_id or "-",
            exc.reason,
        )
        return None
    relation_label = payload.get("relation_label")
    return EvidenceAssociation(
        related=bool(payload["related"]),
        confidence_class=ConfidenceClass(payload["confidence_class"]),
        supporting_span=payload["supporting_span"],
        relation_label=relation_label if isinstance(relation_label, str) else None,
    )


def _existing_bases(note: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (entry["artifact_ref"], entry["quoted_span"]) for entry in note.get("evidence", [])
    }


def match_evidence_to_open_questions(
    *,
    vault_root: Path | str,
    candidates: Iterable[CandidateArtifact],
    store: QuestionStore | None = None,
    complete: CompletionFn | None = None,
    trace_id: str | None = None,
) -> MatchTickSummary:
    """Run one matching tick over ``candidates`` and return its outcome counts.

    This is the production entrypoint every acceptance test asserts against. It
    reads Question notes and artifacts, and writes **only** to the question side
    through the SQ-01 guarded seam.
    """
    resolved_root = Path(vault_root).expanduser().resolve()
    question_store = store if store is not None else QuestionStore(resolved_root)
    candidate_list: Sequence[CandidateArtifact] = list(candidates)
    counters = _Counters()

    for note in _open_questions(resolved_root, counters):
        question_id = note["question_id"]
        seen_bases = _existing_bases(note)
        new_entries: list[dict[str, Any]] = []

        for candidate in candidate_list:
            # Scope first, before any content is resolved: a cross-scope artifact's
            # text must never be read, prompted, or logged (content-free denial).
            if candidate.scope != note["scope"]:
                counters.bump("excluded_cross_scope")
                continue
            artifact_text = _resolve_content(resolved_root, candidate)
            if artifact_text is None:
                counters.bump("unresolved_artifact")
                continue

            counters.bump("evaluated_pairs")
            association = judge_association(
                question_text=note["text"],
                artifact_text=artifact_text,
                complete=complete,
                trace_id=trace_id,
            )
            if association is None:
                counters.bump("degraded")
                continue
            if not association.related:
                counters.bump("unrelated")
                continue
            # The deterministic gate (RQ-SQ2). The model's judgment alone never
            # attaches anything.
            if not association.clears_threshold():
                counters.bump("below_threshold")
                continue
            span = association.supporting_span
            # Verbatim or nothing: a span the artifact does not actually contain
            # would put a fabricated quote into a human-legible evidence trail.
            if not span.strip() or span not in artifact_text:
                counters.bump("unverifiable_span")
                continue
            basis = (candidate.artifact_ref, span)
            # Idempotency fold key is (question_id, artifact_ref) narrowed by the
            # quoted basis: re-ticking never duplicates an identical-basis entry,
            # while a later pass carrying a materially different span still may add
            # one.
            if basis in seen_bases:
                counters.bump("duplicate_basis")
                continue
            seen_bases.add(basis)
            new_entries.append(
                {
                    "artifact_ref": candidate.artifact_ref,
                    "source_stream": candidate.source_stream,
                    "matched_at": _utc_now(),
                    "confidence_class": association.confidence_class.value,
                    "provenance_ref": candidate.provenance_ref,
                    "quoted_span": span,
                }
            )

        if not new_entries:
            continue
        # Atomic guarded append (#4610 P2): the open-status predicate and the
        # evidence write are one operation inside the store's exclusive per-note
        # lock, so a human close that lands mid-tick fails the append closed --
        # a closed question is never resurrected and never receives evidence
        # through this race (INV-SQ-F partial failure).
        try:
            _updated, _receipt, appended_entries = question_store.append_evidence(
                question_id, new_entries
            )
        except QuestionNotOpenError:
            counters.bump("excluded_non_open")
            continue
        except (
            KnowledgeWriteConflict,
            QuestionNoteRoundTripError,
            OSError,
            ValueError,
            ValidationError,
        ) as exc:
            # The seam refused or lost the write: a concurrent human edit (CAS
            # conflict -- the canonical note is untouched, a stale `open`
            # payload never overwrites a close), a round-trip refusal, or a
            # question note deleted mid-tick. Never fatal to the tick; counted
            # per PAIR so every evaluated pair still lands in exactly one
            # bucket. Re-offerable sources retry on their next event; a
            # Heimdal-cursor pair is a logged loss once the cursor advances.
            _LOGGER.warning(
                "Standing Questions evidence append refused for %s (%d entries): %s",
                question_id,
                len(new_entries),
                exc,
            )
            counters.bump("append_refused", len(new_entries))
            continue
        dropped = len(new_entries) - len(appended_entries)
        if dropped:
            # Basis already present on the fresh in-lock read: a concurrent tick
            # won the lock first. Idempotency, not attachment.
            counters.bump("duplicate_basis", dropped)
        if appended_entries:
            counters.bump("attached", len(appended_entries))

    return counters.summary()


__all__ = [
    "CONFIDENCE_CLASS_RANK",
    "EVIDENCE_ASSOCIATION_SCHEMA_REF",
    "EVIDENCE_ATTACH_CONFIDENCE_FLOOR",
    "CandidateArtifact",
    "ConfidenceClass",
    "EvidenceAssociation",
    "MatchTickSummary",
    "judge_association",
    "match_evidence_to_open_questions",
    "VAULT_REF_PREFIX",
]
