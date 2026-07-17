"""Explicit governed migration into the canonical vault settings root."""

from __future__ import annotations

import ctypes
import fcntl
import json
import logging
import os
import shutil
import tempfile
from hashlib import sha256
from pathlib import Path

import yaml

from app.settings.locations import (
    LEGACY_COMPILED_DIR,
    LEGACY_HEALTH_SETTINGS,
    LEGACY_SYSTEM_SETTINGS,
    canonical_settings_root,
    contained_settings_path,
)
from app.vault.paths import get_vault_system_dir_rel
from app.receipts.settings_write import (
    ReceiptDurabilityUncertainError,
    SettingsWriteReceipt,
    emit_settings_write_receipt,
)
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard


MIGRATION_ACTION = "settings.location.migrate"
_TRANSACTION_PREFIX = ".settings-migration-"
_TRANSACTION_MARKER = "transaction.json"
logger = logging.getLogger(__name__)


def _path_present(path: Path) -> bool:
    """Return true for real paths and symlinks, including dangling symlinks."""

    return path.exists() or path.is_symlink()


def _atomic_exchange_directories(left: Path, right: Path) -> None:
    """Exchange two same-filesystem directories in one kernel operation."""

    libc = ctypes.CDLL(None, use_errno=True)
    left_bytes = os.fsencode(left)
    right_bytes = os.fsencode(right)
    if hasattr(libc, "renameatx_np"):
        rename = libc.renameatx_np
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-2, left_bytes, -2, right_bytes, 0x00000002)
    elif hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-100, left_bytes, -100, right_bytes, 0x00000002)
    else:
        raise RuntimeError(
            "atomic settings publication requires renameatx_np or renameat2"
        )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(left), str(right))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    directories: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"settings durability tree must not contain symlinks: {path}")
        if path.is_dir():
            directories.append(path)
            continue
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    for directory in reversed(directories):
        _fsync_directory(directory)
    _fsync_directory(root)


def _markdown_from_yaml(raw: str) -> str:
    payload = yaml.safe_load(raw)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("legacy system settings YAML must contain a mapping")
    normalized = yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    return f"---\n{normalized}\n---\n\n# System settings\n"


def _reject_symlinked_source(root: Path, source: Path) -> Path:
    """Keep migration reads and deletes on lexical, non-symlink vault paths."""

    contained_settings_path(root, source)
    cursor = source
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError(f"settings migration source must not be a symlink: {cursor}")
        cursor = cursor.parent
    return source


def _legacy_root(root: Path, relative: Path) -> Path:
    return _reject_symlinked_source(root, root / relative)


def _migration_files(vault_root: Path) -> list[tuple[Path, Path, str | None]]:
    mappings: list[tuple[Path, Path, str | None]] = []
    compiled = _legacy_root(vault_root, LEGACY_COMPILED_DIR)
    if compiled.exists():
        for source in sorted(compiled.rglob("*")):
            _reject_symlinked_source(vault_root, source)
            if source.is_file():
                relative = source.relative_to(compiled)
                if relative == Path("system-settings.yaml"):
                    mappings.append((source, Path("system-settings.md"), "yaml_to_markdown"))
                else:
                    mappings.append((source, relative, None))

    legacy_system_root = _legacy_root(vault_root, LEGACY_SYSTEM_SETTINGS.parent)
    if legacy_system_root.exists():
        for source in sorted(legacy_system_root.rglob("*")):
            _reject_symlinked_source(vault_root, source)
            if not source.is_file():
                continue
            if source.name == ".gitkeep":
                continue
            relative = source.relative_to(legacy_system_root)
            if source.name.casefold() == "health.md":
                mappings.append((source, Path("health.md"), None))
                continue
            if source == vault_root / LEGACY_SYSTEM_SETTINGS:
                mappings.append((source, Path("system-settings.md"), "yaml_to_markdown"))
            else:
                mappings.append((source, relative, None))

    for legacy_health in _legacy_health_paths(vault_root):
        if legacy_health.is_file():
            mappings.append((legacy_health, Path("health.md"), None))
    return mappings


