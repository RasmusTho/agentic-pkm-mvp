"""Heimdal interest model + steering: A18 (Epic #3019, #3043).

Enacts journeys J3 (interest model) / J2 (in-flow steering) / J4 (post-hoc
steering) / J5 (per-source filters) under
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §2
("Markdown-first control surface") and `docs/HEIMDAL/FABLE_COMPANION.md`
§9-k: every steering capability is a **note edit the agent reads as
intent**. Chat and item action surfaces are transports/lenses onto these
notes -- they own no capability themselves (ADR-0049 §2: "any UI is a lens
with better ergonomics, never the sole home of a capability").

Ownership line (binding, per the governing Issue): **watching = Heimdal**
(mechanical -- this module writes the control-surface notes Heimdal reads
to decide what to fetch/attend to); **selecting = Mimer** (cognition --
what is worth attending, out of scope here per §9-k(b)).

Four capabilities, four distinct write shapes:

1. **Interest weights (`interests.md`)** -- a human-editable weight table.
   A hand-edit is explicit intent and outranks inference. The
   `confidence`/`evidence`/`decay` columns are agent-authored, derived
   bookkeeping the agent maintains -- never a channel to silently overwrite
   a human's weight edit. Reuses the A14 `INTERESTS` `SettingsNoteSpec`
   (`app.heimdal.settings_notes`) and its generic
   `apply_agent_update`/read-then-merge cycle verbatim: that function
   already refuses to touch a field it does not recognize as
   agent-authored, which is exactly the enforcement this AC needs -- no
   duplicate mechanism is built here.

2. **In-flow steering (`watchlist.md` / `never.md` appends)** -- "watch
   this" / "never this", drivable from chat OR an item. Both transports
   call the same :func:`append_watch` / :func:`append_never` here, which
   append one durable line to the note's body through the governed
   `app.knowledge.write_ops.append_note_relative` seam (never
   `write_settings_note`, which replaces a note's full frontmatter+body and
   would silently drop prior entries or human edits made directly on
   disk). The action is the same regardless of which surface produced it
   -- "the action is a transport onto the note" (governing Issue).

3. **Post-hoc steering (`steering.log.md` appends)** -- "less of this" /
   "mute" / "wrong" write append-only lines via :func:`append_steering_log`.
   Reuses the new A18 `STEERING_LOG` `SettingsNoteSpec` (append-only-log
   authority class) for path resolution. The entries themselves are body
   lines written exactly once per caller-stable operation identity through
   `append_note_relative`; their durable body bytes are **never changed** once
   appended (mirrors HEIM-1's append-only discipline, applied to a vault note
   instead of the DB-backed observation log). A per-log host lock serializes
   cooperating writers, while the governed seam publishes seed, append, and
   derived bookkeeping as one atomic file transaction. Retries therefore
   observe either the prior complete note or the next complete note and never
   duplicate an already-published operation. This is deliberately **not**
   `app.heimdal.settings_notes.write_settings_note`/`render_note`, which
   regenerate the note's full content (frontmatter + static descriptive
   body) from scratch and would silently discard every previously appended
   line. `steering.log.md` is the one `_heimdal/**` note whose body itself
   is the durable record, not a rendering of frontmatter fields, so it
   needs a distinct reconciliation path from every other note in this
   package.

4. **Per-source filters (`sources/*.md`)** -- reuses the A14 `SOURCE_CONFIG`
   spec verbatim (:func:`update_source_filters`); this module adds no new
   schema for it, only a steering-shaped convenience wrapper.

Every durable intent entry in this module reaches the vault through the same
governed append seam every other Heimdal control note uses
(`app.knowledge.write_ops.append_note_relative` + the caller-selected
`app.write_guard.WriteGuard`). For the steering log, that seam atomically
publishes the complete append transaction while preserving every prior body
byte and access-control metadata. This module asserts the capability action
before every append, then passes the same guard and action through so
`append_note_relative` reasserts the caller-authorized policy at its own seam.

Out of scope (per the governing Issue): watch-as-selection cognition
(Mimer's, §9-k(b)), native-app editor rendering, automatic source
onboarding beyond writing the `sources/*.md` filter notes.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
from typing import Any, Literal, Optional
from collections.abc import Iterator
import yaml

from app.heimdal.settings_notes import (
    INTERESTS,
    NEVER_LIST,
    SOURCE_CONFIG,
    STEERING_LOG,
    WATCHLIST,
    SettingsNote,
    apply_agent_update,
    note_rel_path,
    read_settings_note,
    render_note,
    write_settings_note,
)
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.write_ops import (
    _AtomicAppendAuthority,
    _bind_host_append_route,
    _mark_host_atomic_append_indeterminate,
    _open_atomic_append_authority,
    _open_durable_host_fence_root,
    _require_no_host_indeterminate_fence,
    append_note_relative,
)
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Distinct action strings per capability so a WriteGuard audit trail (and a
# future per-action allow/deny policy) can tell these apart, mirroring
# `app.heimdal.settings_notes.SETTINGS_NOTE_WRITE_ACTION` /
# `app.heimdal.consent_surface.CONSENT_READOUT_WRITE_ACTION`'s convention.
INFLOW_APPEND_WRITE_ACTION = "heimdal.interest_steering.inflow_append"
POSTHOC_STEERING_WRITE_ACTION = "heimdal.interest_steering.posthoc_append"
INTEREST_WEIGHT_WRITE_ACTION = "heimdal.interest_steering.interest_update"
SOURCE_FILTER_WRITE_ACTION = "heimdal.interest_steering.source_filter_update"
_STEERING_OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_STEERING_LOCKS_GUARD = threading.Lock()
_STEERING_LOCKS: dict[str, threading.RLock] = {}

# The two in-flow steering targets (J2/J3): "watch this" -> watchlist.md,
# "never this" -> never.md. Kept as a closed Literal so a caller cannot
# invent a third in-flow target without a deliberate schema change.
InflowKind = Literal["watch", "never"]

# The transport a steering action arrived through -- recorded in the
# appended line so the durable trail says *how* intent was expressed, not
# just what it was. Both transports produce the identical durable append;
# neither owns the capability (ADR-0049 §2 / governing Issue).
SteeringSource = Literal["chat", "item"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _assert_append_allowed(write_guard: WriteGuard, action: str) -> None:
    """Defense-in-depth guard at the capability call site.

    The same guard and action are passed to ``append_note_relative`` so its
    seam assertion preserves this caller's authorization instead of
    reauthorizing through the unrelated default policy.
    """
    write_guard.assert_writes_allowed(action)


# ---------------------------------------------------------------------------
# 1. Interest weights (interests.md) -- hand-edit outranks inference
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InterestDerivedUpdate:
    """One agent-derived update to a single named interest's bookkeeping
    columns. Never carries a `weight` -- that field belongs to the human
    only; passing it here would be rejected by `apply_agent_update`."""

    interest: str
    confidence: Optional[float] = None
    evidence: Optional[list[str]] = None
    decay: Optional[float] = None
    observed_signal: Optional[Any] = None


def read_interests(vault_root: Path) -> SettingsNote | None:
    """Read `interests.md` as it stands on disk, human edits and all."""
    return read_settings_note(vault_root, INTERESTS)


def apply_interest_derived_updates(
    vault_root: Path,
    updates: list[InterestDerivedUpdate],
    *,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> SettingsNote:
    """Reconcile the agent-authored columns (`confidence`/`evidence`/`decay`/
    `observed_signal`) of `interests.md` from fresh inference, **without
    ever touching `weights`** -- the human-editable column.

    This is the concrete mechanism behind the governing Issue's central
    invariant: "A hand-edit is explicit intent and outranks inference."
    Delegates entirely to `app.heimdal.settings_notes.apply_agent_update`,
    which already reads the note first, keeps every human-editable field
    exactly as found on disk, and raises if a caller tries to pass a
    human-editable field name -- no duplicate enforcement is built here,
    this function only shapes `InterestDerivedUpdate` rows into the
    per-column mapping `apply_agent_update` expects.
    """
    existing = read_settings_note(vault_root, INTERESTS)
    existing_confidence: dict[str, Any] = {}
    existing_evidence: dict[str, Any] = {}
    existing_decay: dict[str, Any] = {}
    existing_observed: dict[str, Any] = {}
    if existing is not None:
        existing_confidence = dict(existing.values.get("confidence") or {})
        existing_evidence = dict(existing.values.get("evidence") or {})
        existing_decay = dict(existing.values.get("decay") or {})
        existing_observed = dict(existing.values.get("observed_signal") or {})

    for update in updates:
        if update.confidence is not None:
            existing_confidence[update.interest] = update.confidence
        if update.evidence is not None:
            existing_evidence[update.interest] = update.evidence
        if update.decay is not None:
            existing_decay[update.interest] = update.decay
        if update.observed_signal is not None:
            existing_observed[update.interest] = update.observed_signal

    agent_values: dict[str, Any] = {
        "confidence": existing_confidence,
        "evidence": existing_evidence,
        "decay": existing_decay,
        "observed_signal": existing_observed,
    }
    return apply_agent_update(
        vault_root,
        INTERESTS,
        agent_values,
        write_guard=write_guard,
    )


def set_interest_weight(
    vault_root: Path,
    interest: str,
    weight: float,
    *,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> SettingsNote:
    """The literal human hand-edit path: set one named interest's weight.

    This is a distinct, explicitly-human-facing write -- the only channel
    that may set `weights` (mirrors `apply_agent_update`'s docstring:
    "the only way [to change a human-editable field] is a distinct,
    explicitly-human-facing edit"). Used by tests and any future surface
    that translates an explicit human weight edit into a note write (a
    human editing the file directly in Obsidian bypasses this function
    entirely, which is exactly the point -- both paths land in the same
    note and both are honored identically by `apply_interest_derived_updates`
    afterward).
    """
    existing = read_settings_note(vault_root, INTERESTS)
    values: dict[str, Any] = dict(existing.values) if existing is not None else {}
    weights = dict(values.get("weights") or {})
    weights[interest] = weight
    values["weights"] = weights
    note = SettingsNote(spec=INTERESTS, values=values)
    write_guard.assert_writes_allowed(INTEREST_WEIGHT_WRITE_ACTION)
    write_settings_note(vault_root, note, write_guard=write_guard, action=INTEREST_WEIGHT_WRITE_ACTION)
    return note


# ---------------------------------------------------------------------------
# 2. In-flow steering -- "watch this" / "never this" append durably
# ---------------------------------------------------------------------------

_INFLOW_SPECS = {
    "watch": WATCHLIST,
    "never": NEVER_LIST,
}


def _inflow_rel_path(kind: InflowKind) -> str:
    return note_rel_path(_INFLOW_SPECS[kind])


def append_inflow_steering(
    vault_root: Path,
    kind: InflowKind,
    target: str,
    *,
    source: SteeringSource,
    note: str | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    at: datetime | None = None,
) -> str:
    """Append one durable "watch this" / "never this" line, from chat or an
    item -- either transport produces the identical durable append.

    Returns the exact line written (so a caller/test can assert on it).
    The line is appended to the note's **body**, not its frontmatter --
    `watchlist.md` / `never.md`'s frontmatter `watched`/`never` fields
    (A14 schema) remain the structured, human-editable list; this durable
    line is the append-only *trail* of when/how each entry was added,
    which is what "durable append" means for an in-flow action (a chat
    message or item click is transient; the note line is not). Uses
    `app.knowledge.write_ops.append_note_relative` directly (never
    `write_settings_note`, which would replace -- not append to -- the
    note). The capability guard is asserted here and propagated to the
    append seam for its own assertion.
    """
    timestamp = (at or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    suffix = f" | {note}" if note else ""
    line = f"- [{timestamp}] source={source} target={target!r}{suffix}\n"

    _assert_append_allowed(write_guard, INFLOW_APPEND_WRITE_ACTION)
    rel_path = _inflow_rel_path(kind)
    append_note_relative(
        rel_path,
        line,
        vault_root=vault_root,
        write_guard=write_guard,
        action=INFLOW_APPEND_WRITE_ACTION,
    )
    return line


def append_watch(
    vault_root: Path,
    target: str,
    *,
    source: SteeringSource,
    note: str | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    at: datetime | None = None,
) -> str:
    """"Watch this" -- append durably to `watchlist.md`, from chat or an item."""
    return append_inflow_steering(
        vault_root, "watch", target, source=source, note=note, write_guard=write_guard, at=at
    )


def append_never(
    vault_root: Path,
    target: str,
    *,
    source: SteeringSource,
    note: str | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    at: datetime | None = None,
) -> str:
    """"Never this" -- append durably to `never.md`, from chat or an item."""
    return append_inflow_steering(
        vault_root, "never", target, source=source, note=note, write_guard=write_guard, at=at
    )


def read_inflow_body(vault_root: Path, kind: InflowKind) -> str:
    """Read the raw body text of `watchlist.md` / `never.md` (appended lines
    and all) -- a thin convenience for callers/tests that need to assert on
    the durable append trail rather than the parsed frontmatter."""
    rel_path = _inflow_rel_path(kind)
    path = vault_root / rel_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. Post-hoc steering (steering.log.md) -- append-only immutable trail
# ---------------------------------------------------------------------------

# Closed set of post-hoc steering verbs the governing Issue names
# ("less of this" / "mute" / "wrong"). A caller passes any short free-text
# verb; this is documentation of the expected vocabulary, not an enforced
# enum, so a future verb does not require a schema change to add.
POSTHOC_STEERING_VERBS = ("less_of_this", "mute", "wrong")
def _split_steering_log_bytes(raw: bytes) -> tuple[dict[str, Any], bytes]:
    """Parse frontmatter while returning every byte after its closer intact."""
    if not (raw.startswith(b"---\r\n") or raw.startswith(b"---\n")):
        raise ValueError("steering log is missing YAML frontmatter")

    offset = 0
    closing_end = -1
    frontmatter_lines: list[bytes] = []
    for index, line in enumerate(raw.splitlines(keepends=True)):
        content = line.rstrip(b"\r\n")
        if index > 0 and content == b"---":
            closing_end = offset + len(content)
            break
        if index > 0:
            frontmatter_lines.append(line)
        offset += len(line)
    if closing_end < 0:
        raise ValueError("steering log has unterminated YAML frontmatter")

    try:
        parsed = yaml.safe_load(b"".join(frontmatter_lines).decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("steering log has malformed YAML frontmatter") from exc
    if parsed is None:
        frontmatter: dict[str, Any] = {}
    elif isinstance(parsed, dict):
        frontmatter = parsed
    else:
        raise ValueError("steering log YAML frontmatter must be a mapping")
    return frontmatter, raw[closing_end:]


def _build_steering_log_transaction(
    raw: bytes | None,
    proposed_append: bytes,
    *,
    payload: dict[str, Any],
    timestamp: str,
) -> tuple[bytes, bytes, str]:
    """Build one complete seed/append/bookkeeping publication.

    Existing body bytes are carried forward verbatim. A matching operation
    id contributes no new append bytes, while a mismatched reuse fails before
    the governed append seam publishes anything.
    """

    if raw is None:
        seed = SettingsNote(
            spec=STEERING_LOG,
            values={"entry_count": 0, "last_appended": None},
        )
        raw = render_note(seed).encode("utf-8")

    frontmatter, body_bytes = _split_steering_log_bytes(raw)
    entries = _steering_log_entries(raw)
    operation_id = payload["operation_id"]
    matches = [
        entry
        for entry in entries
        if entry.payload and entry.payload["operation_id"] == operation_id
    ]
    if len(matches) > 1:
        raise RuntimeError(
            f"operation_id collision: duplicate durable entries for {operation_id}"
        )
    if matches:
        if matches[0].payload != payload:
            raise ValueError(f"operation_id collision for {operation_id}")
        actual_append = b""
        durable_line = matches[0].line
        final_entries = entries
    else:
        actual_append = proposed_append
        durable_line = proposed_append.decode("utf-8")
        final_entries = [
            *entries,
            _SteeringLogEntry(line=durable_line, timestamp=timestamp, payload=payload),
        ]

    frontmatter.update(
        {
            "entry_count": len(final_entries),
            "last_appended": final_entries[-1].timestamp if final_entries else None,
        }
    )
    rendered_frontmatter = (
        dump_frontmatter(frontmatter, "").removesuffix("\n").encode("utf-8")
    )
    return rendered_frontmatter + body_bytes + actual_append, actual_append, durable_line


@contextmanager
def _locked_steering_log(vault_root: Path) -> Iterator[_AtomicAppendAuthority]:
    """Serialize one inode and lexical resource across remaps and aliases."""
    relative = note_rel_path(STEERING_LOG)
    with _open_atomic_append_authority(vault_root, relative) as authority:
        lock_keys = sorted(authority.coordination_keys)
        with _STEERING_LOCKS_GUARD:
            process_locks = [
                _STEERING_LOCKS.setdefault(key, threading.RLock())
                for key in lock_keys
            ]

        lock_root = Path(tempfile.gettempdir()) / "agentic-pkm-heimdal-locks"
        with ExitStack() as stack:
            for process_lock in process_locks:
                stack.enter_context(process_lock)
            directory_flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            lock_parent_fd = os.open(lock_root.parent, directory_flags)
            stack.callback(os.close, lock_parent_fd)
            try:
                os.mkdir(lock_root.name, mode=0o700, dir_fd=lock_parent_fd)
            except FileExistsError:
                pass
            os.fsync(lock_parent_fd)
            lock_root_fd = os.open(
                lock_root.name,
                directory_flags,
                dir_fd=lock_parent_fd,
            )
            stack.callback(os.close, lock_root_fd)
            os.fsync(lock_root_fd)
            lock_fds: list[int] = []
            for key in lock_keys:
                name = f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.lock"
                file_flags = (
                    os.O_RDWR
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                )
                try:
                    lock_fd = os.open(
                        name,
                        file_flags | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=lock_root_fd,
                    )
                except FileExistsError:
                    lock_fd = os.open(
                        name,
                        file_flags,
                        dir_fd=lock_root_fd,
                    )
                stack.callback(os.close, lock_fd)
                observed = os.fstat(lock_fd)
                if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
                    raise KnowledgeWriteConflict(
                        "steering log host lock must be one regular file"
                    )
                lock_fds.append(lock_fd)
            os.fsync(lock_root_fd)
            for lock_fd in lock_fds:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            host_state_fd = _open_durable_host_fence_root(authority)
            lock_fd_by_key = {
                key: lock_fd for key, lock_fd in zip(lock_keys, lock_fds, strict=True)
            }
            bound_authority = replace(
                authority,
                host_state_fd=host_state_fd,
                host_state_stat=os.fstat(host_state_fd),
                host_witness_root_path=lock_root,
                host_witness_root_fd=lock_root_fd,
                host_witness_root_stat=os.fstat(lock_root_fd),
                host_witness_fds=tuple(
                    (key, lock_fd_by_key[key]) for key in authority.coordination_keys
                ),
            )
            try:
                bound_authority.assert_live()
                bound_authority.assert_host_state_live()
                bound_authority.assert_host_witness_live()
                _bind_host_append_route(bound_authority)
                _require_no_host_indeterminate_fence(bound_authority)
                yield bound_authority
                try:
                    bound_authority.assert_live()
                    bound_authority.assert_host_state_live()
                    bound_authority.assert_host_witness_live()
                    _require_no_host_indeterminate_fence(bound_authority)
                except KnowledgeWriteConflict:
                    try:
                        _mark_host_atomic_append_indeterminate(
                            bound_authority,
                            "post-transaction-authority-check",
                            "root or host authority changed before lock release",
                        )
                    except BaseException:
                        pass
                    raise
            finally:
                os.close(host_state_fd)
                for lock_fd in reversed(lock_fds):
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)


@dataclass(frozen=True)
class _SteeringLogEntry:
    line: str
    timestamp: str
    payload: dict[str, Any] | None


def _steering_log_entries(raw: bytes) -> list[_SteeringLogEntry]:
    """Return structured entries plus countable legacy steering lines."""
    _frontmatter, body_bytes = _split_steering_log_bytes(raw)
    if body_bytes and not body_bytes.endswith(b"\n"):
        raise RuntimeError("unterminated steering log entry or body tail")
    entries: list[_SteeringLogEntry] = []
    for line_bytes in body_bytes.splitlines(keepends=True):
        line = line_bytes.decode("utf-8")
        content = line.rstrip("\r\n")
        if not content.startswith("- [") or "] " not in content:
            continue
        if not line_bytes.endswith(b"\n"):
            raise RuntimeError("unterminated steering log entry")
        timestamp, payload_text = content[3:].split("] ", 1)
        if payload_text.startswith("{"):
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError as exc:
                raise RuntimeError("malformed structured steering log entry") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("operation_id"), str):
                raise RuntimeError("structured steering log entry is missing operation_id")
            entries.append(_SteeringLogEntry(line=line, timestamp=timestamp, payload=payload))
        elif payload_text.startswith("verb=") and " source=" in payload_text:
            entries.append(_SteeringLogEntry(line=line, timestamp=timestamp, payload=None))
    return entries


def append_steering_log(
    vault_root: Path,
    verb: str,
    target: str,
    *,
    source: SteeringSource,
    operation_id: str,
    note: str | None = None,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    at: datetime | None = None,
) -> str:
    """Append one immutable post-hoc steering line to `steering.log.md`.

    ``operation_id`` is the caller-stable idempotency identity. Reusing it
    with identical content returns the durable existing line and repairs any
    pending frontmatter bookkeeping; reusing it with different content fails
    loud. Cooperating processes serialize only this resolved steering log.

    "Less of this" / "mute" / "wrong" (or any other post-hoc verb) each
    become one line appended to the log's body through
    `app.knowledge.write_ops.append_note_relative`. The seam publishes the
    body append and agent-authored frontmatter bookkeeping
    (`entry_count`/`last_appended`) together as one atomic transaction. Its
    transform is constrained to carry every prior body byte forward verbatim;
    `apply_agent_update`/`write_settings_note` are not used because they would
    regenerate the note's body and discard the append-only history.
    """
    if not _STEERING_OPERATION_ID_RE.fullmatch(operation_id):
        raise ValueError(
            "operation_id must be 1-128 characters using letters, digits, '.', '_', ':', or '-'"
        )

    timestamp = (at or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    payload: dict[str, Any] = {
        "note": note,
        "operation_id": operation_id,
        "source": source,
        "target": target,
        "verb": verb,
    }
    encoded_payload = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    line = f"- [{timestamp}] {encoded_payload}\n"

    durable_line = line

    def build_transaction(
        current: bytes | None,
        proposed: bytes,
    ) -> tuple[bytes, bytes]:
        nonlocal durable_line
        replacement, actual_append, durable_line = _build_steering_log_transaction(
            current,
            proposed,
            payload=payload,
            timestamp=timestamp,
        )
        return replacement, actual_append

    _assert_append_allowed(write_guard, POSTHOC_STEERING_WRITE_ACTION)
    with _locked_steering_log(vault_root) as authority:
        append_note_relative(
            note_rel_path(STEERING_LOG),
            line,
            vault_root=vault_root,
            write_guard=write_guard,
            action=POSTHOC_STEERING_WRITE_ACTION,
            _atomic_transform=build_transaction,
            _atomic_authority=authority,
        )
    return durable_line


def read_steering_log_body(vault_root: Path) -> str:
    """Read the raw body text of `steering.log.md` (every appended line, in
    append order) -- the immutable trail itself, not the frontmatter
    bookkeeping about it."""
    rel_path = note_rel_path(STEERING_LOG)
    path = vault_root / rel_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. Per-source filters (sources/*.md) -- reuses A14's SOURCE_CONFIG verbatim
# ---------------------------------------------------------------------------


def update_source_filters(
    vault_root: Path,
    source_id: str,
    filters: list[str],
    *,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> SettingsNote:
    """Set the human-editable `filters` list for one `sources/{source_id}.md`
    note. A distinct, explicitly-human-facing write (mirrors
    `set_interest_weight`) -- `source_id`/`filters` are human-editable per
    the A14 `SOURCE_CONFIG` spec; `last_fetched`/`last_error` stay untouched
    here (agent-authored, reconciled elsewhere by whatever runs the fetch,
    out of scope for this slice)."""
    existing = read_settings_note(vault_root, SOURCE_CONFIG, source_id=source_id)
    values: dict[str, Any] = dict(existing.values) if existing is not None else {}
    values["source_id"] = source_id
    values["filters"] = list(filters)
    note = SettingsNote(spec=SOURCE_CONFIG, values=values)
    write_guard.assert_writes_allowed(SOURCE_FILTER_WRITE_ACTION)
    write_settings_note(
        vault_root,
        note,
        write_guard=write_guard,
        action=SOURCE_FILTER_WRITE_ACTION,
        source_id=source_id,
    )
    return note


__all__ = [
    "INFLOW_APPEND_WRITE_ACTION",
    "INTEREST_WEIGHT_WRITE_ACTION",
    "POSTHOC_STEERING_VERBS",
    "POSTHOC_STEERING_WRITE_ACTION",
    "SOURCE_FILTER_WRITE_ACTION",
    "InflowKind",
    "InterestDerivedUpdate",
    "SteeringSource",
    "apply_interest_derived_updates",
    "append_inflow_steering",
    "append_never",
    "append_steering_log",
    "append_watch",
    "read_inflow_body",
    "read_interests",
    "read_steering_log_body",
    "set_interest_weight",
    "update_source_filters",
]
