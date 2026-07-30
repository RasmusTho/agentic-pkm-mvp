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
   `append_note_relative` and are **never** rewritten once appended (mirrors
   HEIM-1's append-only discipline, applied to a vault note instead of the
   DB-backed observation log). A per-log host lock serializes cooperating
   writers, and retries reconcile any already-appended operation plus the
   derived bookkeeping instead of duplicating it. The note's
   agent-authored frontmatter bookkeeping (`entry_count`/`last_appended`) is
   reconciled through `_patch_frontmatter_preserving_body`, a body-preserving
   frontmatter patch -- deliberately **not**
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

Every durable intent entry in this module reaches the vault through the
same governed append seam every other Heimdal control note uses
(`app.knowledge.write_ops.append_note_relative` + the caller-selected
`app.write_guard.WriteGuard`). The steering-log seed and derived
frontmatter use guarded atomic replacements because they must preserve
crash recovery and the existing body bytes. This module asserts the
capability action before every append, then passes the same guard and
action through so `append_note_relative` reasserts the caller-authorized
policy at its own seam.

Out of scope (per the governing Issue): watch-as-selection cognition
(Mimer's, §9-k(b)), native-app editor rendering, automatic source
onboarding beyond writing the `sources/*.md` filter notes.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Literal, Optional
from collections.abc import Iterator
from uuid import uuid4

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
from app.knowledge.write_ops import append_note_relative
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter

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


def _ensure_steering_log_seed(vault_root: Path, *, write_guard: WriteGuard) -> None:
    """Create `steering.log.md` with its initial frontmatter+body if it does
    not exist yet.

    The complete seed is rendered through the normal settings-note renderer,
    then installed by atomic replacement so an interrupted first write cannot
    leave a partial YAML document for a retry to mistake for a durable seed.
    """
    rel_path = note_rel_path(STEERING_LOG)
    path = vault_root / rel_path
    if path.exists():
        return
    write_guard.assert_writes_allowed(POSTHOC_STEERING_WRITE_ACTION)
    note = SettingsNote(spec=STEERING_LOG, values={"entry_count": 0, "last_appended": None})
    _atomic_replace_bytes(path, render_note(note).encode("utf-8"))


def _atomic_replace_bytes(path: Path, content: bytes) -> None:
    """Durably install complete bytes at ``path`` using a sibling stage."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with staged.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        staged.unlink(missing_ok=True)


def _split_steering_log_bytes(raw: bytes) -> tuple[dict[str, Any], bytes]:
    """Parse frontmatter while returning every byte after its closer intact."""
    if not (raw.startswith(b"---\r\n") or raw.startswith(b"---\n")):
        raise ValueError("steering log is missing YAML frontmatter")

    offset = 0
    closing_end = -1
    for index, line in enumerate(raw.splitlines(keepends=True)):
        content = line.rstrip(b"\r\n")
        if index > 0 and content == b"---":
            closing_end = offset + len(content)
            break
        offset += len(line)
    if closing_end < 0:
        raise ValueError("steering log has unterminated YAML frontmatter")

    frontmatter_only = raw[:closing_end].decode("utf-8") + "\n"
    frontmatter, _body = load_frontmatter(frontmatter_only)
    return frontmatter, raw[closing_end:]


def _patch_steering_log_frontmatter(
    vault_root: Path,
    patch: dict[str, Any],
    *,
    write_guard: WriteGuard,
) -> None:
    """Rewrite only `steering.log.md`'s YAML frontmatter, preserving the
    body byte-for-byte through an atomic same-directory replacement.

    Deliberately bypasses `write_settings_note`/`render_note` (which
    regenerate the full note, including a fresh static descriptive body)
    -- those would silently discard every previously appended steering
    line. This is the one `_heimdal/**` note where the body is the durable
    record rather than a rendering of frontmatter, so its frontmatter
    reconciliation must preserve the body explicitly instead of trusting
    the generic renderer to do so.
    """
    write_guard.assert_writes_allowed(POSTHOC_STEERING_WRITE_ACTION)
    rel_path = note_rel_path(STEERING_LOG)
    path = vault_root / rel_path
    fm, body_bytes = _split_steering_log_bytes(path.read_bytes())
    fm.update(patch)
    rendered_frontmatter = dump_frontmatter(fm, "").removesuffix("\n").encode("utf-8")
    _atomic_replace_bytes(path, rendered_frontmatter + body_bytes)


@contextmanager
def _locked_steering_log(vault_root: Path) -> Iterator[None]:
    """Serialize cooperating writers for one resolved steering-log path."""
    target = (vault_root / note_rel_path(STEERING_LOG)).expanduser().resolve()
    lock_key = str(target)
    with _STEERING_LOCKS_GUARD:
        process_lock = _STEERING_LOCKS.setdefault(lock_key, threading.RLock())

    lock_root = Path(tempfile.gettempdir()) / "agentic-pkm-heimdal-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_name = hashlib.sha256(lock_key.encode("utf-8")).hexdigest()
    with process_lock, (lock_root / f"{lock_name}.lock").open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class _SteeringLogEntry:
    line: str
    timestamp: str
    payload: dict[str, Any] | None


def _steering_log_entries(raw: bytes) -> list[_SteeringLogEntry]:
    """Return structured entries plus countable legacy steering lines."""
    _frontmatter, body_bytes = _split_steering_log_bytes(raw)
    entries: list[_SteeringLogEntry] = []
    for line in body_bytes.decode("utf-8").splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if not content.startswith("- [") or "] " not in content:
            continue
        timestamp, payload_text = content[3:].split("] ", 1)
        if payload_text.startswith("{"):
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError as exc:
                raise RuntimeError("malformed structured steering log entry") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("operation_id"), str):
                raise RuntimeError("structured steering log entry is missing operation_id")
            entries.append(_SteeringLogEntry(line=line, timestamp=timestamp, payload=payload))
        elif " verb=" in payload_text and " source=" in payload_text:
            entries.append(_SteeringLogEntry(line=line, timestamp=timestamp, payload=None))
    return entries


def _reconcile_steering_log_bookkeeping(
    vault_root: Path,
    *,
    write_guard: WriteGuard,
) -> None:
    path = vault_root / note_rel_path(STEERING_LOG)
    entries = _steering_log_entries(path.read_bytes())
    _patch_steering_log_frontmatter(
        vault_root,
        {
            "entry_count": len(entries),
            "last_appended": entries[-1].timestamp if entries else None,
        },
        write_guard=write_guard,
    )


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
    become one line appended to the log's body via
    `app.knowledge.write_ops.append_note_relative` -- never rewritten,
    never removed, no code path in this module reads the body back to
    mutate a prior line (the append-only invariant this AC checks). After
    the body append, the note's agent-authored frontmatter bookkeeping
    (`entry_count`/`last_appended`) is reconciled via
    `_patch_steering_log_frontmatter`, which preserves the body (every
    prior appended line) verbatim -- `apply_agent_update`/
    `write_settings_note` are not used here because they would regenerate
    the note's full content and discard the append-only history.
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
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    line = f"- [{timestamp}] {encoded_payload}\n"

    _assert_append_allowed(write_guard, POSTHOC_STEERING_WRITE_ACTION)
    with _locked_steering_log(vault_root):
        _ensure_steering_log_seed(vault_root, write_guard=write_guard)
        path = vault_root / note_rel_path(STEERING_LOG)
        entries = _steering_log_entries(path.read_bytes())
        matches = [
            entry
            for entry in entries
            if entry.payload and entry.payload["operation_id"] == operation_id
        ]
        if len(matches) > 1:
            raise RuntimeError(f"operation_id collision: duplicate durable entries for {operation_id}")
        if matches:
            if matches[0].payload != payload:
                raise ValueError(f"operation_id collision for {operation_id}")
            _reconcile_steering_log_bookkeeping(vault_root, write_guard=write_guard)
            return matches[0].line

        append_note_relative(
            note_rel_path(STEERING_LOG),
            line,
            vault_root=vault_root,
            write_guard=write_guard,
            action=POSTHOC_STEERING_WRITE_ACTION,
        )
        _reconcile_steering_log_bookkeeping(vault_root, write_guard=write_guard)
        return line


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
