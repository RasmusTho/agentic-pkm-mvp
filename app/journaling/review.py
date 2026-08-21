"""Governed review and materialization of staged journal candidates (JRNL-04).

The vault-visible Panel checkbox is the sole acceptance input.  A checked
accept action is durable pending intent; this module never needs an in-memory
approval object or a second tap after a transient WriteGuard refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
from uuid import uuid4

from app.journaling.draft import (
    CANONICAL_JOURNAL_SUBDIR,
    _draft_relative_path,
    _locked_draft,
)
from app.journaling.lifecycle import (
    JournalCandidateType,
    JournalCandidateContractError,
    checked_journal_action,
    journal_decline_finding_id,
    strip_journal_review_panel,
)
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.write_ops import (
    _atomic_rename_noreplace_at,
    append_note_relative,
    locked_atomic_append_authority,
)
from app.proposals.declined_ledger import (
    DECLINED_LEDGER_WRITE_ACTION,
    DeclinedLedger,
    default_declined_ledger,
)
from app.services.outbox import serialize_outbox_record
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


JOURNAL_ENTRY_ACCEPT_WRITE_ACTION = "journal.entry.accept"
JOURNAL_ENTRY_ACCEPTED_EVENT = "journal.entry.accepted"
JOURNAL_ENTRY_DECLINED_EVENT = "journal.entry.declined"
JOURNAL_REVIEW_EVENT_SOURCE = "app.journaling.review"
DEFAULT_JOURNAL_REVIEW_OUTBOX_PATH = Path("runtime/journal-review-outbox.jsonl")

_RETIREMENT_MARKER = ".journal-retire-"
_RETIRED_MARKER = ".journal-retired-"
_CANDIDATE_NAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})(?P<addendum>-addendum)?\.md$"
)


class JournalReviewError(RuntimeError):
    """Base class for fail-loud review refusals."""


class JournalReviewConflictError(JournalReviewError):
    """The durable review state is malformed, ambiguous, or changed."""


class JournalAcceptedEntryExistsError(JournalReviewError):
    """A primary candidate cannot replace an existing canonical daily note."""


class JournalReviewState(str, Enum):
    NOT_YET_REVIEWED = "not_yet_reviewed"
    ACCEPTED_PENDING_MATERIALIZATION = "accepted_pending_materialization"
    FULLY_MATERIALIZED = "fully_materialized"
    DISMISSAL_PENDING = "dismissal_pending"
    DISMISSED = "dismissed"


@dataclass(frozen=True)
class JournalReviewProjection:
    state: JournalReviewState
    canonical_path: str
    candidate_path: str | None
    candidate_type: str | None
    rendered_body: str | None
    status_message: str


@dataclass(frozen=True)
class JournalReviewResult:
    state: JournalReviewState
    action: str | None
    canonical_path: str
    candidate_path: str | None
    candidate_type: str | None
    receipt_id: str | None
    decision_token_ref: str | None
    status_message: str


@dataclass(frozen=True)
class JournalReviewTickResult:
    scanned_dates: tuple[str, ...]
    results: tuple[JournalReviewResult, ...]

    @property
    def materialized(self) -> int:
        return sum(
            result.state is JournalReviewState.FULLY_MATERIALIZED
            for result in self.results
        )

    @property
    def pending(self) -> int:
        return sum(
            result.state
            in {
                JournalReviewState.ACCEPTED_PENDING_MATERIALIZATION,
                JournalReviewState.DISMISSAL_PENDING,
            }
            for result in self.results
        )


@dataclass(frozen=True)
class _Candidate:
    relative_path: Path
    candidate_type: JournalCandidateType
    draft_id: str
    frontmatter: dict[str, Any]
    body: str
    raw: bytes
    identity: os.stat_result
    action: str | None
    storage_filename: str


def journal_draft_relative_path(
    vault_root: Path, for_date: date, *, is_addendum: bool
) -> Path:
    """Return JRNL-03's canonical candidate location for review callers."""

    return _draft_relative_path(
        Path(vault_root).expanduser().resolve(),
        for_date,
        is_addendum=is_addendum,
    )


def project_journal_review(
    *, vault_context: VaultContext, for_date: date
) -> JournalReviewProjection:
    """Render the current review state without mutating any durable surface."""

    vault_root = _vault_root(vault_context)
    canonical_rel = _canonical_relative_path(for_date)
    canonical = vault_root / canonical_rel
    selected = _select_candidate(vault_root, for_date)
    if selected is None:
        if _path_exists_no_symlink(canonical):
            _require_accepted_canonical(canonical.read_bytes(), canonical_rel.as_posix())
            return JournalReviewProjection(
                state=JournalReviewState.FULLY_MATERIALIZED,
                canonical_path=canonical_rel.as_posix(),
                candidate_path=None,
                candidate_type=None,
                rendered_body=None,
                status_message="Saved",
            )
        retired = _retired_candidates(vault_root, for_date)
        if retired:
            for relative_path, candidate_type, storage_path in retired:
                candidate = _read_candidate_path(
                    vault_root,
                    storage_path,
                    relative_path=relative_path,
                    candidate_type=candidate_type,
                    for_date=for_date,
                )
                if candidate.action != "dismiss":
                    raise JournalReviewConflictError(
                        "accepted candidate archive exists without its canonical journal"
                    )
                expected_name = (
                    f".{relative_path.name}{_RETIRED_MARKER}"
                    f"{_decline_receipt_id(candidate)}"
                )
                if storage_path.name != expected_name:
                    raise JournalReviewConflictError(
                        "dismissed candidate archive is not bound to its exact receipt"
                    )
            return JournalReviewProjection(
                state=JournalReviewState.DISMISSED,
                canonical_path=canonical_rel.as_posix(),
                candidate_path=None,
                candidate_type=None,
                rendered_body=None,
                status_message="Dismissed",
            )
        return JournalReviewProjection(
            state=JournalReviewState.NOT_YET_REVIEWED,
            canonical_path=canonical_rel.as_posix(),
            candidate_path=None,
            candidate_type=None,
            rendered_body=None,
            status_message="Not yet reviewed",
        )

    relative_path, candidate_type, storage_path = selected
    candidate = _read_candidate_path(
        vault_root,
        storage_path,
        relative_path=relative_path,
        candidate_type=candidate_type,
        for_date=for_date,
    )
    state, message = _projection_state(candidate.action)
    return JournalReviewProjection(
        state=state,
        canonical_path=canonical_rel.as_posix(),
        candidate_path=relative_path.as_posix(),
        candidate_type=candidate_type,
        rendered_body=_strip_review_panel(candidate.body),
        status_message=message,
    )


