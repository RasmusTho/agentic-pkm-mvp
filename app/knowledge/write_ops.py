from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
from typing import TYPE_CHECKING, Literal
import uuid

from app.knowledge.adapters import _atomic_rename_noreplace_at
from app.knowledge.contracts import WriteReceipt
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.locators import make_note_locator, make_note_locator_from_absolute
from app.knowledge.references import build_obsidian_advanced_uri
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings
from app.knowledge.service import resolve_knowledge_port

if TYPE_CHECKING:
    from app.write_guard import WriteGuard

# Default action asserted at both knowledge write ports (#2910 for
# ``write_note_from_absolute``, extended to ``write_note_relative`` by #2953,
# formal-model.md §3 gap 1 / P-1). This is the shared root-cause seam: ~20
# production call sites reach the vault through these two ports with no
# WriteGuard at the port itself -- some already assert caller-side with their
# own distinct action string (defense-in-depth, e.g. #2808/#2809), but several
# (promotion queue, vault layout, filesystem vault adapter, alpha human flows,
# and -- for the relative-path port -- ``app/mcp/vault_tools.py``) reached the
# vault completely unguarded. Asserting here with a generic default action
# closes every one of those gaps in a single change, and is safe/idempotent
# for callers that already asserted their own action.
KNOWLEDGE_WRITE_ACTION = "knowledge.write_note"
_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_CANDIDATE_STAGE_OPEN_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
CandidateCreateResult = Literal["written", "already_exists"]


def _candidate_relative_parts(note_rel_path: str) -> tuple[str, ...]:
    if not note_rel_path or "\x00" in note_rel_path or "\\" in note_rel_path:
        raise ValueError("candidate note path must be a portable vault-relative POSIX path")
    path = PurePosixPath(note_rel_path)
    if path.is_absolute() or path.as_posix() != note_rel_path:
        raise ValueError("candidate note path must be a normalized vault-relative POSIX path")
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("candidate note path must stay inside the vault")
    return parts


def _require_regular_candidate_target(
    parent_fd: int,
    target_name: str,
) -> None:
    target_stat = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISREG(target_stat.st_mode):
        raise OSError(
            errno.EINVAL,
            "candidate target exists but is not a regular file",
            target_name,
        )


def candidate_note_exists_durable(
    note_rel_path: str,
    *,
    vault_root: Path | str,
) -> bool:
    """Durably observe a regular candidate target without mutating the vault."""

    parts = _candidate_relative_parts(note_rel_path)
    resolved_root = Path(vault_root).expanduser().resolve()
    current_dir_fd: int | None = None
    try:
        current_dir_fd = os.open(resolved_root, _DIRECTORY_OPEN_FLAGS)
        for component in parts[:-1]:
            try:
                child_fd = os.open(
                    component,
                    _DIRECTORY_OPEN_FLAGS,
                    dir_fd=current_dir_fd,
                )
            except FileNotFoundError:
                return False
            superseded_fd = current_dir_fd
            current_dir_fd = child_fd
            os.close(superseded_fd)

        try:
            _require_regular_candidate_target(current_dir_fd, parts[-1])
        except FileNotFoundError:
            return False
        os.fsync(current_dir_fd)
        return True
    finally:
        if current_dir_fd is not None:
            owned_fd = current_dir_fd
            current_dir_fd = None
            os.close(owned_fd)


