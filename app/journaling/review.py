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
import stat
from typing import Any

from app.agents.panel_agent.parser import find_panels, parse_panel
from app.journaling.draft import (
    CANONICAL_JOURNAL_SUBDIR,
    _draft_relative_path,
    _locked_draft,
)
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.write_ops import (
    append_note_relative,
    locked_atomic_append_authority,
)
from app.proposals.declined_ledger import DeclinedLedger, default_declined_ledger
from app.services.outbox import serialize_outbox_record
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


JOURNAL_ENTRY_ACCEPT_WRITE_ACTION = "journal.entry.accept"
JOURNAL_ENTRY_ACCEPTED_EVENT = "journal.entry.accepted"
JOURNAL_ENTRY_DECLINED_EVENT = "journal.entry.declined"
JOURNAL_REVIEW_EVENT_SOURCE = "app.journaling.review"

_PRIMARY_ACCEPT_LABEL = "Accept this draft as today's journal entry"
_ADDENDUM_ACCEPT_LABEL = "Accept and append this addendum to today's journal"
_DISMISS_LABEL = "Dismiss this journal candidate"


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
class _Candidate:
    relative_path: Path
    candidate_type: str
    draft_id: str
    frontmatter: dict[str, Any]
    body: str
    raw: bytes
    identity: os.stat_result
    action: str | None


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
        return JournalReviewProjection(
            state=JournalReviewState.NOT_YET_REVIEWED,
            canonical_path=canonical_rel.as_posix(),
            candidate_path=None,
            candidate_type=None,
            rendered_body=None,
            status_message="Not yet reviewed",
        )

    relative_path, candidate_type = selected
    candidate = _read_candidate_path(
        vault_root, relative_path, candidate_type=candidate_type, for_date=for_date
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
    selected = _select_candidate(vault_root, for_date)
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

    candidate_rel, candidate_type = selected
    with _locked_draft(vault_root, candidate_rel) as (directory_fd, filename):
        try:
            candidate = _read_candidate_at(
                directory_fd,
                filename,
                relative_path=candidate_rel,
                candidate_type=candidate_type,
                for_date=for_date,
            )
        except FileNotFoundError:
            projection = project_journal_review(
                vault_context=vault_context, for_date=for_date
            )
            return JournalReviewResult(
                state=projection.state,
                action=None,
                canonical_path=projection.canonical_path,
                candidate_path=projection.candidate_path,
                candidate_type=projection.candidate_type,
                receipt_id=None,
                decision_token_ref=None,
                status_message=projection.status_message,
            )

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
                filename=filename,
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
            filename=filename,
            outbox_path=Path(outbox_path),
            write_guard=write_guard,
            now=_aware_now(now),
        )


