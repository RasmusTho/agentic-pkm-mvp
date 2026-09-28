"""Governed capture append to the vault inbox (SEP-08a, issue #1790).

``POST /api/companion/capture`` is the bounded capture action: friction-free
intake of "things I need to take care of" as a commitment to future-self
appended to the vault inbox note. A capture is plain vault intake — never an
app-owned task: the contract carries no due dates, no app-managed task
states, no reminders (``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md``
§Resolved Q17). Captured material resurfaces later only by relevance, like
any vault material.

The action rides the existing governed machinery — no parallel write path:

- **policy** — ``WriteGuard`` gates the bounded action
  (``companion.capture.append``); blocked states are explicit 409s, mirroring
  the vault-browser queue-review action.
- **validation** — an explicit schema (``extra="forbid"``) plus a non-empty
  text check; a capture is never silently dropped, and due-date/task-state
  fields are rejected at the schema boundary.
- **deterministic writer** — ``app.knowledge.write_ops.append_note_relative``
  performs the append and returns the runtime ``WriteReceipt``; the
  acknowledgement surfaces that receipt verbatim and is never fabricated by
  the endpoint.
- **event pipeline** — a ``capture.inbox.appended`` outbox event records the
  applied append (JSONL audit log plus DB outbox mirror, same pattern as the
  Panel confirmation service). For governed writes this event carries the
  AuthorityReceipt and is required before returning a success acknowledgement.
  The payload is metadata-only; the captured text itself is durable in the
  vault, not duplicated into event logs.

vault-inbox note convention (reused from existing repo conventions):

- the inbox directory resolves via ``app.vault.paths.get_vault_inbox_dir_rel``
  (env ``VAULT_INBOX_DIR_REL`` → ``system-settings.yaml paths.inbox_dir_rel``
  → ``vault.layout.md inbox_folder``);
- captures land in ``<inbox_dir_rel>/inbox.md``; ``VAULT_CAPTURE_NOTE_REL``
  overrides the note path (mirrors ``VAULT_CHANGE_LOG_NOTE_REL`` in
  ``app/services/inbox.py``);
- entries reuse the timestamped-bullet line convention from
  ``app/services/inbox.py`` — ``- [<utc-iso>] <text>`` with two-space
  continuation lines for multi-line captures. Deliberately *not* ``- [ ]``
  checkbox syntax: a capture is not a task.
"""

from __future__ import annotations

import array
import logging
import os
import re
import sys
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import regex
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes.ingest_binding import ingest_binding_status
from app.api.compatibility_mutation import (
    reject_scoped_vault_mutation,
    require_compatibility_mutation,
)
from app.api.routes.vault_resolution import active_vault_root_or_selection_required
from app.events.models import new_trace_id
from app.events.schema import make_outbox_event
from app.knowledge.locators import normalize_note_path
from app.governance.governed_write import (
    AuthorityReceipt,
    GovernedWriteAdapter,
    GovernedWriteGrant,
)
from app.knowledge.write_ops import append_note_relative
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services.outbox import (
    EVENT_ID_FINGERPRINT,
    append_jsonl_outbox_event,
    coerce_outbox_event,
    derive_idempotency_key,
    write_outbox_event,
)
from app.vault.paths import get_vault_inbox_dir_rel, get_vault_sources_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError
from app.standing_questions.registration import RegistrationProposalResult, propose_question_registration

logger = logging.getLogger(__name__)
_DEFAULT_IGNORABLE_RE = regex.compile(r"\p{Default_Ignorable_Code_Point}+")

router = APIRouter(prefix="/companion", tags=["companion"])

CAPTURE_APPENDED_EVENT = "capture.inbox.appended"
_WRITE_GUARD_ACTION = "companion.capture.append"
_WRITE_CLASS = "vault_capture_append"
_DEFAULT_CAPTURE_NOTE_NAME = "inbox.md"
_EVENT_SOURCE = "companion.capture"
_STATE_OWNER = "knowledge"
_GOVERNED_WRITE_ADAPTER = GovernedWriteAdapter()


class CaptureEventPersistenceError(RuntimeError):
    """Raised when governed capture accountability cannot be persisted."""