def create_candidate_note_once(
    note_rel_path: str,
    content: str,
    *,
    vault_root: Path | str,
    action: str,
    write_guard: "WriteGuard | None" = None,
) -> CandidateCreateResult:
    """Create one candidate atomically, preserving any existing target.

    This is deliberately candidate-specific. It owns only invocation-local
    parent preparation and one hidden stage; it does not change generic
    ``KnowledgePort.write_note`` semantics or coordinate other writers.
    """

    from app.write_guard import DEFAULT_WRITE_GUARD

    parts = _candidate_relative_parts(note_rel_path)
    resolved_root = Path(vault_root).expanduser().resolve()
    guard = write_guard or DEFAULT_WRITE_GUARD
    guard.assert_writes_allowed(action)
    payload = content.encode("utf-8")

    current_dir_fd: int | None = None
    stage_fd: int | None = None
    stage_name: str | None = None
    stage_owned = False
    stage_unlink_attempted = False
    cleanup_error: BaseException | None = None

    def record_cleanup_error(exc: BaseException) -> None:
        nonlocal cleanup_error
        if cleanup_error is None:
            cleanup_error = exc

    try:
        current_dir_fd = os.open(resolved_root, _DIRECTORY_OPEN_FLAGS)
        for component in parts[:-1]:
            try:
                os.mkdir(component, mode=0o777, dir_fd=current_dir_fd)
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
            os.fsync(current_dir_fd)
            child_fd = os.open(
                component,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=current_dir_fd,
            )
            superseded_fd = current_dir_fd
            current_dir_fd = child_fd
            os.close(superseded_fd)

        stage_name = f".candidate-stage-{uuid.uuid4().hex}"
        stage_fd = os.open(
            stage_name,
            _CANDIDATE_STAGE_OPEN_FLAGS,
            0o600,
            dir_fd=current_dir_fd,
        )
        stage_owned = True
        offset = 0
        while offset < len(payload):
            written = os.write(stage_fd, payload[offset:])
            if written <= 0:
                raise OSError(
                    errno.EIO,
                    "candidate stage write made no progress",
                    stage_name,
                )
            offset += written
        os.fsync(stage_fd)
        owned_stage_fd = stage_fd
        stage_fd = None
        os.close(owned_stage_fd)

        try:
            _atomic_rename_noreplace_at(
                current_dir_fd,
                stage_name,
                current_dir_fd,
                parts[-1],
            )
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            stage_unlink_attempted = True
            os.unlink(stage_name, dir_fd=current_dir_fd)
            stage_owned = False
            os.fsync(current_dir_fd)
            _require_regular_candidate_target(current_dir_fd, parts[-1])
            return "already_exists"

        stage_owned = False
        os.fsync(current_dir_fd)
        return "written"
    finally:
        if stage_fd is not None:
            owned_stage_fd = stage_fd
            stage_fd = None
            try:
                os.close(owned_stage_fd)
            except BaseException as exc:  # noqa: BLE001 - preserve fail-closed cleanup
                record_cleanup_error(exc)

        if (
            stage_owned
            and not stage_unlink_attempted
            and stage_name is not None
            and current_dir_fd is not None
        ):
            stage_unlink_attempted = True
            try:
                os.unlink(stage_name, dir_fd=current_dir_fd)
            except BaseException as exc:  # noqa: BLE001 - exact owned-stage cleanup
                record_cleanup_error(exc)
            else:
                stage_owned = False
                try:
                    os.fsync(current_dir_fd)
                except BaseException as exc:  # noqa: BLE001 - cleanup durability is required
                    record_cleanup_error(exc)

        if current_dir_fd is not None:
            owned_dir_fd = current_dir_fd
            current_dir_fd = None
            try:
                os.close(owned_dir_fd)
            except BaseException as exc:  # noqa: BLE001 - every owner gets one close attempt
                record_cleanup_error(exc)

        if cleanup_error is not None:
            raise cleanup_error


def default_vault_root_for_path(path: Path | str) -> Path:
    resolved = Path(path).expanduser().resolve()
    return Path(resolved.anchor) if resolved.anchor else Path("/")


def read_note_text_with_version(path: Path | str) -> tuple[str, str]:
    """Read once, preserving text bytes while hashing the exact filesystem payload."""

    raw = Path(path).read_bytes()
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def _local_fs_settings() -> KnowledgeSettings:
    return KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.FS_VAULT,
        fallback_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        allow_fallback=False,
        strict_startup=False,
    )


def _require_canonical_write(
    receipt: WriteReceipt,
    *,
    accept_staged_conflict: bool,
) -> WriteReceipt:
    if receipt.outcome == "conflict_staged" and not accept_staged_conflict:
        artifact = receipt.conflict_artifact or "an unknown conflict artifact"
        raise KnowledgeWriteConflict(
            f"rewritten note conflict staged at {artifact}; canonical note unchanged",
            receipt=receipt,
        )
    return receipt


def write_note_from_absolute(
    path: Path | str,
    content: str,
    *,
    vault_root: Path | str,
    action: str = KNOWLEDGE_WRITE_ACTION,
    write_guard: "WriteGuard | None" = None,
    expected_version: str | None = None,
    writer_identity: str | None = None,
    accept_staged_conflict: bool = False,
) -> WriteReceipt:
    # Guard-at-seam (#2910): assert WriteGuard inside the port itself, before
    # any path resolution or filesystem mutation, so a blocked write is
    # atomic (zero bytes touched) regardless of which caller reached this
    # seam. ``action`` defaults to the generic port action but callers that
    # need the #2877 named bootstrap escape (pre-vault-selection provisioning
    # such as the yggdrasil-init scaffolder) pass their own escape action
    # string through explicitly -- the escape lives in the guard's allow-list
    # (``DEFAULT_BOOTSTRAP_ACTIONS`` in app/write_guard.py), never in an
    # unconditional skip here. A denying guard still blocks unconditionally.
    #
    # Imported lazily (not at module level): app.write_guard -> health_contract
    # -> events.outbox -> outbox.events -> events.schema -> settings.runtime ->
    # settings.compiler -> settings.writeback -> app.knowledge.write_ops closes
    # a circular import back to this module (the same cycle #2809 documented
    # for app/settings/writeback.py; this port is the shared root cause every
    # writeback caller ultimately routes through).
    from app.write_guard import DEFAULT_WRITE_GUARD

    guard = write_guard or DEFAULT_WRITE_GUARD
    guard.assert_writes_allowed(action)
    resolved_root = Path(os.path.realpath(os.path.expanduser(os.fspath(vault_root))))
    if expected_version is None:
        resolved_path = Path(os.path.realpath(os.path.expanduser(os.fspath(path))))
        resolved_path.relative_to(resolved_root)
        locator = make_note_locator_from_absolute(resolved_path, vault_root=resolved_root)
    else:
        # Preserve the caller-authorized lexical vault-relative path. Resolving
        # the leaf here would let a symlink swap between the final caller policy
        # check and this helper silently retarget a matching content token to a
        # different note. The filesystem adapter rejects an aliased
        # expected-version locator, while its descriptor/no-follow CAS protects
        # replacements after that check.
        lexical_path = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
        try:
            relative_path = lexical_path.relative_to(resolved_root)
        except ValueError:
            lexical_root = Path(os.path.abspath(os.path.expanduser(os.fspath(vault_root))))
            relative_path = lexical_path.relative_to(lexical_root)
        locator = make_note_locator(relative_path.as_posix())
    # Absolute path writes target the local filesystem boundary directly.
    port = resolve_knowledge_port(vault_root=resolved_root, settings=_local_fs_settings())
    kwargs: dict[str, str] = {}
    if expected_version is not None:
        kwargs["expected_version"] = expected_version
    if writer_identity is not None:
        kwargs["writer_identity"] = writer_identity
    receipt = port.write_note(locator, content, **kwargs)
    return _require_canonical_write(
        receipt,
        accept_staged_conflict=accept_staged_conflict,
    )