def _accept_candidate(
    candidate: _Candidate,
    *,
    vault_root: Path,
    canonical_rel: Path,
    directory_fd: int,
    filename: str,
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
        marker = (
            f"<!-- journal:addendum_receipt_id={receipt_id} "
            f"draft_id={candidate.draft_id} -->"
        )
        proposed_append = (
            f"\n## Addendum — {accepted_at}\n\n"
            f"{materialized_body.rstrip()}\n\n{marker}\n"
        ).encode("utf-8")

        def addendum_transform(
            current_raw: bytes | None, proposed: bytes
        ) -> tuple[bytes, bytes]:
            nonlocal materialized_at
            if current_raw is None:
                raise JournalAcceptedEntryExistsError(
                    "an addendum requires an existing accepted journal entry"
                )
            current_frontmatter, current_body = _load_raw_frontmatter(current_raw)
            _require_accepted_frontmatter(
                current_frontmatter, canonical_rel.as_posix()
            )
            marker_bytes = marker.encode("utf-8")
            if marker_bytes in current_body:
                materialized_at = _accepted_addendum_timestamp(
                    current_body, marker_bytes
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
    _unlink_candidate_if_unchanged(
        directory_fd, filename, candidate.identity, candidate.raw
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
    filename: str,
    canonical_rel: Path,
    outbox_path: Path,
    declined_ledger: DeclinedLedger,
    write_guard: WriteGuard,
    now: datetime,
) -> JournalReviewResult:
    timestamp = _iso(now)
    receipt_id = "journal-decline-" + hashlib.sha256(
        (
            f"{candidate.draft_id}\x1f{candidate.candidate_type}\x1f"
            f"{hashlib.sha256(candidate.raw).hexdigest()}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    declined_ledger.record_decline(
        candidate.draft_id,
        finding_class="journal.candidate",
        reason="human_dismissed",
        declined_at=timestamp,
        write_guard=write_guard,
    )
    _emit_event_once(
        outbox_path,
        event=JOURNAL_ENTRY_DECLINED_EVENT,
        event_id=receipt_id,
        trace_id=candidate.draft_id,
        timestamp=timestamp,
        payload={
            "draft_id": candidate.draft_id,
            "candidate_type": candidate.candidate_type,
            "sources": list(_sources(candidate.frontmatter)),
            "reason": "human_dismissed",
        },
    )
    _unlink_candidate_if_unchanged(
        directory_fd, filename, candidate.identity, candidate.raw
    )
    return _result(
        state=JournalReviewState.DISMISSED,
        action="dismiss",
        canonical_rel=canonical_rel,
        candidate=candidate,
        receipt_id=receipt_id,
        status_message="Dismissed",
    )


def _select_candidate(
    vault_root: Path, for_date: date
) -> tuple[Path, str] | None:
    primary = journal_draft_relative_path(
        vault_root, for_date, is_addendum=False
    )
    addendum = journal_draft_relative_path(
        vault_root, for_date, is_addendum=True
    )
    primary_exists = _path_exists_no_symlink(vault_root / primary)
    addendum_exists = _path_exists_no_symlink(vault_root / addendum)
    if primary_exists and addendum_exists:
        raise JournalReviewConflictError(
            "both primary and addendum candidates exist for the same day"
        )
    if addendum_exists:
        return addendum, "addendum"
    if primary_exists:
        return primary, "primary"
    return None


def _read_candidate_path(
    vault_root: Path,
    relative_path: Path,
    *,
    candidate_type: str,
    for_date: date,
) -> _Candidate:
    parent = vault_root / relative_path.parent
    parent_fd = os.open(
        parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        return _read_candidate_at(
            parent_fd,
            relative_path.name,
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
    candidate_type: str,
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
    )


def _checked_action(body: str, *, candidate_type: str) -> str | None:
    expected_accept = (
        _ADDENDUM_ACCEPT_LABEL if candidate_type == "addendum" else _PRIMARY_ACCEPT_LABEL
    )
    matching_actions: list[tuple[str, bool]] = []
    for panel in find_panels(body):
        parsed = parse_panel(panel.raw_block, panel.panel_id)
        for action in parsed.actions:
            if action.label in {expected_accept, _DISMISS_LABEL}:
                matching_actions.append((action.label, action.checked))

    labels = [label for label, _checked in matching_actions]
    if labels.count(expected_accept) != 1 or labels.count(_DISMISS_LABEL) != 1:
        raise JournalReviewConflictError(
            "journal candidate must carry exactly one accept and one dismiss "
            "action in a valid AI-åtgärder Panel"
        )
    checked = {label for label, is_checked in matching_actions if is_checked}
    if len(checked) > 1:
        raise JournalReviewConflictError(
            "journal candidate has both accept and dismiss checked"
        )
    if expected_accept in checked:
        return "accept"
    if _DISMISS_LABEL in checked:
        return "dismiss"
    return None


def _strip_review_panel(body: str) -> str:
    rendered = body
    removed = 0
    for panel in find_panels(body):
        parsed = parse_panel(panel.raw_block, panel.panel_id)
        labels = {action.label for action in parsed.actions}
        if _DISMISS_LABEL in labels and labels.intersection(
            {_PRIMARY_ACCEPT_LABEL, _ADDENDUM_ACCEPT_LABEL}
        ):
            rendered = rendered.replace(panel.raw_block, "", 1)
            removed += 1
    if removed != 1:
        raise JournalReviewConflictError(
            "journal candidate review Panel is missing or ambiguous"
        )
    return rendered.strip() + "\n"


def _require_candidate_frontmatter(
    frontmatter: dict[str, Any], *, candidate_type: str, for_date: date
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


def _unlink_candidate_if_unchanged(
    directory_fd: int,
    filename: str,
    expected: os.stat_result,
    expected_raw: bytes,
) -> None:
    try:
        current = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (
        not stat.S_ISREG(current.st_mode)
        or (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino)
        or current.st_size != expected.st_size
        or current.st_mtime_ns != expected.st_mtime_ns
        or current.st_ctime_ns != expected.st_ctime_ns
    ):
        raise JournalReviewConflictError(
            "journal candidate changed after materialization; it was preserved for review"
        )
    descriptor = os.open(
        filename,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        current_raw = b""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            current_raw += chunk
    finally:
        os.close(descriptor)
    if current_raw != expected_raw:
        raise JournalReviewConflictError(
            "journal candidate content changed after materialization; it was preserved"
        )
    os.unlink(filename, dir_fd=directory_fd)
    os.fsync(directory_fd)


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
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_RDWR
        | os.O_APPEND
        | os.O_CREAT
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(outbox_path, flags, 0o600)
    except OSError as exc:
        raise JournalReviewError(
            f"journal review receipt store cannot be opened safely: {exc}"
        ) from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise JournalReviewError("journal review receipt store must be regular")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            raw = b""
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                raw += chunk
            for line in raw.splitlines():
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if existing.get("event_id") == event_id:
                    if existing != record:
                        raise JournalReviewConflictError(
                            "journal review receipt id already exists with different "
                            "transition evidence"
                        )
                    return

            encoded = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
            written = 0
            while written < len(encoded):
                written += os.write(descriptor, encoded[written:])
            os.fsync(descriptor)
            named = outbox_path.lstat()
            after = os.fstat(descriptor)
            if (
                stat.S_ISLNK(named.st_mode)
                or not stat.S_ISREG(named.st_mode)
                or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)
            ):
                raise JournalReviewError(
                    "journal review receipt path changed during durable append"
                )
            parent_fd = os.open(
                outbox_path.parent,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _accepted_addendum_timestamp(body: bytes, marker: bytes) -> str:
    marker_index = body.find(marker)
    heading = body[:marker_index].rsplit("## Addendum — ".encode("utf-8"), 1)
    if len(heading) != 2:
        raise JournalReviewConflictError(
            "accepted addendum receipt is missing its materialization timestamp"
        )
    raw_timestamp = heading[1].splitlines()[0]
    try:
        timestamp = raw_timestamp.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JournalReviewConflictError(
            "accepted addendum receipt has an invalid materialization timestamp"
        ) from exc
    return _normalized_timestamp(timestamp, description="accepted addendum receipt")


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
    "JournalAcceptedEntryExistsError",
    "JournalReviewConflictError",
    "JournalReviewError",
    "JournalReviewProjection",
    "JournalReviewResult",
    "JournalReviewState",
    "journal_draft_relative_path",
    "process_journal_review",
    "project_journal_review",
]
