from __future__ import annotations

import errno
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from uuid import uuid4

import yaml

from app.config.paths import VaultRootMisconfiguredError, resolve_optional_vault_root
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.write_ops import (
    KNOWLEDGE_WRITE_ACTION,
    _RelativeStage,
    _atomic_rename_noreplace_at,
    _read_stable_descriptor,
    _require_live_relative_directory_chain,
    _same_file_identity,
    write_note_relative,
)
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


def _publish_append_note(
    *,
    stage: _RelativeStage,
    slug: str,
) -> Path:
    """Publish one MCP append at the first atomically available suffix."""

    parent_fd = stage.directory_fds[-1]
    stage_fd = stage.stage_fd
    stage_name = stage.stage_name
    stage_identity = stage.stage_identity
    _require_live_relative_directory_chain(
        stage.vault_root,
        stage.directory.parts,
        stage.directory_fds,
        context="MCP append publication",
    )
    try:
        named_stage = os.stat(stage_name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise KnowledgeWriteConflict("MCP append stage identity changed") from exc
    if (
        not stat.S_ISREG(named_stage.st_mode)
        or named_stage.st_nlink != 1
        or not stat.S_ISREG(os.fstat(stage_fd).st_mode)
        or not _same_file_identity(named_stage, stage_identity)
    ):
        raise KnowledgeWriteConflict("MCP append stage identity changed")

    counter = 1
    while True:
        candidate_name = f"{slug}.md" if counter == 1 else f"{slug}-{counter}.md"
        try:
            _atomic_rename_noreplace_at(
                parent_fd,
                stage_name,
                parent_fd,
                candidate_name,
            )
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            try:
                current_stage = os.stat(
                    stage_name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except OSError as stat_exc:
                raise KnowledgeWriteConflict(
                    "MCP append stage changed during allocation"
                ) from stat_exc
            if not _same_file_identity(current_stage, stage_identity):
                raise KnowledgeWriteConflict("MCP append stage changed during allocation")
            counter += 1
            continue
        break

    os.fsync(parent_fd)
    published = os.stat(candidate_name, dir_fd=parent_fd, follow_symlinks=False)
    published_payload, published_identity = _read_stable_descriptor(stage_fd)
    if (
        not stat.S_ISREG(published.st_mode)
        or published.st_nlink != 1
        or not _same_file_identity(published, stage_identity)
        or not _same_file_identity(published_identity, stage_identity)
        or published_payload != stage.payload
    ):
        raise KnowledgeWriteConflict("MCP append publication identity changed")
    _require_live_relative_directory_chain(
        stage.vault_root,
        stage.directory.parts,
        stage.directory_fds,
        context="MCP append publication",
    )
    canonical_target = os.stat(
        candidate_name,
        dir_fd=parent_fd,
        follow_symlinks=False,
    )
    if (
        not stat.S_ISREG(canonical_target.st_mode)
        or canonical_target.st_nlink != 1
        or not _same_file_identity(canonical_target, stage_identity)
    ):
        raise KnowledgeWriteConflict("MCP append canonical target changed")
    _require_live_relative_directory_chain(
        stage.vault_root,
        stage.directory.parts,
        stage.directory_fds,
        context="MCP append acknowledgement",
    )
    relative_path = (stage.directory / candidate_name).as_posix()
    return stage.vault_root / relative_path


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
    directory = PurePosixPath(relative_dir)
    if (
        directory.is_absolute()
        or directory.as_posix() != relative_dir
        or not directory.parts
        or any(part in {"", ".", ".."} for part in directory.parts)
    ):
        raise VaultToolError("relative_dir must be a normalized vault-relative path")
    stage_name = f".mcp-append-stage-{uuid4().hex}.md"
    published_path: Path | None = None

    def publish(stage: _RelativeStage) -> None:
        nonlocal published_path
        published_path = _publish_append_note(stage=stage, slug=slug)

    write_note_relative(
        (directory / stage_name).as_posix(),
        content,
        vault_root=root,
        _stage_publisher=publish,
    )
    if published_path is None:
        raise KnowledgeWriteConflict("MCP append did not publish a canonical note")
    return published_path


__all__ = ["VaultToolError", "append_note", "get_vault_root"]