def process_journal_review(
    *,
    vault_context: VaultContext,
    for_date: date,
    outbox_path: Path,
    declined_ledger: DeclinedLedger | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    now: datetime | None = None,
) -> JournalReviewResult:
    """Process the checked action on the current staged journal candidate.

    No approval flag, destination, or accepted body is accepted from callers.
    The current on-disk candidate and its exact Panel action are authoritative.
    """

    vault_root = _vault_root(vault_context)
    canonical_rel = _canonical_relative_path(for_date)
    primary_rel = journal_draft_relative_path(
        vault_root, for_date, is_addendum=False
    )
    with _locked_draft(vault_root, primary_rel) as (directory_fd, _primary_name):
        selected = _select_candidate_at(directory_fd, for_date)
        if selected is None:
            projection = project_journal_review(
                vault_context=vault_context, for_date=for_date
            )
            return JournalReviewResult(
                state=projection.state,
                action=None,
                canonical_path=projection.canonical_path,
                candidate_path=None,
                candidate_type=None,
                receipt_id=None,
                decision_token_ref=None,
                status_message=projection.status_message,
            )

        logical_name, candidate_type, filename = selected
        candidate_rel = primary_rel.parent / logical_name
        try:
            candidate = _read_candidate_at(
                directory_fd,
                filename,
                relative_path=candidate_rel,
                candidate_type=candidate_type,
                for_date=for_date,
            )
        except FileNotFoundError:
            raise JournalReviewConflictError(
                "journal candidate disappeared while its per-day lifecycle lock was held"
            ) from None

        if candidate.action is None:
            return _result(
                state=JournalReviewState.NOT_YET_REVIEWED,
                action=None,
                canonical_rel=canonical_rel,
                candidate=candidate,
                status_message="Not yet reviewed",
            )
        if candidate.action == "dismiss":
            return _dismiss_candidate(
                candidate,
                directory_fd=directory_fd,
                canonical_rel=canonical_rel,
                outbox_path=Path(outbox_path),
                declined_ledger=declined_ledger or default_declined_ledger(),
                write_guard=write_guard,
                now=_aware_now(now),
            )

        try:
            # Assert before any acceptance-owned lock, parent creation, recovery
            # artifact, or canonical mutation. append_note_relative asserts the
            # same named action again at the production vault port.
            write_guard.assert_writes_allowed(JOURNAL_ENTRY_ACCEPT_WRITE_ACTION)
        except WritesBlockedError:
            return _result(
                state=JournalReviewState.ACCEPTED_PENDING_MATERIALIZATION,
                action="accept",
                canonical_rel=canonical_rel,
                candidate=candidate,
                status_message="Accepted — waiting to save",
            )

        return _accept_candidate(
            candidate,
            vault_root=vault_root,
            canonical_rel=canonical_rel,
            directory_fd=directory_fd,
            outbox_path=Path(outbox_path),
            write_guard=write_guard,
            now=_aware_now(now),
        )


def process_journal_reviews_tick(
    *,
    vault_context: VaultContext,
    outbox_path: Path | None = None,
    declined_ledger: DeclinedLedger | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    now: datetime | None = None,
    only_date: date | None = None,
) -> JournalReviewTickResult:
    """Observe durable candidates and advance checked actions once per tick.

    This is the production retry seam. A checked accept remains in the vault
    when WriteGuard blocks; a later healthy invocation rediscovers and
    materializes it without another human action.
    """

    dates = (only_date,) if only_date is not None else _candidate_dates(vault_context)
    receipt_path = outbox_path or default_journal_review_outbox_path()
    results = tuple(
        process_journal_review(
            vault_context=vault_context,
            for_date=for_date,
            outbox_path=receipt_path,
            declined_ledger=declined_ledger,
            write_guard=write_guard,
            now=now,
        )
        for for_date in dates
    )
    return JournalReviewTickResult(
        scanned_dates=tuple(item.isoformat() for item in dates),
        results=results,
    )


def default_journal_review_outbox_path() -> Path:
    override = os.getenv("JOURNAL_REVIEW_OUTBOX_PATH", "").strip()
    return Path(override).expanduser() if override else DEFAULT_JOURNAL_REVIEW_OUTBOX_PATH


