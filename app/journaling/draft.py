"""Stage provenance-separated conversational journal proposals (JRNL-03).

The only durable effect in this module is an atomic write beneath the vault's
system ``drafts/journal`` directory.  It never writes or edits the canonical
daily journal path.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import errno
from enum import Enum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
from typing import Iterator, Mapping, Protocol
from uuid import uuid4

from app.activation.gate import ActivationDecision, ActivationPosture
from app.activation.journal_draft import (
    JOURNAL_DRAFT_CAPABILITY_ID,
    build_journal_draft_receipt_record,
    evaluate_journal_draft_activation,
)
from app.agent_memory.candidate import ReviewState
from app.journaling.day_context import (
    DayContextBundle,
    DayContextItem,
    assemble_day_context,
)
from app.knowledge_acquisition.candidate_writeback import ARTIFACT_CLASS
from app.knowledge_compilation.proposal_builders import (
    ProposalContext,
    build_cited_unreviewed_compilation_draft,
)
from app.knowledge_compilation.runtime_artifacts import (
    CompilationDraft,
    ContextAuthorityLimits,
    SourceRef,
)
from app.reasoning.multi import (
    MaterializedReasoningInput,
    ReasoningSourceInput,
    materialize_reasoning_inputs,
    run_multi_note_reasoning,
)
from app.reasoning.schema import ReasoningOutput
from app.vault.manager import VaultContext
from app.vault.paths import get_vault_system_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


JOURNAL_DRAFT_WRITE_ACTION = "journal.draft.write"
JOURNAL_DRAFTS_SUBDIR = Path("drafts") / "journal"
CANONICAL_JOURNAL_SUBDIR = Path("1_Calendar") / "Daily"
DEFAULT_STALENESS_DAYS = 14

_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_MISSING_SOURCE_OCCURRENCES = object()


class UnresolvableJournalCitationError(ValueError):
    """A transcript or day-context provenance reference did not resolve."""


class JournalDraftBlockedError(RuntimeError):
    """JRNL-03's own activation record refused the proposal run."""


class ReasoningFunction(Protocol):
    def __call__(
        self, object_ids: Sequence[str], *, trace_id: str | None = None
    ) -> ReasoningOutput: ...


class SourceKind(str, Enum):
    """Typed origin of one journal input occurrence."""

    TRANSCRIPT = "transcript"
    DAY_CONTEXT = "day_context"


@dataclass(frozen=True)
class SourceIdentity:
    """Collision-free identity for one occurrence entering trust admission."""

    source_kind: SourceKind
    external_id: str
    occurrence: int

    def __post_init__(self) -> None:
        if not self.external_id.strip():
            raise ValueError("journal source identity requires a non-empty external_id")
        if self.external_id != self.external_id.strip():
            raise ValueError("journal source identity external_id must be canonical")
        if self.occurrence <= 0:
            raise ValueError("journal source identity occurrence must be positive")

    @property
    def admission_id(self) -> str:
        external_id = self.external_id.strip()
        return (
            f"journal-source:{self.source_kind.value}:{self.occurrence}:"
            f"{len(external_id)}:{external_id}"
        )


@dataclass(frozen=True)
class _CognitionCitation:
    """Resolvable public citation for one internally typed source occurrence."""

    reference: str
    source_kind: SourceKind
    occurrence: int
    content_sha256: str


@dataclass(frozen=True)
class _SourceContentVersion:
    """Durable identity for the exact source version admitted into a draft."""

    content_sha256: str
    admitted_content: str


@dataclass(frozen=True)
class _SourceSnapshot:
    """Raw bytes and metadata captured from one open source-file version."""

    raw_content: bytes
    stat_result: os.stat_result


@dataclass(frozen=True)
class _ResolvedSession:
    session_id: str
    relative_path: str
    owner_turns: tuple[str, ...]
    review_state: ReviewState | None

    @property
    def source_id(self) -> str:
        return f"session:{self.session_id}"


@dataclass(frozen=True)
class JournalDraftResult:
    path: str
    is_addendum: bool
    compilation_draft: CompilationDraft
    activation_receipt_id: str


