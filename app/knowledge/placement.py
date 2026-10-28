"""Bounded HKA placement owner, composed directly and never installed implicitly.

The private, fsynced placement intent is recovery evidence for this effect, not
an artifact registry. Human identity and provenance remain in unchanged source
bytes. See AUTOOPS-05's supported-filesystem and transition matrix.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import time
from typing import Any, Callable, Iterator, TypedDict, cast
from uuid import uuid4

from app.governance.governed_write import (
    DecisionToken,
    GovernedWriteAdapter,
    GovernedWriteGrant,
    InvalidDecisionTokenError,
)
from app.instance.channel_transfer import require_source_root_ingress
from app.instance.context_bound_read import ContextBoundReadError
from app.instance.context_bound_write import context_bound_write_window
from app.instance.errors import RegistryError
from app.instance.vault_registry import VaultRegistryStore
from app.knowledge import make_note_locator
from app.knowledge.write_ops import (
    _atomic_rename_noreplace_at,
    _read_stable_descriptor,
)
from app.knowledge.contracts import WriteReceipt
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeWriteConflict
from app.knowledge.multiwriter import NoteClass, WriteOperation, classify_note_in_vault
from app.services.artifact_identity import resolve_note_artifact_identity
from app.vault.manager import nearest_enclosing_vault_root
from app.vault.active_context_v1 import ActiveContextError, ActiveContextSetV1
from app.vault.path_overlap import (
    VaultPathOverlapError,
    assert_targets_do_not_overlap_capture_note,
    vault_path_is_within,
    vault_paths_overlap,
)
from app.vault.paths import (
    get_vault_sources_dir_rel,
    get_vault_system_dir_rel,
)
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError
from scripts.yaml_roundtrip import load_frontmatter

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_STATE = ".pkm-placement"
_PHASES = {"reserved", "prepared", "publishing", "activated", "retiring", "committed"}
_COMMITTED = {"activated", "retiring", "committed"}


class _GrantBinding(TypedDict):
    action: str
    write_class: str
    actor: str
    resource: str


@dataclass(frozen=True)
class PlacementIntent:
    request_id: str
    operation: str
    artifact_id: str
    source: str
    destination: str
    expected_source_generation: str
    expected_destination_generation: str
    context_ref: str
    vault_generation: str


@dataclass(frozen=True)
class PlacementResult:
    status: str
    record: dict[str, Any] | None = None
    reason: str | None = None

    @property
    def source_committed(self) -> bool:
        return self.record is not None and self.record.get("phase") in _COMMITTED


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _inode(value: os.stat_result) -> list[int]:
    return [value.st_dev, value.st_ino]


def _snapshot(fd: int) -> tuple[bytes, dict[str, Any]]:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise KnowledgeCapabilityError("placement requires a regular human note")
    raw, info = _read_stable_descriptor(fd)
    return raw, {
        "inode": _inode(info),
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "sha256": sha256(raw).hexdigest(),
    }


def _entry(parent: int, name: str) -> dict[str, Any] | None:
    try:
        fd = os.open(name, _READ, dir_fd=parent)
    except FileNotFoundError:
        return None
    try:
        return _snapshot(fd)[1]
    finally:
        os.close(fd)


def _private_directory(parent: int, name: str) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
    except FileExistsError:
        pass
    fd = os.open(name, _DIRECTORY, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise KnowledgeCapabilityError(
                "placement recovery directory must be private and owner-controlled"
            )
        # An existing name may come from an interrupted mkdir whose parent
        # synchronization failed. Presence is not a durability receipt.
        os.fsync(parent)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _canonical_leaf(parent: int, name: str) -> None:
    if name in os.listdir(parent):
        return
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise KnowledgeCapabilityError("placement cannot address a filesystem name through an alias")


def _canonical_directory(root: int, path: PurePosixPath) -> int:
    """Require the actual directory-entry spelling as well as no-follow opens."""
    current = os.dup(root)
    try:
        for part in path.parts:
            if part not in os.listdir(current):
                raise KnowledgeCapabilityError("placement parent is unavailable or aliased")
            following = os.open(part, _DIRECTORY, dir_fd=current)
            os.close(current)
            current = following
        return current
    except Exception:
        os.close(current)
        raise


class KnowledgePlacementOwner:
    """One trusted, immutable selected-vault binding for normal Markdown notes.

    ``context_is_current`` is the WSP binding check supplied by the server. An
    absent filesystem qualification refuses before source effects. No HTTP,
    MCP, GUI or singleton constructs this owner in AUTOOPS-05.
    """

    def __init__(
        self,
        *,
        vault_root: Path,
        context_ref: str,
        vault_generation: str,
        actor: str,
        active_context: ActiveContextSetV1,
        target_binding_id: str,
        registry_store: VaultRegistryStore,
        context_is_current: Callable[[], bool],
        authority_is_current: Callable[[PlacementIntent], bool],
        filesystem: str | None = None,
        write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    ) -> None:
        self.root = Path(os.path.abspath(vault_root))
        if self.root.resolve() != self.root:
            raise KnowledgeCapabilityError("placement root must be canonical and unaliased")
        self.root_identity = _inode(self.root.stat())
        self.context_ref = context_ref
        self.vault_generation = vault_generation
        self.actor = actor
        self.active_context = active_context
        self.target_binding_id = target_binding_id
        self.registry_store = registry_store
        self.context_is_current = context_is_current
        self.authority_is_current = authority_is_current
        self.filesystem = filesystem
        self.write_guard = write_guard

    def _context(self) -> None:
        if (
            not isinstance(self.active_context, ActiveContextSetV1)
            or not isinstance(self.registry_store, VaultRegistryStore)
            or self.active_context.context_id != self.context_ref
            or str(self.active_context.generation) != self.vault_generation
            or self.active_context.principal_context.principal_id != self.actor
            or self.target_binding_id not in self.active_context.binding_ids
        ):
            raise WritesBlockedError(
                "rejected",
                "placement requires the complete server-bound context and selected target",
                "placement",
            )
        configured_registry = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
        if (
            not configured_registry
            or Path(configured_registry).resolve() != self.registry_store.path.resolve()
        ):
            raise WritesBlockedError(
                "rejected", "placement registry differs from the bound instance", "placement"
            )
        if (
            not all((self.actor, self.context_ref, self.vault_generation))
            or not self.context_is_current()
        ):
            raise WritesBlockedError(
                "unavailable",
                "placement selected-vault context is unavailable or stale",
                "placement",
            )
        if self.root.resolve() != self.root or _inode(self.root.stat()) != self.root_identity:
            raise KnowledgeWriteConflict("placement root identity changed")
        try:
            require_source_root_ingress(self.root, allow_admitted_effect=True)
            snapshot = self.registry_store.read_existing()
            selected = snapshot.registrations.get(self.target_binding_id)
            if (
                snapshot.app_install_id != self.active_context.instance_identity
                or selected is None
                or Path(selected.path).resolve() != self.root
            ):
                raise WritesBlockedError(
                    "rejected", "placement root is not the server-selected binding", "placement"
                )
        except RegistryError as exc:
            raise WritesBlockedError(
                "rejected", "placement source ingress is unavailable", "placement"
            ) from exc
        self._unexpired()

    def _unexpired(self) -> None:
        # Match GOV's bound-context rule at HKA's additional waits/effect seams.
        # Holding a lease never extends the immutable snapshot's lifetime.
        if (
            self.active_context.expires_at is not None
            and self.active_context.expires_at <= time.time()
        ):
            raise InvalidDecisionTokenError("active context expired at the placement seam")

    @contextmanager
    def _effect_window(self, intent: PlacementIntent) -> Iterator[GovernedWriteGrant]:
        """Reuse MVR/GOV ownership, principal and binding leases; never mint selection."""
        self._authority(intent)
        gov = GovernedWriteAdapter()
        grant = gov.issue_decision_token(
            write_guard=self.write_guard, **self._grant_binding(intent)
        )
        grant = gov.bind_context(
            grant, context=self.active_context, target_binding_id=self.target_binding_id
        )
        with context_bound_write_window(
            self.active_context,
            target_binding_id=self.target_binding_id,
            token=grant.decision_token,
            registry_store=self.registry_store,
            **self._grant_binding(intent),
        ) as root:
            if root != self.root:
                raise InvalidDecisionTokenError("placement root differs from the selected binding")
            yield grant

    def _token(self, record: dict[str, Any]) -> DecisionToken:
        raw = dict(record["grant"]["decision_token"])
        if raw.get("target_binding_id") != self.target_binding_id or _digest(
            raw.get("active_context")
        ) != _digest(asdict(self.active_context)):
            raise InvalidDecisionTokenError(
                "placement recovery context differs from the original token"
            )
        # Reuse the trusted typed snapshot only after exact comparison with its
        # persisted representation; JSON data never creates context authority.
        raw["active_context"] = self.active_context
        token = DecisionToken(**raw)
        GovernedWriteAdapter().validate_context(
            token, context=self.active_context, target_binding_id=self.target_binding_id
        )
        self._unexpired()
        return token

    def _path(self, value: str) -> PurePosixPath:
        path = PurePosixPath(value)
        if (
            not value
            or value != value.strip()
            or path.is_absolute()
            or path.as_posix() != value
            or any(part in {".", ".."} or part.startswith(".") for part in path.parts)
            or "\\" in value
            or ":" in value
            or "\x00" in value
            or path.suffix.lower() != ".md"
            or path.parts[0].casefold()
            in {"settings", "events", "event-log", "_heimdal", "_conflicts", "_system"}
        ):
            raise KnowledgeCapabilityError(
                "placement requires a canonical vault-relative human-note path"
            )
        if vault_path_is_within(value, get_vault_system_dir_rel(self.root), vault_root=self.root):
            raise KnowledgeCapabilityError(
                "placement cannot borrow system authority through a filesystem alias"
            )
        try:
            assert_targets_do_not_overlap_capture_note([value], vault_root=self.root)
        except VaultPathOverlapError as exc:
            raise KnowledgeCapabilityError(
                "placement cannot borrow capture-append authority through a filesystem alias"
            ) from exc
        absolute = self.root.joinpath(*path.parts)
        if nearest_enclosing_vault_root(absolute, search_root=self.root) != self.root:
            raise KnowledgeCapabilityError("placement cannot cross a nested-vault boundary")
        if (
            classify_note_in_vault(
                value,
                WriteOperation.WRITE,
                vault_root=self.root,
                sources_root_rel=get_vault_sources_dir_rel(self.root),
            )
            is not NoteClass.REWRITTEN
        ):
            raise KnowledgeCapabilityError(
                "placement cannot change a retained or append-only artifact class"
            )
        return path

    def source_generation(self, source: str, artifact_id: str) -> str:
        self._context()
        path = self._path(source)
        root = os.open(self.root, _DIRECTORY)
        parent = -1
        try:
            parent = _canonical_directory(root, path.parent)
            _canonical_leaf(parent, path.name)
            fd = os.open(path.name, _READ, dir_fd=parent)
            try:
                if os.fstat(fd).st_nlink != 1:
                    raise KnowledgeCapabilityError(
                        "an unreserved source must have exactly one link"
                    )
                raw, snapshot = _snapshot(fd)
                self._identity(source, artifact_id, raw)
                return _digest(snapshot)
            finally:
                os.close(fd)
        finally:
            if parent >= 0:
                os.close(parent)
            os.close(root)

    def destination_generation(self, destination: str) -> str:
        self._context()
        path = self._path(destination)
        root = os.open(self.root, _DIRECTORY)
        parent = -1
        try:
            parent = _canonical_directory(root, path.parent)
            return self._absent_generation(parent, path)
        finally:
            if parent >= 0:
                os.close(parent)
            os.close(root)

    def _absent_generation(self, parent: int, path: PurePosixPath) -> str:
        try:
            os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return _digest(
                {
                    "root": self.root_identity,
                    "path": str(path),
                    "parent": _inode(os.fstat(parent)),
                    "entry": "absent",
                }
            )
        raise KnowledgeWriteConflict("placement destination already exists")

    def _identity(self, source: str, artifact_id: str, raw: bytes) -> None:
        frontmatter, _ = load_frontmatter(raw.decode("utf-8"))
        if isinstance(frontmatter, dict) and any(
            frontmatter.get(key) == "chat-session" for key in ("type", "kind")
        ):
            raise KnowledgeCapabilityError(
                "Canvas session placement remains with its existing authority owner"
            )
        identity = resolve_note_artifact_identity(
            artifact_path=self.root / source,
            vault_root=self.root,
            safe_note_path=source,
            body=raw.decode("utf-8"),
            heal_missing_uuid=False,
        )
        if (
            not identity.owns_identity
            or identity.artifact_kind != "human_note"
            or identity.artifact_id != artifact_id
        ):
            raise KnowledgeWriteConflict(
                "placement source identity does not match the bound artifact"
            )

    @contextmanager
    def _locked(self) -> Iterator[tuple[int, int]]:
        self._context()
        root = os.open(self.root, _DIRECTORY)
        state = lock = -1
        try:
            state = _private_directory(root, _STATE)
            if os.fstat(state).st_dev != os.fstat(root).st_dev:
                raise KnowledgeCapabilityError("placement recovery must share the vault filesystem")
            lock = os.open("lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=state)
            info = os.fstat(lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise KnowledgeCapabilityError("placement lock is not a private regular file")
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._live(root, state)
            yield root, state
        finally:
            if lock >= 0:
                os.close(lock)
            if state >= 0:
                os.close(state)
            os.close(root)

    def _live(self, root: int, state: int) -> None:
        self._context()
        if _inode(os.fstat(root)) != self.root_identity or _inode(
            os.stat(_STATE, dir_fd=root, follow_symlinks=False)
        ) != _inode(os.fstat(state)):
            raise KnowledgeWriteConflict("placement recovery namespace changed")
        self._unexpired()

    def _load(self, state: int, name: str) -> dict[str, Any] | None:
        try:
            fd = os.open(name, _READ, dir_fd=state)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise KnowledgeWriteConflict("placement evidence is not a private regular record")
            value = json.load(handle)
        if (
            not isinstance(value, dict)
            or value.get("schema") != "hka.placement.v1"
            or value.get("phase") not in _PHASES
            or not isinstance(value.get("intent"), dict)
            or value.get("intent_digest") != _digest(value["intent"])
        ):
            raise KnowledgeWriteConflict(
                "placement evidence is malformed; reconciliation is required"
            )
        try:
            intent = PlacementIntent(**value["intent"])
            snapshot = value["snapshot"]
            if (
                not all(isinstance(item, str) and item for item in asdict(intent).values())
                or set(snapshot) != {"inode", "size", "mtime_ns", "mode", "uid", "gid", "sha256"}
                or not isinstance(snapshot["inode"], list)
                or len(snapshot["inode"]) != 2
                or not all(type(item) is int for item in snapshot["inode"])
                or not all(
                    type(snapshot[key]) is int for key in ("size", "mtime_ns", "mode", "uid", "gid")
                )
                or intent.expected_source_generation != _digest(snapshot)
                or type(value["cleanup_complete"]) is not bool
                or not isinstance(value["binding"], dict)
                or not isinstance(value["parents"], list)
                or len(value["parents"]) != 2
                or any(
                    not isinstance(parent, list)
                    or len(parent) != 2
                    or not all(type(item) is int for item in parent)
                    for parent in value["parents"]
                )
            ):
                raise ValueError("invalid placement evidence shape")
            DecisionToken(**value["grant"]["decision_token"])
            if value["phase"] == "committed" and not value["receipt"]["receipt_id"]:
                raise ValueError("committed placement has no receipt")
        except (KeyError, TypeError, ValueError) as exc:
            raise KnowledgeWriteConflict(
                "placement evidence is incomplete; reconciliation is required"
            ) from exc
        return value

    def _store(self, root: int, state: int, name: str, value: dict[str, Any]) -> None:
        self._live(root, state)
        temporary = f".record-{uuid4().hex}"
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=state
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=state, dst_dir_fd=state)
        os.fsync(state)

    def _qualify(self, state: int) -> None:
        if self.filesystem != "local-posix-v1" or not (
            sys.platform == "darwin" or sys.platform.startswith("linux")
        ):
            raise KnowledgeCapabilityError(
                "placement requires an explicitly qualified local POSIX filesystem"
            )
        # Test the actual mounted filesystem before touching a source name.
        prefix = f".probe-{uuid4().hex}"
        names = [prefix + suffix for suffix in ("a", "b", "c")]
        try:
            for name in names[:2]:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=state)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            try:
                _atomic_rename_noreplace_at(state, names[0], state, names[1])
            except FileExistsError:
                pass
            else:
                raise KnowledgeCapabilityError("filesystem did not enforce no-replace rename")
            _atomic_rename_noreplace_at(state, names[0], state, names[2])
            os.link(names[2], names[0], src_dir_fd=state, dst_dir_fd=state, follow_symlinks=False)
            os.fsync(state)
        finally:
            for name in names:
                try:
                    os.unlink(name, dir_fd=state)
                except FileNotFoundError:
                    pass
            os.fsync(state)

    def place_artifact(self, intent: PlacementIntent, *, recover: bool = False) -> PlacementResult:
        """Execute once, read an existing result, or explicitly reconcile one intent.

        Ordinary replay never re-enters an uncertain source effect. ``recover``
        resumes only transitions proved safe by the saved inode/generation and
        the current namespace; it requires the same current server authority.
        """
        record: dict[str, Any] | None = None
        try:
            self._context()
            if (
                intent.operation not in {"artifact.move", "artifact.rename"}
                or not intent.request_id
                or not intent.artifact_id
            ):
                return PlacementResult(
                    "invalid", reason="placement operation, request and identity are required"
                )
            if (intent.context_ref, intent.vault_generation) != (
                self.context_ref,
                self.vault_generation,
            ):
                return PlacementResult(
                    "rejected", reason="placement context differs from the selected vault"
                )
            source, destination = self._path(intent.source), self._path(intent.destination)
            if source == destination:
                return PlacementResult(
                    "invalid", reason="placement requires a different destination"
                )
            if intent.operation == "artifact.rename" and source.parent != destination.parent:
                return PlacementResult(
                    "invalid", reason="rename must preserve its parent directory"
                )
            with self._effect_window(intent) as grant, self._locked() as (root, state):
                self._authority(intent)
                name = sha256(intent.request_id.encode()).hexdigest() + ".json"
                record = self._load(state, name)
                if record is not None:
                    if (
                        record["intent_digest"] != _digest(asdict(intent))
                        or record["binding"] != self._binding()
                    ):
                        return PlacementResult(
                            "conflicted",
                            reason="placement request is already bound to another intent or authority",
                        )
                    if not recover:
                        return self._result(record)
                else:
                    if recover:
                        return PlacementResult(
                            "not_found", reason="placement has no durable recovery intent"
                        )
                    for other_name in os.listdir(state):
                        if not other_name.endswith(".json"):
                            continue
                        other = self._load(state, other_name)
                        if other is not None and other["phase"] != "committed":
                            prior = other["intent"]
                            if prior["artifact_id"] == intent.artifact_id or any(
                                vault_paths_overlap(old, current, vault_root=self.root)
                                for old in (prior["source"], prior["destination"])
                                for current in (intent.source, intent.destination)
                            ):
                                return PlacementResult(
                                    "conflicted",
                                    reason="placement artifact or destination has an outstanding reservation",
                                )
                    self._qualify(state)
                    with self._parents(root, source, destination) as (src, dst):
                        snapshot = _entry(src, source.name)
                        if snapshot is None:
                            return PlacementResult(
                                "not_found", reason="placement source is unavailable"
                            )
                        if _digest(snapshot) != intent.expected_source_generation:
                            return PlacementResult(
                                "conflicted", reason="expected source generation is stale"
                            )
                        if (
                            self._absent_generation(dst, destination)
                            != intent.expected_destination_generation
                        ):
                            return PlacementResult(
                                "conflicted", reason="expected destination generation is stale"
                            )
                        fd = os.open(source.name, _READ, dir_fd=src)
                        try:
                            if os.fstat(fd).st_nlink != 1:
                                raise KnowledgeCapabilityError(
                                    "an unreserved source must have exactly one link"
                                )
                            raw, checked = _snapshot(fd)
                            if checked != snapshot:
                                raise KnowledgeWriteConflict(
                                    "source changed during placement preflight"
                                )
                            self._identity(intent.source, intent.artifact_id, raw)
                        finally:
                            os.close(fd)
                        record = {
                            "schema": "hka.placement.v1",
                            "intent": asdict(intent),
                            "intent_digest": _digest(asdict(intent)),
                            "binding": self._binding(),
                            "phase": "reserved",
                            "snapshot": snapshot,
                            "parents": [_inode(os.fstat(src)), _inode(os.fstat(dst))],
                            "grant": asdict(grant),
                            "receipt": None,
                            "cleanup_complete": False,
                        }
                        self._store(root, state, name, record)
                self._qualify(state)
                with self._parents(root, source, destination) as (src, dst):
                    transaction = _private_directory(state, name.removesuffix(".json"))
                    try:
                        self._advance(root, state, transaction, src, dst, name, record, intent)
                    finally:
                        os.close(transaction)
                return self._result(record)
        except WritesBlockedError as exc:
            return PlacementResult("recovery_required" if record else "rejected", record, str(exc))
        except (
            InvalidDecisionTokenError,
            ContextBoundReadError,
            RegistryError,
            ActiveContextError,
        ) as exc:
            return PlacementResult("recovery_required" if record else "rejected", record, str(exc))
        except KnowledgeCapabilityError as exc:
            return PlacementResult(
                "recovery_required" if record else "not_supported", record, str(exc)
            )
        except KnowledgeWriteConflict as exc:
            return PlacementResult(
                "recovery_required" if record else "conflicted", record, str(exc)
            )
        except Exception as exc:
            # A failed fsync or receipt write can follow a namespace effect. Do
            # not infer a terminal result from the in-memory phase in this case.
            return PlacementResult(
                "recovery_required",
                record,
                f"placement outcome requires durable evidence reconciliation ({type(exc).__name__})",
            )

    def _binding(self) -> dict[str, Any]:
        return {
            "root": self.root_identity,
            "context_ref": self.context_ref,
            "vault_generation": self.vault_generation,
            "actor": self.actor,
            "target_binding_id": self.target_binding_id,
            "active_context_digest": _digest(asdict(self.active_context)),
        }

    def _grant_binding(self, intent: PlacementIntent) -> _GrantBinding:
        return {
            "action": f"operation.{intent.operation}",
            "write_class": "vault_placement",
            "actor": self.actor,
            "resource": intent.source,
        }

    def _authority(self, intent: PlacementIntent) -> None:
        if not self.authority_is_current(intent):
            raise WritesBlockedError(
                "rejected",
                "the bound placement delegation/policy is no longer current",
                f"operation.{intent.operation}",
            )
        self.write_guard.assert_writes_allowed(f"operation.{intent.operation}")

    @contextmanager
    def _parents(
        self, root: int, source: PurePosixPath, destination: PurePosixPath
    ) -> Iterator[tuple[int, int]]:
        src = _canonical_directory(root, source.parent)
        dst = -1
        try:
            dst = _canonical_directory(root, destination.parent)
            _canonical_leaf(src, source.name)
            if not (os.fstat(src).st_dev == os.fstat(dst).st_dev == os.fstat(root).st_dev):
                raise KnowledgeCapabilityError("placement cannot cross filesystem mounts")
            yield src, dst
        finally:
            if dst >= 0:
                os.close(dst)
            os.close(src)

    def _seam(
        self,
        root: int,
        state: int,
        src: int,
        dst: int,
        record: dict[str, Any],
        intent: PlacementIntent,
    ) -> None:
        self._live(root, state)
        self._path(intent.source)
        self._path(intent.destination)
        self._authority(intent)
        GovernedWriteAdapter().validate_decision_token(
            decision_token=self._token(record),
            **self._grant_binding(intent),
        )
        with self._parents(
            root, PurePosixPath(intent.source), PurePosixPath(intent.destination)
        ) as (current_src, current_dst):
            identities = [_inode(os.fstat(current_src)), _inode(os.fstat(current_dst))]
            if identities != record["parents"] or identities != [
                _inode(os.fstat(src)),
                _inode(os.fstat(dst)),
            ]:
                raise KnowledgeWriteConflict("placement parent generation changed")
        self._unexpired()

    def _advance(
        self,
        root: int,
        state: int,
        transaction: int,
        src: int,
        dst: int,
        name: str,
        record: dict[str, Any],
        intent: PlacementIntent,
    ) -> None:
        source, destination = PurePosixPath(intent.source), PurePosixPath(intent.destination)
        expected = record["snapshot"]

        def require(parent: int, leaf: str) -> None:
            if _entry(parent, leaf) != expected:
                raise KnowledgeWriteConflict(
                    "placement inode or generation changed; retained evidence requires reconciliation"
                )

        def advance(phase: str) -> None:
            record["phase"] = phase
            self._store(root, state, name, record)

        self._seam(root, state, src, dst, record, intent)
        if record["phase"] == "reserved":
            require(src, source.name)
            if self._absent_generation(dst, destination) != intent.expected_destination_generation:
                raise KnowledgeWriteConflict("placement destination generation changed")
            if _entry(transaction, "original") is None:
                self._seam(root, state, src, dst, record, intent)
                os.link(
                    source.name,
                    "original",
                    src_dir_fd=src,
                    dst_dir_fd=transaction,
                    follow_symlinks=False,
                )
            require(transaction, "original")
            require(src, source.name)
            retained_fd = os.open("original", _READ, dir_fd=transaction)
            try:
                os.fsync(retained_fd)
            finally:
                os.close(retained_fd)
            os.fsync(transaction)
            advance("prepared")
        if record["phase"] == "prepared":
            # Persist uncertainty before entering the public namespace syscall.
            # A failed link/fsync/phase write cannot later look safely unapplied.
            self._seam(root, state, src, dst, record, intent)
            advance("publishing")
        if record["phase"] == "publishing":
            require(transaction, "original")
            require(src, source.name)
            self._seam(root, state, src, dst, record, intent)
            try:
                os.link(
                    "original",
                    destination.name,
                    src_dir_fd=transaction,
                    dst_dir_fd=dst,
                    follow_symlinks=False,
                )
            except FileExistsError:
                # Only this exact retained inode is evidence of an interrupted
                # publication. Equal content at a different inode is a conflict.
                require(dst, destination.name)
            os.fsync(dst)
            require(src, source.name)
            require(dst, destination.name)
            self._seam(root, state, src, dst, record, intent)
            advance("activated")
        if record["phase"] == "activated":
            require(dst, destination.name)
            require(src, source.name)
            advance("retiring")
        if record["phase"] == "retiring":
            require(dst, destination.name)
            if _entry(transaction, "retired") is None:
                require(src, source.name)
                self._seam(root, state, src, dst, record, intent)
                _atomic_rename_noreplace_at(src, source.name, transaction, "retired")
            # Reassert both namespace barriers on recovery, including when the
            # retained entry proves the rename happened in an earlier process.
            os.fsync(src)
            os.fsync(transaction)
            if _entry(transaction, "retired") != expected:
                # Preserve a replacement that won the source name. Restore it
                # only with no-replace semantics; a second winner stays intact.
                try:
                    self._seam(root, state, src, dst, record, intent)
                    _atomic_rename_noreplace_at(transaction, "retired", src, source.name)
                    os.fsync(src)
                    os.fsync(transaction)
                except FileExistsError:
                    pass
                raise KnowledgeWriteConflict(
                    "source replacement was retained or restored; placement is ambiguous"
                )
            if _entry(src, source.name) is not None:
                raise KnowledgeWriteConflict(
                    "source name was reused; do not remove the new artifact"
                )
            require(dst, destination.name)
            self._seam(root, state, src, dst, record, intent)
            mutation = WriteReceipt(
                intent.operation,
                make_note_locator(intent.destination, vault=self.target_binding_id),
                "knowledge.placement",
                trace_id=intent.request_id,
                writer_identity=self.actor,
            )
            authority = GovernedWriteAdapter().record_authority_receipt(
                decision_token=self._token(record),
                mutation_receipt=cast(Any, mutation),
                state_owner="knowledge",
                resource=intent.source,
                trace_id=intent.request_id,
                effect_id=intent.request_id,
            )
            record["receipt"] = {
                "receipt_id": authority.receipt_id,
                "artifact_id": intent.artifact_id,
                "source_locator": intent.source,
                "destination_locator": intent.destination,
                "source_generation": intent.expected_source_generation,
                "destination_generation": _digest(expected),
                "source_receipt": asdict(mutation),
                "governed_write": {**record["grant"], "authority_receipt": asdict(authority)},
                "projection_repair": ["locator", "store", "index", "link"],
            }
            advance("committed")
        if record["phase"] == "committed" and not record["cleanup_complete"]:
            # Only private recovery links are retired. A current destination
            # inode is required even if a later legitimate edit changed bytes.
            current = _entry(dst, destination.name)
            if current is None or current["inode"] != expected["inode"]:
                raise KnowledgeWriteConflict("destination changed before recovery-link cleanup")
            for leaf in ("original", "retired"):
                retained = _entry(transaction, leaf)
                if retained is not None:
                    if retained["inode"] != expected["inode"]:
                        raise KnowledgeWriteConflict("private recovery entry changed; preserve it")
                    self._seam(root, state, src, dst, record, intent)
                    os.unlink(leaf, dir_fd=transaction)
            os.fsync(transaction)
            record["cleanup_complete"] = True
            self._store(root, state, name, record)

    def _result(self, record: dict[str, Any]) -> PlacementResult:
        record = json.loads(json.dumps(record))
        if (
            record["phase"] == "committed"
            and record.get("receipt")
            and record.get("cleanup_complete")
        ):
            return PlacementResult(
                "convergence_pending",
                record,
                "source placement is receipted; rebuild locator/Store/index/link from the verified destination",
            )
        return PlacementResult(
            "recovery_required",
            record,
            "reconcile this durable placement intent before another source effect",
        )