def _candidate_dates(vault_context: VaultContext) -> tuple[date, ...]:
    vault_root = _vault_root(vault_context)
    primary = journal_draft_relative_path(
        vault_root, date.min, is_addendum=False
    )
    directory = vault_root / primary.parent
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return ()
    dates: set[date] = set()
    for name in names:
        logical_name = name
        if name.startswith(".") and _RETIREMENT_MARKER in name:
            logical_name = name[1:].split(_RETIREMENT_MARKER, 1)[0]
        match = _CANDIDATE_NAME_RE.fullmatch(logical_name)
        if match is None:
            continue
        observed = (directory / name).lstat()
        if stat.S_ISLNK(observed.st_mode) or not stat.S_ISREG(observed.st_mode):
            raise JournalReviewConflictError(
                "journal candidate lifecycle path must be a regular file"
            )
        dates.add(date.fromisoformat(match.group("date")))
    return tuple(sorted(dates))


def _accept_candidate(
    candidate: _Candidate,
    *,
    vault_root: Path,
    canonical_rel: Path,
    directory_fd: int,
    outbox_path: Path,
    write_guard: WriteGuard,
    now: datetime,
) -> JournalReviewResult:
    candidate_digest = hashlib.sha256(candidate.raw).hexdigest()
    decision_token_ref = "dtok-" + hashlib.sha256(
        (
            f"journal-human-checkbox\x1f{candidate.draft_id}\x1f"
            f"{candidate.candidate_type}\x1f{candidate_digest}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    receipt_id = "journal-accept-" + hashlib.sha256(
        (
            f"{decision_token_ref}\x1f{canonical_rel.as_posix()}\x1f"
            f"{candidate.candidate_type}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    accepted_at = _iso(now)
    materialized_at = accepted_at
    materialized_body = _strip_review_panel(candidate.body).rstrip() + "\n"

    if candidate.candidate_type == "primary":
        proposed_append = materialized_body.encode("utf-8")

        def primary_transform(
            current_raw: bytes | None, proposed: bytes
        ) -> tuple[bytes, bytes]:
            nonlocal materialized_at
            _assert_candidate_unchanged_at(directory_fd, candidate)
            if current_raw is not None:
                current_frontmatter, _current_body = _load_raw_frontmatter(current_raw)
                if (
                    current_frontmatter.get("authority_state") == "accepted"
                    and current_frontmatter.get("acceptance_receipt_id") == receipt_id
                    and current_frontmatter.get("accepted_draft_id")
                    == candidate.draft_id
                    and current_frontmatter.get("decision_token_ref")
                    == decision_token_ref
                ):
                    _require_accepted_frontmatter(
                        current_frontmatter, canonical_rel.as_posix()
                    )
                    materialized_at = _normalized_timestamp(
                        current_frontmatter["accepted_at"],
                        description="accepted journal entry",
                    )
                    return current_raw, b""
                raise JournalAcceptedEntryExistsError(
                    "the canonical daily note already exists; a primary candidate "
                    "can never replace its body"
                )
            accepted_frontmatter = dict(candidate.frontmatter)
            accepted_frontmatter["authority_state"] = "accepted"
            accepted_frontmatter["accepted_by"] = "human"
            accepted_frontmatter["accepted_at"] = accepted_at
            accepted_frontmatter["acceptance_receipt_id"] = receipt_id
            accepted_frontmatter["decision_token_ref"] = decision_token_ref
            accepted_frontmatter["accepted_draft_id"] = candidate.draft_id
            accepted_frontmatter.pop("kind", None)
            accepted_frontmatter.pop("journal_candidate_type", None)
            accepted_frontmatter.pop("expires", None)
            replacement = dump_frontmatter(
                accepted_frontmatter, proposed.decode("utf-8")
            ).encode("utf-8")
            return replacement, proposed

        action = "accept"
        transform = primary_transform
    else:
        proposed_append = _render_addendum_block(
            receipt_id=receipt_id,
            draft_id=candidate.draft_id,
            accepted_at=accepted_at,
            materialized_body=materialized_body,
        )

        def addendum_transform(
            current_raw: bytes | None, proposed: bytes
        ) -> tuple[bytes, bytes]:
            nonlocal materialized_at
            _assert_candidate_unchanged_at(directory_fd, candidate)
            if current_raw is None:
                raise JournalAcceptedEntryExistsError(
                    "an addendum requires an existing accepted journal entry"
                )
            current_frontmatter, current_body = _load_raw_frontmatter(current_raw)
            _require_accepted_frontmatter(
                current_frontmatter, canonical_rel.as_posix()
            )
            recovered = _recover_addendum_block(
                current_body,
                receipt_id=receipt_id,
                draft_id=candidate.draft_id,
                materialized_body=materialized_body,
            )
            if recovered is not None:
                materialized_at = recovered
                expected = _render_addendum_block(
                    receipt_id=receipt_id,
                    draft_id=candidate.draft_id,
                    accepted_at=materialized_at,
                    materialized_body=materialized_body,
                )
                if not current_body.endswith(expected):
                    raise JournalReviewConflictError(
                        "accepted addendum block is no longer the exact journal suffix"
                    )
                return current_raw, b""
            return current_raw + proposed, proposed

        action = "accept_addendum"
        transform = addendum_transform

    try:
        with locked_atomic_append_authority(
            vault_root, canonical_rel.as_posix()
        ) as authority:
            append_note_relative(
                canonical_rel.as_posix(),
                proposed_append.decode("utf-8"),
                vault_root=vault_root,
                action=JOURNAL_ENTRY_ACCEPT_WRITE_ACTION,
                write_guard=write_guard,
                _atomic_transform=transform,
                _atomic_authority=authority,
            )
    except KnowledgeWriteConflict as exc:
        raise JournalReviewConflictError(
            "the canonical journal entry changed during acceptance; the durable "
            "checked candidate remains available for a safe retry"
        ) from exc

    payload = {
        "draft_id": candidate.draft_id,
        "candidate_type": candidate.candidate_type,
        "final_note_path": canonical_rel.as_posix(),
        "sources": list(_sources(candidate.frontmatter)),
        "decision_token_ref": decision_token_ref,
        "authority_receipt_id": receipt_id,
        "accepted_by": "human",
        "accepted_at": materialized_at,
        "operation": action,
    }
    _emit_event_once(
        outbox_path,
        event=JOURNAL_ENTRY_ACCEPTED_EVENT,
        event_id=receipt_id,
        trace_id=candidate.draft_id,
        timestamp=materialized_at,
        payload=payload,
    )
    _retire_candidate_if_unchanged(
        directory_fd,
        candidate,
        receipt_id=receipt_id,
    )
    return _result(
        state=JournalReviewState.FULLY_MATERIALIZED,
        action=action,
        canonical_rel=canonical_rel,
        candidate=candidate,
        receipt_id=receipt_id,
        decision_token_ref=decision_token_ref,
        status_message="Saved",
    )


def _dismiss_candidate(
    candidate: _Candidate,
    *,
    directory_fd: int,
    canonical_rel: Path,
    outbox_path: Path,
    declined_ledger: DeclinedLedger,
    write_guard: WriteGuard,
    now: datetime,
) -> JournalReviewResult:
    # Reading/reconciling the receipt creates its lock file on first use, so
    # assert the shared decline action before any dismissal-owned filesystem
    # mutation. DeclinedLedger asserts the same action again at its write port.
    write_guard.assert_writes_allowed(DECLINED_LEDGER_WRITE_ACTION)
    finding_id = journal_decline_finding_id(
        candidate_type=candidate.candidate_type,
        for_date=str(candidate.frontmatter["for_date"]),
        frontmatter=candidate.frontmatter,
        body=candidate.body,
    )
    receipt_id = _decline_receipt_id(candidate)
    existing_event = _read_event(outbox_path, receipt_id)
    ledger_receipt = declined_ledger.get_receipt(finding_id)
    event_timestamp = (
        _normalized_timestamp(
            existing_event.get("timestamp"), description="journal decline event"
        )
        if existing_event is not None
        else None
    )
    ledger_timestamp = (
        _normalized_timestamp(
            ledger_receipt.declined_at, description="journal decline ledger receipt"
        )
        if ledger_receipt is not None and ledger_receipt.declined_at is not None
        else None
    )
    if event_timestamp and ledger_timestamp and event_timestamp != ledger_timestamp:
        raise JournalReviewConflictError(
            "journal dismissal ledger and event carry different timestamps"
        )
    timestamp = event_timestamp or ledger_timestamp or _iso(now)
    durable_decline = declined_ledger.record_decline(
        finding_id,
        finding_class="journal.candidate",
        reason="human_dismissed",
        declined_at=timestamp,
        write_guard=write_guard,
    )
    if durable_decline.declined_at != timestamp:
        raise JournalReviewConflictError(
            "journal dismissal ledger changed evidence under a stable finding id"
        )
    _emit_event_once(
        outbox_path,
        event=JOURNAL_ENTRY_DECLINED_EVENT,
        event_id=receipt_id,
        trace_id=finding_id,
        timestamp=timestamp,
        payload={
            "finding_id": finding_id,
            "candidate_type": candidate.candidate_type,
            "sources": list(_sources(candidate.frontmatter)),
            "reason": "human_dismissed",
        },
    )
    _retire_candidate_if_unchanged(
        directory_fd,
        candidate,
        receipt_id=receipt_id,
    )
    return _result(
        state=JournalReviewState.DISMISSED,
        action="dismiss",
        canonical_rel=canonical_rel,
        candidate=candidate,
        receipt_id=receipt_id,
        status_message="Dismissed",
    )


def _decline_receipt_id(candidate: _Candidate) -> str:
    finding_id = journal_decline_finding_id(
        candidate_type=candidate.candidate_type,
        for_date=str(candidate.frontmatter["for_date"]),
        frontmatter=candidate.frontmatter,
        body=candidate.body,
    )
    return "journal-decline-" + hashlib.sha256(
        f"journal-decline\x1f{finding_id}".encode("utf-8")
    ).hexdigest()[:24]


def _select_candidate(
    vault_root: Path, for_date: date
) -> tuple[Path, JournalCandidateType, Path] | None:
    primary = journal_draft_relative_path(
        vault_root, for_date, is_addendum=False
    )
    parent = vault_root / primary.parent
    try:
        names = os.listdir(parent)
    except FileNotFoundError:
        return None
    selection = _select_candidate_names(names, for_date)
    if selection is None:
        return None
    logical_name, candidate_type, storage_name = selection
    storage_path = primary.parent / storage_name
    mode = (vault_root / storage_path).lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise JournalReviewConflictError(
            "journal candidate lifecycle path must be a regular non-symlink file"
        )
    return primary.parent / logical_name, candidate_type, storage_path


def _retired_candidates(
    vault_root: Path, for_date: date
) -> tuple[tuple[Path, JournalCandidateType, Path], ...]:
    primary = journal_draft_relative_path(
        vault_root, for_date, is_addendum=False
    )
    parent = vault_root / primary.parent
    try:
        names = os.listdir(parent)
    except FileNotFoundError:
        return ()
    candidates: tuple[tuple[str, JournalCandidateType], ...] = (
        (f"{for_date.isoformat()}.md", "primary"),
        (f"{for_date.isoformat()}-addendum.md", "addendum"),
    )
    retired: list[tuple[Path, JournalCandidateType, Path]] = []
    for logical_name, candidate_type in candidates:
        prefix = f".{logical_name}{_RETIRED_MARKER}"
        for storage_name in names:
            if not storage_name.startswith(prefix):
                continue
            storage_path = primary.parent / storage_name
            mode = (vault_root / storage_path).lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise JournalReviewConflictError(
                    "journal candidate archive must be a regular non-symlink file"
                )
            retired.append(
                (primary.parent / logical_name, candidate_type, storage_path)
            )
    return tuple(retired)


def _select_candidate_at(
    directory_fd: int, for_date: date
) -> tuple[str, JournalCandidateType, str] | None:
    selection = _select_candidate_names(os.listdir(directory_fd), for_date)
    if selection is None:
        return None
    logical_name, candidate_type, storage_name = selection
    observed = os.stat(storage_name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(observed.st_mode):
        raise JournalReviewConflictError(
            "journal candidate lifecycle path must be a regular file"
        )
    return logical_name, candidate_type, storage_name


def _select_candidate_names(
    names: list[str], for_date: date
) -> tuple[str, JournalCandidateType, str] | None:
    primary_name = f"{for_date.isoformat()}.md"
    addendum_name = f"{for_date.isoformat()}-addendum.md"
    matches: list[tuple[str, JournalCandidateType, str]] = []
    candidates: tuple[tuple[str, JournalCandidateType], ...] = (
        (primary_name, "primary"),
        (addendum_name, "addendum"),
    )
    for logical_name, candidate_type in candidates:
        retirement_prefix = f".{logical_name}{_RETIREMENT_MARKER}"
        for name in names:
            if name == logical_name or name.startswith(retirement_prefix):
                matches.append((logical_name, candidate_type, name))
    if len(matches) > 1:
        raise JournalReviewConflictError(
            "multiple primary/addendum/retiring candidates exist for the same day"
        )
    return matches[0] if matches else None


def _read_candidate_path(
    vault_root: Path,
    storage_path: Path,
    *,
    relative_path: Path,
    candidate_type: JournalCandidateType,
    for_date: date,
) -> _Candidate:
    parent = vault_root / storage_path.parent
    parent_fd = os.open(
        parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        return _read_candidate_at(
            parent_fd,
            storage_path.name,
            relative_path=relative_path,
            candidate_type=candidate_type,
            for_date=for_date,
        )
    finally:
        os.close(parent_fd)


def _read_candidate_at(
    directory_fd: int,
    filename: str,
    *,
    relative_path: Path,
    candidate_type: JournalCandidateType,
    for_date: date,
) -> _Candidate:
    descriptor = os.open(
        filename,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        named = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or opened.st_nlink != 1
            or named.st_nlink != 1
        ):
            raise JournalReviewConflictError(
                "journal candidate must be one stable regular file"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or after.st_ctime_ns != opened.st_ctime_ns
        ):
            raise JournalReviewConflictError(
                "journal candidate changed while the review action was read"
            )
    finally:
        os.close(descriptor)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JournalReviewConflictError(
            "journal candidate must be valid UTF-8 Markdown"
        ) from exc
    frontmatter, body = load_frontmatter(text)
    _require_candidate_frontmatter(
        frontmatter, candidate_type=candidate_type, for_date=for_date
    )
    action = _checked_action(body, candidate_type=candidate_type)
    return _Candidate(
        relative_path=relative_path,
        candidate_type=candidate_type,
        draft_id=str(frontmatter["uuid"]),
        frontmatter=frontmatter,
        body=body,
        raw=raw,
        identity=opened,
        action=action,
        storage_filename=filename,
    )


def _checked_action(body: str, *, candidate_type: JournalCandidateType) -> str | None:
    try:
        return checked_journal_action(
            body,
            candidate_type=candidate_type,
        )
    except JournalCandidateContractError as exc:
        raise JournalReviewConflictError(str(exc)) from exc


def _strip_review_panel(body: str) -> str:
    try:
        return strip_journal_review_panel(body)
    except JournalCandidateContractError as exc:
        raise JournalReviewConflictError(str(exc)) from exc


def _require_candidate_frontmatter(
    frontmatter: dict[str, Any], *, candidate_type: JournalCandidateType, for_date: date
) -> None:
    expected = {
        "kind": "journal-draft",
        "journal_candidate_type": candidate_type,
        "for_date": for_date.isoformat(),
        "derived_by": "conversation",
        "authority_state": "proposal",
    }
    for key, value in expected.items():
        if frontmatter.get(key) != value:
            raise JournalReviewConflictError(
                f"journal candidate has invalid {key!r}; expected {value!r}"
            )
    if not str(frontmatter.get("uuid") or "").strip():
        raise JournalReviewConflictError("journal candidate requires a durable uuid")
    if not _sources(frontmatter):
        raise JournalReviewConflictError(
            "journal candidate requires permanent source provenance"
        )


def _require_accepted_canonical(raw: bytes, path: str) -> None:
    frontmatter, _body = _load_raw_frontmatter(raw)
    _require_accepted_frontmatter(frontmatter, path)


def _require_accepted_frontmatter(frontmatter: dict[str, Any], path: str) -> None:
    if (
        frontmatter.get("authority_state") != "accepted"
        or frontmatter.get("accepted_by") != "human"
        or frontmatter.get("derived_by") != "conversation"
        or not frontmatter.get("acceptance_receipt_id")
        or not frontmatter.get("accepted_at")
        or not frontmatter.get("decision_token_ref")
    ):
        raise JournalAcceptedEntryExistsError(
            f"canonical journal target {path} exists but is not a JRNL-04 accepted entry"
        )


def _load_raw_frontmatter(raw: bytes) -> tuple[dict[str, Any], bytes]:
    text = raw.decode("utf-8")
    frontmatter, body = load_frontmatter(text)
    body_bytes = body.encode("utf-8")
    if not raw.endswith(body_bytes):
        raise JournalReviewConflictError(
            "canonical journal frontmatter/body boundary is not stable UTF-8"
        )
    return frontmatter, body_bytes


def _assert_candidate_unchanged_at(directory_fd: int, candidate: _Candidate) -> None:
    """Reject publication if the owner changed the checked candidate meanwhile.

    This runs inside the canonical write transaction, so the body stamped into the
    accepted note is the same body that the owner actually approved.
    """
    try:
        current = _read_candidate_at(
            directory_fd,
            candidate.storage_filename,
            relative_path=candidate.relative_path,
            candidate_type=candidate.candidate_type,
            for_date=date.fromisoformat(str(candidate.frontmatter["for_date"])),
        )
    except FileNotFoundError:
        raise JournalReviewConflictError(
            "journal candidate disappeared during canonical acceptance; the owner must retry"
        ) from None
    if current.identity != candidate.identity or current.raw != candidate.raw:
        raise JournalReviewConflictError(
            "journal candidate changed before canonical acceptance; the current edited draft remains available"
        )


def _retire_candidate_if_unchanged(
    directory_fd: int,
    candidate: _Candidate,
    *,
    receipt_id: str,
) -> None:
    logical_name = candidate.relative_path.name
    retirement_name = f".{logical_name}{_RETIREMENT_MARKER}{receipt_id}"
    retired_name = f".{logical_name}{_RETIRED_MARKER}{receipt_id}"
    moved = candidate.storage_filename == logical_name
    if moved:
        try:
            os.stat(retirement_name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise JournalReviewConflictError(
                "journal candidate retirement path already exists"
            )
        try:
            _atomic_rename_noreplace_at(
                directory_fd,
                candidate.storage_filename,
                directory_fd,
                retirement_name,
            )
        except FileExistsError as exc:
            raise JournalReviewConflictError(
                "journal candidate retirement path appeared concurrently"
            ) from exc
        os.fsync(directory_fd)
    elif candidate.storage_filename != retirement_name:
        raise JournalReviewConflictError(
            "journal candidate retirement evidence does not match its receipt"
        )

    descriptor = os.open(
        retirement_name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        named = os.stat(
            retirement_name, dir_fd=directory_fd, follow_symlinks=False
        )
        current_raw = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            current_raw += chunk
    finally:
        os.close(descriptor)

    matches = (
        stat.S_ISREG(opened.st_mode)
        and stat.S_ISREG(named.st_mode)
        and opened.st_nlink == 1
        and named.st_nlink == 1
        and (opened.st_dev, opened.st_ino)
        == (candidate.identity.st_dev, candidate.identity.st_ino)
        and (named.st_dev, named.st_ino) == (opened.st_dev, opened.st_ino)
        and opened.st_size == candidate.identity.st_size
        and opened.st_mtime_ns == candidate.identity.st_mtime_ns
        and current_raw == candidate.raw
    )
    if not matches:
        if moved:
            try:
                os.stat(logical_name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                try:
                    _atomic_rename_noreplace_at(
                        directory_fd,
                        retirement_name,
                        directory_fd,
                        logical_name,
                    )
                except FileExistsError:
                    pass
                os.fsync(directory_fd)
        raise JournalReviewConflictError(
            "journal candidate changed during conditional retirement; the "
            "replacement was preserved"
        )
    try:
        _atomic_rename_noreplace_at(
            directory_fd,
            retirement_name,
            directory_fd,
            retired_name,
        )
    except FileExistsError as exc:
        raise JournalReviewConflictError(
            "journal candidate retired archive already exists for this receipt"
        ) from exc
    os.fsync(directory_fd)

    # Re-read the inert archive after publication. It is intentionally retained
    # as receipt-bound recovery evidence: no unlink-by-name window can delete a
    # concurrently substituted file, and JRNL-03/JRNL-04 ignore retired names.
    archived = _read_stable_named_bytes(directory_fd, retired_name)
    if archived != candidate.raw:
        try:
            _atomic_rename_noreplace_at(
                directory_fd,
                retired_name,
                directory_fd,
                logical_name,
            )
        except FileExistsError:
            pass
        os.fsync(directory_fd)
        raise JournalReviewConflictError(
            "journal candidate changed during final retirement; the replacement "
            "was preserved"
        )


def _read_stable_named_bytes(directory_fd: int, filename: str) -> bytes:
    descriptor = os.open(
        filename,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        opened = os.fstat(descriptor)
        named = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise JournalReviewConflictError(
                "journal candidate archive must be one stable regular file"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or after.st_ctime_ns != opened.st_ctime_ns
        ):
            raise JournalReviewConflictError(
                "journal candidate archive changed while it was verified"
            )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _emit_event_once(
    outbox_path: Path,
    *,
    event: str,
    event_id: str,
    trace_id: str,
    timestamp: str,
    payload: dict[str, Any],
) -> None:
    record = serialize_outbox_record(
        {
            "event": event,
            "event_id": event_id,
            "trace_id": trace_id,
            "source": JOURNAL_REVIEW_EVENT_SOURCE,
            "timestamp": timestamp,
            "payload": payload,
        },
        default_source=JOURNAL_REVIEW_EVENT_SOURCE,
    )
    if record is None:
        raise JournalReviewError("journal review receipt could not be serialized")
    parent_fd, lock_fd = _lock_outbox(outbox_path)
    try:
        raw, records = _read_outbox_at(parent_fd, outbox_path.name)
        exact = [row for row in records if row.get("event_id") == event_id]
        if len(exact) > 1:
            raise JournalReviewConflictError(
                "journal review receipt id appears more than once"
            )
        if exact and exact[0] != record:
            raise JournalReviewConflictError(
                "journal review receipt id already exists with different "
                "transition evidence"
            )
        normalized = _normalized_outbox_bytes(raw)
        desired = normalized
        if not exact:
            desired += (json.dumps(record, ensure_ascii=False) + "\n").encode(
                "utf-8"
            )
        if desired != raw:
            _atomic_replace_at(parent_fd, outbox_path.name, desired)
        _fsync_named_file(parent_fd, outbox_path.name)
        os.fsync(parent_fd)
        _raw_after, records_after = _read_outbox_at(parent_fd, outbox_path.name)
        proved = [row for row in records_after if row.get("event_id") == event_id]
        if proved != [record]:
            raise JournalReviewError(
                "journal review receipt was not durably re-readable after publish"
            )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        os.close(parent_fd)


def _read_event(outbox_path: Path, event_id: str) -> dict[str, Any] | None:
    parent_fd, lock_fd = _lock_outbox(outbox_path)
    try:
        _raw, records = _read_outbox_at(parent_fd, outbox_path.name)
        exact = [row for row in records if row.get("event_id") == event_id]
        if len(exact) > 1:
            raise JournalReviewConflictError(
                "journal review receipt id appears more than once"
            )
        return exact[0] if exact else None
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        os.close(parent_fd)


def _lock_outbox(outbox_path: Path) -> tuple[int, int]:
    try:
        parent_fd = os.open(
            outbox_path.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise JournalReviewError(
            "journal review receipt parent must already exist as a durable directory"
        ) from exc
    lock_name = f".{outbox_path.name}.journal-review.lock"
    lock_fd: int | None = None
    try:
        lock_fd = os.open(
            lock_name,
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_fd,
        )
        opened = os.fstat(lock_fd)
        named = os.stat(lock_name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise JournalReviewError(
                "journal review receipt lock must be one stable regular file"
            )
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        named_after_lock = os.stat(
            lock_name, dir_fd=parent_fd, follow_symlinks=False
        )
        opened_after_lock = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(named_after_lock.st_mode)
            or named_after_lock.st_nlink != 1
            or opened_after_lock.st_nlink != 1
            or (opened_after_lock.st_dev, opened_after_lock.st_ino)
            != (named_after_lock.st_dev, named_after_lock.st_ino)
        ):
            raise JournalReviewError(
                "journal review receipt lock changed during acquisition"
            )
    except BaseException:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(parent_fd)
        raise
    assert lock_fd is not None
    return parent_fd, lock_fd


def _read_outbox_at(
    parent_fd: int, filename: str
) -> tuple[bytes, list[dict[str, Any]]]:
    try:
        descriptor = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return b"", []
    try:
        observed = os.fstat(descriptor)
        named = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or not stat.S_ISREG(named.st_mode)
            or (observed.st_dev, observed.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise JournalReviewError(
                "journal review receipt store must be one stable regular file"
            )
        raw = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            raw += chunk
        observed_after = os.fstat(descriptor)
        named_after = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        if (
            observed_after.st_size != observed.st_size
            or observed_after.st_mtime_ns != observed.st_mtime_ns
            or observed_after.st_ctime_ns != observed.st_ctime_ns
            or (observed_after.st_dev, observed_after.st_ino)
            != (named_after.st_dev, named_after.st_ino)
        ):
            raise JournalReviewError(
                "journal review receipt store changed while it was read"
            )
    finally:
        os.close(descriptor)
    normalized = _normalized_outbox_bytes(raw)
    records: list[dict[str, Any]] = []
    for line in normalized.splitlines():
        if not line:
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise JournalReviewError("journal review receipt line must be an object")
        records.append(parsed)
    return raw, records


def _normalized_outbox_bytes(raw: bytes) -> bytes:
    if not raw:
        return b""
    normalized = bytearray()
    lines = raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        terminated = line.endswith(b"\n")
        content = line[:-1] if terminated else line
        if content:
            try:
                parsed = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                if index == len(lines) - 1 and not terminated:
                    break
                raise JournalReviewError(
                    "journal review receipt store contains non-tail corruption"
                ) from exc
            if not isinstance(parsed, dict):
                raise JournalReviewError(
                    "journal review receipt line must be a JSON object"
                )
        normalized.extend(content)
        normalized.extend(b"\n")
    return bytes(normalized)


def _atomic_replace_at(parent_fd: int, filename: str, content: bytes) -> None:
    temp_name = f".{filename}.{uuid4().hex}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temp_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        written = 0
        while written < len(content):
            count = os.write(descriptor, content[written:])
            if count <= 0:
                raise OSError("journal review receipt write made no progress")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temp_name,
            filename,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        os.fsync(parent_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temp_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def _fsync_named_file(parent_fd: int, filename: str) -> None:
    descriptor = os.open(
        filename,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_fd,
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _render_addendum_block(
    *, receipt_id: str, draft_id: str, accepted_at: str, materialized_body: str
) -> bytes:
    digest = hashlib.sha256(materialized_body.encode("utf-8")).hexdigest()
    metadata = json.dumps(
        {
            "accepted_at": accepted_at,
            "body_sha256": digest,
            "draft_id": draft_id,
            "receipt_id": receipt_id,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        f"\n<!-- journal:addendum:start {metadata} -->\n"
        f"## Addendum — {accepted_at}\n\n"
        f"{materialized_body.rstrip()}\n"
        f"<!-- journal:addendum:end receipt_id={receipt_id} -->\n"
    ).encode("utf-8")


def _recover_addendum_block(
    body: bytes,
    *,
    receipt_id: str,
    draft_id: str,
    materialized_body: str,
) -> str | None:
    prefix = b"<!-- journal:addendum:start "
    matches: list[tuple[dict[str, Any], int]] = []
    cursor = 0
    while True:
        start = body.find(prefix, cursor)
        if start < 0:
            break
        line_end = body.find(b" -->\n", start)
        if line_end < 0:
            raise JournalReviewConflictError(
                "accepted addendum metadata is truncated"
            )
        raw_metadata = body[start + len(prefix) : line_end]
        try:
            metadata = json.loads(raw_metadata)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JournalReviewConflictError(
                "accepted addendum metadata is malformed"
            ) from exc
        if isinstance(metadata, dict) and metadata.get("receipt_id") == receipt_id:
            matches.append((metadata, start))
        cursor = line_end + 5
    if not matches:
        return None
    if len(matches) != 1:
        raise JournalReviewConflictError(
            "accepted addendum receipt appears more than once"
        )
    metadata, _start = matches[0]
    if metadata.get("draft_id") != draft_id:
        raise JournalReviewConflictError(
            "accepted addendum receipt is bound to a different draft"
        )
    accepted_at = _normalized_timestamp(
        metadata.get("accepted_at"), description="accepted addendum receipt"
    )
    expected_digest = hashlib.sha256(materialized_body.encode("utf-8")).hexdigest()
    if metadata.get("body_sha256") != expected_digest:
        raise JournalReviewConflictError(
            "accepted addendum receipt body digest does not match the candidate"
        )
    expected = _render_addendum_block(
        receipt_id=receipt_id,
        draft_id=draft_id,
        accepted_at=accepted_at,
        materialized_body=materialized_body,
    )
    if body.count(expected) != 1:
        raise JournalReviewConflictError(
            "accepted addendum receipt does not bind one exact append block"
        )
    return accepted_at


def _normalized_timestamp(value: object, *, description: str) -> str:
    try:
        timestamp = str(value)
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JournalReviewConflictError(
            f"{description} has an invalid materialization timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise JournalReviewConflictError(
            f"{description} timestamp must carry a timezone"
        )
    return _iso(parsed.astimezone(timezone.utc))


def _path_exists_no_symlink(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise JournalReviewConflictError(
            f"journal review path {path} must be a regular non-symlink file"
        )
    return True


def _sources(frontmatter: dict[str, Any]) -> tuple[str, ...]:
    raw = frontmatter.get("sources")
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw if str(item).strip())


def _projection_state(action: str | None) -> tuple[JournalReviewState, str]:
    if action == "accept":
        return (
            JournalReviewState.ACCEPTED_PENDING_MATERIALIZATION,
            "Accepted — waiting to save",
        )
    if action == "dismiss":
        return JournalReviewState.DISMISSAL_PENDING, "Dismissal pending"
    return JournalReviewState.NOT_YET_REVIEWED, "Not yet reviewed"


def _result(
    *,
    state: JournalReviewState,
    action: str | None,
    canonical_rel: Path,
    candidate: _Candidate,
    status_message: str,
    receipt_id: str | None = None,
    decision_token_ref: str | None = None,
) -> JournalReviewResult:
    return JournalReviewResult(
        state=state,
        action=action,
        canonical_path=canonical_rel.as_posix(),
        candidate_path=candidate.relative_path.as_posix(),
        candidate_type=candidate.candidate_type,
        receipt_id=receipt_id,
        decision_token_ref=decision_token_ref,
        status_message=status_message,
    )


def _canonical_relative_path(for_date: date) -> Path:
    return CANONICAL_JOURNAL_SUBDIR / f"{for_date.isoformat()}.md"


def _vault_root(context: VaultContext) -> Path:
    if context.status != "selected" or not context.active_vault_path:
        raise ValueError("journal review requires a selected active vault")
    root = Path(context.active_vault_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("journal review requires an existing active vault")
    return root


def _aware_now(value: datetime | None) -> datetime:
    selected = value or datetime.now(timezone.utc)
    if selected.tzinfo is None:
        selected = selected.replace(tzinfo=timezone.utc)
    return selected.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


__all__ = [
    "JOURNAL_ENTRY_ACCEPT_WRITE_ACTION",
    "JOURNAL_ENTRY_ACCEPTED_EVENT",
    "JOURNAL_ENTRY_DECLINED_EVENT",
    "DEFAULT_JOURNAL_REVIEW_OUTBOX_PATH",
    "JournalAcceptedEntryExistsError",
    "JournalReviewConflictError",
    "JournalReviewError",
    "JournalReviewProjection",
    "JournalReviewResult",
    "JournalReviewState",
    "JournalReviewTickResult",
    "default_journal_review_outbox_path",
    "journal_draft_relative_path",
    "process_journal_review",
    "process_journal_reviews_tick",
    "project_journal_review",
]