def draft_journal_entry(
    *,
    vault_context: VaultContext,
    for_date: date,
    session_id: str,
    day_context: DayContextBundle | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    activation_posture: ActivationPosture | None = None,
    reasoning_fn: ReasoningFunction = run_multi_note_reasoning,
    now: datetime | None = None,
    staleness_days: int = DEFAULT_STALENESS_DAYS,
) -> JournalDraftResult:
    """Build and atomically stage one proposal for ``for_date``.

    Before acceptance, every same-day call rewrites the same candidate path
    while retaining every contributing session.  Once a canonical daily note
    exists, the target switches to a distinct addendum candidate; the
    canonical note is only observed and is never opened for writing here.
    """

    vault_root = _vault_root(vault_context)
    if not session_id.strip():
        raise ValueError("draft_journal_entry requires a non-empty session_id")
    if staleness_days <= 0:
        raise ValueError("staleness_days must be positive")

    bundle = day_context or assemble_day_context(
        vault_context=vault_context, for_date=for_date
    )
    if bundle.for_date != for_date:
        raise ValueError("day_context date does not match the requested journal date")

    accepted_path = vault_root / CANONICAL_JOURNAL_SUBDIR / f"{for_date.isoformat()}.md"
    is_addendum = accepted_path.exists()
    draft_rel = _draft_relative_path(vault_root, for_date, is_addendum=is_addendum)
    context_items = tuple(_iter_context_items(bundle))

    # Production mutation seam. Opening the secure staging directory or its
    # lock can create filesystem entries, so the guard is immediately before
    # that transaction begins. The lock then serializes read/compose/replace,
    # preventing same-day lost updates rather than merely preventing torn bytes.
    write_guard.assert_writes_allowed(JOURNAL_DRAFT_WRITE_ACTION)
    with _locked_draft(vault_root, draft_rel) as (directory_fd, filename):
        existing_frontmatter = _load_existing_draft_frontmatter_at(
            directory_fd, filename
        )
        previous_session_ids = (
            _session_ids(
                existing_frontmatter.get("sources"),
                existing_frontmatter.get(
                    "source_occurrences", _MISSING_SOURCE_OCCURRENCES
                ),
                vault_root=vault_root,
            )
            if existing_frontmatter
            else ()
        )
        all_session_ids = _deduplicate((*previous_session_ids, session_id.strip()))
        sessions = tuple(
            _resolve_session(vault_root, prior_session_id)
            for prior_session_id in all_session_ids
        )

        _validate_session_citations(vault_root, sessions)
        _validate_context_citations(vault_root, context_items)
        source_identities = _source_identities(sessions, context_items)
        source_content_versions = _source_content_versions(
            vault_root, sessions, context_items, source_identities
        )
        source_ids = tuple(identity.admission_id for identity in source_identities)
        review_states = _source_review_states(
            vault_root, sessions, context_items, source_identities
        )
        activation = evaluate_journal_draft_activation(
            source_ids,
            review_states={
                identity.admission_id: review_states[identity]
                for identity in source_identities
            },
            posture=activation_posture,
            now=now,
        )
        source_blocks = _non_proposal_source_reasons(activation)
        if source_blocks:
            raise JournalDraftBlockedError(
                "journal draft source admission blocked: " + ", ".join(source_blocks)
            )
        if not activation.activatable:
            reasons = ", ".join(activation.blocked_reasons) or "unknown"
            raise JournalDraftBlockedError(f"journal draft activation blocked: {reasons}")

        reasoning_sources = _materialize_reasoning_sources(
            vault_root=vault_root,
            sessions=sessions,
            context_items=context_items,
            source_identities=source_identities,
        )
        cognition_citations = _cognition_citations(
            sessions=sessions,
            context_items=context_items,
            source_identities=source_identities,
            source_content_versions=source_content_versions,
        )
        cognition, cognition_body = _run_cognition(
            reasoning_fn,
            reasoning_sources,
            cognition_citations,
            activation.receipt.receipt_id,
        )
        body = _build_body(
            for_date=for_date,
            sessions=sessions,
            context_items=context_items,
            is_addendum=is_addendum,
            cognition_body=cognition_body,
            source_identities=source_identities,
            source_content_versions=source_content_versions,
        )
        context_identities = source_identities[len(sessions) :]
        source_refs = tuple(
            SourceRef(
                artifact_id=session.source_id,
                note_path=session.relative_path,
                role="conversation",
                review_state=_review_state_value(session.review_state),
            )
            for session in sessions
        ) + tuple(
            SourceRef(
                artifact_id=identity.external_id,
                note_path=_reference_path(identity.external_id),
                role="system_context",
                review_state=_review_state_value(review_states[identity]),
            )
            for item, identity in zip(context_items, context_identities, strict=True)
        )
        compilation = build_cited_unreviewed_compilation_draft(
            ProposalContext(
                source_refs=source_refs,
                authority_limits=ContextAuthorityLimits(
                    may_inform=True, may_propose=True
                ),
                content=body,
                uncertainty_notes=(
                    "Raw transcript and candidate day-context sources remain cited "
                    "at their actual review posture; this artifact is a proposal only."
                ),
                generated_by=JOURNAL_DRAFT_CAPABILITY_ID,
                trace_ref=activation.receipt.receipt_id,
            ),
            title=(
                f"Journal addendum candidate {for_date.isoformat()}"
                if is_addendum
                else f"Journal draft {for_date.isoformat()}"
            ),
        )
        existing_uuid = str(existing_frontmatter.get("uuid") or "").strip()
        if existing_uuid:
            compilation = compilation.model_copy(update={"artifact_id": existing_uuid})

        checked_at = now or datetime.now(timezone.utc)
        created = str(existing_frontmatter.get("created") or _iso(checked_at))
        receipt_record = build_journal_draft_receipt_record(activation)
        receipts = _retained_receipts(
            existing_frontmatter.get("activation_receipts"), receipt_record
        )
        frontmatter: dict[str, object] = {
            "uuid": compilation.artifact_id,
            "kind": "journal-draft",
            "journal_candidate_type": "addendum" if is_addendum else "primary",
            "for_date": for_date.isoformat(),
            "derived_by": "conversation",
            "authority_state": "proposal",
            "proposed_by": {
                "capability": JOURNAL_DRAFT_CAPABILITY_ID,
                "cognition": cognition,
            },
            "sources": [identity.external_id for identity in source_identities],
            "source_occurrences": [
                {
                    "kind": identity.source_kind.value,
                    "external_id": identity.external_id,
                    "occurrence": identity.occurrence,
                    "content_sha256": source_content_versions[
                        identity.admission_id
                    ].content_sha256,
                    "admitted_content": source_content_versions[
                        identity.admission_id
                    ].admitted_content,
                }
                for identity in source_identities
            ],
            "activation_receipt_id": activation.receipt.receipt_id,
            "activation_receipts": receipts,
            "created": created,
            "updated": _iso(checked_at),
            "expires": _iso(checked_at + timedelta(days=staleness_days)),
        }
        note_text = dump_frontmatter(frontmatter, compilation.body or "") + _review_actions(
            is_addendum=is_addendum
        )

        # Re-resolve inside the same serialized transaction immediately before
        # replace so a removed or newly blocked source cannot be laundered into
        # the proposal through a stale admission snapshot.
        fresh_sessions = tuple(
            _resolve_session(vault_root, session.session_id) for session in sessions
        )
        _validate_session_citations(vault_root, fresh_sessions)
        _validate_context_citations(vault_root, context_items)
        fresh_review_states = _source_review_states(
            vault_root, fresh_sessions, context_items, source_identities
        )
        if fresh_review_states != review_states:
            raise JournalDraftBlockedError(
                "journal draft source admission changed before staging"
            )
        if (
            _source_content_versions(
                vault_root, fresh_sessions, context_items, source_identities
            )
            != source_content_versions
        ):
            raise JournalDraftBlockedError(
                "journal draft source content changed before staging"
            )
        _atomic_write_at(directory_fd, filename, note_text)

    return JournalDraftResult(
        path=draft_rel.as_posix(),
        is_addendum=is_addendum,
        compilation_draft=compilation,
        activation_receipt_id=activation.receipt.receipt_id,
    )