def _target_text(source: Path, transform: str | None) -> str:
    raw = source.read_text(encoding="utf-8")
    return _markdown_from_yaml(raw) if transform == "yaml_to_markdown" else raw


def _legacy_health_paths(root: Path) -> tuple[Path, ...]:
    resolved_root = root.resolve()
    paths = {_reject_symlinked_source(resolved_root, resolved_root / LEGACY_HEALTH_SETTINGS)}
    try:
        configured_system_dir = Path(get_vault_system_dir_rel(resolved_root))
    except (OSError, ValueError):
        pass
    else:
        configured_health = resolved_root / configured_system_dir / "Settings" / "health.md"
        _reject_symlinked_source(resolved_root, configured_health)
        paths.add(configured_health)
    return tuple(sorted(paths, key=str))


def _prepared_mappings(
    canonical: Path,
    mappings: list[tuple[Path, Path, str | None]],
) -> list[tuple[Path, Path, str]]:
    """Validate all sources before the guard and collapse identical aliases."""

    prepared: list[tuple[Path, Path, str]] = []
    by_target: dict[Path, tuple[Path, str]] = {}
    for source, relative, transform in mappings:
        text = _target_text(source, transform)
        prior = by_target.get(relative)
        if prior is not None:
            prior_source, prior_text = prior
            if prior_text != text:
                raise FileExistsError(
                    "legacy settings sources conflict at canonical target: "
                    f"{prior_source} and {source} both map to {canonical / relative}"
                )
            continue
        target = canonical / relative
        if target.exists() and target.read_text(encoding="utf-8") != text:
            raise FileExistsError(
                f"canonical settings artifact conflicts with legacy source: {target} shadows {source}"
            )
        by_target[relative] = (source, text)
        prepared.append((source, relative, text))
    return prepared


def _source_fingerprints(
    mappings: list[tuple[Path, Path, str | None]],
) -> dict[Path, tuple[int, int, int, str]]:
    fingerprints: dict[Path, tuple[int, int, int, str]] = {}
    for source, _relative, _transform in mappings:
        stat = source.stat()
        fingerprints[source] = (
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            sha256(source.read_bytes()).hexdigest(),
        )
    return fingerprints


def _sources_match(
    expected: dict[Path, tuple[int, int, int, str]],
) -> bool:
    try:
        current = _source_fingerprints(
            [(source, Path(), None) for source in expected]
        )
    except (OSError, ValueError):
        return False
    return current == expected


def _legacy_manifest_matches(
    root: Path, expected: dict[Path, tuple[int, int, int, str]]
) -> bool:
    try:
        current = _source_fingerprints(_migration_files(root))
    except (OSError, ValueError):
        return False
    return current == expected


def _canonical_manifest(
    root: Path, canonical: Path
) -> dict[Path, tuple[int, int, int, str]]:
    files: list[tuple[Path, Path, str | None]] = []
    if _path_present(canonical):
        _reject_symlinked_source(root, canonical)
        if not canonical.is_dir():
            raise ValueError(f"canonical settings root must be a directory: {canonical}")
        for path in sorted(canonical.rglob("*")):
            _reject_symlinked_source(root, path)
            if path.is_file():
                files.append((path, path.relative_to(canonical), None))
    absolute = _source_fingerprints(files)
    return {
        path.relative_to(canonical): fingerprint
        for path, fingerprint in absolute.items()
    }


def _decode_transaction_manifest(
    marker: dict[str, object], key: str
) -> dict[Path, tuple[int, int, int, str]]:
    raw = marker.get(key)
    if not isinstance(raw, dict):
        raise RuntimeError(f"settings migration transaction lacks trusted {key}")
    decoded: dict[Path, tuple[int, int, int, str]] = {}
    for path, value in raw.items():
        if (
            not isinstance(path, str)
            or not isinstance(value, list)
            or len(value) != 4
            or not all(isinstance(item, int) for item in value[:3])
            or not isinstance(value[3], str)
        ):
            raise RuntimeError(f"settings migration transaction has invalid {key}")
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"settings migration transaction has unsafe {key}")
        decoded[relative] = (value[0], value[1], value[2], value[3])
    return decoded


