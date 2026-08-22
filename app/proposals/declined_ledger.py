"""The declined-proposal ledger (EXP-2, #2995).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §3
(EXP-2). Parent: #2980 (Capability Hardening / Cognitive Expansion). This is
the shared, cross-cutting mechanism every proposal-emitting pass (Connect's
``app.expansion.connect``, the G2 curation passes, and later E8's
contradiction pass) consults before re-proposing a finding the human already
said no to. ``app.expansion.connect`` already declares the consultation
contract (:class:`app.expansion.connect.DeclinedLedgerPort`) and wires a
permanent no-op default; this module is the real, durable implementation of
that same protocol -- it does not fork the port shape, only supplies a real
backing store for it.

Hard invariants held by this module (do not relax without an owner-ratified
ADR):

- **Derived, rebuildable, never authority-bearing.** The ledger is
  suppression state, not knowledge (spec §3: "never indexed, never admitted
  as context, never an input to cognition"). It is never registered with, or
  reachable from, any retrieval/index/context-assembly seam
  (``app.retrieval.*``, ``app.context_bundles``, ``app.knowledge_compilation``)
  -- there is no code path here that returns ledger content as a
  ``RetrievalHit``/``RetrievalResponse`` or admits it into a context bundle.
  This module has zero imports from and zero callers in any of those seams.
- **Delete-safe by construction.** A missing, empty, or unreadable/corrupt
  ledger file degrades to "everything is re-proposable" -- :meth:`is_declined`
  never raises for a missing/empty/malformed store; deleting the file is a
  supported operation, not an error condition (spec: "deleting it re-enables
  re-proposal, never errors").
  request").
- **Content-based reset is automatic, not a manual override.** The ledger
  keys purely on the caller-supplied ``finding_id`` string. Every finding_id
  in this codebase is itself content-derived (hash over class + note-identity
  set + span/theme basis -- see
  ``app.expansion.connect.compute_connect_finding_id`` and
  ``app.curation.findings.CurationFinding``), so a changed content basis
  mints a *different* finding_id automatically; this module needs no
  content-hash logic of its own to satisfy "declining a link once is not
  declining it forever after both notes are rewritten" -- it falls out of
  the id scheme it consumes.
- **Idempotent decline recording.** Recording the same ``finding_id`` as
  declined twice is a no-op (one ledger line survives per finding_id, keeping
  the first durable receipt); it never changes evidence under a stable id and
  never duplicates suppression.
- **WriteGuard-gated, named action.** :data:`DECLINED_LEDGER_WRITE_ACTION`
  (``proposals.declined_ledger.record``) is asserted before any file I/O,
  matching the dotted ``<module>.<verb>`` convention used elsewhere
  (``curation.propose_write``, ``panel.writeback``). Reads
  (:meth:`is_declined`) are never WriteGuard-gated -- a health-blocked
  runtime must still be able to suppress previously-declined proposals; only
  the write path (recording a new decline) is gated.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
from pathlib import Path
import stat
import threading
from typing import Iterator
from uuid import uuid4

from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# Dotted <module>.<verb> convention (mirrors CURATION_PROPOSE_WRITE_ACTION).
DECLINED_LEDGER_WRITE_ACTION = "proposals.declined_ledger.record"

# Derived/rebuildable state dir -- same convention as
# app.relevance.attention_loop.DEFAULT_REACHOUT_RECEIPTS_PATH and siblings
# (runtime/<module>/*.jsonl, gitignored, safe to delete wholesale).
DEFAULT_DECLINED_LEDGER_PATH = Path("runtime/proposals/declined.jsonl")
_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


@dataclass(frozen=True)
class DeclineReceipt:
    """One decline record. ``finding_id`` is the sole suppression key --
    this dataclass intentionally carries no note content, span text, or
    theme label: the ledger must stay content-free enough that it could
    never be mistaken for, or accidentally admitted as, knowledge."""

    finding_id: str
    finding_class: str
    reason: str | None = None
    declined_at: str | None = None

    def to_json_line(self) -> str:
        return json.dumps(
            {
                "finding_id": self.finding_id,
                "finding_class": self.finding_class,
                "reason": self.reason,
                "declined_at": self.declined_at,
            },
            sort_keys=True,
        )


class DeclinedLedger:
    """File-backed :class:`app.expansion.connect.DeclinedLedgerPort` implementation.

    Structurally-typed against that Protocol (``is_declined(finding_id) -> bool``)
    without importing ``app.expansion`` -- ``app.proposals`` is shared
    substrate several passes (Connect, G2 curation, later E8) consult, so it
    must not depend on any one consumer.
    """

    def __init__(self, path: Path | str = DEFAULT_DECLINED_LEDGER_PATH) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _read_all(self) -> dict[str, DeclineReceipt]:
        """Load every currently-declined finding_id -> its latest receipt.

        Missing file, empty file, or any unreadable/malformed line degrades
        to "nothing declined" for that line -- this method never raises.
        Delete-safe by construction: a wholesale-deleted ledger file behaves
        identically to a freshly-provisioned empty one.
        """
        if not self._path.exists():
            return {}
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return {}

        receipts: dict[str, DeclineReceipt] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                # A corrupt line is skipped, not fatal -- the ledger is
                # derived state; partial corruption degrades toward
                # under-suppression (re-proposable), never toward a crash.
                continue
            finding_id = row.get("finding_id")
            if not isinstance(finding_id, str) or not finding_id:
                continue
            receipts[finding_id] = DeclineReceipt(
                finding_id=finding_id,
                finding_class=str(row.get("finding_class") or ""),
                reason=row.get("reason"),
                declined_at=row.get("declined_at"),
            )
        return receipts

    def is_declined(self, finding_id: str) -> bool:
        """True if *finding_id* currently has a live decline receipt.

        Never raises -- a missing/corrupt store simply reports False for
        every finding_id (delete-safe posture). This is the sole method the
        :class:`app.expansion.connect.DeclinedLedgerPort` protocol requires;
        every other method here is this module's own write/inspection API.
        """
        return finding_id in self._read_all()

    def get_receipt(self, finding_id: str) -> DeclineReceipt | None:
        """Return the first durable receipt for one suppression identity."""

        return self._read_all().get(finding_id)

    def record_decline(
        self,
        finding_id: str,
        *,
        finding_class: str,
        reason: str | None = None,
        declined_at: str | None = None,
        write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    ) -> DeclineReceipt:
        """Record *finding_id* as declined. Idempotent: re-recording the same
        finding_id preserves its first durable receipt rather than changing
        evidence under a stable identity. The complete read/merge/replace is
        serialized across threads and processes and published atomically."""
        write_guard.assert_writes_allowed(DECLINED_LEDGER_WRITE_ACTION)

        proposed = DeclineReceipt(
            finding_id=finding_id,
            finding_class=finding_class,
            reason=reason,
            declined_at=declined_at,
        )
        with self._locked_store():
            receipts = self._read_all()
            receipt = receipts.get(finding_id) or proposed
            receipts[finding_id] = receipt
            self._atomic_replace(receipts)
            return receipt

    @contextmanager
    def _locked_store(self) -> Iterator[None]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        key = os.path.abspath(os.fspath(self._path))
        with _PROCESS_LOCKS_GUARD:
            process_lock = _PROCESS_LOCKS.setdefault(key, threading.RLock())
        with process_lock:
            lock_path = self._path.with_name(f".{self._path.name}.lock")
            descriptor = os.open(
                lock_path,
                os.O_RDWR
                | os.O_CREAT
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            try:
                observed = os.fstat(descriptor)
                named = lock_path.lstat()
                if (
                    not stat.S_ISREG(observed.st_mode)
                    or observed.st_nlink != 1
                    or not stat.S_ISREG(named.st_mode)
                    or (observed.st_dev, observed.st_ino)
                    != (named.st_dev, named.st_ino)
                ):
                    raise RuntimeError("declined ledger lock must be one stable file")
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                named_after_lock = lock_path.lstat()
                opened_after_lock = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(named_after_lock.st_mode)
                    or named_after_lock.st_nlink != 1
                    or opened_after_lock.st_nlink != 1
                    or (opened_after_lock.st_dev, opened_after_lock.st_ino)
                    != (named_after_lock.st_dev, named_after_lock.st_ino)
                ):
                    raise RuntimeError(
                        "declined ledger lock changed during acquisition"
                    )
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def _atomic_replace(self, receipts: dict[str, DeclineReceipt]) -> None:
        lines = [receipts[key].to_json_line() for key in sorted(receipts)]
        encoded = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        parent_fd = os.open(
            self._path.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        temp_name = f".{self._path.name}.{uuid4().hex}.tmp"
        temp_fd: int | None = None
        try:
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_fd,
            )
            written = 0
            while written < len(encoded):
                count = os.write(temp_fd, encoded[written:])
                if count <= 0:
                    raise OSError("declined ledger atomic write made no progress")
                written += count
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None
            os.replace(
                temp_name,
                self._path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)

    def suppressed_count(self, finding_ids: list[str]) -> int:
        """Count how many of *finding_ids* are currently declined -- a small
        helper for passes that want a receipt count without re-deriving
        membership per-id themselves."""
        receipts = self._read_all()
        return sum(1 for fid in finding_ids if fid in receipts)


def default_path_from_env() -> Path:
    """Resolve the ledger path, honoring ``DECLINED_LEDGER_PATH`` for test/CI
    isolation the same way ``RUNTIME_TRACE_DIR``-style overrides work
    elsewhere in ``app/`` -- absent, falls back to the ratified default."""
    override = os.getenv("DECLINED_LEDGER_PATH")
    if override:
        return Path(override).expanduser()
    return DEFAULT_DECLINED_LEDGER_PATH


def default_declined_ledger() -> DeclinedLedger:
    """Construct the ledger at its default (env-overridable) path. This is
    the factory ``app.expansion.connect.ConnectPassConfig`` should use in
    place of the permanent no-op default now that a real store exists."""
    return DeclinedLedger(default_path_from_env())


__all__ = [
    "DECLINED_LEDGER_WRITE_ACTION",
    "DEFAULT_DECLINED_LEDGER_PATH",
    "DeclineReceipt",
    "DeclinedLedger",
    "default_declined_ledger",
    "default_path_from_env",
]
