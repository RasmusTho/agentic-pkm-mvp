"""Exact, inert DEV repair mechanics for two independently classified identity cases.

The module does not select targets, allocate identities, load a controller, or dispatch a
native operation.  A separately governed host runner may pass a frozen private target set
through :func:`run_supportable_repair_batch`.  Every artifact is re-qualified from the
canonical source inventory inside the caller-owned fence immediately before its CAS.

Private proposals intentionally retain paths, identities, and original/candidate bytes so
that exact readback and rollback are possible.  Those objects have no serialization helper.
The only public result is the closed, content-free counter receipt validated below.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Protocol

import yaml

from app.briefing.compose import (
    BriefingIdentityMigration,
    migrate_briefing_identity,
    prepare_briefing_identity_migration,
)
from app.knowledge.write_ops import write_note_from_absolute
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


RECEIPT_CONTRACT = "native-source-identity-supportable-repair.v1"
ACTION = "operator.repair-supportable-source-identity"
WRITER_IDENTITY = "operator.supportable-source-identity-repair"
EXPECTED_COMPANION_COUNT = 23
EXPECTED_BRIEFING_COUNT = 26
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_RESULTS = frozenset({"committed", "failed", "indeterminate"})
_MAX_PRIVATE_FILE_BYTES = 8 * 1024 * 1024
_REASONS = frozenset({
    "authority_refused",
    "context_refused",
    "write_refused",
    "readback_indeterminate",
})


class SupportableRepairRefusal(RuntimeError):
    """Fixed refusal without private exception text."""

    def __init__(self, reason: str) -> None:
        if reason not in _REASONS:
            reason = "context_refused"
        self.reason = reason
        super().__init__(reason)


class _MissingRelative(FileNotFoundError):
    pass


@dataclass(frozen=True)
class CompanionContinuityProposal:
    """Private exact-byte proposal for one already-established companion identity."""

    source_rel: str
    companion_rel: str
    identity: str
    observed_at: str
    original_text: str
    candidate_text: str
    original_sha256: str
    candidate_sha256: str


@dataclass(frozen=True)
class BriefingRepairProposal:
    """Private wrapper around the canonical composer migration proposal."""

    for_date: date
    migration: BriefingIdentityMigration
    original_text: str
    original_sha256: str
    candidate_sha256: str


@dataclass(frozen=True)
class RepairBatch:
    """Frozen private target set bound to one revision, image, and selection."""

    revision: str
    image_digest: str
    selection_sha256: str
    target_set_sha256: str
    vault_fingerprint: str
    companion: tuple[CompanionContinuityProposal, ...]
    briefings: tuple[BriefingRepairProposal, ...]


@dataclass(frozen=True)
class RepairAuthoritySnapshot:
    """Fresh host facts read by the effects implementation inside its owned fence."""

    revision: str
    image_digest: str
    selection_sha256: str
    target_set_sha256: str
    vault_fingerprint: str
    controller_unloaded: bool
    write_guard_healthy: bool
    writers_isolated: bool
    owned_operation_fences_healthy: bool


class RepairEffects(Protocol):
    """Host-owned proof seam; implementations must read facts, not accept booleans."""

    def owned_repair_fence(self) -> AbstractContextManager[None]: ...

    def read_repair_authority(self) -> RepairAuthoritySnapshot: ...


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _vault_context_root(vault_context: Any) -> Path:
    value = getattr(vault_context, "active_vault_path", None)
    if not isinstance(value, str) or not value:
        raise SupportableRepairRefusal("context_refused")
    try:
        root = Path(value).expanduser().resolve(strict=True)
    except OSError:
        raise SupportableRepairRefusal("context_refused") from None
    if not root.is_dir():
        raise SupportableRepairRefusal("context_refused")
    return root


def _safe_relative(value: str) -> PurePosixPath:
    try:
        relative = PurePosixPath(value)
    except (TypeError, ValueError):
        raise SupportableRepairRefusal("context_refused") from None
    if (
        not value
        or relative.is_absolute()
        or value != relative.as_posix()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise SupportableRepairRefusal("context_refused")
    return relative


def _stable_stat_tuple(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _open_root(root: Path) -> tuple[Path, int, os.stat_result]:
    try:
        resolved = root.expanduser().resolve(strict=True)
        named_before = os.stat(resolved, follow_symlinks=False)
        descriptor = os.open(
            resolved,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or _stable_stat_tuple(named_before) != _stable_stat_tuple(opened)
        ):
            os.close(descriptor)
            raise OSError
        return resolved, descriptor, named_before
    except OSError:
        raise SupportableRepairRefusal("authority_refused") from None


def _open_relative_parent(
    root: Path, relative: PurePosixPath,
) -> tuple[Path, int, list[tuple[int, int, os.stat_result]], str]:
    resolved, root_fd, root_named = _open_root(root)
    opened: list[tuple[int, int, os.stat_result]] = [(root_fd, -1, root_named)]
    current_fd = root_fd
    try:
        for part in relative.parts[:-1]:
            named_before = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            child_fd = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=current_fd,
            )
            child = os.fstat(child_fd)
            if (
                not stat.S_ISDIR(child.st_mode)
                or _stable_stat_tuple(named_before) != _stable_stat_tuple(child)
            ):
                os.close(child_fd)
                raise OSError
            opened.append((child_fd, current_fd, named_before))
            current_fd = child_fd
        return resolved, current_fd, opened, relative.name
    except FileNotFoundError:
        for descriptor, _parent, _named in reversed(opened):
            os.close(descriptor)
        raise _MissingRelative from None
    except OSError:
        for descriptor, _parent, _named in reversed(opened):
            os.close(descriptor)
        raise SupportableRepairRefusal("authority_refused") from None


def _verify_open_chain(
    resolved_root: Path,
    opened: list[tuple[int, int, os.stat_result]],
    parts: tuple[str, ...],
) -> None:
    try:
        for index in range(len(opened) - 1, 0, -1):
            descriptor, parent_fd, named_before = opened[index]
            named_after = os.stat(parts[index - 1], dir_fd=parent_fd, follow_symlinks=False)
            if (
                _stable_stat_tuple(named_before) != _stable_stat_tuple(named_after)
                or _stable_stat_tuple(named_before)
                != _stable_stat_tuple(os.fstat(descriptor))
            ):
                raise OSError
        root_after = os.stat(resolved_root, follow_symlinks=False)
        root_fd, _parent, root_before = opened[0]
        if (
            _stable_stat_tuple(root_before) != _stable_stat_tuple(root_after)
            or _stable_stat_tuple(root_before) != _stable_stat_tuple(os.fstat(root_fd))
        ):
            raise OSError
    except OSError:
        raise SupportableRepairRefusal("authority_refused") from None


def _regular_nofollow_text(root: Path, relative_value: str) -> tuple[str, str]:
    """Read one bounded regular file through stable root-relative descriptors."""

    relative = _safe_relative(relative_value)
    try:
        resolved, parent_fd, opened, leaf = _open_relative_parent(root, relative)
    except _MissingRelative:
        raise SupportableRepairRefusal("authority_refused") from None
    descriptor: int | None = None
    try:
        named_before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        descriptor = os.open(
            leaf,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > _MAX_PRIVATE_FILE_BYTES
            or _stable_stat_tuple(named_before) != _stable_stat_tuple(before)
        ):
            raise OSError
        raw = b""
        while len(raw) <= before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
        after = os.fstat(descriptor)
        named_after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if (
            len(raw) != before.st_size
            or _stable_stat_tuple(before) != _stable_stat_tuple(after)
            or _stable_stat_tuple(before) != _stable_stat_tuple(named_after)
        ):
            raise OSError
        _verify_open_chain(resolved, opened, relative.parts[:-1])
        return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeDecodeError):
        raise SupportableRepairRefusal("authority_refused") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for directory_fd, _parent, _named in reversed(opened):
            os.close(directory_fd)


def _relative_entry_exists(root: Path, relative_value: str) -> bool:
    relative = _safe_relative(relative_value)
    try:
        resolved, parent_fd, opened, leaf = _open_relative_parent(root, relative)
    except _MissingRelative:
        return False
    try:
        try:
            found = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            found = None
        _verify_open_chain(resolved, opened, relative.parts[:-1])
        if found is None:
            return False
        if not stat.S_ISREG(found.st_mode) or found.st_nlink != 1:
            raise SupportableRepairRefusal("authority_refused")
        return True
    finally:
        for directory_fd, _parent, _named in reversed(opened):
            os.close(directory_fd)


def _stable_directory_names(root: Path, relative_value: str) -> tuple[str, ...]:
    relative = _safe_relative(relative_value)
    try:
        resolved, parent_fd, opened, leaf = _open_relative_parent(root, relative)
    except _MissingRelative:
        return ()
    descriptor: int | None = None
    try:
        try:
            named_before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            _verify_open_chain(resolved, opened, relative.parts[:-1])
            return ()
        descriptor = os.open(
            leaf,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or _stable_stat_tuple(named_before) != _stable_stat_tuple(before)
        ):
            raise OSError
        first = tuple(sorted(os.listdir(descriptor)))
        second = tuple(sorted(os.listdir(descriptor)))
        named_after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if (
            first != second
            or _stable_stat_tuple(before) != _stable_stat_tuple(os.fstat(descriptor))
            or _stable_stat_tuple(before) != _stable_stat_tuple(named_after)
        ):
            raise OSError
        _verify_open_chain(resolved, opened, relative.parts[:-1])
        return first
    except OSError:
        raise SupportableRepairRefusal("authority_refused") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for directory_fd, _parent, _named in reversed(opened):
            os.close(directory_fd)


def _companion_file(root: Path, identity: str) -> str:
    from app.services.companion_note import companion_path

    canonical = companion_path(identity, root).as_posix()
    legacy = f"_system/companions/{identity}.md"
    present = [
        relative
        for relative in dict.fromkeys((canonical, legacy))
        if _relative_entry_exists(root, relative)
    ]
    if len(present) != 1:
        raise SupportableRepairRefusal("authority_refused")
    return present[0]


def _companion_claim_counts(
    root: Path, *, identity: str, current_source_rel: str,
) -> tuple[int, int]:
    """Count exact companion UUID/current-locator claims across both supported trees."""

    from app.ops.native_source_identity_persistence import _canonical_uuid
    from app.services.companion_note import companion_path

    canonical = companion_path(identity, root).parent.as_posix()
    legacy = "_system/companions"
    directories: list[str] = []
    for directory in (canonical, legacy):
        if any(directory == existing for existing in directories):
            continue
        directories.append(directory)
    identity_claims = current_locator_claims = 0
    for directory in directories:
        names = _stable_directory_names(root, directory)
        for name in names:
            if not name.endswith(".md") or "/" in name:
                continue
            candidate = f"{directory}/{name}"
            raw, _version = _regular_nofollow_text(root, candidate)
            try:
                frontmatter, _body = load_frontmatter(raw)
            except Exception:
                raise SupportableRepairRefusal("authority_refused") from None
            if not isinstance(frontmatter, dict):
                raise SupportableRepairRefusal("authority_refused")
            declared = _canonical_uuid(frontmatter.get("uuid"))
            if declared is None:
                raise SupportableRepairRefusal("authority_refused")
            identity_claims += declared == identity
            current_locator_claims += frontmatter.get("source_ref") == current_source_rel
        if _stable_directory_names(root, directory) != names:
            raise SupportableRepairRefusal("authority_refused")
    return identity_claims, current_locator_claims


def _canonical_inventory(root: Path) -> tuple[Any, ...]:
    from app.ops.native_source_identity_persistence import _registry_plan

    _policy, observations = _registry_plan(root)
    return observations


def _strict_source_frontmatter(raw: str) -> dict[str, Any]:
    """Capture one source mapping without normalizing ambiguous YAML to absence."""

    from app.rebuildability.product_total_loss import capture_source_frontmatter

    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}
    closing = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing is None:
        raise SupportableRepairRefusal("authority_refused")
    try:
        node = yaml.compose("".join(lines[1:closing]), Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        raise SupportableRepairRefusal("authority_refused") from None
    if node is not None:
        if not isinstance(node, yaml.MappingNode):
            raise SupportableRepairRefusal("authority_refused")
        seen: set[str] = set()
        for key_node, _value_node in node.value:
            if not isinstance(key_node, yaml.ScalarNode) or key_node.value in seen:
                raise SupportableRepairRefusal("authority_refused")
            seen.add(key_node.value)
    captured = capture_source_frontmatter(raw)
    if captured is None:
        raise SupportableRepairRefusal("authority_refused")
    return captured


def _source_claims(root: Path, observations: tuple[Any, ...]) -> tuple[dict[str, int], set[str]]:
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.ops.native_source_identity_persistence import _canonical_uuid

    claims: dict[str, int] = {}
    locators: set[str] = set()
    for observation in observations:
        relative = observation.path.relative_to(root).as_posix()
        if relative in locators:
            raise SupportableRepairRefusal("authority_refused")
        locators.add(relative)
        try:
            raw, _identity = read_recovery_snapshot_relative(relative, vault_root=root)
        except Exception:
            raise SupportableRepairRefusal("authority_refused") from None
        frontmatter = _strict_source_frontmatter(raw)
        raw_declared = frontmatter.get("uuid")
        declared = _canonical_uuid(raw_declared)
        if declared is None and raw_declared not in (None, ""):
            raise SupportableRepairRefusal("authority_refused")
        if declared is not None:
            claims[declared] = claims.get(declared, 0) + 1
    return claims, locators


def _validated_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise SupportableRepairRefusal("context_refused") from None
    if parsed.tzinfo is None or not value:
        raise SupportableRepairRefusal("context_refused")
    return value


def prepare_companion_continuity_repair(
    *, vault_root: Path, source_rel: str, observed_at: str,
) -> CompanionContinuityProposal:
    """Compute one concrete Scenario-F proposal from fresh canonical reads."""

    from app.knowledge.profile_authority_store import is_profile_note_source
    from app.knowledge.write_ops import read_recovery_snapshot_relative
    from app.ops.native_source_identity_persistence import _canonical_uuid
    from app.rebuildability import canonical_product_body_text, parse_bounded_frontmatter
    from app.services.companion_note import (
        IDENTITY_HISTORY_MAX,
        find_duplicate_companions,
        is_companion_path,
        read_companion,
    )
    from app.services.note_uuid import is_read_only_derived_artifact

    root = vault_root.expanduser().resolve(strict=True)
    timestamp = _validated_timestamp(observed_at)
    try:
        relative = Path(source_rel)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != source_rel:
            raise ValueError
        source = root / relative
        if source.is_symlink():
            raise ValueError
        source.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        raise SupportableRepairRefusal("context_refused") from None

    observations = _canonical_inventory(root)
    selected = tuple(item.path.relative_to(root).as_posix() for item in observations)
    if selected.count(source_rel) != 1:
        raise SupportableRepairRefusal("authority_refused")
    claims, locators = _source_claims(root, observations)
    raw, _source_identity = read_recovery_snapshot_relative(source_rel, vault_root=root)
    frontmatter, body, error = parse_bounded_frontmatter(raw)
    declared = _canonical_uuid(frontmatter.get("uuid")) if error is None else None
    if (
        declared is None
        or claims.get(declared) != 1
        or is_profile_note_source(root, source_rel, declared)
        or is_read_only_derived_artifact(frontmatter)
    ):
        raise SupportableRepairRefusal("authority_refused")
    if any(item.uuid == declared for item in find_duplicate_companions(root)):
        raise SupportableRepairRefusal("authority_refused")
    companion = read_companion(root, declared)
    if companion is None or _canonical_uuid(companion.uuid) != declared:
        raise SupportableRepairRefusal("authority_refused")
    identity_claims, current_locator_claims = _companion_claim_counts(
        root,
        identity=declared,
        current_source_rel=source_rel,
    )
    if (
        identity_claims != 1
        or current_locator_claims != 0
        or companion.source_ref == source_rel
        or companion.source_ref in locators
        or not is_companion_path(Path(companion.source_ref), vault_root=root)
    ):
        raise SupportableRepairRefusal("authority_refused")
    current_hash = hashlib.sha256(
        canonical_product_body_text(body).encode("utf-8")
    ).hexdigest()
    if companion.content_hash == current_hash:
        raise SupportableRepairRefusal("authority_refused")

    companion_rel = _companion_file(root, declared)
    original, original_sha256 = _regular_nofollow_text(root, companion_rel)
    try:
        companion_fm, companion_body = load_frontmatter(original)
    except Exception:
        raise SupportableRepairRefusal("authority_refused") from None
    if not isinstance(companion_fm, dict):
        raise SupportableRepairRefusal("authority_refused")
    before = dict(companion_fm)
    if (
        before.get("uuid") != declared
        or before.get("source_ref") != companion.source_ref
        or before.get("content_hash") != companion.content_hash
    ):
        raise SupportableRepairRefusal("authority_refused")
    history = before.get("identity_history", [])
    if not isinstance(history, list):
        raise SupportableRepairRefusal("authority_refused")
    entry = {
        "timestamp": timestamp,
        "event": "path_change",
        "before": {
            "source_ref": companion.source_ref,
            "content_hash": companion.content_hash,
        },
        "after": {"source_ref": source_rel, "content_hash": current_hash},
        "reason": "canonical source continuity repair",
    }
    candidate_fm = dict(before)
    candidate_fm["source_ref"] = source_rel
    candidate_fm["content_hash"] = current_hash
    candidate_fm["identity_history"] = [*history, entry][-IDENTITY_HISTORY_MAX:]
    candidate = dump_frontmatter(candidate_fm, companion_body)
    after, after_body = load_frontmatter(candidate)
    unchanged_before = dict(before)
    unchanged_after = dict(after)
    for key in ("source_ref", "content_hash", "identity_history"):
        unchanged_before.pop(key, None)
        unchanged_after.pop(key, None)
    if unchanged_before != unchanged_after or companion_body != after_body:
        raise SupportableRepairRefusal("authority_refused")
    return CompanionContinuityProposal(
        source_rel=source_rel,
        companion_rel=companion_rel,
        identity=declared,
        observed_at=timestamp,
        original_text=original,
        candidate_text=candidate,
        original_sha256=original_sha256,
        candidate_sha256=_sha256_text(candidate),
    )


def commit_companion_continuity_repair(
    proposal: CompanionContinuityProposal,
    *,
    vault_root: Path,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> None:
    """Re-prove and publish exactly one companion proposal by canonical CAS."""

    root = vault_root.expanduser().resolve(strict=True)
    fresh = prepare_companion_continuity_repair(
        vault_root=root,
        source_rel=proposal.source_rel,
        observed_at=proposal.observed_at,
    )
    if fresh != proposal:
        raise SupportableRepairRefusal("authority_refused")
    target = root / proposal.companion_rel
    try:
        write_note_from_absolute(
            target,
            proposal.candidate_text,
            vault_root=root,
            action=ACTION,
            write_guard=write_guard,
            expected_version=proposal.original_sha256,
            writer_identity=WRITER_IDENTITY,
        )
    except Exception:
        raise SupportableRepairRefusal("write_refused") from None
    _text, version = _regular_nofollow_text(root, proposal.companion_rel)
    if version != proposal.candidate_sha256:
        raise SupportableRepairRefusal("readback_indeterminate")


def prepare_briefing_repair(
    *, vault_context: Any, for_date: date,
) -> BriefingRepairProposal:
    """Bind the existing composer-owned proposal to exact original bytes."""

    migration = prepare_briefing_identity_migration(
        vault_context=vault_context,
        for_date=for_date,
    )
    if migration is None:
        raise SupportableRepairRefusal("authority_refused")
    root = _vault_context_root(vault_context)
    original, version = _regular_nofollow_text(root, migration.note_rel_path)
    if version != migration.expected_version:
        raise SupportableRepairRefusal("authority_refused")
    try:
        before, before_body = load_frontmatter(original)
        after, after_body = load_frontmatter(migration.content)
    except Exception:
        raise SupportableRepairRefusal("authority_refused") from None
    before_without_uuid = dict(before)
    after_without_uuid = dict(after)
    before_without_uuid.pop("uuid", None)
    after_without_uuid.pop("uuid", None)
    if (
        before.get("uuid") is not None
        or not isinstance(after.get("uuid"), str)
        or before_without_uuid != after_without_uuid
        or before_body != after_body
    ):
        raise SupportableRepairRefusal("authority_refused")
    return BriefingRepairProposal(
        for_date=for_date,
        migration=migration,
        original_text=original,
        original_sha256=version,
        candidate_sha256=_sha256_text(migration.content),
    )


def _vault_fingerprint(root: Path) -> str:
    resolved, descriptor, named = _open_root(root)
    try:
        _verify_open_chain(resolved, [(descriptor, -1, named)], ())
        payload = {"device": named.st_dev, "inode": named.st_ino}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    finally:
        os.close(descriptor)


def _target_set_sha256(
    companion: tuple[CompanionContinuityProposal, ...],
    briefings: tuple[BriefingRepairProposal, ...],
) -> str:
    payload = {
        "briefings": [
            {
                "candidate_sha256": item.candidate_sha256,
                "date": item.for_date.isoformat(),
                "expected_version": item.migration.expected_version,
                "note_rel": item.migration.note_rel_path,
                "original_sha256": item.original_sha256,
            }
            for item in briefings
        ],
        "companion": [
            {
                "candidate_sha256": item.candidate_sha256,
                "companion_rel": item.companion_rel,
                "identity": item.identity,
                "observed_at": item.observed_at,
                "original_sha256": item.original_sha256,
                "source_rel": item.source_rel,
            }
            for item in companion
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_companion_proposal(
    root: Path, proposal: CompanionContinuityProposal,
) -> None:
    from app.ops.native_source_identity_persistence import _canonical_uuid
    from app.services.companion_note import companion_path, is_companion_path

    source_rel = _safe_relative(proposal.source_rel).as_posix()
    companion_rel = _safe_relative(proposal.companion_rel).as_posix()
    canonical_identity = _canonical_uuid(proposal.identity)
    canonical_companion = (
        companion_path(proposal.identity, root).as_posix()
        if canonical_identity is not None
        else ""
    )
    legacy_companion = f"_system/companions/{proposal.identity}.md"
    if (
        canonical_identity != proposal.identity
        or is_companion_path(Path(source_rel), vault_root=root)
        or companion_rel not in {canonical_companion, legacy_companion}
        or _sha256_text(proposal.original_text) != proposal.original_sha256
        or _sha256_text(proposal.candidate_text) != proposal.candidate_sha256
    ):
        raise SupportableRepairRefusal("context_refused")
    _validated_timestamp(proposal.observed_at)


def _validate_briefing_proposal(
    root: Path, vault_context: Any, proposal: BriefingRepairProposal,
) -> None:
    from app.briefing.compose import briefing_note_path

    note_rel = _safe_relative(proposal.migration.note_rel_path).as_posix()
    expected = briefing_note_path(
        vault_context=vault_context,
        for_date=proposal.for_date,
    ).relative_to(root).as_posix()
    if (
        note_rel != expected
        or proposal.migration.expected_version != proposal.original_sha256
        or proposal.migration.content == proposal.original_text
        or _sha256_text(proposal.original_text) != proposal.original_sha256
        or _sha256_text(proposal.migration.content) != proposal.candidate_sha256
    ):
        raise SupportableRepairRefusal("context_refused")


def prepare_repair_batch(
    *,
    vault_root: Path,
    vault_context: Any,
    companion_sources: tuple[str, ...],
    briefing_dates: tuple[date, ...],
    observed_at: str,
    revision: str,
    image_digest: str,
    selection_sha256: str,
) -> RepairBatch:
    """Freeze the exact reviewed target set without publishing private material."""

    root = vault_root.expanduser().resolve(strict=True)
    if _vault_context_root(vault_context) != root:
        raise SupportableRepairRefusal("context_refused")
    if (
        len(companion_sources) != EXPECTED_COMPANION_COUNT
        or len(set(companion_sources)) != EXPECTED_COMPANION_COUNT
        or len(briefing_dates) != EXPECTED_BRIEFING_COUNT
        or len(set(briefing_dates)) != EXPECTED_BRIEFING_COUNT
    ):
        raise SupportableRepairRefusal("context_refused")
    companion = tuple(
        prepare_companion_continuity_repair(
            vault_root=root,
            source_rel=source_rel,
            observed_at=observed_at,
        )
        for source_rel in companion_sources
    )
    briefings = tuple(
        prepare_briefing_repair(
            vault_context=vault_context,
            for_date=for_date,
        )
        for for_date in briefing_dates
    )
    batch = RepairBatch(
        revision=revision,
        image_digest=image_digest,
        selection_sha256=selection_sha256,
        target_set_sha256=_target_set_sha256(companion, briefings),
        vault_fingerprint=_vault_fingerprint(root),
        companion=companion,
        briefings=briefings,
    )
    _validate_batch(batch, vault_root=root, vault_context=vault_context)
    return batch


def commit_briefing_repair(
    proposal: BriefingRepairProposal,
    *,
    vault_context: Any,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> None:
    """Re-prove and delegate exactly one write to the composer migration seam."""

    fresh = prepare_briefing_repair(
        vault_context=vault_context,
        for_date=proposal.for_date,
    )
    if fresh != proposal:
        raise SupportableRepairRefusal("authority_refused")
    try:
        receipt = migrate_briefing_identity(
            vault_context=vault_context,
            for_date=proposal.for_date,
            write_guard=write_guard,
        )
    except Exception:
        raise SupportableRepairRefusal("write_refused") from None
    if receipt is None:
        raise SupportableRepairRefusal("readback_indeterminate")
    root = _vault_context_root(vault_context)
    _text, version = _regular_nofollow_text(root, proposal.migration.note_rel_path)
    if version != proposal.candidate_sha256:
        raise SupportableRepairRefusal("readback_indeterminate")


def _rollback_exact(
    *,
    relative: str,
    root: Path,
    expected_candidate_sha256: str,
    original_text: str,
    original_sha256: str,
    write_guard: WriteGuard,
) -> str:
    """Rollback only exact repair bytes; mismatch is preserved and indeterminate."""

    if (
        _sha256_text(original_text) != original_sha256
        or _SHA256.fullmatch(expected_candidate_sha256) is None
    ):
        raise SupportableRepairRefusal("context_refused")
    try:
        _current, current_sha256 = _regular_nofollow_text(root, relative)
    except SupportableRepairRefusal:
        return "indeterminate"
    if current_sha256 != expected_candidate_sha256:
        return "indeterminate"
    try:
        write_note_from_absolute(
            root / _safe_relative(relative),
            original_text,
            vault_root=root,
            action=ACTION,
            write_guard=write_guard,
            expected_version=expected_candidate_sha256,
            writer_identity=WRITER_IDENTITY,
        )
        _restored, restored_sha256 = _regular_nofollow_text(root, relative)
    except Exception:
        return "indeterminate"
    return "committed" if restored_sha256 == original_sha256 else "indeterminate"


def rollback_companion_continuity_repair(
    proposal: CompanionContinuityProposal,
    *,
    batch: RepairBatch,
    effects: RepairEffects,
    vault_root: Path,
    vault_context: Any,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> str:
    root = vault_root.expanduser().resolve(strict=True)
    _validate_batch(batch, vault_root=root, vault_context=vault_context)
    _validate_companion_proposal(root, proposal)
    if proposal not in batch.companion:
        raise SupportableRepairRefusal("context_refused")
    return _fenced_rollback(
        batch=batch,
        effects=effects,
        rollback=lambda: _rollback_exact(
            relative=proposal.companion_rel,
            root=root,
            expected_candidate_sha256=proposal.candidate_sha256,
            original_text=proposal.original_text,
            original_sha256=proposal.original_sha256,
            write_guard=write_guard,
        ),
    )


def rollback_briefing_repair(
    proposal: BriefingRepairProposal,
    *,
    batch: RepairBatch,
    effects: RepairEffects,
    vault_root: Path,
    vault_context: Any,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> str:
    root = vault_root.expanduser().resolve(strict=True)
    _validate_batch(batch, vault_root=root, vault_context=vault_context)
    _validate_briefing_proposal(root, vault_context, proposal)
    if proposal not in batch.briefings:
        raise SupportableRepairRefusal("context_refused")
    return _fenced_rollback(
        batch=batch,
        effects=effects,
        rollback=lambda: _rollback_exact(
            relative=proposal.migration.note_rel_path,
            root=root,
            expected_candidate_sha256=proposal.candidate_sha256,
            original_text=proposal.original_text,
            original_sha256=proposal.original_sha256,
            write_guard=write_guard,
        ),
    )


def _validate_batch(
    batch: RepairBatch, *, vault_root: Path, vault_context: Any,
) -> None:
    root = vault_root.expanduser().resolve(strict=True)
    if (
        _vault_context_root(vault_context) != root
        or _REVISION.fullmatch(batch.revision) is None
        or _IMAGE_DIGEST.fullmatch(batch.image_digest) is None
        or _SHA256.fullmatch(batch.selection_sha256) is None
        or _SHA256.fullmatch(batch.target_set_sha256) is None
        or _SHA256.fullmatch(batch.vault_fingerprint) is None
        or len(batch.companion) != EXPECTED_COMPANION_COUNT
        or len(batch.briefings) != EXPECTED_BRIEFING_COUNT
        or len({item.source_rel for item in batch.companion}) != len(batch.companion)
        or len({item.for_date for item in batch.briefings}) != len(batch.briefings)
    ):
        raise SupportableRepairRefusal("context_refused")
    for companion_proposal in batch.companion:
        _validate_companion_proposal(root, companion_proposal)
    for briefing_proposal in batch.briefings:
        _validate_briefing_proposal(root, vault_context, briefing_proposal)
    if (
        _target_set_sha256(batch.companion, batch.briefings)
        != batch.target_set_sha256
        or _vault_fingerprint(root) != batch.vault_fingerprint
    ):
        raise SupportableRepairRefusal("context_refused")


def _validate_authority(batch: RepairBatch, authority: RepairAuthoritySnapshot) -> None:
    if (
        authority.revision != batch.revision
        or authority.image_digest != batch.image_digest
        or authority.selection_sha256 != batch.selection_sha256
        or authority.target_set_sha256 != batch.target_set_sha256
        or authority.vault_fingerprint != batch.vault_fingerprint
        or any(type(value) is not bool for value in (
            authority.controller_unloaded,
            authority.write_guard_healthy,
            authority.writers_isolated,
            authority.owned_operation_fences_healthy,
        ))
        or not all((
            authority.controller_unloaded,
            authority.write_guard_healthy,
            authority.writers_isolated,
            authority.owned_operation_fences_healthy,
        ))
    ):
        raise SupportableRepairRefusal("authority_refused")


def _fenced_rollback(
    *, batch: RepairBatch, effects: RepairEffects, rollback: Any,
) -> str:
    before: RepairAuthoritySnapshot | None = None
    try:
        with effects.owned_repair_fence():
            before = effects.read_repair_authority()
            _validate_authority(batch, before)
            outcome = rollback()
            after = effects.read_repair_authority()
            _validate_authority(batch, after)
            return outcome if after == before else "indeterminate"
    except Exception:
        if before is None:
            raise SupportableRepairRefusal("authority_refused") from None
        return "indeterminate"


def _public_receipt(
    *, result: str, planned: int, repaired: int, refused: int, indeterminate: int,
) -> dict[str, Any]:
    return validate_public_receipt({
        "contract": RECEIPT_CONTRACT,
        "channel": "dev",
        "result": result,
        "planned_count": planned,
        "repaired_count": repaired,
        "refused_count": refused,
        "indeterminate_count": indeterminate,
        "automatic_producer_started": False,
        "automatic_deployment_started": False,
    })


def validate_public_receipt(payload: Any) -> dict[str, Any]:
    """Accept only fixed counts/booleans; private material has no schema slot."""

    keys = {
        "contract", "channel", "result", "planned_count", "repaired_count",
        "refused_count", "indeterminate_count", "automatic_producer_started",
        "automatic_deployment_started",
    }
    if not isinstance(payload, dict) or set(payload) != keys:
        raise SupportableRepairRefusal("context_refused")
    if (
        payload["contract"] != RECEIPT_CONTRACT
        or payload["channel"] != "dev"
        or payload["result"] not in _RESULTS
        or any(type(payload[key]) is not int or payload[key] < 0 for key in (
            "planned_count", "repaired_count", "refused_count", "indeterminate_count",
        ))
        or payload["planned_count"] != (
            payload["repaired_count"]
            + payload["refused_count"]
            + payload["indeterminate_count"]
        )
        or payload["automatic_producer_started"] is not False
        or payload["automatic_deployment_started"] is not False
        or (payload["result"] == "committed" and (
            payload["refused_count"] or payload["indeterminate_count"]
        ))
        or (payload["result"] == "failed" and payload["indeterminate_count"])
        or (payload["result"] == "indeterminate" and not payload["indeterminate_count"])
    ):
        raise SupportableRepairRefusal("context_refused")
    return dict(payload)


def _classify_readback(
    root: Path, relative: str, *, original: str, candidate: str,
) -> str:
    try:
        _text, current = _regular_nofollow_text(root, relative)
    except SupportableRepairRefusal:
        return "indeterminate"
    if current == candidate:
        return "committed"
    if current == original:
        return "refused"
    return "indeterminate"


def run_supportable_repair_batch(
    batch: RepairBatch,
    *,
    effects: RepairEffects,
    vault_root: Path,
    vault_context: Any,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> dict[str, Any]:
    """Run one exact private batch inside a host-owned fence; never replay internally."""

    root = vault_root.expanduser().resolve(strict=True)
    _validate_batch(batch, vault_root=root, vault_context=vault_context)
    planned = len(batch.companion) + len(batch.briefings)
    repaired = refused = indeterminate = 0
    before: RepairAuthoritySnapshot | None = None
    try:
        with effects.owned_repair_fence():
            before = effects.read_repair_authority()
            _validate_authority(batch, before)
            for proposal in batch.companion:
                try:
                    commit_companion_continuity_repair(
                        proposal,
                        vault_root=root,
                        write_guard=write_guard,
                    )
                    outcome = "committed"
                except Exception:
                    outcome = _classify_readback(
                        root,
                        proposal.companion_rel,
                        original=proposal.original_sha256,
                        candidate=proposal.candidate_sha256,
                    )
                repaired += outcome == "committed"
                refused += outcome == "refused"
                indeterminate += outcome == "indeterminate"
            for briefing_proposal in batch.briefings:
                try:
                    commit_briefing_repair(
                        briefing_proposal,
                        vault_context=vault_context,
                        write_guard=write_guard,
                    )
                    outcome = "committed"
                except Exception:
                    outcome = _classify_readback(
                        root,
                        briefing_proposal.migration.note_rel_path,
                        original=briefing_proposal.original_sha256,
                        candidate=briefing_proposal.candidate_sha256,
                    )
                repaired += outcome == "committed"
                refused += outcome == "refused"
                indeterminate += outcome == "indeterminate"
            after = effects.read_repair_authority()
            _validate_authority(batch, after)
            if after != before:
                indeterminate += repaired + refused
                repaired = 0
                refused = 0
    except Exception:
        if repaired or refused or indeterminate:
            indeterminate += repaired + refused
            repaired = 0
            refused = 0
        else:
            raise SupportableRepairRefusal(
                "authority_refused" if before is not None else "context_refused"
            ) from None
    result = "indeterminate" if indeterminate else ("failed" if refused else "committed")
    return _public_receipt(
        result=result,
        planned=planned,
        repaired=repaired,
        refused=refused,
        indeterminate=indeterminate,
    )


__all__ = [
    "ACTION",
    "BriefingRepairProposal",
    "CompanionContinuityProposal",
    "EXPECTED_BRIEFING_COUNT",
    "EXPECTED_COMPANION_COUNT",
    "RECEIPT_CONTRACT",
    "RepairAuthoritySnapshot",
    "RepairBatch",
    "SupportableRepairRefusal",
    "commit_briefing_repair",
    "commit_companion_continuity_repair",
    "prepare_briefing_repair",
    "prepare_companion_continuity_repair",
    "prepare_repair_batch",
    "rollback_briefing_repair",
    "rollback_companion_continuity_repair",
    "run_supportable_repair_batch",
    "validate_public_receipt",
]