def _assert_trusted_tree(
    root: Path,
    tree: Path,
    expected: dict[Path, tuple[int, int, int, str]],
    *,
    label: str,
) -> None:
    if not _path_present(tree):
        raise RuntimeError(f"trusted settings {label} is missing")
    if tree.is_symlink() or not tree.is_dir():
        raise RuntimeError(f"trusted settings {label} must be a real directory")
    try:
        manifest = _canonical_manifest(root, tree)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"trusted settings {label} failed containment checks") from exc
    if manifest != expected:
        raise RuntimeError(f"trusted settings {label} does not match its manifest")


def _write_transaction_state(
    transaction: Path,
    state: str,
    *,
    had_canonical: bool,
    receipt: SettingsWriteReceipt,
    backup_manifest: dict[Path, tuple[int, int, int, str]] | None = None,
    published_manifest: dict[Path, tuple[int, int, int, str]] | None = None,
) -> None:
    marker = transaction / _TRANSACTION_MARKER
    pending = transaction / f"{_TRANSACTION_MARKER}.tmp"
    payload = json.dumps(
        {
            "version": 2,
            "state": state,
            "had_canonical": had_canonical,
            "receipt_key": receipt.key,
            "receipt_timestamp": receipt.timestamp,
            "receipt_value": receipt.value,
            "receipt_old_value": receipt.old_value,
            "backup_manifest": {
                str(path): list(fingerprint)
                for path, fingerprint in (backup_manifest or {}).items()
            },
            "published_manifest": {
                str(path): list(fingerprint)
                for path, fingerprint in (published_manifest or {}).items()
            },
        }
    )
    with pending.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(pending, marker)
    _fsync_directory(transaction)


def _owned_transactions(root: Path) -> list[Path]:
    owned: list[Path] = []
    for candidate in sorted(root.glob(f"{_TRANSACTION_PREFIX}*")):
        marker = candidate / _TRANSACTION_MARKER
        if not (candidate.is_dir() and not candidate.is_symlink() and marker.is_file()):
            continue
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            owned.append(candidate)
            continue
        if not isinstance(payload, dict) or payload.get("state") not in {
            "committed",
            "rolled_back",
        }:
            owned.append(candidate)
    return owned


def _transaction_receipt_is_durable(marker: dict[str, object]) -> bool:
    from app.outbox.events import get_index_outbox_path

    path = get_index_outbox_path()
    if not path.is_file():
        return False
    expected_key = marker.get("receipt_key")
    expected_timestamp = marker.get("receipt_timestamp")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        payload = record.get("payload") if isinstance(record, dict) else None
        if not isinstance(payload, dict):
            continue
        if (
            payload.get("key") == expected_key
            and payload.get("timestamp") == expected_timestamp
        ):
            return True
    return False


