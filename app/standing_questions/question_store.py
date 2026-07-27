"""Guarded, vault-canonical storage for human-terminal Question notes."""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from app.knowledge.contracts import WriteReceipt
from app.knowledge.write_ops import write_note_relative
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

WRITE_ACTION = "standing_questions.write_note"
QUESTION_DIRECTORY = "questions"
_HUMAN_OWNED_FIELDS = frozenset({"text", "status"})
_SYSTEM_OWNED_FIELDS = frozenset(
    {
        "evidence",
        "candidate_answer_ref",
        "standing_answer_ref",
        "last_matched_at",
        "last_refreshed_at",
    }
)
_IMMUTABLE_FIELDS = frozenset({"question_id", "scope", "created_at", "registered_via"})
_QUESTION_ID_RE = re.compile(r"^sq-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_RFC3339_DATETIME_RE = re.compile(
    r"^(?P<date>\d{4}-(?:0[1-9]|1[0-2])-\d{2})"
    r"T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
    r"(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$",
    re.ASCII | re.IGNORECASE,
)
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "question-note.schema.json"
_LOGGER = logging.getLogger(__name__)
_QUESTION_NOTE_FORMAT_CHECKER = FormatChecker()


@_QUESTION_NOTE_FORMAT_CHECKER.checks("date-time")
def _is_rfc3339_datetime(value: object) -> bool:
    """Validate the schema's RFC 3339 boundary without optional package imports."""
    if not isinstance(value, str):
        # JSON Schema's format assertion only applies after the type keyword.
        return True
    match = _RFC3339_DATETIME_RE.fullmatch(value)
    if match is None:
        return False
    try:
        datetime.strptime(match.group("date"), "%Y-%m-%d")
    except ValueError:
        return False
    return True


class HumanOwnedFieldMutationError(ValueError):
    """Raised before a write when an engine attempts to change human-owned content."""


def mint_question_id() -> str:
    return f"sq-{uuid.uuid4()}"


def question_note_path(question_id: str) -> str:
    _validate_question_id(question_id)
    return f"{QUESTION_DIRECTORY}/{question_id}.md"


def _validate_question_id(question_id: str) -> None:
    if not _QUESTION_ID_RE.fullmatch(question_id):
        raise ValueError("question_id must use the sq-<uuid> namespace")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _schema_validator() -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    # This seam owns its checker instead of relying on jsonschema's optional dependency
    # discovery. A stale host environment must not turn "format: date-time" into a no-op.
    return Draft202012Validator(schema, format_checker=_QUESTION_NOTE_FORMAT_CHECKER)


def validate_question_note(note: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a Question-note frontmatter payload and return a detached dict."""
    payload = dict(note)
    _schema_validator().validate(payload)
    return payload


def serialize_question_note(note: Mapping[str, Any]) -> str:
    payload = validate_question_note(note)
    # Shared round-trip helper (app.episodes.notes and 30+ other modules), not a
    # hand-rolled YAML split/dump -- keeps frontmatter parsing/rendering in one place.
    return dump_frontmatter(payload, payload["text"])


def parse_question_note(content: str) -> dict[str, Any]:
    metadata, _body = load_frontmatter(content)
    return validate_question_note(metadata)


class QuestionStore:
    """The sole production seam for writes to Question notes.

    The store deliberately exposes two write classes. New notes are created only
    by a caller that represents an already-confirmed registration. Existing notes
    can receive only bounded system-owned updates from the engine.
    """

    def __init__(self, vault_root: Path | str, *, write_guard: WriteGuard | None = None) -> None:
        self.vault_root = Path(vault_root).expanduser().resolve()
        self.write_guard = write_guard or DEFAULT_WRITE_GUARD

    def create_question(
        self,
        *,
        text: str,
        scope: str,
        registered_via: str,
        question_id: str | None = None,
        created_at: str | None = None,
    ) -> tuple[dict[str, Any], WriteReceipt]:
        question_id = question_id or mint_question_id()
        _validate_question_id(question_id)
        note: dict[str, Any] = {
            "question_id": question_id,
            "scope": scope,
            "text": text,
            "status": "open",
            "created_at": created_at if created_at is not None else _utc_now(),
            "registered_via": registered_via,
            "standing_answer_ref": None,
            "candidate_answer_ref": None,
            "evidence": [],
            "last_matched_at": None,
            "last_refreshed_at": None,
        }
        path = self._path(question_id)
        if path.exists():
            raise FileExistsError(f"Question note already exists: {question_id}")
        receipt = self._write(note)
        return note, receipt

    def read_question(self, question_id: str) -> dict[str, Any]:
        return parse_question_note(self._path(question_id).read_text(encoding="utf-8"))

    def update_system_fields(
        self, question_id: str, updates: Mapping[str, Any]
    ) -> tuple[dict[str, Any], WriteReceipt]:
        current = self.read_question(question_id)
        changes = dict(updates)
        forbidden = set(changes) & (_HUMAN_OWNED_FIELDS | _IMMUTABLE_FIELDS)
        unknown = set(changes) - _SYSTEM_OWNED_FIELDS
        if forbidden or unknown:
            fields = ", ".join(sorted(forbidden | unknown))
            _LOGGER.warning(
                "Rejected Standing Questions engine write for human-owned or unsupported fields: %s",
                fields,
            )
            raise HumanOwnedFieldMutationError(
                f"engine cannot mutate Question-note fields: {fields}"
            )
        if "evidence" in changes:
            evidence = changes["evidence"]
            if not isinstance(evidence, list) or evidence[: len(current["evidence"])] != current["evidence"]:
                raise ValueError("engine evidence updates must append to the existing evidence list")
        updated = {**current, **changes}
        receipt = self._write(updated)
        return updated, receipt

    def _path(self, question_id: str) -> Path:
        return self.vault_root / question_note_path(question_id)

    def _write(self, note: Mapping[str, Any]) -> WriteReceipt:
        payload = validate_question_note(note)
        # This is the production seam assertion. It runs before serialisation,
        # path creation, or any filesystem mutation; write_note_relative repeats
        # the guard at the shared port as defense in depth.
        self.write_guard.assert_writes_allowed(WRITE_ACTION)
        receipt = write_note_relative(
            question_note_path(payload["question_id"]),
            serialize_question_note(payload),
            vault_root=self.vault_root,
            action=WRITE_ACTION,
            write_guard=self.write_guard,
        )
        return replace(receipt, operation=WRITE_ACTION)


__all__ = [
    "HumanOwnedFieldMutationError",
    "QUESTION_DIRECTORY",
    "QuestionStore",
    "WRITE_ACTION",
    "mint_question_id",
    "parse_question_note",
    "question_note_path",
    "serialize_question_note",
    "validate_question_note",
]
