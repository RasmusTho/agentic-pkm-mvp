"""Refresh standing-question answers from a derived evidence delta (SQ-04).

The refresh entrypoint is deliberately a thin coordinator around the delivered
Create engine.  It derives the delta and pending-review state from the canonical
Question note and staged draft on every tick, supplies already-resolved evidence
sources to ``create.answer_note``, and writes only the system-owned candidate
pointer/timestamp after Create has receipted a draft.
"""

from __future__ import annotations

import logging
import fcntl
import os
import stat
import threading
from contextlib import contextmanager
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.components.llm.constrained import (
    CompletionFn,
    ConstrainedCompletionError,
    constrained_completion,
    register_schema,
)
from app.expansion.create import (
    CreatePassReport,
    CreateRequest,
    OutputKind,
    SourceInput,
    UnresolvableCitationError,
    run_create_pass,
)
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge_compilation.runtime_artifacts import CompilationDraft
from app.standing_questions.projection import (
    QuestionsDirectoryMissingError,
    iter_question_notes,
)
from app.standing_questions.question_store import QuestionStore
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import load_frontmatter

_LOGGER = logging.getLogger(__name__)
_REFRESH_LOCKS_GUARD = threading.Lock()
_REFRESH_LOCKS: dict[str, threading.RLock] = {}


class UnreadableVaultReferenceError(RuntimeError):
    """A persisted vault ref could not be inspected safely."""

# RQ-SQ1 is deliberately named and single-sourced.  The starting posture from
# the standing-questions README prefers an extra dismiss over a missed
# contradiction.  Tuning this value is a later live-data decision, not part of
# this implementation slice.
EVIDENCE_DELTA_REFRESH_THRESHOLD = 1

ANSWER_REFRESH_SCHEMA_REF = "standing_questions.answer_contradiction.v1"
_ANSWER_REFRESH_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "contradicts_standing_answer": {"type": "boolean"},
        "contradiction_basis": {"type": ["string", "null"]},
    },
    "required": ["contradicts_standing_answer", "contradiction_basis"],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"properties": {"contradicts_standing_answer": {"const": True}}},
            "then": {"properties": {"contradiction_basis": {"type": "string", "minLength": 1}}},
        }
    ],
}
register_schema(ANSWER_REFRESH_SCHEMA_REF, _ANSWER_REFRESH_SCHEMA)

_CONTRADICTION_SYSTEM_PROMPT = (
    "Compare a newly drafted candidate answer with the current standing answer. "
    "Return only JSON matching the supplied schema. Mark true only when the two "
    "conclusions materially disagree. If true, quote a concise basis grounded in "
    "the supplied texts; do not invent facts."
)


@dataclass(frozen=True)
class AnswerRefreshSummary:
    """Observable result of one refresh tick, with every candidate classified."""

    refresh_candidates: tuple[str, ...] = ()
    deferred_pending_review: tuple[str, ...] = ()
    drafted: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def _evidence_delta(note: Mapping[str, Any]) -> list[dict[str, Any]]:
    last_refreshed_at = note.get("last_refreshed_at")
    if last_refreshed_at is None:
        return list(note.get("evidence", []))
    cutoff = _parse_timestamp(last_refreshed_at)
    return [
        entry
        for entry in note.get("evidence", [])
        if _parse_timestamp(entry["matched_at"]) > cutoff
    ]


def _resolve_vault_ref(vault_root: Path, reference: str) -> Path | None:
    try:
        if reference.startswith("vault://"):
            relative = reference[len("vault://") :]
        else:
            relative = reference
        path = (vault_root / relative).resolve()
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        raise UnreadableVaultReferenceError(reference) from exc
    try:
        if not path.is_relative_to(vault_root):
            return None
        if not path.is_file():
            return None
        return path
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        raise UnreadableVaultReferenceError(reference) from exc