def _recover_interrupted_transaction(
    root: Path, canonical: Path
) -> SettingsWriteReceipt | None:
    transactions = _owned_transactions(root)
    if not transactions:
        return None
    if len(transactions) != 1:
        raise RuntimeError("multiple interrupted settings migrations require operator recovery")
    transaction = transactions[0]
    marker = json.loads((transaction / _TRANSACTION_MARKER).read_text(encoding="utf-8"))
    if not isinstance(marker, dict):
        raise RuntimeError("invalid interrupted settings migration marker")
    state = marker.get("state")
    had_canonical = bool(marker.get("had_canonical"))
    backup_manifest = _decode_transaction_manifest(marker, "backup_manifest")
    published_manifest = _decode_transaction_manifest(marker, "published_manifest")
    backup = transaction / "canonical-before"
    staged = transaction / "canonical-next"
    if state == "committed":
        _assert_trusted_tree(
            root, canonical, published_manifest, label="committed canonical tree"
        )
        return None
    if (
        state == "published"
        and _transaction_receipt_is_durable(marker)
    ):
        _assert_trusted_tree(
            root, canonical, published_manifest, label="published canonical tree"
        )
        _quarantine_legacy_sources(root, transaction)
        marker["state"] = "committed"
        pending = transaction / f"{_TRANSACTION_MARKER}.tmp"
        with pending.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(marker))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, transaction / _TRANSACTION_MARKER)
        _fsync_directory(transaction)
        return SettingsWriteReceipt(
            key=str(marker.get("receipt_key") or "settings.location"),
            value=marker.get("receipt_value"),
            old_value=marker.get("receipt_old_value"),
            file=str(canonical),
            surface="migration",
            actor="operator",
            timestamp=str(marker.get("receipt_timestamp")),
            is_runtime_gating=False,
        )
    if state not in {"prepared", "published"}:
        raise RuntimeError("unknown interrupted settings migration state")
    recovery_receipt = SettingsWriteReceipt(
        key=str(marker.get("receipt_key") or "settings.location"),
        value=marker.get("receipt_value"),
        old_value=marker.get("receipt_old_value"),
        file=str(canonical),
        surface="migration",
        actor="operator",
        timestamp=str(marker.get("receipt_timestamp")),
        is_runtime_gating=False,
    )

    if had_canonical:
        if not _path_present(canonical):
            # Atomic exchange never removes the canonical name. An absent tree
            # therefore comes from an obsolete/tampered transaction and must
            # never trigger restoration of an untrusted backup path.
            raise RuntimeError(
                "interrupted settings migration is missing its canonical tree"
            )
        try:
            canonical_manifest = _canonical_manifest(root, canonical)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "interrupted canonical settings failed containment checks"
            ) from exc
        if canonical_manifest == backup_manifest:
            # Publication had not happened. A completed staged tree is checked
            # when its manifest was durably recorded; a partial real directory
            # is a valid pre-publication crash artifact.
            if _path_present(staged):
                if staged.is_symlink() or not staged.is_dir():
                    raise RuntimeError("staged settings recovery tree is untrusted")
                if published_manifest:
                    _assert_trusted_tree(
                        root,
                        staged,
                        published_manifest,
                        label="staged canonical tree",
                    )
        elif canonical_manifest == published_manifest:
            if _path_present(staged) and _path_present(backup):
                raise RuntimeError("multiple settings backup trees require operator recovery")
            prior = staged if _path_present(staged) else backup
            _assert_trusted_tree(
                root, prior, backup_manifest, label="recovery backup tree"
            )
            if prior == staged:
                os.replace(staged, backup)
                _fsync_directory(transaction)
            _quarantine_published_tree(
                root,
                canonical,
                transaction,
                expected_manifest=published_manifest,
                backup_manifest=backup_manifest,
                had_canonical=True,
            )
        else:
            raise RuntimeError(
                "interrupted canonical settings does not match a trusted manifest"
            )
    elif _path_present(canonical):
        _quarantine_published_tree(
            root,
            canonical,
            transaction,
            expected_manifest=published_manifest,
            backup_manifest=backup_manifest,
            had_canonical=False,
        )
    _write_transaction_state(
        transaction,
        "rolled_back",
        had_canonical=had_canonical,
        receipt=recovery_receipt,
        backup_manifest=backup_manifest,
        published_manifest=published_manifest,
    )
    return None


def _quarantine_published_tree(
    root: Path,
    canonical: Path,
    transaction: Path,
    *,
    expected_manifest: dict[Path, tuple[int, int, int, str]],
    backup_manifest: dict[Path, tuple[int, int, int, str]],
    had_canonical: bool,
) -> Path:
    quarantine = transaction / "published-rollback"
    if _path_present(quarantine):
        raise RuntimeError("published rollback quarantine already exists")
    backup = transaction / "canonical-before"
    if had_canonical:
        _assert_trusted_tree(
            root, backup, backup_manifest, label="recovery backup tree"
        )
        _atomic_exchange_directories(canonical, backup)
        _fsync_directory(root)
        _fsync_directory(transaction)
        os.replace(backup, quarantine)
        _fsync_directory(transaction)
    else:
        os.replace(canonical, quarantine)
        _fsync_directory(root)
        _fsync_directory(transaction)
    if _canonical_manifest(root, quarantine) != expected_manifest:
        raise RuntimeError(
            "published settings changed during rollback; operator recovery required"
        )
    if had_canonical:
        _assert_trusted_tree(
            root, canonical, backup_manifest, label="restored canonical tree"
        )
    elif _path_present(canonical):
        raise RuntimeError(
            "canonical settings reappeared during rollback; operator recovery required"
        )
    return quarantine


