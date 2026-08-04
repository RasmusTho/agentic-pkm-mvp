"""Guarded, vault-canonical storage for human-terminal Question notes."""
from __future__ import annotations

import fcntl
import json
import logging
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

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
    r"(?P<second>[0-5][0-9]|60)(?P<fraction>\.[0-9]+)?"
    r"(?P<timezone>[Zz]|(?P<offset_sign>[+-])"
    r"(?P<offset_hour>[01][0-9]|2[0-3]):(?P<offset_minute>[0-5][0-9]))$",
    re.ASCII,
)
#: UTC dates (year, month, day) on which a leap second was actually announced and
#: inserted at ``23:59:60Z``, per the IERS Bulletin C leap-second announcements.
#:
#: MAINTENANCE: this table is repo-local and hand-maintained on purpose — validation
#: must never perform a network lookup, and a durable-write seam must not depend on an
#: external service being reachable. When IERS announces a new leap second, add its UTC
#: date here and bump ``ANNOUNCED_LEAP_SECOND_TABLE_REVIEWED``. Until then, a ``:60``
#: second at any other instant is rejected, not stored. See
#: ``docs/STANDING_QUESTIONS/STORE_QUESTION_NOTES_AND_PROJECTION.md :: What This Task Does``.
ANNOUNCED_LEAP_SECOND_UTC_DATES: frozenset[tuple[int, int, int]] = frozenset(
    {
        (1972, 6, 30),
        (1972, 12, 31),
        (1973, 12, 31),
        (1974, 12, 31),
        (1975, 12, 31),
        (1976, 12, 31),
        (1977, 12, 31),
        (1978, 12, 31),
        (1979, 12, 31),
        (1981, 6, 30),
        (1982, 6, 30),
        (1983, 6, 30),
        (1985, 6, 30),
        (1987, 12, 31),
        (1989, 12, 31),
        (1990, 12, 31),
        (1992, 6, 30),
        (1993, 6, 30),
        (1994, 6, 30),
        (1995, 12, 31),
        (1997, 6, 30),
        (1998, 12, 31),
        (2005, 12, 31),
        (2008, 12, 31),
        (2012, 6, 30),
        (2015, 6, 30),
        (2016, 12, 31),
    }
)
#: Date this repo-local table was last reconciled against the IERS announcements.
#: No leap second has been announced since 2016-12-31.
ANNOUNCED_LEAP_SECOND_TABLE_REVIEWED = "2026-07-28"
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "question-note.schema.json"
_LOGGER = logging.getLogger(__name__)
_QUESTION_NOTE_FORMAT_CHECKER = FormatChecker()


@dataclass(frozen=True)
class Rfc3339DateTime:
    """Parsed components shared by validation and projection adaptation."""

    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    fraction: str
    offset_minutes: int

    def utc_date_and_minute(
        self, *, minute_delta: int = 0
    ) -> tuple[int, int, int, int, int]:
        """Return the offset-adjusted UTC calendar date, hour, and minute.

        ``minute_delta`` shifts the result by whole minutes. The projection boundary
        passes ``1`` to fold a leap second onto the following minute; no caller needs a
        larger shift, and a larger one is refused by :func:`_shift_gregorian_date`
        because the legal offset range (±23:59) plus one minute can never move the
        calendar date by more than a day.
        """
        utc_minute, minute = divmod(
            self.hour * 60 + self.minute - self.offset_minutes + minute_delta,
            60,
        )
        day_delta, hour = divmod(utc_minute, 24)
        year, month, day = _shift_gregorian_date(
            self.year,
            self.month,
            self.day,
            day_delta,
        )
        return year, month, day, hour, minute


def _is_gregorian_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_in_gregorian_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if _is_gregorian_leap_year(year) else 28
    return 30 if month in {4, 6, 9, 11} else 31


def _shift_gregorian_date(
    year: int, month: int, day: int, day_delta: int
) -> tuple[int, int, int]:
    """Shift a proleptic Gregorian date by at most one day."""
    if day_delta not in {-1, 0, 1}:
        raise ValueError("RFC 3339 offset adjustment cannot exceed one day")
    if day_delta == 0:
        return year, month, day
    if day_delta == -1:
        if day > 1:
            return year, month, day - 1
        if month > 1:
            previous_month = month - 1
            return year, previous_month, _days_in_gregorian_month(year, previous_month)
        return year - 1, 12, 31
    if day < _days_in_gregorian_month(year, month):
        return year, month, day + 1
    if month < 12:
        return year, month + 1, 1
    return year + 1, 1, 1


def _is_announced_leap_second(timestamp: Rfc3339DateTime) -> bool:
    """Check whether a local ``:60`` maps to an announced UTC leap second.

    RFC 3339 permits ``:60`` only where a leap second was actually announced, so a
    legal *position* (a June/December month-end ``23:59`` UTC) is not sufficient.
    Acceptance is decided against :data:`ANNOUNCED_LEAP_SECOND_UTC_DATES`.
    """
    utc_year, utc_month, utc_day, utc_hour, utc_minute = timestamp.utc_date_and_minute()
    return (
        (utc_hour, utc_minute) == (23, 59)
        and (utc_year, utc_month, utc_day) in ANNOUNCED_LEAP_SECOND_UTC_DATES
    )