@contextmanager
def _question_refresh_lock(vault_root: Path, question_id: str) -> Iterator[None]:
    """Serialize refresh read/check/create/update for one Question.

    The lock is operational metadata, not Question state. A process-local
    ``RLock`` covers threads and the companion ``flock`` covers independent
    workers, so two refresh ticks cannot both pass the pending check before
    either writes the candidate pointer.
    """

    lock_path = vault_root / "questions" / f".{question_id}.refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(lock_path)
    with _REFRESH_LOCKS_GUARD:
        process_lock = _REFRESH_LOCKS.setdefault(key, threading.RLock())
    with process_lock:
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            opened = os.fstat(descriptor)
            named = os.stat(lock_path, follow_symlinks=False)
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(named.st_mode)
                or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise RuntimeError("standing-question refresh lock must be a stable regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = os.fstat(descriptor)
            named_after = os.stat(lock_path, follow_symlinks=False)
            if (
                not stat.S_ISREG(locked.st_mode)
                or not stat.S_ISREG(named_after.st_mode)
                or locked.st_nlink != 1
                or (locked.st_dev, locked.st_ino)
                != (named_after.st_dev, named_after.st_ino)
            ):
                raise RuntimeError("standing-question refresh lock changed during acquisition")
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _pending_candidate(vault_root: Path, note: Mapping[str, Any], *, now: datetime) -> bool:
    """Derive pending state from the current draft, never from a stored flag."""

    reference = note.get("candidate_answer_ref")
    if not isinstance(reference, str) or not reference.strip():
        return False
    try:
        path = _resolve_vault_ref(vault_root, reference)
    except UnreadableVaultReferenceError:
        return True
    if path is None:
        # A missing draft is no longer pending; the next tick may safely rebuild
        # the candidate from the still-present evidence log.
        return False
    try:
        raw = path.read_text(encoding="utf-8")
        frontmatter, _body = load_frontmatter(raw)
    except (OSError, UnicodeError, ValueError):
        # A live referenced draft that cannot be inspected must not be clobbered.
        return True
    expires = frontmatter.get("expires") if isinstance(frontmatter, dict) else None
    if isinstance(expires, str):
        try:
            if _parse_timestamp(expires) <= now.astimezone(timezone.utc):
                return False
        except ValueError:
            return True
    # Acceptance advances this field. Dismissal removes/archives the staged
    # draft through EXP-4, so an existing proposal remains protected regardless
    # of checkbox text while an acceptance transaction is in flight.
    return frontmatter.get("authority_state") != "accepted"


def _source_inputs(
    evidence: Sequence[Mapping[str, Any]],
    evidence_sources: Mapping[str, SourceInput],
) -> tuple[SourceInput, ...]:
    """Build Create inputs from caller-resolved sources without fetching them.

    The primary lookup key is each evidence entry's ``provenance_ref``.  The
    artifact-ref fallback keeps the seam usable by existing matching callers,
    while the resulting Create ``object_id`` remains the provenance ref so the
    draft's SourceRefs name the evidence-log provenance explicitly.
    """

    sources: list[SourceInput] = []
    for entry in evidence:
        provenance_ref = str(entry["provenance_ref"])
        artifact_ref = str(entry["artifact_ref"])
        source = evidence_sources.get(provenance_ref) or evidence_sources.get(artifact_ref)
        if source is None:
            raise UnresolvableCitationError(
                f"evidence provenance {provenance_ref!r} was not resolved by the caller"
            )
        sources.append(
            SourceInput(
                object_id=provenance_ref,
                note_path=source.note_path or artifact_ref,
                text=source.text,
                quoted_spans=(str(entry["quoted_span"]),),
                language=source.language,
                review_state=source.review_state,
            )
        )
    return tuple(sources)


def _read_standing_answer(
    vault_root: Path, note: Mapping[str, Any]
) -> tuple[bool, str | None]:
    reference = note.get("standing_answer_ref")
    if not isinstance(reference, str) or not reference.strip():
        return False, None
    try:
        path = _resolve_vault_ref(vault_root, reference)
    except UnreadableVaultReferenceError:
        return True, None
    if path is None:
        return True, None
    try:
        return True, path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return True, None


def _contradiction_metadata(
    draft: CompilationDraft,
    *,
    standing_answer_referenced: bool,
    standing_answer: str | None,
    complete: CompletionFn | None,
    trace_id: str | None,
) -> Mapping[str, Any]:
    if not standing_answer_referenced:
        return {
            "contradicts_standing_answer": False,
            "contradiction": False,
            "contradiction_basis": None,
        }
    if standing_answer is None:
        return {
            "contradiction": "unknown",
            "contradicts_standing_answer": "unknown",
            "contradiction_basis": None,
        }
    try:
        payload = constrained_completion(
            ANSWER_REFRESH_SCHEMA_REF,
            system=_CONTRADICTION_SYSTEM_PROMPT,
            user=(
                "Current standing answer:\n"
                + standing_answer.strip()
                + "\n\nNew candidate answer:\n"
                + (draft.body or "").strip()
            ),
            task_kind="decide",
            trace_id=trace_id,
            complete=complete,
        )
    except ConstrainedCompletionError as exc:
        _LOGGER.warning(
            "standing-answer contradiction judgment degraded to UNKNOWN "
            "(schema_ref=%s trace_id=%s): %s",
            ANSWER_REFRESH_SCHEMA_REF,
            trace_id or "-",
            exc.reason,
        )
        return {
            "contradiction": "unknown",
            "contradicts_standing_answer": "unknown",
            "contradiction_basis": None,
        }
    contradicts = bool(payload["contradicts_standing_answer"])
    basis = payload.get("contradiction_basis")
    return {
        "contradicts_standing_answer": contradicts,
        "contradiction": contradicts,
        "contradiction_basis": basis if isinstance(basis, str) else None,
    }


def refresh_answers_on_evidence_delta(
    *,
    vault_root: Path | str,
    outbox_path: Path,
    evidence_sources: Mapping[str, SourceInput],
    store: QuestionStore | None = None,
    contradiction_complete: CompletionFn | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    now: datetime | None = None,
    trace_id: str | None = None,
) -> AnswerRefreshSummary:
    """Run one derived refresh tick for every open Question note.

    ``evidence_sources`` is an already-resolved read-side map. This function
    does not fetch provenance refs or mutate source artifacts. The only Question
    write is ``candidate_answer_ref`` plus ``last_refreshed_at`` after a
    successful Create staging receipt; ``status`` and ``standing_answer_ref``
    are deliberately absent from the write payload.
    """

    resolved_root = Path(vault_root).expanduser().resolve()
    question_store = store or QuestionStore(resolved_root, write_guard=write_guard)
    tick_now = now or _utc_now()
    refresh_candidates: list[str] = []
    deferred: list[str] = []
    drafted: list[str] = []
    blocked: list[str] = []
    try:
        notes = iter_question_notes(resolved_root)
    except QuestionsDirectoryMissingError:
        return AnswerRefreshSummary()

    for _source_path, note in notes:
        if note["status"] != "open":
            continue
        question_id = note["question_id"]
        with _question_refresh_lock(resolved_root, question_id):
            # Re-read inside the per-question lock. The initial projection is
            # only discovery; eligibility and all state transitions use fresh
            # vault truth.
            current = question_store.read_question(question_id)
            if current["status"] != "open":
                continue
            delta = _evidence_delta(current)
            if len(delta) < EVIDENCE_DELTA_REFRESH_THRESHOLD:
                continue
            refresh_candidates.append(question_id)
            if _pending_candidate(resolved_root, current, now=tick_now):
                deferred.append(question_id)
                continue
            try:
                # The delta decides whether to refresh; the candidate answer is
                # synthesized over the complete current evidence log so a refresh
                # never drops context that was present in an earlier candidate.
                sources = _source_inputs(current["evidence"], evidence_sources)
                request = CreateRequest(
                    kind=OutputKind.ANSWER_NOTE,
                    title=f"Answer: {current['text']}",
                    sources=sources,
                    question=current["text"],
                    trace_id=trace_id,
                )
                standing_answer_referenced, standing_answer = _read_standing_answer(
                    resolved_root, current
                )
                report: CreatePassReport = run_create_pass(
                    request,
                    vault_root=resolved_root,
                    outbox_path=outbox_path,
                    write_guard=write_guard,
                    now=tick_now,
                    draft_frontmatter_enricher=lambda draft: _contradiction_metadata(
                        draft,
                        standing_answer_referenced=standing_answer_referenced,
                        standing_answer=standing_answer,
                        complete=contradiction_complete,
                        trace_id=trace_id,
                    ),
                )
            except UnresolvableCitationError:
                blocked.append(question_id)
                continue
            if not report.activatable or report.draft_path is None or report.receipt_id is None:
                blocked.append(question_id)
                continue

            # Re-read immediately before the guarded system update. This preserves
            # the pending-review and terminal-status race guarantees on the Question
            # seam; no human-owned field is ever supplied here.
            current, observed_version = question_store.read_question_with_version(question_id)
            if current["status"] != "open":
                blocked.append(question_id)
                continue
            if _pending_candidate(resolved_root, current, now=tick_now):
                deferred.append(question_id)
                continue
            try:
                question_store.update_system_fields_if_unchanged(
                    question_id,
                    current,
                    {
                        "candidate_answer_ref": f"vault://{report.draft_path}",
                        "last_refreshed_at": _iso(tick_now),
                    },
                    expected_version=observed_version,
                )
            except KnowledgeWriteConflict:
                latest = question_store.read_question(question_id)
                if _pending_candidate(resolved_root, latest, now=tick_now):
                    deferred.append(question_id)
                else:
                    blocked.append(question_id)
                continue
            drafted.append(question_id)

    return AnswerRefreshSummary(
        refresh_candidates=tuple(refresh_candidates),
        deferred_pending_review=tuple(deferred),
        drafted=tuple(drafted),
        blocked=tuple(blocked),
    )


__all__ = [
    "ANSWER_REFRESH_SCHEMA_REF",
    "AnswerRefreshSummary",
    "EVIDENCE_DELTA_REFRESH_THRESHOLD",
    "refresh_answers_on_evidence_delta",
]
