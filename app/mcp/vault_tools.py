from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import os
import re
import stat
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import yaml

from app.config.paths import VaultRootMisconfiguredError, resolve_optional_vault_root
from app.knowledge.write_ops import KNOWLEDGE_WRITE_ACTION, write_note_relative
from app.write_guard import DEFAULT_WRITE_GUARD


class VaultToolError(Exception):
    """Raised when vault-backed MCP actions cannot proceed."""


def _as_path(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return None


def _resolve_mcp_env_root() -> Path | None:
    for env_var in ("MCP_VAULT_ROOT", "VAULT_DIR"):
        env_root = os.getenv(env_var)
        if not env_root or not env_root.strip():
            continue
        path = Path(env_root).expanduser()
        if not path.exists():
            raise VaultRootMisconfiguredError(env_var, path)
        return path.resolve()
    return None


def get_vault_root(settings: Mapping[str, Any] | None = None) -> Path:
    """Return the configured vault root directory."""

    candidates: list[Any] = []
    if settings:
        for key in ("vault_root", "root", "path"):
            if key in settings:
                candidates.append(settings[key])
        vault_settings = settings.get("vault")
        if isinstance(vault_settings, Mapping):
            for key in ("root", "path"):
                if key in vault_settings:
                    candidates.append(vault_settings[key])
    for candidate in candidates:
        path = _as_path(candidate)
        if path:
            return path
    try:
        env_root = _resolve_mcp_env_root()
        if env_root is not None:
            return env_root
        resolved = resolve_optional_vault_root()
    except VaultRootMisconfiguredError as exc:
        raise VaultToolError(str(exc)) from exc
    if resolved is not None:
        return resolved
    raise VaultToolError(
        "vault root is required; pass vault_root/settings or configure MCP_VAULT_ROOT, VAULT_DIR, or VAULT_ROOT"
    )


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "note"


def _next_available_path(directory: Path, slug: str) -> Path:
    candidate = directory / f"{slug}.md"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{slug}-{counter}.md"
        counter += 1
    return candidate


@contextmanager
def _append_allocation_lock(vault_root: Path) -> Iterator[None]:
    """Serialize MCP append path allocation without changing append semantics."""

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    root_fd = os.open(vault_root, directory_flags)
    lock_fd: int | None = None
    try:
        opened_root = os.fstat(root_fd)
        named_root = os.stat(vault_root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened_root.st_mode)
            or not stat.S_ISDIR(named_root.st_mode)
            or (opened_root.st_dev, opened_root.st_ino)
            != (named_root.st_dev, named_root.st_ino)
        ):
            raise VaultToolError("vault root changed while preparing MCP append")
        lock_name = ".mcp-append-note.lock"
        lock_flags = (
            os.O_RDWR
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        for _attempt in range(9):
            try:
                lock_fd = os.open(
                    lock_name,
                    lock_flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=root_fd,
                )
            except FileExistsError:
                try:
                    lock_fd = os.open(lock_name, lock_flags, dir_fd=root_fd)
                except FileNotFoundError:
                    continue
            except OSError as exc:
                if exc.errno == errno.ENOENT:
                    continue
                raise
            break
        else:
            raise VaultToolError("MCP append lock identity did not converge")
        assert lock_fd is not None
        opened_lock = os.fstat(lock_fd)
        named_lock = os.stat(lock_name, dir_fd=root_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened_lock.st_mode)
            or opened_lock.st_nlink != 1
            or not stat.S_ISREG(named_lock.st_mode)
            or named_lock.st_nlink != 1
            or (opened_lock.st_dev, opened_lock.st_ino)
            != (named_lock.st_dev, named_lock.st_ino)
        ):
            raise VaultToolError("MCP append lock is not one stable regular file")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        named_after_lock = os.stat(lock_name, dir_fd=root_fd, follow_symlinks=False)
        if (named_after_lock.st_dev, named_after_lock.st_ino) != (
            opened_lock.st_dev,
            opened_lock.st_ino,
        ):
            raise VaultToolError("MCP append lock changed while acquiring authority")
        yield
    except OSError as exc:
        raise VaultToolError(f"could not establish MCP append authority: {exc}") from exc
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        os.close(root_fd)


def append_note(
    *,
    title: str,
    body: str,
    tags: Sequence[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    vault_root: Path | str | None = None,
    settings: Mapping[str, Any] | None = None,
    relative_dir: str = "_mcp",
) -> Path:
    """Create a markdown note with frontmatter inside the vault."""

    if not isinstance(title, str) or not title.strip():
        raise VaultToolError("title is required")
    if not isinstance(body, str) or not body.strip():
        raise VaultToolError("body is required")
    root = _as_path(vault_root) if vault_root else get_vault_root(settings)
    if root is None:
        raise VaultToolError("vault root is required")
    root = root.expanduser().resolve()
    slug = _slugify(title)
    note_tags = [tag for tag in (tags or []) if isinstance(tag, str) and tag.strip()]
    frontmatter: dict[str, Any] = {"title": title.strip()}
    if note_tags:
        frontmatter["tags"] = note_tags
    if metadata:
        frontmatter["metadata"] = metadata
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    body_block = body.rstrip()
    content = f"---\n{yaml_block}\n---\n\n{body_block}\n"
    DEFAULT_WRITE_GUARD.assert_writes_allowed(KNOWLEDGE_WRITE_ACTION)
    with _append_allocation_lock(root):
        target_dir = root / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        note_path = _next_available_path(target_dir, slug)
        write_note_relative(note_path.relative_to(root).as_posix(), content, vault_root=root)
    return note_path


__all__ = ["VaultToolError", "append_note", "get_vault_root"]