def parse_rfc3339_datetime(value: str) -> Rfc3339DateTime | None:
    """Return validated RFC 3339 components, or ``None`` for an invalid value."""
    match = _RFC3339_DATETIME_RE.fullmatch(value)
    if match is None:
        return None
    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    # RFC 3339 uses a four-digit proleptic Gregorian year and includes 0000.
    # datetime.strptime() rejects that boundary, so validate the calendar directly.
    if not 1 <= day <= _days_in_gregorian_month(year, month):
        return None
    offset_minutes = 0
    if match.group("timezone") not in {"Z", "z"}:
        offset_minutes = int(match.group("offset_hour")) * 60 + int(
            match.group("offset_minute")
        )
        if match.group("offset_sign") == "-":
            offset_minutes = -offset_minutes
    timestamp = Rfc3339DateTime(
        year=year,
        month=month,
        day=day,
        hour=int(match.group("hour")),
        minute=int(match.group("minute")),
        second=int(match.group("second")),
        fraction=match.group("fraction") or "",
        offset_minutes=offset_minutes,
    )
    # RFC 3339 admits ":60" only where a leap second was announced, so a legal
    # position is not enough; the value is checked against the announced table.
    if timestamp.second == 60 and not _is_announced_leap_second(timestamp):
        return None
    return timestamp


@_QUESTION_NOTE_FORMAT_CHECKER.checks("date-time")
def _is_rfc3339_datetime(value: object) -> bool:
    """Validate the schema's RFC 3339 boundary without optional package imports."""
    if not isinstance(value, str):
        # JSON Schema's format assertion only applies after the type keyword.
        return True
    return parse_rfc3339_datetime(value) is not None


class HumanOwnedFieldMutationError(ValueError):
    """Raised before a write when an engine attempts to change human-owned content."""


class QuestionNotOpenError(RuntimeError):
    """Raised at the guarded write seam when an evidence append targets a
    question that is no longer ``open`` (INV-SQ-F: answered/closed/rejected are
    terminal for the engine)."""


def mint_question_id() -> str:
    return f"sq-{uuid.uuid4()}"


def question_note_path(question_id: str) -> str:
    _validate_question_id(question_id)
    return f"{QUESTION_DIRECTORY}/{question_id}.md"


def question_note_lock_path(vault_root: Path | str, question_id: str) -> Path:
    """The per-note lock file :meth:`QuestionStore.append_evidence` serializes on.

    Exposed (rather than kept private) so the atomicity contract is testable
    against the exact file the seam locks. A ``.md.lock`` sibling follows the
    ``app.agent_memory.provisional_write`` ledger-lock idiom and is invisible to
    the projection walker (which only reads ``*.md``).
    """
    return (
        Path(vault_root).expanduser().resolve()
        / f"{question_note_path(question_id)}.lock"
    )


@contextmanager
def _question_note_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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

    def append_evidence(
        self,
        question_id: str,
        entries: Sequence[Mapping[str, Any]],
        *,
        matched_at: str | None = None,
    ) -> tuple[dict[str, Any], WriteReceipt | None, list[dict[str, Any]]]:
        """Atomically append evidence entries to an ``open`` question (#4610 P2).

        The open-status predicate and the append are one operation at this
        guarded seam: the note is re-read *inside* an exclusive per-note flock
        (:func:`question_note_lock_path`), the status predicate runs against
        that same fresh read, and the write derives from it -- so concurrent
        engine writers serialize, and a close that lands before this writer's
        turn raises :class:`QuestionNotOpenError` instead of appending to (or
        overwriting the terminal status of) a non-open question. Checking
        status in the caller and writing through a separate read-modify-write
        (the pre-#4610 shape) left a window where a mid-flight human close
        received new evidence or was resurrected by a stale ``open`` payload.

        Idempotency is preserved under the same fresh read: an entry whose
        ``(artifact_ref, quoted_span)`` basis already exists on the note (for
        example appended by a concurrent tick that won the lock first) is
        dropped, never duplicated. When every entry is dropped, nothing is
        written and the receipt is ``None``.

        Returns ``(note, receipt, appended_entries)`` -- ``appended_entries``
        is the subset of ``entries`` actually written, so a caller's outcome
        counters can distinguish attached from duplicate-dropped.
        """
        entry_list = [dict(entry) for entry in entries]
        if not entry_list:
            raise ValueError("append_evidence requires at least one evidence entry")
        path = self._path(question_id)
        with _question_note_lock(question_note_lock_path(self.vault_root, question_id)):
            current = parse_question_note(path.read_text(encoding="utf-8"))
            if current["status"] != "open":
                raise QuestionNotOpenError(
                    f"question {question_id} is {current['status']!r}; evidence appends "
                    "only ever target open questions (INV-SQ-F)"
                )
            existing_bases = {
                (entry.get("artifact_ref"), entry.get("quoted_span"))
                for entry in current["evidence"]
            }
            fresh_entries = [
                entry
                for entry in entry_list
                if (entry.get("artifact_ref"), entry.get("quoted_span")) not in existing_bases
            ]
            if not fresh_entries:
                return current, None, []
            updated = {
                **current,
                "evidence": [*current["evidence"], *fresh_entries],
                "last_matched_at": matched_at if matched_at is not None else _utc_now(),
            }
            receipt = self._write(updated)
            return updated, receipt, fresh_entries

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
    "ANNOUNCED_LEAP_SECOND_TABLE_REVIEWED",
    "ANNOUNCED_LEAP_SECOND_UTC_DATES",
    "HumanOwnedFieldMutationError",
    "QUESTION_DIRECTORY",
    "QuestionNotOpenError",
    "QuestionStore",
    "Rfc3339DateTime",
    "WRITE_ACTION",
    "mint_question_id",
    "parse_question_note",
    "parse_rfc3339_datetime",
    "question_note_lock_path",
    "question_note_path",
    "serialize_question_note",
    "validate_question_note",
]