def _quarantine_legacy_sources(root: Path, transaction: Path) -> None:
    quarantine = transaction / "legacy-recovery"
    quarantine.mkdir(parents=True, exist_ok=True)
    _fsync_directory(transaction)


    _fsync_directory(quarantine)
    compiled = _legacy_root(root, LEGACY_COMPILED_DIR)
    if compiled.exists():
        os.replace(compiled, quarantine / "compiled")
        _fsync_directory(root)
        _fsync_directory(quarantine)

    legacy_system_root = _legacy_root(root, LEGACY_SYSTEM_SETTINGS.parent)
    if legacy_system_root.exists():
        (quarantine / "system").parent.mkdir(parents=True, exist_ok=True)
        os.replace(legacy_system_root, quarantine / "system")
        _fsync_directory(legacy_system_root.parent)
        _fsync_directory(quarantine)

    for index, legacy_health in enumerate(_legacy_health_paths(root)):
        if legacy_health.is_file():
            target = quarantine / f"health-{index}.md"
            os.replace(legacy_health, target)
            _fsync_directory(legacy_health.parent)
            _fsync_directory(quarantine)
        try:
            legacy_health.parent.rmdir()
        except OSError:
            # A compatibility directory may hold unrelated operator files.
            # Only the named health artifact belongs to this migration.
            pass
    _fsync_tree(quarantine)
    _fsync_directory(transaction)


def _retired_legacy_roots_exist(root: Path) -> bool:
    return (
        _legacy_root(root, LEGACY_COMPILED_DIR).exists()
        or _legacy_root(root, LEGACY_SYSTEM_SETTINGS.parent).exists()
        or any(path.is_file() for path in _legacy_health_paths(root))
    )