def write_note_relative(
    note_rel_path: str,
    content: str,
    *,
    vault_root: Path | str,
    action: str = KNOWLEDGE_WRITE_ACTION,
    write_guard: "WriteGuard | None" = None,
    expected_version: str | None = None,
    writer_identity: str | None = None,
    accept_staged_conflict: bool = False,
) -> WriteReceipt:
    # Guard-at-seam (#2953, extending #2910): assert WriteGuard inside this
    # port too, before any path resolution or filesystem mutation, mirroring
    # ``write_note_from_absolute`` exactly. Several production callers already
    # assert caller-side with their own distinct action string (defense-in-
    # depth, e.g. materialize_moment/materialize_promoted_memory/
    # write_candidate_note) -- double-assert is harmless and stays valid. But
    # at least one production caller (``app/mcp/vault_tools.py``) reached this
    # relative-path port completely unguarded; asserting here with a generic
    # default action closes that gap the same way #2910 closed it for the
    # absolute-path port. ``action`` defaults to the generic port action but
    # callers that need the #2877 named bootstrap escape pass their own escape
    # action string through explicitly -- the escape lives in the guard's
    # allow-list (``DEFAULT_BOOTSTRAP_ACTIONS`` in app/write_guard.py), never
    # in an unconditional skip here. A denying guard still blocks
    # unconditionally.
    #
    # Imported lazily for the same circular-import reason documented on
    # ``write_note_from_absolute`` above (app.write_guard -> health_contract
    # -> ... -> app.knowledge.write_ops).
    from app.write_guard import DEFAULT_WRITE_GUARD

    guard = write_guard or DEFAULT_WRITE_GUARD
    guard.assert_writes_allowed(action)
    resolved_root = Path(vault_root).expanduser().resolve()
    locator = make_note_locator(note_rel_path)
    port = resolve_knowledge_port(vault_root=resolved_root, settings=_local_fs_settings())
    kwargs: dict[str, str] = {}
    if expected_version is not None:
        kwargs["expected_version"] = expected_version
    if writer_identity is not None:
        kwargs["writer_identity"] = writer_identity
    receipt = port.write_note(locator, content, **kwargs)
    return _require_canonical_write(
        receipt,
        accept_staged_conflict=accept_staged_conflict,
    )


def append_note_relative(
    note_rel_path: str,
    content: str,
    *,
    vault_root: Path | str,
    action: str = KNOWLEDGE_WRITE_ACTION,
    write_guard: "WriteGuard | None" = None,
) -> WriteReceipt:
    # Guard-at-seam (#3129): append-only writes share the same production
    # boundary as relative overwrites. Assert before resolving the port so an
    # unhealthy/safe-mode runtime cannot mutate the vault through append.
    # The lazy import preserves the circular-import avoidance used by the
    # sibling write seams above.
    from app.write_guard import DEFAULT_WRITE_GUARD

    guard = write_guard or DEFAULT_WRITE_GUARD
    guard.assert_writes_allowed(action)
    resolved_root = Path(vault_root).expanduser().resolve()
    locator = make_note_locator(note_rel_path)
    port = resolve_knowledge_port(vault_root=resolved_root, settings=_local_fs_settings())
    return port.append_note(locator, content)


def advanced_uri_from_vault_path(path: Path | str, *, vault_root: Path | str) -> str:
    resolved_path = Path(path).expanduser().resolve()
    resolved_root = Path(vault_root).expanduser().resolve()
    try:
        rel = resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        rel = resolved_path.name
    return build_obsidian_advanced_uri(make_note_locator(rel))


__all__ = [
    "CandidateCreateResult",
    "KNOWLEDGE_WRITE_ACTION",
    "advanced_uri_from_vault_path",
    "append_note_relative",
    "candidate_note_exists_durable",
    "create_candidate_note_once",
    "default_vault_root_for_path",
    "read_note_text_with_version",
    "write_note_from_absolute",
    "write_note_relative",
]