class CaptureRequest(BaseModel):
    """A capture is plain text intake.

    ``extra="forbid"`` keeps the contract honest: a due-date or task-state
    field is rejected explicitly (422) instead of being silently discarded.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


class CaptureResponse(BaseModel):
    """Runtime acknowledgement of a written capture.

    ``operation`` and ``adapter`` are surfaced verbatim from the deterministic
    writer's ``WriteReceipt``; ``note_path`` is the vault-relative inbox
    reference where the capture landed. The endpoint never fabricates an
    acknowledgement — this model is only built from an actual write receipt.

    ``ingest_warning`` is populated when the write itself succeeded but the
    watcher/worker are not confirmed bound to the vault the capture just
    landed in (#3119) — a vault selected/initialized through the Companion UI
    can silently diverge from the watcher/worker's independent boot-time
    binding, so a bare "written" acknowledgement would misrepresent whether
    the capture will ever be ingested/findable. ``None`` means the watcher is
    confirmed bound to this vault (or binding status could not meaningfully
    diverge, e.g. no watcher expected in this deployment).
    """

    outcome: Literal["written"] = "written"
    note_path: str
    operation: str
    adapter: str
    captured_at: str
    trace_id: str
    events_emitted: list[str] = Field(default_factory=list)
    governed_write: dict[str, Any] | None = None
    ingest_warning: str | None = None
    registration_state: Literal["proposal_pending", "not_qualified", "degraded"] = "not_qualified"
    registration_proposal_id: str | None = None


def _capture_note_rel(vault_root: Path) -> str:
    override = (os.getenv("VAULT_CAPTURE_NOTE_REL") or "").strip()
    if override:
        return normalize_note_path(override)
    inbox_rel = get_vault_inbox_dir_rel(vault_root)
    return normalize_note_path((Path(inbox_rel) / _DEFAULT_CAPTURE_NOTE_NAME).as_posix())


def _nearest_existing_directory(path: Path) -> Path:
    candidate = path
    while not candidate.is_dir() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate.resolve(strict=False)


def _linux_mount_type(path: Path) -> str | None:
    """Return the Linux mount type for path using the read-only mount table."""
    try:
        resolved = path.resolve(strict=False)
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError:
        return None

    best_mount: Path | None = None
    best_type: str | None = None
    for line in mountinfo.splitlines():
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        fields = left.split()
        right_fields = right.split()
        if len(fields) < 5 or not right_fields:
            continue
        mount_path = re.sub(
            r"\\([0-7]{3})",
            lambda match: chr(int(match.group(1), 8)),
            fields[4],
        )
        mount = Path(mount_path)
        if resolved != mount and mount not in resolved.parents:
            continue
        if best_mount is None or len(mount.parts) > len(best_mount.parts):
            best_mount = mount
            best_type = right_fields[0]
    return best_type


def _linux_ext4_casefolded(path: Path) -> bool | None:
    """Read the ext4 per-directory casefold flag; None means unknown filesystem state."""
    if _linux_mount_type(path) != "ext4":
        return None
    try:
        import fcntl

        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return None
    try:
        flags = array.array("L", [0])
        ioctl_read = 2
        get_flags = (
            (ioctl_read << 30)
            | (flags.itemsize << 16)
            | (ord("f") << 8)
            | 1
        )
        fcntl.ioctl(descriptor, get_flags, flags, True)
        return bool(flags[0] & 0x40000000)  # FS_CASEFOLD_FL
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _probe_case_insensitive_directory(path: Path) -> bool | None:
    """Probe entries in exactly this directory; None means there was no usable probe."""
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                except OSError:
                    continue
                for index, character in enumerate(entry.name):
                    if not character.isascii() or not character.isalpha():
                        continue
                    alternate_name = (
                        entry.name[:index]
                        + character.swapcase()
                        + entry.name[index + 1 :]
                    )
                    alternate = path / alternate_name
                    try:
                        return os.path.samefile(entry.path, alternate)
                    except FileNotFoundError:
                        return False
                    except OSError:
                        continue
    except OSError:
        return None
    return None


def _filesystem_name_semantics(
    path: Path,
) -> tuple[bool | None, bool | None, bool | None]:
    """Return case, normalization, and ignorable-code-point lookup behavior."""
    if sys.platform.startswith("linux"):
        lookup_dir_exists = path.is_dir()
        # New ext4 directories inherit FS_CASEFOLD_FL from their parent; an
        # existing directory must be checked directly because flags are local.
        candidate = (
            path.resolve(strict=False)
            if lookup_dir_exists
            else _nearest_existing_directory(path)
        )
        ext4_casefolded = _linux_ext4_casefolded(candidate)
        if ext4_casefolded is not None:
            return ext4_casefolded, ext4_casefolded, ext4_casefolded
        if not lookup_dir_exists:
            return None, None, None
        # Other Linux filesystems can be probed for ASCII case behavior, but
        # their Unicode normalization behavior is unknown and must stay guarded.
        return _probe_case_insensitive_directory(candidate), None, None

    if sys.platform == "darwin":
        # APFS/HFS+ name normalization is volume-wide. If the requested parent
        # does not exist yet, an existing ancestor on that same volume provides
        # the case-sensitivity probe; its Unicode normalization behavior is
        # known independently of case sensitivity.
        candidate = _nearest_existing_directory(path)
        try:
            device = candidate.stat().st_dev
        except OSError:
            return None, True, None
        while True:
            result = _probe_case_insensitive_directory(candidate)
            if result is not None:
                return result, True, None if result else False

            parent = candidate.parent
            if parent == candidate:
                return None, True, None
            try:
                if parent.stat().st_dev != device:
                    return None, True, None
            except OSError:
                return None, True, None
            candidate = parent.resolve(strict=False)

    if path.is_dir():
        result = _probe_case_insensitive_directory(path.resolve(strict=False))
        return result, None, False if result is False else None
    return None, None, None


def _same_path_prefix(
    left: Path,
    right: Path,
    *,
    case_insensitive: bool | None,
    normalization_insensitive: bool | None,
    default_ignorables_insensitive: bool | None = None,
) -> bool:
    if left == right:
        return True
    try:
        return os.path.samefile(left, right)
    except OSError:
        pass
    left_name = left.name
    right_name = right.name
    if normalization_insensitive is not False:
        left_name = unicodedata.normalize("NFD", left_name)
        right_name = unicodedata.normalize("NFD", right_name)
    if default_ignorables_insensitive is True or (
        default_ignorables_insensitive is None and case_insensitive is not False
    ):
        left_name = _DEFAULT_IGNORABLE_RE.sub("", left_name)
        right_name = _DEFAULT_IGNORABLE_RE.sub("", right_name)
    if case_insensitive is False:
        return left_name == right_name
    left_name = left_name.casefold()
    right_name = right_name.casefold()
    if normalization_insensitive is not False:
        left_name = unicodedata.normalize("NFD", left_name)
        right_name = unicodedata.normalize("NFD", right_name)
    return left_name == right_name


def _path_is_within(candidate: Path, parent: Path) -> bool:
    candidate_parts = candidate.parts
    parent_parts = parent.parts
    if len(candidate_parts) < len(parent_parts) or candidate_parts[0] != parent_parts[0]:
        return False

    candidate_prefix = Path(candidate_parts[0])
    parent_prefix = Path(parent_parts[0])
    for index, (candidate_part, parent_part) in enumerate(
        zip(candidate_parts[1:], parent_parts[1:]), start=1
    ):
        candidate_prefix /= candidate_part
        parent_prefix /= parent_part
        if candidate_prefix == parent_prefix:
            continue
        try:
            if os.path.samefile(candidate_prefix, parent_prefix):
                continue
        except OSError:
            pass
        (
            case_insensitive,
            normalization_insensitive,
            default_ignorables_insensitive,
        ) = _filesystem_name_semantics(parent_prefix.parent)
        if not _same_path_prefix(
            candidate_prefix,
            parent_prefix,
            case_insensitive=case_insensitive,
            normalization_insensitive=normalization_insensitive,
            default_ignorables_insensitive=default_ignorables_insensitive,
        ):
            return False
    return True


def _capture_target_overlaps_sources(
    note_rel: str, sources_dir_rel: str, *, vault_root: Path
) -> bool:
    """Compare normalized paths, following symlinks and filesystem aliases."""
    root = vault_root.expanduser().resolve(strict=False)
    capture_path = Path(normalize_note_path(note_rel))
    if not capture_path.is_absolute():
        capture_path = root / capture_path
    capture_path = capture_path.resolve(strict=False)
    sources_path = (root / sources_dir_rel).resolve(strict=False)
    return _path_is_within(capture_path, sources_path) or _path_is_within(
        sources_path, capture_path
    )


def _compose_entry(text: str, captured_at: str) -> str:
    lines = text.splitlines() or [text]
    first = f"- [{captured_at}] {lines[0]}"
    continuation = [f"  {line}" for line in lines[1:]]
    return "\n".join([first, *continuation]) + "\n"


def _compose_append_entry(
    note_rel: str, text: str, captured_at: str, *, vault_root: Path
) -> str:
    entry = _compose_entry(text, captured_at)
    note_path = (vault_root / note_rel).resolve()
    root = vault_root.resolve()
    try:
        note_path.relative_to(root)
    except ValueError:
        return entry
    if not note_path.exists():
        return entry
    existing = note_path.read_text(encoding="utf-8")
    if existing and not existing.endswith("\n"):
        return "\n" + entry
    return entry


def _resolve_outbox_path() -> Path:
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


def _governed_write_payload(
    grant: GovernedWriteGrant,
    authority_receipt: AuthorityReceipt,
) -> dict[str, Any]:
    return {
        "policy_decision": asdict(grant.policy_decision),
        "decision_token": asdict(grant.decision_token),
        "authority_receipt": asdict(authority_receipt),
    }


def _writeguard_blocked_detail(exc: WritesBlockedError) -> dict[str, Any]:
    return {
        "error": "writeguard_blocked",
        "state": "blocked",
        "message": str(exc),
        "reason": exc.reason,
    }


def _offer_question_registration_proposal(
    *, vault_root: Path, note_rel: str, trace_id: str
) -> RegistrationProposalResult | None:
    """Run proposal-only capture classification after the durable append."""
    try:
        return propose_question_registration(
            capture_note_path=vault_root / note_rel,
            vault_root=vault_root,
            trace_id=trace_id,
        )
    except (OSError, WritesBlockedError):
        logger.warning("standing-question proposal pass degraded trace_id=%s", trace_id, exc_info=True)
        return None


def _emit_capture_event(payload: dict[str, Any], trace_id: str) -> list[str]:
    """Record the applied append on the event pipeline.

    JSONL audit log is the required local accountability sink. The DB outbox
    mirror is used when a pg backend is configured. At least one sink must
    persist the event before the endpoint acknowledges the governed write.
    """
    evt = make_outbox_event(
        event=CAPTURE_APPENDED_EVENT,
        source=_EVENT_SOURCE,
        payload=payload,
        trace_id=trace_id,
    )
    emitted = False
    try:
        emitted = append_jsonl_outbox_event(
            _resolve_outbox_path(), evt, default_source=_EVENT_SOURCE
        )
    except Exception as exc:
        logger.warning(
            "capture event jsonl write failed trace_id=%s err=%s",
            trace_id,
            exc,
        )

    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if backend == "pg" or db_url:
        outbox_evt = coerce_outbox_event(evt, default_source=_EVENT_SOURCE)
        if outbox_evt is not None:
            try:
                stored_id = write_outbox_event(
                    outbox_evt,
                    idempotency_key=derive_idempotency_key(
                        outbox_evt.event, outbox_evt.event_id, EVENT_ID_FINGERPRINT
                    ),
                )
                emitted = emitted or bool(stored_id)
            except Exception as exc:
                logger.warning(
                    "capture event db outbox write failed trace_id=%s err=%s",
                    trace_id,
                    exc,
                )

    if not emitted:
        raise CaptureEventPersistenceError(
            "capture AuthorityReceipt was not persisted to any outbox sink"
        )

    return [CAPTURE_APPENDED_EVENT]


@router.post("/capture", response_model=CaptureResponse)
def capture_to_inbox(req: CaptureRequest, request: Request) -> CaptureResponse | JSONResponse:
    """Append a capture to the vault inbox note through the governed pipeline."""
    trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
    reject_scoped_vault_mutation(request)

    # Validation — never silently drop text: whitespace-only is an explicit,
    # named rejection (schema validation already rejected missing/empty text
    # and any due-date/task-state field).
    text = req.text.strip("\n").strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "empty_capture",
                "message": (
                    "Capture text must contain non-whitespace characters; "
                    "nothing was written."
                ),
            },
        )

    # Policy — preserve the legacy guard-first failure ordering. Blocked writes
    # must return writeguard_blocked before any vault binding or inbox lookup.
    try:
        DEFAULT_WRITE_GUARD.assert_writes_allowed(_WRITE_GUARD_ACTION)
    except WritesBlockedError as exc:
        raise HTTPException(
            status_code=409,
            detail=_writeguard_blocked_detail(exc),
        ) from exc

    # vault-inbox note convention — resolution failures are explicit, the text is
    # never silently dropped.
    vault_root = active_vault_root_or_selection_required(require_initialized=True)
    if isinstance(vault_root, JSONResponse):
        return vault_root
    try:
        note_rel = _capture_note_rel(vault_root)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "inbox_convention_unresolved",
                "message": (
                    "The vault inbox note convention could not be resolved; "
                    f"nothing was written. {exc}"
                ),
            },
        ) from exc

    # The governed capture inbox is outside the sensor/acquisition archive.
    # Resolve the selected vault's configured Sources root before issuing any
    # authorization token, and fail closed when that authority is malformed.
    try:
        sources_dir_rel = get_vault_sources_dir_rel(vault_root)
        overlaps_sources = _capture_target_overlaps_sources(
            note_rel, sources_dir_rel, vault_root=vault_root
        )
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "sources_zone_unresolved",
                "message": (
                    "The vault Sources zone could not be resolved; "
                    f"nothing was written. {exc}"
                ),
            },
        ) from exc
    if overlaps_sources:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "capture_sources_overlap",
                "message": (
                    "The capture target overlaps the vault Sources zone; "
                    "nothing was written."
                ),
            },
        )

    # Policy — the governed-write adapter maps WriteGuard approval to a
    # DecisionToken before the state-owning writer mutates the vault.
    try:
        grant = _GOVERNED_WRITE_ADAPTER.issue_decision_token(
            write_guard=DEFAULT_WRITE_GUARD,
            action=_WRITE_GUARD_ACTION,
            write_class=_WRITE_CLASS,
            actor=_EVENT_SOURCE,
            resource=note_rel,
        )
    except WritesBlockedError as exc:
        raise HTTPException(
            status_code=409,
            detail=_writeguard_blocked_detail(exc),
        ) from exc

    # Deterministic writer — the governed append; its WriteReceipt is the
    # runtime acknowledgement.
    captured_at = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    receipt = append_note_relative(
        note_rel,
        _compose_append_entry(note_rel, text, captured_at, vault_root=vault_root),
        vault_root=vault_root,
    )
    authority_receipt = _GOVERNED_WRITE_ADAPTER.record_authority_receipt(
        decision_token=grant.decision_token,
        mutation_receipt=receipt,
        state_owner=_STATE_OWNER,
        trace_id=trace_id,
    )
    governed_write = _governed_write_payload(grant, authority_receipt)

    # Event pipeline — record the applied append (metadata only).
    try:
        events_emitted = _emit_capture_event(
            {
                "note_path": receipt.locator.path,
                "operation": receipt.operation,
                "adapter": receipt.adapter,
                "captured_at": captured_at,
                "decision_token_id": grant.decision_token.token_id,
                "authority_receipt_id": authority_receipt.receipt_id,
                "governed_write": governed_write,
            },
            trace_id=trace_id,
        )
    except CaptureEventPersistenceError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "authority_receipt_persistence_failed",
                "state": "not_acknowledged",
                "message": (
                    "The capture was written, but its AuthorityReceipt could "
                    "not be persisted; success acknowledgement was withheld."
                ),
                "trace_id": trace_id,
            },
        ) from exc

    registration = _offer_question_registration_proposal(
        vault_root=vault_root, note_rel=note_rel, trace_id=trace_id
    )
    registration_state: Literal["proposal_pending", "not_qualified", "degraded"]
    if registration is None or not registration.classification.classified:
        registration_state = "degraded"
    elif registration.proposal_id is not None:
        registration_state = "proposal_pending"
    else:
        registration_state = "not_qualified"

    # Ingest-binding visibility (#3119) — the write above already succeeded;
    # this only decides whether to accompany "written" with a warning that the
    # watcher/worker are not confirmed bound to this vault. Never gates or
    # delays the write itself, and a check failure must not turn a successful
    # capture into an error response.
    ingest_warning: str | None = None
    try:
        binding = ingest_binding_status(selected_vault_path=str(vault_root))
        if binding.state in ("unbound", "diverged"):
            ingest_warning = binding.detail
    except Exception:
        logger.warning("ingest binding status check failed during capture", exc_info=True)

    return CaptureResponse(
        note_path=receipt.locator.path,
        operation=receipt.operation,
        adapter=receipt.adapter,
        captured_at=captured_at,
        trace_id=trace_id,
        events_emitted=events_emitted,
        governed_write=governed_write,
        ingest_warning=ingest_warning,
        registration_state=registration_state,
        registration_proposal_id=registration.proposal_id if registration else None,
    )


@router.post(
    "/capture/compatibility",
    response_model=CaptureResponse,
    dependencies=[Depends(require_compatibility_mutation)],
)
def capture_to_inbox_compatibility(req: CaptureRequest, request: Request) -> CaptureResponse | JSONResponse:
    """Callable migrated route; activation in shipped HTML remains deferred."""

    return capture_to_inbox(req, request)


__all__ = ["router", "CaptureRequest", "CaptureResponse", "CAPTURE_APPENDED_EVENT"]