def migrate_settings_location(
    vault_root: Path,
    *,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> SettingsWriteReceipt:
    """Atomically publish a canonical settings tree and remove retired roots.

    Conflicting canonical/legacy artifacts fail before the WriteGuard or any
    mutation. The operator must resolve that conflict explicitly; the migration
    never guesses, overwrites, or merges authority-bearing content.
    """

    root = Path(vault_root).expanduser().resolve()
    canonical = canonical_settings_root(root)
    guard_checked = False
    if _owned_transactions(root):
        write_guard.assert_writes_allowed(MIGRATION_ACTION)
        guard_checked = True
        recovery_lock = os.open(root, os.O_RDONLY)
        try:
            fcntl.flock(recovery_lock, fcntl.LOCK_EX)
            try:
                recovered_receipt = _recover_interrupted_transaction(root, canonical)
            finally:
                fcntl.flock(recovery_lock, fcntl.LOCK_UN)
        finally:
            os.close(recovery_lock)
        if recovered_receipt is not None:
            return recovered_receipt
    mappings = _migration_files(root)
    prepared = _prepared_mappings(canonical, mappings)
    legacy_fingerprints = _source_fingerprints(mappings)
    canonical_fingerprints = _canonical_manifest(root, canonical)
    had_canonical = canonical.exists()

    if not guard_checked:
        write_guard.assert_writes_allowed(MIGRATION_ACTION)

    lock_descriptor = os.open(root, os.O_RDONLY)
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
    except Exception:
        os.close(lock_descriptor)
        raise

    # Re-read recovery state inside the same lock that protects publication.
    # Another migration may have created an interrupted transaction while this
    # process waited for the lock.
    try:
        if _owned_transactions(root):
            recovered_receipt = _recover_interrupted_transaction(root, canonical)
            if recovered_receipt is not None:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                os.close(lock_descriptor)
                return recovered_receipt
            mappings = _migration_files(root)
            prepared = _prepared_mappings(canonical, mappings)
            legacy_fingerprints = _source_fingerprints(mappings)
            canonical_fingerprints = _canonical_manifest(root, canonical)
            had_canonical = canonical.exists()
    except Exception:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
        raise

    # The manifest was built before the guard so conflicts remain fail-before-
    # guard. Rebuild it under the exclusive migration lock before any mutation,
    # closing the validation-to-rename race between cooperating writers.
    try:
        locked_mappings = _migration_files(root)
        locked_prepared = _prepared_mappings(canonical, locked_mappings)
        locked_changed = (
            _source_fingerprints(locked_mappings) != legacy_fingerprints
            or locked_prepared != prepared
        )
    except Exception:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
        raise
    if locked_changed:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
        raise RuntimeError("settings changed before migration lock; retry required")

    if not prepared:
        retired_roots_exist = _retired_legacy_roots_exist(root)
        transaction = (
            Path(tempfile.mkdtemp(prefix=_TRANSACTION_PREFIX, dir=canonical.parent))
            if retired_roots_exist
            else None
        )
        receipt = SettingsWriteReceipt(
            key="settings.location",
            value={
                "canonical": "settings",
                "migrated_files": 0,
                **({"recovery": transaction.name} if transaction else {}),
            },
            old_value={
                "canonical": "settings" if had_canonical else None,
                "legacy_files": 0,
            },
            file=str(canonical),
            surface="migration",
            actor="operator",
            is_runtime_gating=False,
        )
        try:
            if transaction is not None:
                _write_transaction_state(
                    transaction,
                    "prepared",
                    had_canonical=had_canonical,
                    receipt=receipt,
                    backup_manifest=canonical_fingerprints,
                    published_manifest=canonical_fingerprints,
                )
            emit_settings_write_receipt(receipt, require_durable=True)
            if transaction is not None:
                try:
                    _write_transaction_state(
                        transaction,
                        "committed",
                        had_canonical=had_canonical,
                        receipt=receipt,
                        backup_manifest=canonical_fingerprints,
                        published_manifest=canonical_fingerprints,
                    )
                except OSError as exc:
                    logger.warning(
                        "settings cleanup committed but transaction marker update failed: %s",
                        exc,
                    )
                try:
                    _quarantine_legacy_sources(root, transaction)
                except (OSError, ValueError) as exc:
                    logger.warning(
                        "settings cleanup committed but legacy cleanup was incomplete: %s",
                        exc,
                    )
        except Exception:
            if transaction is not None:
                shutil.rmtree(transaction, ignore_errors=True)
                _fsync_directory(root)
            raise
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)
        return receipt

    canonical.parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(
        tempfile.mkdtemp(prefix=_TRANSACTION_PREFIX, dir=canonical.parent)
    )
    staged = transaction / "canonical-next"
    staged.mkdir()
    receipt = SettingsWriteReceipt(
        key="settings.location",
        value={
            "canonical": "settings",
            "migrated_files": len(prepared),
            "recovery": transaction.name,
        },
        old_value={
            "canonical": "settings" if had_canonical else None,
            "legacy_files": len(prepared),
        },
        file=str(canonical),
        surface="migration",
        actor="operator",
        is_runtime_gating=False,
    )
    backup = transaction / "canonical-before"
    published = False
    committed = False
    receipt_durability_uncertain = False
    process_interrupted = False
    rollback_incomplete = False
    staged_manifest: dict[Path, tuple[int, int, int, str]] = {}
    try:
        _write_transaction_state(
            transaction,
            "prepared",
            had_canonical=had_canonical,
            receipt=receipt,
            backup_manifest=canonical_fingerprints,
        )
        if canonical.exists():
            shutil.copytree(canonical, staged, dirs_exist_ok=True, symlinks=True)
        for _source, relative, text in prepared:
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

        if (
            not _legacy_manifest_matches(root, legacy_fingerprints)
            or _canonical_manifest(root, canonical) != canonical_fingerprints
        ):
            raise RuntimeError("settings changed during migration preparation; retry required")

        staged_manifest = _canonical_manifest(root, staged)
        _fsync_tree(staged)
        if _canonical_manifest(root, staged) != staged_manifest:
            raise RuntimeError("staged settings changed during durability sync; retry required")
        _write_transaction_state(
            transaction,
            "prepared",
            had_canonical=had_canonical,
            receipt=receipt,
            backup_manifest=canonical_fingerprints,
            published_manifest=staged_manifest,
        )

        if canonical.exists():
            _atomic_exchange_directories(canonical, staged)
            published = True
            _fsync_directory(root)
            _fsync_directory(transaction)
            os.replace(staged, backup)
            _fsync_directory(transaction)
            if _canonical_manifest(root, backup) != canonical_fingerprints:
                raise RuntimeError(
                    "canonical settings changed during exchange; recovery preserved"
                )
        else:
            os.replace(staged, canonical)
            published = True
            _fsync_directory(root)
        _write_transaction_state(
            transaction,
            "published",
            had_canonical=had_canonical,
            receipt=receipt,
            backup_manifest=canonical_fingerprints,
            published_manifest=staged_manifest,
        )

        # The durable receipt is the commit boundary. Before it succeeds, any
        # failure restores the previous canonical tree. After it succeeds,
        # compatibility cleanup is best-effort: canonical-wins reads remain
        # unambiguous and the committed write is always receipted.
        try:
            emit_settings_write_receipt(receipt, require_durable=True)
        except ReceiptDurabilityUncertainError as exc:
            receipt_durability_uncertain = True
            logger.warning(
                "settings migration published with receipt durability pending recovery: %s",
                exc,
            )
        else:
            committed = True
            try:
                _write_transaction_state(
                    transaction,
                    "committed",
                    had_canonical=had_canonical,
                    receipt=receipt,
                    backup_manifest=canonical_fingerprints,
                    published_manifest=staged_manifest,
                )
            except OSError as exc:
                logger.warning(
                    "settings migration committed but transaction marker update failed: %s",
                    exc,
                )
    except Exception:
        if not committed:
            recovery_collision = False
            if published and canonical.exists():
                try:
                    if (
                        had_canonical
                        and not _path_present(backup)
                        and _path_present(staged)
                    ):
                        _assert_trusted_tree(
                            root,
                            staged,
                            canonical_fingerprints,
                            label="post-exchange backup tree",
                        )
                        os.replace(staged, backup)
                        _fsync_directory(transaction)
                    _quarantine_published_tree(
                        root,
                        canonical,
                        transaction,
                        expected_manifest=staged_manifest,
                        backup_manifest=canonical_fingerprints,
                        had_canonical=had_canonical,
                    )
                except Exception:
                    recovery_collision = True
                    rollback_incomplete = True
            if transaction.exists() and not recovery_collision:
                _write_transaction_state(
                    transaction,
                    "rolled_back",
                    had_canonical=had_canonical,
                    receipt=receipt,
                    backup_manifest=canonical_fingerprints,
                    published_manifest=staged_manifest if published else None,
                )
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
        raise
    except BaseException:
        # Process-level interruption leaves the durable transaction for the
        # next governed run, while the kernel lock must still be released in
        # in-process crash simulations and cooperative cancellation.
        process_interrupted = True
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
        raise
    finally:
        if (
            not process_interrupted
            and not rollback_incomplete
            and staged.exists()
            and not staged.is_symlink()
        ):
            shutil.rmtree(staged, ignore_errors=True)

    if receipt_durability_uncertain:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
        return receipt

    try:
        if not _legacy_manifest_matches(root, legacy_fingerprints):
            logger.warning(
                "settings migration committed after legacy sources changed; "
                "all current legacy data will be quarantined"
            )
        _quarantine_legacy_sources(root, transaction)
    except (OSError, ValueError) as exc:
        logger.warning(
            "settings migration committed but legacy cleanup was incomplete: %s",
            exc,
        )
    # Keep the owned committed transaction as a recovery artifact. Legacy
    # roots are removed atomically into this quarantine, never recursively
    # deleted after a racy check. Committed markers are ignored by automatic
    # crash recovery and can be pruned later by an explicit retention policy.
    fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
    os.close(lock_descriptor)
    return receipt


__all__ = ["MIGRATION_ACTION", "migrate_settings_location"]