def _vault_root(context: VaultContext) -> Path:
    if context.status != "selected" or not context.active_vault_path:
        raise ValueError("draft_journal_entry requires a selected active vault")
    root = Path(context.active_vault_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("draft_journal_entry requires an existing active vault")
    return root


def _draft_relative_path(
    vault_root: Path, for_date: date, *, is_addendum: bool
) -> Path:
    system_dir = Path(get_vault_system_dir_rel(vault_root))
    if system_dir.is_absolute() or ".." in system_dir.parts:
        raise ValueError("journal draft staging path escapes the active vault")
    suffix = "-addendum" if is_addendum else ""
    return (
        system_dir
        / JOURNAL_DRAFTS_SUBDIR
        / f"{for_date.isoformat()}{suffix}.md"
    )


@contextmanager
def _locked_draft(
    vault_root: Path, relative_path: Path
) -> Iterator[tuple[int, str]]:
    """Open a no-follow staging directory and hold the per-draft lock."""

    lock_key = f"{vault_root}:{relative_path}"
    with _PROCESS_LOCKS_GUARD:
        process_lock = _PROCESS_LOCKS.setdefault(lock_key, threading.RLock())
    with process_lock:
        yield from _locked_draft_process_safe(vault_root, relative_path)


def _locked_draft_process_safe(
    vault_root: Path, relative_path: Path
) -> Iterator[tuple[int, str]]:
    root_fd = os.open(vault_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    current_fd = root_fd
    bootstrap_fd: int | None = None
    lock_fd: int | None = None
    try:
        # The per-draft lock lives in the staging directory, so first use needs
        # a stable lock anchored in the already-existing vault root. Holding it
        # through directory creation and acquisition of the per-draft flock
        # prevents separate processes from racing on bootstrap. It is released
        # before the transaction body; established drafts still serialize on
        # their narrower per-draft lock.
        bootstrap_fd = _open_lock_at(
            root_fd,
            ".journal-draft-bootstrap.lock",
            symlink_message="journal draft bootstrap lock path is a symlink",
        )
        fcntl.flock(bootstrap_fd, fcntl.LOCK_EX)
        for component in relative_path.parent.parts:
            try:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current_fd,
                )
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    next_fd = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=current_fd,
                    )
                except OSError as exc:
                    raise ValueError(
                        "journal draft staging component is a symlink or not a directory"
                    ) from exc
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise ValueError(
                        "journal draft staging component is a symlink or not a directory"
                    ) from exc
                raise
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd

        lock_name = f".{relative_path.name}.lock"
        lock_fd = _open_lock_at(
            current_fd,
            lock_name,
            symlink_message="journal draft lock path is a symlink",
        )
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            fcntl.flock(bootstrap_fd, fcntl.LOCK_UN)
            os.close(bootstrap_fd)
            bootstrap_fd = None
            yield current_fd, relative_path.name
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            lock_fd = None
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if bootstrap_fd is not None:
            fcntl.flock(bootstrap_fd, fcntl.LOCK_UN)
            os.close(bootstrap_fd)
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def _open_lock_at(
    directory_fd: int, filename: str, *, symlink_message: str
) -> int:
    """Create/open one regular no-follow lock file beneath ``directory_fd``."""

    try:
        try:
            descriptor = os.open(
                filename,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            descriptor = os.open(
                filename,
                os.O_RDWR | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ValueError(symlink_message) from exc
        raise

    try:
        opened = os.fstat(descriptor)
        named = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode):
            raise ValueError("journal draft lock path is not a regular file")
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise ValueError("journal draft lock path changed while opening")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _load_existing_draft_frontmatter_at(
    directory_fd: int, filename: str
) -> dict[str, object]:
    try:
        descriptor = os.open(
            filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd
        )
    except FileNotFoundError:
        return {}
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError("existing journal draft target is a symlink") from exc
        raise
    with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
        frontmatter, _body = load_frontmatter(handle.read())
    if (
        frontmatter.get("kind") != "journal-draft"
        or frontmatter.get("authority_state") != "proposal"
        or frontmatter.get("derived_by") != "conversation"
    ):
        raise ValueError(
            f"existing journal draft at {filename} has an incompatible contract"
        )
    return frontmatter


def _session_ids(
    raw_sources: object,
    raw_source_occurrences: object,
    *,
    vault_root: Path,
) -> tuple[str, ...]:
    if raw_source_occurrences is not _MISSING_SOURCE_OCCURRENCES:
        if not isinstance(raw_source_occurrences, list):
            raise UnresolvableJournalCitationError(
                "stored journal source occurrences must be a list"
            )
        if not isinstance(raw_sources, list):
            raise UnresolvableJournalCitationError(
                "stored journal sources must accompany typed source occurrences"
            )
        parsed_identities: list[SourceIdentity] = []
        expected_occurrences: dict[tuple[SourceKind, str], int] = {}
        typed_sessions: list[str] = []
        for item in raw_source_occurrences:
            if not isinstance(item, dict):
                raise UnresolvableJournalCitationError(
                    "stored journal source occurrence must be a mapping"
                )
            try:
                source_kind = SourceKind(str(item.get("kind") or ""))
            except ValueError as exc:
                raise UnresolvableJournalCitationError(
                    "stored journal source occurrence has an invalid kind"
                ) from exc
            external_id = item.get("external_id")
            occurrence = item.get("occurrence")
            content_sha256 = item.get("content_sha256")
            admitted_content = item.get("admitted_content")
            if (
                not isinstance(external_id, str)
                or isinstance(occurrence, bool)
                or not isinstance(occurrence, int)
                or not isinstance(content_sha256, str)
                or len(content_sha256) != 64
                or any(character not in "0123456789abcdef" for character in content_sha256)
                or not isinstance(admitted_content, str)
            ):
                raise UnresolvableJournalCitationError(
                    "stored journal source occurrence is incomplete"
                )
            try:
                identity = SourceIdentity(source_kind, external_id, occurrence)
            except ValueError as exc:
                raise UnresolvableJournalCitationError(
                    "stored journal source occurrence is invalid"
                ) from exc
            key = (identity.source_kind, identity.external_id)
            prior_occurrences = expected_occurrences.get(key, 0)
            if source_kind is SourceKind.TRANSCRIPT and prior_occurrences:
                raise UnresolvableJournalCitationError(
                    "stored journal source occurrences contain a duplicate transcript"
                )
            expected_occurrence = prior_occurrences + 1
            if identity.occurrence != expected_occurrence:
                raise UnresolvableJournalCitationError(
                    "stored journal source occurrence sequence is invalid"
                )
            expected_occurrences[key] = expected_occurrence
            parsed_identities.append(identity)
            if identity.source_kind is SourceKind.TRANSCRIPT:
                if (
                    not identity.external_id.startswith("session:")
                    or not identity.external_id.removeprefix("session:")
                ):
                    raise UnresolvableJournalCitationError(
                        "stored transcript source occurrence has an invalid external_id"
                    )
                typed_sessions.append(identity.external_id.removeprefix("session:"))
        if raw_sources != [identity.external_id for identity in parsed_identities]:
            raise UnresolvableJournalCitationError(
                "stored journal sources disagree with typed source occurrences"
            )
        if not typed_sessions:
            raise UnresolvableJournalCitationError(
                "stored journal source occurrences require a transcript"
            )
        return tuple(typed_sessions)
    if not isinstance(raw_sources, list):
        raise UnresolvableJournalCitationError(
            "stored legacy journal sources must be a list"
        )
    legacy_sessions: list[str] = []
    for source in raw_sources:
        if (
            not isinstance(source, str)
            or not source.strip()
            or source != source.strip()
        ):
            raise UnresolvableJournalCitationError(
                "stored legacy journal source is invalid"
            )
        if not source.startswith("session:"):
            continue
        session_id = source.removeprefix("session:")
        if not session_id:
            raise UnresolvableJournalCitationError(
                "stored legacy transcript source has an empty session_id"
            )
        context_path = (vault_root / _reference_path(source)).resolve()
        try:
            context_path.relative_to(vault_root)
        except ValueError as exc:
            raise UnresolvableJournalCitationError(
                f"legacy journal source escapes the active vault: {source}"
            ) from exc
        context_resolves = context_path.is_file()
        matching_transcripts = 0
        for path in (vault_root / ".chats").glob("**/*.md"):
            frontmatter, _body = load_frontmatter(path.read_text(encoding="utf-8"))
            if str(frontmatter.get("session_id") or "").strip() == session_id:
                matching_transcripts += 1
        if context_resolves and matching_transcripts:
            raise UnresolvableJournalCitationError(
                f"legacy journal source role is ambiguous: {source}"
            )
        if matching_transcripts > 1:
            raise UnresolvableJournalCitationError(
                f"session:{session_id} resolved to {matching_transcripts} transcript files"
            )
        if matching_transcripts == 1:
            if session_id in legacy_sessions:
                raise UnresolvableJournalCitationError(
                    "stored legacy journal sources contain a duplicate transcript"
                )
            legacy_sessions.append(session_id)
        elif not context_resolves:
            raise UnresolvableJournalCitationError(
                f"legacy journal source no longer resolves: {source}"
            )
    if not legacy_sessions:
        raise UnresolvableJournalCitationError(
            "stored legacy journal sources require a transcript"
        )
    return tuple(legacy_sessions)


def _deduplicate(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _resolve_session(vault_root: Path, session_id: str) -> _ResolvedSession:
    matches: list[tuple[Path, dict[str, object], str]] = []
    for path in sorted((vault_root / ".chats").glob("**/*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = load_frontmatter(text)
        if str(frontmatter.get("session_id") or "").strip() == session_id:
            matches.append((path, frontmatter, body))
    if len(matches) != 1:
        raise UnresolvableJournalCitationError(
            f"session:{session_id} resolved to {len(matches)} transcript files"
        )
    path, frontmatter, body = matches[0]
    owner_turns = _owner_turns(body)
    return _ResolvedSession(
        session_id=session_id,
        relative_path=path.relative_to(vault_root).as_posix(),
        owner_turns=owner_turns,
        review_state=_review_state(frontmatter, default=ReviewState.UNREVIEWED),
    )


def _owner_turns(body: str) -> tuple[str, ...]:
    normalized_body = body.replace("\r\n", "\n").replace("\r", "\n")
    role_markers = tuple(
        re.finditer(
            r"^\*\*(Owner|Agent):\*\*[ \t]*(.*)$",
            normalized_body,
            flags=re.MULTILINE,
        )
    )
    turns: list[str] = []
    for index, marker in enumerate(role_markers):
        if marker.group(1) != "Owner":
            continue
        next_marker_start = (
            role_markers[index + 1].start()
            if index + 1 < len(role_markers)
            else len(normalized_body)
        )
        inline_content = marker.group(2).strip()
        continuation = normalized_body[marker.end() : next_marker_start].strip()
        content = "\n\n".join(
            part for part in (inline_content, continuation) if part
        )
        if content:
            turns.append(content)
    return tuple(turns)


def _iter_context_items(bundle: DayContextBundle) -> Iterable[DayContextItem]:
    for source_name in sorted(bundle.sections):
        yield from bundle.sections[source_name].items


def _validate_session_citations(
    vault_root: Path, sessions: tuple[_ResolvedSession, ...]
) -> None:
    if not sessions:
        raise UnresolvableJournalCitationError(
            "a journal draft requires at least one resolvable conversation session"
        )
    for session in sessions:
        if not session.owner_turns:
            raise UnresolvableJournalCitationError(
                f"session:{session.session_id} contains no owner turns"
            )
        path = (vault_root / session.relative_path).resolve()
        try:
            path.relative_to(vault_root)
        except ValueError as exc:
            raise UnresolvableJournalCitationError(
                f"session:{session.session_id} escapes the active vault"
            ) from exc
        if not path.is_file():
            raise UnresolvableJournalCitationError(
                f"session:{session.session_id} transcript no longer resolves"
            )
        frontmatter, _body = load_frontmatter(path.read_text(encoding="utf-8"))
        if str(frontmatter.get("session_id") or "").strip() != session.session_id:
            raise UnresolvableJournalCitationError(
                f"session:{session.session_id} transcript identity changed"
            )


def _validate_context_citations(
    vault_root: Path, items: tuple[DayContextItem, ...]
) -> None:
    for item in items:
        reference = item.provenance_ref.strip()
        relative_path = _reference_path(reference)
        path = (vault_root / relative_path).resolve()
        try:
            path.relative_to(vault_root)
        except ValueError as exc:
            raise UnresolvableJournalCitationError(
                f"citation escapes the active vault: {reference}"
            ) from exc
        if not path.is_file():
            raise UnresolvableJournalCitationError(
                f"citation does not resolve: {reference}"
            )
        if "#" in reference:
            _validate_jsonl_fragment(path, reference.split("#", 1)[1], reference)


def _source_content_versions(
    vault_root: Path,
    sessions: tuple[_ResolvedSession, ...],
    context_items: tuple[DayContextItem, ...],
    source_identities: tuple[SourceIdentity, ...],
) -> dict[str, _SourceContentVersion]:
    """Capture exact raw-source digests plus the admitted semantic content."""

    versions: dict[str, _SourceContentVersion] = {}
    session_identities = source_identities[: len(sessions)]
    context_identities = source_identities[len(sessions) :]
    for session, identity in zip(sessions, session_identities, strict=True):
        snapshot = _read_source_snapshot(vault_root / session.relative_path)
        text = _decode_source_snapshot(snapshot, identity.external_id)
        frontmatter, body = load_frontmatter(text)
        if str(frontmatter.get("session_id") or "").strip() != session.session_id:
            raise UnresolvableJournalCitationError(
                f"session:{session.session_id} transcript identity changed"
            )
        owner_turns = _owner_turns(body)
        if owner_turns != session.owner_turns:
            raise UnresolvableJournalCitationError(
                f"session:{session.session_id} source version changed after resolution"
            )
        versions[identity.admission_id] = _SourceContentVersion(
            content_sha256=hashlib.sha256(snapshot.raw_content).hexdigest(),
            admitted_content="\n".join(owner_turns),
        )

    for item, identity in zip(context_items, context_identities, strict=True):
        snapshot = _read_source_snapshot(
            vault_root / _reference_path(item.provenance_ref)
        )
        resolved_content = _resolve_context_item_content(item, snapshot)
        if item.content != resolved_content:
            raise UnresolvableJournalCitationError(
                f"day-context source version changed after bundle assembly: "
                f"{item.provenance_ref}"
            )
        versions[identity.admission_id] = _SourceContentVersion(
            content_sha256=hashlib.sha256(snapshot.raw_content).hexdigest(),
            admitted_content=json.dumps(
                resolved_content, sort_keys=True, ensure_ascii=False
            ),
        )
    return versions


def _read_source_snapshot(path: Path) -> _SourceSnapshot:
    """Read one stable inode version without normalizing its raw bytes."""

    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        raw_content = source.read()
        after = os.fstat(source.fileno())
    before_version = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_version = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_version != after_version:
        raise UnresolvableJournalCitationError(
            f"source changed while being read: {path.as_posix()}"
        )
    return _SourceSnapshot(raw_content=raw_content, stat_result=after)


def _decode_source_snapshot(snapshot: _SourceSnapshot, reference: str) -> str:
    try:
        return snapshot.raw_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnresolvableJournalCitationError(
            f"citation is not valid UTF-8: {reference}"
        ) from exc


def _resolve_context_item_content(
    item: DayContextItem, snapshot: _SourceSnapshot
) -> dict[str, object]:
    """Re-derive one day-context semantic item from its cited durable source."""

    reference = item.provenance_ref
    text = _decode_source_snapshot(snapshot, reference)
    if "#" in reference:
        fragment = reference.split("#", 1)[1]
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            created = datetime.fromisoformat(
                str(record.get("created_at") or "").replace("Z", "+00:00")
            )
            candidate = f"{record.get('object_id')}:{record.get('key')}:{created.isoformat()}"
            if candidate != fragment:
                continue
            return {
                "object_id": str(record.get("object_id") or ""),
                "vault_uuid": record.get("vault_uuid"),
                "key": str(record.get("key") or ""),
                "created_at": created.isoformat(),
            }
        raise UnresolvableJournalCitationError(
            f"citation fragment does not resolve: {reference}"
        )

    frontmatter, _body = load_frontmatter(text)
    if frontmatter.get("artifact_class") == ARTIFACT_CLASS:
        provenance = frontmatter.get("provenance")
        if not isinstance(provenance, dict):
            raise UnresolvableJournalCitationError(
                f"candidate provenance does not resolve: {reference}"
            )
        created = datetime.fromisoformat(
            str(frontmatter.get("created") or "").replace("Z", "+00:00")
        )
        return {
            "content_identity": str(provenance.get("content_identity") or ""),
            "created_at": created.isoformat(),
            "source_kind": provenance.get("source_kind"),
            "url": provenance.get("url"),
        }
    if frontmatter.get("artifact_class") == "commitment":
        changed = datetime.fromtimestamp(
            snapshot.stat_result.st_mtime, tz=timezone.utc
        ).astimezone()
        return {
            "commitment_id": str(frontmatter.get("commitment_id") or ""),
            "state": frontmatter.get("commitment_state"),
            "target_ref": frontmatter.get("target_ref"),
            "summary": frontmatter.get("summary"),
            "changed_at": changed.isoformat(),
        }
    raise UnresolvableJournalCitationError(
        f"unsupported day-context provenance source: {reference}"
    )


def _reference_path(reference: str) -> str:
    relative = reference.split("#", 1)[0]
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise UnresolvableJournalCitationError(
            f"citation must be vault-relative: {reference}"
        )
    return path.as_posix()


def _validate_jsonl_fragment(path: Path, fragment: str, reference: str) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        candidate = (
            f"{record.get('object_id')}:{record.get('key')}:{record.get('created_at')}"
        )
        if candidate == fragment:
            return
    raise UnresolvableJournalCitationError(
        f"citation fragment does not resolve: {reference}"
    )


def _review_state(
    frontmatter: Mapping[str, object], *, default: ReviewState | None
) -> ReviewState | None:
    raw = str(frontmatter.get("review_state") or "").strip().lower()
    if not raw:
        return default
    if raw in {"draft", "provisional", "unreviewed"}:
        return ReviewState.UNREVIEWED
    if raw in {"accepted", "protected"}:
        return ReviewState.ACCEPTED
    if raw == "reviewed":
        return ReviewState.REVIEWED
    if raw == "rejected":
        return ReviewState.REJECTED
    if raw == "revised":
        return ReviewState.REVISED
    return None


def _source_review_states(
    vault_root: Path,
    sessions: tuple[_ResolvedSession, ...],
    context_items: tuple[DayContextItem, ...],
    source_identities: tuple[SourceIdentity, ...],
) -> dict[SourceIdentity, ReviewState | None]:
    session_identities = source_identities[: len(sessions)]
    context_identities = source_identities[len(sessions) :]
    states = {
        identity: session.review_state
        for session, identity in zip(sessions, session_identities, strict=True)
    }
    for item, identity in zip(context_items, context_identities, strict=True):
        path = vault_root / _reference_path(identity.external_id)
        state: ReviewState | None = None
        if path.suffix.lower() == ".md":
            frontmatter, _body = load_frontmatter(path.read_text(encoding="utf-8"))
            state = _review_state(frontmatter, default=None)
        states[identity] = state
    return states


def _source_identities(
    sessions: tuple[_ResolvedSession, ...],
    context_items: tuple[DayContextItem, ...],
) -> tuple[SourceIdentity, ...]:
    counts: dict[tuple[SourceKind, str], int] = {}

    def occurrence(source_kind: SourceKind, external_id: str) -> SourceIdentity:
        normalized_id = external_id.strip()
        if external_id != normalized_id:
            raise UnresolvableJournalCitationError(
                "journal source identity contains surrounding whitespace: "
                f"{external_id!r}"
            )
        key = (source_kind, normalized_id)
        counts[key] = counts.get(key, 0) + 1
        return SourceIdentity(source_kind, normalized_id, counts[key])

    return tuple(
        occurrence(SourceKind.TRANSCRIPT, session.source_id) for session in sessions
    ) + tuple(
        occurrence(SourceKind.DAY_CONTEXT, item.provenance_ref)
        for item in context_items
    )


def _cognition_citations(
    *,
    sessions: tuple[_ResolvedSession, ...],
    context_items: tuple[DayContextItem, ...],
    source_identities: tuple[SourceIdentity, ...],
    source_content_versions: Mapping[str, _SourceContentVersion],
) -> dict[str, _CognitionCitation]:
    """Bind private admission keys to resolvable, occurrence-aware citations."""

    session_identities = source_identities[: len(sessions)]
    context_identities = source_identities[len(sessions) :]
    citations = {
        identity.admission_id: _CognitionCitation(
            reference=session.relative_path,
            source_kind=identity.source_kind,
            occurrence=identity.occurrence,
            content_sha256=source_content_versions[
                identity.admission_id
            ].content_sha256,
        )
        for session, identity in zip(sessions, session_identities, strict=True)
    }
    citations.update(
        {
            identity.admission_id: _CognitionCitation(
                reference=item.provenance_ref,
                source_kind=identity.source_kind,
                occurrence=identity.occurrence,
                content_sha256=source_content_versions[
                    identity.admission_id
                ].content_sha256,
            )
            for item, identity in zip(
                context_items, context_identities, strict=True
            )
        }
    )
    return citations


def _review_state_value(state: ReviewState | None) -> str:
    return state.value if state is not None else "unknown"


def _non_proposal_source_reasons(decision: ActivationDecision) -> tuple[str, ...]:
    admitted = set(decision.admitted_artifact_ids)
    blocked: list[str] = []
    for evaluated in decision.receipt.evaluated:
        if evaluated.artifact_id in admitted:
            continue
        provenance = next(
            axis for axis in evaluated.axes if axis.axis == "provenance"
        )
        blocked.append(f"{evaluated.artifact_id}:{provenance.reason}")
    return tuple(blocked)


def _materialize_reasoning_sources(
    *,
    vault_root: Path,
    sessions: tuple[_ResolvedSession, ...],
    context_items: tuple[DayContextItem, ...],
    source_identities: tuple[SourceIdentity, ...],
) -> tuple[MaterializedReasoningInput, ...]:
    """Project JRNL inputs into UUID-addressable reasoning objects.

    These objects are rebuildable machine mirrors of already-cited vault
    sources. Stable UUID5 identities make redrafts update the same projection
    instead of manufacturing new identities on every pass.
    """

    session_identities = source_identities[: len(sessions)]
    context_identities = source_identities[len(sessions) :]
    raw_sources: list[ReasoningSourceInput] = [
        ReasoningSourceInput(
            source_id=identity.admission_id,
            text="\n".join(session.owner_turns),
        )
        for session, identity in zip(sessions, session_identities, strict=True)
    ]
    raw_sources.extend(
        ReasoningSourceInput(
            source_id=identity.admission_id,
            text=json.dumps(item.content, sort_keys=True, ensure_ascii=False),
        )
        for item, identity in zip(context_items, context_identities, strict=True)
    )
    try:
        return materialize_reasoning_inputs(
            raw_sources, namespace_key=f"journal:{vault_root}"
        )
    except Exception:
        return ()


def _build_body(
    *,
    for_date: date,
    sessions: tuple[_ResolvedSession, ...],
    context_items: tuple[DayContextItem, ...],
    is_addendum: bool,
    cognition_body: str,
    source_identities: tuple[SourceIdentity, ...],
    source_content_versions: Mapping[str, _SourceContentVersion],
) -> str:
    title = "Addendum candidate" if is_addendum else "Journal draft"
    lines = [f"# {title} — {for_date.isoformat()}", "", "## My reflection", ""]
    conversation_footnotes: list[str] = []
    conversation_index = 0
    session_identities = source_identities[: len(sessions)]
    context_identities = source_identities[len(sessions) :]
    for session, identity in zip(sessions, session_identities, strict=True):
        for turn in session.owner_turns:
            conversation_index += 1
            lines.append(f"I reflected: {turn} [^conversation-{conversation_index}]")
            lines.append("")
            conversation_footnotes.append(
                f"[^conversation-{conversation_index}]: {session.source_id} "
                f"(`{session.relative_path}`); source kind: `transcript`; "
                f"occurrence: {identity.occurrence}; content sha256: "
                f"`{source_content_versions[identity.admission_id].content_sha256}`; "
                "owner's conversation words."
            )

    lines.extend(["## Day context folded into the draft", ""])
    context_footnotes: list[str] = []
    if not context_items:
        lines.extend(["No additional day-context facts were available.", ""])
    for index, (item, identity) in enumerate(
        zip(context_items, context_identities, strict=True), start=1
    ):
        lines.append(
            "I also had this context available: "
            f"{_describe_context_item(item)}. [^context-{index}]"
        )
        lines.append("")
        context_footnotes.append(
            f"[^context-{index}]: {item.provenance_ref}; system-derived day context, "
            f"source kind: `day_context`; occurrence: {identity.occurrence}; "
            f"content sha256: "
            f"`{source_content_versions[identity.admission_id].content_sha256}`; "
            "not an owner utterance."
        )

    if cognition_body:
        lines.extend(["## Machine cognition (not owner utterance)", ""])
        lines.extend([cognition_body, ""])

    lines.extend(["## Provenance", ""])
    lines.extend(conversation_footnotes)
    lines.extend(context_footnotes)
    return "\n".join(lines).rstrip() + "\n"


def _describe_context_item(item: DayContextItem) -> str:
    for key in (
        "summary",
        "key",
        "content_identity",
        "target_ref",
        "commitment_id",
        "object_id",
    ):
        value = item.content.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return item.provenance_ref


def _run_cognition(
    reasoning_fn: ReasoningFunction,
    sources: tuple[MaterializedReasoningInput, ...],
    citations: Mapping[str, _CognitionCitation],
    trace_id: str,
) -> tuple[dict[str, object], str]:
    object_ids = tuple(source.object_id for source in sources)
    if not object_ids:
        return (
            {
                "engine": "run_multi_note_reasoning",
                "claims": 0,
                "inferences": 0,
                "object_ids": [],
                "outcome": "missing_input",
                "degraded": True,
                "degraded_reason": "missing_input",
            },
            "Cognition degraded: no UUID-addressable reasoning inputs resolved.",
        )
    try:
        output = reasoning_fn(object_ids, trace_id=trace_id)
        claims = output.claims
        inferences = output.inferences
    except Exception:
        return (
            {
                "engine": "run_multi_note_reasoning",
                "claims": 0,
                "inferences": 0,
                "object_ids": list(object_ids),
                "outcome": "provider_failure",
                "degraded": True,
                "degraded_reason": "provider_failure",
            },
            "Cognition degraded; the citation-grounded collation remains available.",
        )
    degraded = output.degraded
    degraded_reason = _bounded_reasoning_degraded_reason(output)
    citation_by_object = {
        source.object_id: citations.get(source.source_id)
        for source in sources
    }
    claim_ids = [claim.id for claim in claims]
    invalid_claim_ids = sorted(
        claim_id for claim_id in claim_ids if not claim_id.strip()
    )
    duplicate_claim_ids = sorted(
        {claim_id for claim_id in claim_ids if claim_ids.count(claim_id) > 1}
    )
    if invalid_claim_ids or duplicate_claim_ids:
        problems: list[str] = []
        if invalid_claim_ids:
            problems.append("empty claim IDs")
        if duplicate_claim_ids:
            problems.append("duplicate claim IDs: " + ", ".join(duplicate_claim_ids))
        raise UnresolvableJournalCitationError(
            "cognition returned an ambiguous claim graph: " + "; ".join(problems)
        )
    unadmitted_claim_ids = sorted(
        {
            str(claim.object_uuid)
            for claim in claims
            if citation_by_object.get(str(claim.object_uuid)) is None
        }
    )
    if unadmitted_claim_ids:
        raise UnresolvableJournalCitationError(
            "cognition returned claims for unadmitted source UUIDs: "
            + ", ".join(unadmitted_claim_ids)
        )
    claims_by_id = {claim.id: claim for claim in claims}
    inference_citations: list[tuple[_CognitionCitation, ...]] = []
    for inference in inferences:
        referenced_claim_ids = (*inference.premises, inference.conclusion_id)
        if not inference.premises or any(
            not claim_id.strip() for claim_id in referenced_claim_ids
        ):
            raise UnresolvableJournalCitationError(
                f"cognition inference {inference.id!r} has an empty premise or conclusion"
            )
        unknown_claim_ids = sorted(
            {
                claim_id
                for claim_id in referenced_claim_ids
                if claim_id not in claims_by_id
            }
        )
        if unknown_claim_ids:
            raise UnresolvableJournalCitationError(
                f"cognition inference {inference.id!r} references unknown claim IDs: "
                + ", ".join(unknown_claim_ids)
            )
        graph_citations: list[_CognitionCitation] = []
        seen_citations: set[tuple[str, SourceKind, int]] = set()
        for claim_id in referenced_claim_ids:
            claim = claims_by_id[claim_id]
            citation = citation_by_object[str(claim.object_uuid)]
            assert citation is not None
            citation_key = (
                citation.reference,
                citation.source_kind,
                citation.occurrence,
            )
            if citation_key not in seen_citations:
                seen_citations.add(citation_key)
                graph_citations.append(citation)
        inference_citations.append(tuple(graph_citations))
    rendered: list[str] = []
    for claim in claims:
        citation = citation_by_object.get(str(claim.object_uuid))
        assert citation is not None
        rendered.append(
            f"- {claim.text} (cognition source: `{citation.reference}`; "
            f"source kind: `{citation.source_kind.value}`; "
            f"occurrence: {citation.occurrence}; content sha256: "
            f"`{citation.content_sha256}`)"
        )
    for inference, rendered_graph_citations in zip(
        inferences, inference_citations, strict=True
    ):
        rendered_citations = " | ".join(
            f"`{citation.reference}`; source kind: "
            f"`{citation.source_kind.value}`; occurrence: {citation.occurrence}"
            f"; content sha256: `{citation.content_sha256}`"
            for citation in rendered_graph_citations
        )
        rendered.append(
            f"- Cross-source synthesis: {inference.rationale} "
            f"(cognition sources: {rendered_citations})"
        )
    if degraded:
        rendered.append(
            "Cognition degraded; the citation-grounded collation remains available."
        )
    return (
        {
            "engine": "run_multi_note_reasoning",
            "claims": len(claims),
            "inferences": len(inferences),
            "object_ids": list(object_ids),
            "outcome": output.outcome,
            "degraded": degraded,
            **({"degraded_reason": degraded_reason} if degraded_reason else {}),
        },
        "\n".join(rendered),
    )


def _bounded_reasoning_degraded_reason(output: ReasoningOutput) -> str | None:
    if not output.degraded:
        return None
    expected = {
        "provider_failure": "provider_failure",
        "empty_output": "empty_provider_output",
        "missing_input": "missing_input",
    }
    allowed = set(expected.values())
    if output.degraded_reason in allowed:
        return output.degraded_reason
    return expected.get(output.outcome, "provider_failure")


def _review_actions(*, is_addendum: bool) -> str:
    accept_label = (
        "Accept and append this addendum to today's journal"
        if is_addendum
        else "Accept this draft as today's journal entry"
    )
    return (
        "\n%% AI:Start %%\n"
        "## AI-åtgärder\n\n"
        f"- [ ] {accept_label}\n"
        "- [ ] Dismiss this journal candidate\n"
        "%% AI:End %%\n"
    )


def _retained_receipts(
    existing: object, current: dict[str, object]
) -> list[dict[str, object]]:
    retained: list[dict[str, object]] = []
    if isinstance(existing, list):
        retained = [
            item
            for item in existing
            if isinstance(item, dict) and isinstance(item.get("event_id"), str)
        ]
    by_id = {str(item["event_id"]): item for item in retained}
    by_id[str(current["event_id"])] = current
    return list(by_id.values())


def resolve_journal_draft_activation_receipt(
    *, vault_context: VaultContext, receipt_id: str
) -> dict[str, object] | None:
    """Resolve an embedded activation record from durable staged drafts."""

    vault_root = _vault_root(vault_context)
    directory_rel = _draft_relative_path(
        vault_root, date.min, is_addendum=False
    ).parent
    directory = vault_root
    for component in directory_rel.parts:
        candidate = directory / component
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(mode):
            raise ValueError("journal draft staging component is a symlink")
        if not stat.S_ISDIR(mode):
            raise ValueError("journal draft staging component is not a directory")
        directory = candidate
    for path in sorted(directory.glob("*.md")):
        if stat.S_ISLNK(path.lstat().st_mode):
            raise ValueError("journal draft target is a symlink")
        frontmatter, _body = load_frontmatter(path.read_text(encoding="utf-8"))
        receipts = frontmatter.get("activation_receipts")
        if not isinstance(receipts, list):
            continue
        for record in receipts:
            if isinstance(record, dict) and record.get("event_id") == receipt_id:
                return record
    return None


def _atomic_write_at(directory_fd: int, filename: str, content: str) -> None:
    try:
        target_stat = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        target_stat = None
    if target_stat is not None and not stat.S_ISREG(target_stat.st_mode):
        raise ValueError("journal draft target is a symlink or non-regular file")

    temporary_name = f".{filename}.{uuid4().hex}.tmp"
    descriptor = os.open(
        temporary_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        raise


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "JOURNAL_DRAFT_WRITE_ACTION",
    "JournalDraftBlockedError",
    "JournalDraftResult",
    "SourceIdentity",
    "SourceKind",
    "UnresolvableJournalCitationError",
    "draft_journal_entry",
    "resolve_journal_draft_activation_receipt",
]
