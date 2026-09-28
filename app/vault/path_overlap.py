"""Filesystem-aware overlap checks for mutually exclusive vault path zones."""

from __future__ import annotations

import array
import os
import re
import sys
import unicodedata
from collections.abc import Sequence
from pathlib import Path, PurePath, PurePosixPath

import regex

from app.path_utils import normalize_note_path
from app.vault.paths import get_vault_capture_note_rel

_DEFAULT_IGNORABLE_RE = regex.compile(r"\p{Default_Ignorable_Code_Point}+")


class VaultPathOverlapError(ValueError):
    """A vault path cannot be proven disjoint from the protected capture note."""


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
        return _probe_case_insensitive_directory(candidate), None, None

    if sys.platform == "darwin":
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
    for candidate_part, parent_part in zip(candidate_parts[1:], parent_parts[1:]):
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


def _path_is_proven_within(candidate: Path, parent: Path) -> bool:
    """Return containment only for equal components or existing same-file aliases."""

    candidate_parts = candidate.parts
    parent_parts = parent.parts
    if len(candidate_parts) < len(parent_parts):
        return False

    candidate_prefix = Path(candidate_parts[0])
    parent_prefix = Path(parent_parts[0])
    if candidate_prefix != parent_prefix:
        try:
            if not os.path.samefile(candidate_prefix, parent_prefix):
                return False
        except OSError:
            return False

    for candidate_part, parent_part in zip(candidate_parts[1:], parent_parts[1:]):
        candidate_prefix /= candidate_part
        parent_prefix /= parent_part
        if candidate_prefix == parent_prefix:
            continue
        try:
            if not os.path.samefile(candidate_prefix, parent_prefix):
                return False
        except OSError:
            return False
    return True


def _absolute_path(value: str | PurePath, *, vault_root: Path) -> Path:
    normalized = normalize_note_path(value)
    path = Path(normalized)
    if not path.is_absolute():
        path = vault_root / path
    return path.resolve(strict=False)


def vault_paths_overlap(
    left: str | PurePath,
    right: str | PurePath,
    *,
    vault_root: Path,
) -> bool:
    """Return whether two vault paths alias or one contains the other."""
    root = vault_root.expanduser().resolve(strict=False)
    left_path = _absolute_path(left, vault_root=root)
    right_path = _absolute_path(right, vault_root=root)
    return _path_is_within(left_path, right_path) or _path_is_within(
        right_path, left_path
    )


def vault_path_is_within(
    candidate: str | PurePath,
    parent: str | PurePath,
    *,
    vault_root: Path,
) -> bool:
    """Return whether a resolved vault path is equal to or beneath another."""
    root = vault_root.expanduser().resolve(strict=False)
    return _path_is_within(
        _absolute_path(candidate, vault_root=root),
        _absolute_path(parent, vault_root=root),
    )


def assert_targets_do_not_overlap_capture_note(
    targets: Sequence[str | PurePath],
    *,
    vault_root: Path,
) -> None:
    """Fail closed unless every actual output is disjoint from the effective inbox note."""
    try:
        capture_note_rel = _validate_capture_note_rel(
            get_vault_capture_note_rel(vault_root)
        )
        selected_root = vault_root.expanduser().resolve(strict=False)
        resolved_capture_note = _absolute_path(
            capture_note_rel,
            vault_root=selected_root,
        )
        # This is an authority check: unlike overlap refusals, a possible
        # case/Unicode alias is not evidence that the path belongs to the vault.
        if not _path_is_proven_within(resolved_capture_note, selected_root):
            raise ValueError("capture note path resolves outside the selected vault")
    except Exception as exc:  # noqa: BLE001 - unresolved authority must fail closed
        raise VaultPathOverlapError(
            f"effective capture note could not be resolved: {exc}"
        ) from exc

    for target in targets:
        try:
            overlaps = vault_paths_overlap(
                target,
                capture_note_rel,
                vault_root=vault_root,
            )
        except Exception as exc:  # noqa: BLE001 - malformed paths must fail closed
            raise VaultPathOverlapError(
                f"unable to prove target {target!r} is disjoint from the capture note: {exc}"
            ) from exc
        if overlaps:
            raise VaultPathOverlapError(
                f"target {target!r} overlaps effective capture note {capture_note_rel!r}"
            )


def _validate_capture_note_rel(value: str) -> str:
    normalized = normalize_note_path(value)
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or path.is_absolute()
        or path.as_posix() != normalized
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("capture note path must be a normalized vault-relative path")
    return normalized


__all__ = [
    "VaultPathOverlapError",
    "assert_targets_do_not_overlap_capture_note",
    "vault_path_is_within",
    "vault_paths_overlap",
]
