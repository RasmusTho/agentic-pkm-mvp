"""Read and close/reopen routes for the SQ-05 Companion review surface."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.api.compatibility_mutation import seal_vault_mutation
from app.api.request_active_context import (
    ScopedRouteRead,
    current_scoped_route_read,
    route_read_vault_root_or_selection_required,
    scoped_note_path_owned_by_binding,
    scoped_route_read,
)
from app.api.routes.vault_resolution import compatibility_vault_root_or_selection_required
from app.auth import require_loopback_or_api_key
from app.config.database import runtime_database_is_named
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.instance.compatibility_binding import compatibility_binding_for_root
from app.expansion.create import standing_question_acceptance_option_id
from app.panel.checkbox_projection import CheckboxProjectionRequest, extract_panel_selectable_options
from app.services.artifact_identity import resolve_note_artifact_identity
from app.standing_questions.projection import (
    QuestionsDirectoryMissingError,
    iter_question_notes,
    read_standing_questions_projection,
    rebuild_standing_questions_projection,
)
from app.standing_questions.question_store import QuestionStore, question_note_path
from app.standing_questions.review import (
    QuestionReviewError,
    dismiss_question_candidate,
    transition_question_status,
)
from app.text.helpers import content_hash
from app.vault.manager import nearest_enclosing_vault_root
from scripts.yaml_roundtrip import load_frontmatter

router = APIRouter(
    prefix="/standing-questions",
    tags=["standing-questions"],
    dependencies=[Depends(seal_vault_mutation)],
)

_LOGGER = logging.getLogger(__name__)


class QuestionListItem(BaseModel):
    question_id: str
    text: str
    status: Literal["open", "answered", "closed"]
    # PostgreSQL TIMESTAMPTZ can represent years outside Python datetime's
    # range. The projection returns its timestamp text so one legal canonical
    # Question cannot make the whole list/detail surface unreadable.
    created_at: str
    evidence_count: int
    has_candidate_answer: bool

    @field_validator("created_at", mode="before")
    @classmethod
    def _created_at_as_text(cls, value: object) -> object:
        # Test and in-process callers may supply normal datetime values. Keep
        # their established JSON representation while accepting out-of-range
        # PostgreSQL timestamp strings losslessly.
        return value.isoformat() if isinstance(value, datetime) else value


class QuestionListResponse(BaseModel):
    questions: list[QuestionListItem]
    include_resolved: bool
    source: str = "standing_questions"
    read_only: bool = True


class EvidenceItem(BaseModel):
    artifact_ref: str
    source_stream: str
    matched_at: str
    confidence_class: str
    provenance_ref: str | None = None
    quoted_span: str
    content_hash: str
    source_note_path: str | None = None


class CandidateAnswer(BaseModel):
    state: Literal[
        "pending",
        "missing",
        "unreadable",
        "not_selectable",
        "acknowledgement_indeterminate",
    ]
    draft_id: str | None = None
    body: str | None = None
    contradicts_standing_answer: bool | str | None = None
    contradiction_basis: str | None = None
    acceptance_control: dict[str, Any] | None = None


class QuestionDetailResponse(QuestionListItem):
    scope: str
    registered_via: str
    question_version: str
    standing_answer_ref: str | None = None
    candidate_answer_ref: str | None = None
    evidence: list[EvidenceItem]
    candidate_answer: CandidateAnswer | None = None
    source: str = "standing_questions"
    read_only: bool = True


class QuestionVersionRequest(BaseModel):
    expected_question_version: str = Field(min_length=1)

    @field_validator("expected_question_version", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


def _acceptance_source_hashes(
    normalized_markdown: str,
    option: Any,
) -> tuple[str, str] | None:
    """Return hashes for the exact unchecked source, including a lost-ack retry."""

    if not option.checked:
        return option.content_hash, option.source_hash
    lines = normalized_markdown.splitlines(keepends=True)
    index = option.source_range.start_line
    if not 0 <= index < len(lines):
        return None
    source_line = lines[index].rstrip("\n")
    newline = lines[index][len(source_line) :]
    checked = re.match(r"^(\s*-\s*\[)x(\]\s*.*)$", source_line)
    if checked is None:
        return None
    unchecked_line = f"{checked.group(1)} {checked.group(2)}"
    unchecked = "".join(lines[:index] + [unchecked_line + newline] + lines[index + 1 :])
    return (
        content_hash(unchecked),
        hashlib.sha256(unchecked_line.encode("utf-8")).hexdigest(),
    )


def _vault_and_binding() -> tuple[Path | JSONResponse, str]:
    root = route_read_vault_root_or_selection_required()
    if isinstance(root, JSONResponse):
        return root, COMPATIBILITY_BINDING_ID
    scoped = current_scoped_route_read()
    if scoped is None:
        try:
            return root, compatibility_binding_for_root(root)
        except Exception as exc:
            raise HTTPException(
                status_code=409,
                detail={"error": "active_context_binding_required"},
            ) from exc
    if scoped.vault_binding_id is None:
        raise HTTPException(status_code=409, detail="active_context_binding_required")
    return root, scoped.vault_binding_id


def _read_projection_rows(vault_binding_id: str) -> list[dict[str, Any]]:
    try:
        return read_standing_questions_projection(vault_binding_id)
    except Exception as exc:  # DB/query health is an explicit degraded state, never empty.
        raise HTTPException(
            status_code=503,
            detail={"error": "question_projection_unavailable", "message": "The question projection could not be read."},
        ) from exc


def _parse_projection_timestamp(value: object) -> datetime:
    text = str(value).replace(" ", "T")
    if text.endswith("+00"):
        text += ":00"
    return datetime.fromisoformat(text)


def _projection_timestamp_key(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return timestamp.isoformat(timespec="microseconds")
    text = str(value)
    try:
        timestamp = _parse_projection_timestamp(text)
    except ValueError:
        return text.strip()
    timestamp = timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
    return timestamp.isoformat(timespec="microseconds")


def _projection_row_matches_note(
    row: dict[str, Any],
    note: dict[str, Any],
    *,
    source_path: str,
) -> bool:
    projected_evidence = row.get("evidence") or []
    if isinstance(projected_evidence, str):
        try:
            projected_evidence = json.loads(projected_evidence)
        except ValueError:
            return False
    try:
        from app.standing_questions.projection import _postgres_timestamptz_value

        timestamp_matches = all(
            _projection_timestamp_key(row.get(field))
            == _projection_timestamp_key(_postgres_timestamptz_value(note.get(field)))
            for field in ("created_at", "last_matched_at", "last_refreshed_at")
        )
    except (TypeError, ValueError, OverflowError):
        timestamp_matches = False
    return (
        all(
            row.get(field) == note.get(field)
            for field in (
                "scope",
                "text",
                "status",
                "registered_via",
                "standing_answer_ref",
                "candidate_answer_ref",
            )
        )
        and projected_evidence == note.get("evidence", [])
        and timestamp_matches
        and row.get("source_path") == source_path
    )


def _current_projection_rows(vault_root: Path, binding_id: str) -> list[dict[str, Any]]:
    try:
        canonical_notes = iter_question_notes(vault_root)
    except QuestionsDirectoryMissingError:
        existing = _read_projection_rows(binding_id)
        if existing:
            raise HTTPException(
                status_code=503,
                detail={"error": "question_projection_stale", "message": "Question notes are unavailable; the projection may be stale."},
            )
        return []
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "question_projection_source_unavailable", "message": "Canonical Question notes could not be read."},
        ) from exc
    rows = _read_projection_rows(binding_id)
    projected_by_id = {str(row.get("question_id")): row for row in rows}
    canonical_by_id = {
        str(note.get("question_id")): (source_path, note)
        for source_path, note in canonical_notes
    }
    if len(projected_by_id) != len(rows) or projected_by_id.keys() != canonical_by_id.keys():
        raise HTTPException(
            status_code=503,
            detail={"error": "question_projection_stale", "message": "The Question projection does not match canonical notes."},
        )
    for question_id, (source_path, note) in canonical_by_id.items():
        if not _projection_row_matches_note(
            projected_by_id[question_id],
            note,
            source_path=source_path,
        ):
            raise HTTPException(
                status_code=503,
                detail={"error": "question_projection_stale", "message": "The Question projection does not match canonical notes."},
            )
    return rows


def _sync_projection_after_mutation(vault_root: Path, binding_id: str) -> None:
    """Refresh the rebuildable query projection after a canonical write commits."""

    if not runtime_database_is_named(os.environ):
        return
    try:
        rebuild_standing_questions_projection(vault_root, vault_binding_id=binding_id)
    except Exception:
        # The vault write is already authoritative and cannot be undone by a
        # failed derived projection refresh. GET checks freshness and reports a
        # 503 until a later producer retry or explicit rebuild succeeds.
        _LOGGER.exception("standing-question projection refresh failed after canonical write")


def _sync_compatibility_projection_after_mutation(vault_root: Path) -> None:
    if not runtime_database_is_named(os.environ):
        return
    try:
        binding_id = compatibility_binding_for_root(vault_root)
    except Exception:
        _LOGGER.exception("standing-question projection binding could not be resolved after canonical write")
        return
    _sync_projection_after_mutation(vault_root, binding_id)


def _item(row: dict[str, Any]) -> QuestionListItem:
    evidence = row.get("evidence") or []
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except ValueError:
            evidence = []
    return QuestionListItem(
        question_id=str(row["question_id"]),
        text=str(row["text"]),
        status=row["status"],
        created_at=row["created_at"],
        evidence_count=len(evidence) if isinstance(evidence, list) else 0,
        has_candidate_answer=bool(row.get("candidate_answer_ref")),
    )


def _source_note_path(
    artifact_ref: object,
    *,
    vault_root: Path,
    scoped: ScopedRouteRead | None,
    require_existing: bool = True,
) -> str | None:
    if not isinstance(artifact_ref, str) or not artifact_ref.startswith("vault://"):
        return None
    raw = artifact_ref[len("vault://") :]
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts or not raw.strip():
        return None
    try:
        resolved = (vault_root / candidate).resolve()
        relative = resolved.relative_to(vault_root.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None
    if nearest_enclosing_vault_root(resolved, search_root=vault_root) != vault_root.resolve():
        return None
    if scoped is not None and not scoped_note_path_owned_by_binding(scoped, resolved):
        return None
    if require_existing and not resolved.is_file():
        return None
    return relative


def _candidate_answer(
    row: dict[str, Any],
    *,
    question_id: str,
    question_version: str,
    vault_root: Path,
    scoped: ScopedRouteRead | None = None,
) -> CandidateAnswer | None:
    candidate_ref = row.get("candidate_answer_ref")
    if not isinstance(candidate_ref, str) or not candidate_ref.strip():
        return None
    try:
        from app.standing_questions.answer_refresh import _resolve_vault_ref

        draft_path = _resolve_vault_ref(vault_root, candidate_ref)
    except Exception:
        return CandidateAnswer(state="unreadable")
    if draft_path is None:
        # A live Question pointer whose draft vanished may be the crash window
        # after EXP-4 materialized the answer but before the Question CAS ack.
        # Do not quietly render it as answered or as a harmless empty candidate.
        return CandidateAnswer(state="acknowledgement_indeterminate")
    if nearest_enclosing_vault_root(draft_path, search_root=vault_root) != vault_root.resolve():
        # Carrier-free compatibility reads still inherit the parent's nested
        # vault boundary. A parent Question may contain a malformed reference
        # to a private child-vault draft; never read or return its body.
        return CandidateAnswer(state="unreadable")
    if scoped is not None and not scoped_note_path_owned_by_binding(scoped, draft_path):
        # Candidate references are vault-relative pointers, but nested child
        # vaults remain binding boundaries. Never return their content, even
        # when the parent Question note contains a malformed cross-binding ref.
        return CandidateAnswer(state="unreadable")
    try:
        note_path = draft_path.resolve().relative_to(vault_root.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return CandidateAnswer(state="unreadable")
    try:
        raw = draft_path.read_text(encoding="utf-8")
        frontmatter, body = load_frontmatter(raw)
    except (OSError, UnicodeError, ValueError):
        return CandidateAnswer(state="unreadable")
    frontmatter = frontmatter or {}
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    try:
        identity = resolve_note_artifact_identity(
            artifact_path=draft_path,
            vault_root=vault_root,
            safe_note_path=note_path,
            body=raw,
            heal_missing_uuid=False,
        )
    except Exception:
        return CandidateAnswer(state="not_selectable", draft_id=draft_id, body=body.strip())
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    options = extract_panel_selectable_options(
        normalized,
        artifact_id=str(identity.artifact_id or ""),
        note_path=note_path,
    )
    expected_option_id = standing_question_acceptance_option_id(draft_id)
    option = next(
        (
            item
            for item in options
            if item.option_id == expected_option_id
            and item.label == f"Accept this draft into the vault (draft {draft_id[:12]})"
            and item.proposal_pending
            and (item.selectable or item.checked)
        ),
        None,
    )
    control: dict[str, Any] | None = None
    state: Literal["pending", "not_selectable"] = "pending"
    if frontmatter.get("question_id") != question_id or identity.artifact_id != draft_id:
        state = "not_selectable"
    elif option is None:
        state = "not_selectable"
    else:
        source_hashes = _acceptance_source_hashes(normalized, option)
        if source_hashes is None:
            return CandidateAnswer(
                state="not_selectable",
                draft_id=draft_id,
                body=body.strip(),
                contradicts_standing_answer=frontmatter.get("contradicts_standing_answer"),
                contradiction_basis=frontmatter.get("contradiction_basis"),
            )
        expected_content_hash, expected_source_hash = source_hashes
        idempotency_material = "\x1f".join(
            (
                question_id,
                question_version,
                candidate_ref,
                expected_content_hash,
                expected_source_hash,
            )
        )
        key = "sq-accept-" + hashlib.sha256(idempotency_material.encode("utf-8")).hexdigest()
        control = CheckboxProjectionRequest(
            artifact_id=str(identity.artifact_id),
            note_path=note_path,
            panel_id=option.panel_id,
            option_id=option.option_id,
            expected_content_hash=expected_content_hash,
            expected_source_hash=expected_source_hash,
            idempotency_key=key,
            review_question_id=question_id,
            expected_question_version=question_version,
        ).model_dump(mode="json")

    return CandidateAnswer(
        state=state,
        draft_id=draft_id,
        body=body.strip(),
        contradicts_standing_answer=frontmatter.get("contradicts_standing_answer"),
        contradiction_basis=frontmatter.get("contradiction_basis"),
        acceptance_control=control,
    )


@router.get("", response_model=QuestionListResponse)
@scoped_route_read
def list_standing_questions(
    include_resolved: bool = Query(default=False),
) -> QuestionListResponse | JSONResponse:
    root, binding_id = _vault_and_binding()
    if isinstance(root, JSONResponse):
        return root
    rows = _current_projection_rows(root, binding_id)
    visible = rows if include_resolved else [row for row in rows if row["status"] == "open"]
    return QuestionListResponse(
        questions=[_item(row) for row in visible],
        include_resolved=include_resolved,
    )


@router.get("/{question_id}", response_model=QuestionDetailResponse)
@scoped_route_read
def read_standing_question(question_id: str) -> QuestionDetailResponse | JSONResponse:
    try:
        question_note_path(question_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"error": "question_not_found"}) from exc
    root, binding_id = _vault_and_binding()
    if isinstance(root, JSONResponse):
        return root
    rows = _current_projection_rows(root, binding_id)
    row = next((item for item in rows if item["question_id"] == question_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "question_not_found"})
    try:
        question, version = QuestionStore(root).read_question_with_version(question_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"error": "question_source_unavailable"}) from exc
    if not _projection_row_matches_note(
        row,
        question,
        source_path=question_note_path(question_id),
    ):
        raise HTTPException(
            status_code=503,
            detail={"error": "question_projection_stale", "message": "The Question changed during detail read."},
        )
    scoped = current_scoped_route_read()
    raw_evidence = row.get("evidence") or []
    if isinstance(raw_evidence, str):
        try:
            raw_evidence = json.loads(raw_evidence)
        except ValueError:
            raw_evidence = []
    evidence: list[EvidenceItem] = []
    if isinstance(raw_evidence, list):
        for entry in raw_evidence:
            if not isinstance(entry, dict):
                continue
            artifact_ref = entry.get("artifact_ref")
            allowed_source_path = _source_note_path(
                artifact_ref,
                vault_root=root,
                scoped=scoped,
                require_existing=False,
            )
            if (
                isinstance(artifact_ref, str)
                and artifact_ref.startswith("vault://")
                and allowed_source_path is None
            ):
                # The citation and quoted span are derived from the referenced
                # note. Suppress the whole item when that note is outside this
                # vault's read boundary, including for legacy unscoped reads.
                continue
            source_note_path = allowed_source_path
            if source_note_path is not None and not (root / source_note_path).is_file():
                # A missing source inside this vault does not invalidate its
                # canonical historical evidence; it only removes navigation.
                source_note_path = None
            evidence.append(
                EvidenceItem(
                    artifact_ref=str(artifact_ref or ""),
                    source_stream=str(entry.get("source_stream") or ""),
                    matched_at=str(entry.get("matched_at") or ""),
                    confidence_class=str(entry.get("confidence_class") or ""),
                    provenance_ref=entry.get("provenance_ref"),
                    quoted_span=str(entry.get("quoted_span") or ""),
                    content_hash=str(entry.get("content_hash") or ""),
                    source_note_path=source_note_path,
                )
            )
    candidate = _candidate_answer(
        row,
        question_id=question_id,
        question_version=version,
        vault_root=root,
        scoped=scoped,
    )
    return QuestionDetailResponse(
        **_item(row).model_dump(),
        scope=question["scope"],
        registered_via=question["registered_via"],
        question_version=version,
        standing_answer_ref=row.get("standing_answer_ref"),
        candidate_answer_ref=row.get("candidate_answer_ref"),
        evidence=evidence,
        candidate_answer=candidate,
    )


def _mutation_root() -> Path | JSONResponse:
    return compatibility_vault_root_or_selection_required(require_initialized=True)


def _raise_review_error(exc: QuestionReviewError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/{question_id}/dismiss",
    response_model=None,
    dependencies=[Depends(require_loopback_or_api_key)],
)
def dismiss_standing_question_candidate(
    question_id: str,
    request: QuestionVersionRequest,
) -> dict[str, Any] | JSONResponse:
    try:
        question_note_path(question_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"error": "question_not_found"}) from exc
    root = _mutation_root()
    if isinstance(root, JSONResponse):
        return root
    try:
        result = dismiss_question_candidate(
            question_id,
            vault_root=root,
            expected_question_version=request.expected_question_version,
        )
        _sync_compatibility_projection_after_mutation(root)
        return result
    except QuestionReviewError as exc:
        _raise_review_error(exc)


@router.post(
    "/{question_id}/close",
    response_model=None,
    dependencies=[Depends(require_loopback_or_api_key)],
)
def close_standing_question(
    question_id: str,
    request: QuestionVersionRequest,
) -> dict[str, Any] | JSONResponse:
    return _change_standing_question_status(question_id, request, status="closed")


@router.post(
    "/{question_id}/reopen",
    response_model=None,
    dependencies=[Depends(require_loopback_or_api_key)],
)
def reopen_standing_question(
    question_id: str,
    request: QuestionVersionRequest,
) -> dict[str, Any] | JSONResponse:
    return _change_standing_question_status(question_id, request, status="open")


def _change_standing_question_status(
    question_id: str,
    request: QuestionVersionRequest,
    *,
    status: Literal["open", "closed"],
) -> dict[str, Any] | JSONResponse:
    try:
        question_note_path(question_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"error": "question_not_found"}) from exc
    root = _mutation_root()
    if isinstance(root, JSONResponse):
        return root
    try:
        result = transition_question_status(
            question_id,
            vault_root=root,
            expected_question_version=request.expected_question_version,
            status=status,
        )
        _sync_compatibility_projection_after_mutation(root)
        return result
    except QuestionReviewError as exc:
        _raise_review_error(exc)


__all__ = [
    "QuestionDetailResponse",
    "QuestionListResponse",
    "router",
]
