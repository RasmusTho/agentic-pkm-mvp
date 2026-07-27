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
    r"^(?P<year>[0-9]{4})-(?P<month>0[1-9]|1[0-2])-(?P<day>[0-9]{2})"
    r"[Tt](?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9]):"
    r"(?P<second>[0-5][0-9]|60)(?:\.[0-9]+)?"
    r"(?P<timezone>[Zz]|(?P<offset_sign>[+-])"
    r"(?P<offset_hour>[01][0-9]|2[0-3]):(?P<offset_minute>[0-5][0-9]))$",
    re.ASCII,
)
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "question-note.schema.json"
_LOGGER = logging.getLogger(__name__)
_QUESTION_NOTE_FORMAT_CHECKER = FormatChecker()


def _is_gregorian_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_in_gregorian_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if _is_gregorian_leap_year(year) else 28
    return 30 if month in {4, 6, 9, 11} else 31


def _shift_gregorian_date(
    year: int, month: int, day: int, day_delta: int
) -> tuple[int, int, int] | None:
    """Shift a four-digit RFC 3339 date by at most one day."""
    if day_delta == 0:
        return year, month, day
    if day_delta == -1:
        if day > 1:
            return year, month, day - 1
        if month > 1:
            previous_month = month - 1
            return year, previous_month, _days_in_gregorian_month(year, previous_month)
        if year == 0:
            return None
        return year - 1, 12, 31
    if day < _days_in_gregorian_month(year, month):
        return year, month, day + 1
    if month < 12:
        return year, month + 1, 1
    if year == 9999:
        return None
    return year + 1, 1, 1


def _is_rfc3339_leap_second(match: re.Match[str]) -> bool:
    """Check whether a local ``:60`` maps to an RFC 3339 UTC leap-second point."""
    timezone_text = match.group("timezone")
    offset_minutes = 0
    if timezone_text not in {"Z", "z"}:
        offset_minutes = int(match.group("offset_hour")) * 60 + int(
            match.group("offset_minute")
        )
        if match.group("offset_sign") == "-":
            offset_minutes = -offset_minutes

    utc_minute = int(match.group("hour")) * 60 + int(match.group("minute")) - offset_minutes
    day_delta = 0
    if utc_minute < 0:
        utc_minute += 24 * 60
        day_delta = -1
    elif utc_minute >= 24 * 60:
        utc_minute -= 24 * 60
        day_delta = 1

    utc_date = _shift_gregorian_date(
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        day_delta,
    )
    if utc_date is None:
        return False
    _utc_year, utc_month, utc_day = utc_date
    return (
        (utc_month, utc_day) in {(6, 30), (12, 31)}
        and divmod(utc_minute, 60) == (23, 59)
    )


@_QUESTION_NOTE_FORMAT_CHECKER.checks("date-time")
def _is_rfc3339_datetime(value: object) -> bool:
    """Validate the schema's RFC 3339 boundary without optional package imports."""
    if not isinstance(value, str):
        # JSON Schema's format assertion only applies after the type keyword.
        return True
    match = _RFC3339_DATETIME_RE.fullmatch(value)
    if match is None:
        return False
    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    # RFC 3339 uses a four-digit proleptic Gregorian year and includes 0000.
    # datetime.strptime() rejects that boundary, so validate the calendar directly.
    if not 1 <= day <= _days_in_gregorian_month(year, month):
        return False
    # A format checker validates legal leap-second positions. Whether a producer
    # may emit a particular announced leap second is a separate clock policy.
    return match.group("second") != "60" or _is_rfc3339_leap_second(match)


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
