"""Explicit stopped-window DEV re-attestation and dormant TEST preparation.

This is new operator authority, never an alternative legacy authentication rule.
The backup manifest is the convergence receipt; it is not a runtime owner store.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import os
import re
import stat
import secrets
import tempfile
import subprocess
import sys
import uuid
from dataclasses import dataclass, replace
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import UUID

from app.instance.instance_state import (
    DeploymentQuiescenceProof,
    InstanceStateLayout,
    InstanceStatePreflightError,
    _atomic_private_write,
    _read_private_bytes,
    _read_private_json,
    _fsync_directory,
)
from app.instance.ownership_ledger import (
    LEGACY_LEDGER_SCHEMA, LEDGER_SCHEMA, LegacyOwner, LedgerSnapshot,
    OwnershipLedger, LedgerError, _KeyMaterial,
)
from app.instance.vault_registry import VaultRegistryStore

_SCHEMA = "agentic-pkm.dev-owner-reattest-backup.v1"
_PREPARATION = "dormant_ownership_preparation"
_NATIVE_CONTEXT = "native_execution_context"


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _refuse() -> InstanceStatePreflightError:
    return InstanceStatePreflightError("DEV owner re-attestation evidence is incomplete or changed")


def _backup_destination(destination: Path, protected: tuple[Path, ...]) -> Path:
    protected = tuple(root.expanduser().resolve(strict=False) for root in protected)
    absolute = destination.expanduser().absolute()
    if absolute != absolute.resolve() or any(
        absolute == root or absolute.is_relative_to(root) or root.is_relative_to(absolute)
        for root in protected
    ):
        raise _refuse()
    if absolute.exists():
        metadata = absolute.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise _refuse()
    return absolute


class _TestPreparationRefusal(InstanceStatePreflightError):
    """Redacted explicit TEST-route refusal; ordinary CLI behavior is unchanged."""


def _test_refusal() -> InstanceStatePreflightError:
    return _TestPreparationRefusal("TEST dormant ownership preparation refused")


@dataclass(frozen=True)
class _Geometry:
    path: Path
    # Ordered root-to-ancestor observations; no identity values leave private evidence.
    ancestry: tuple[tuple[int, int, int, int, int], ...]


def _capture_geometry(path: Path) -> _Geometry:
    path = Path(path).expanduser()
    try:
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        # pathlib on Python 3.12 reports a symlink loop as RuntimeError,
        # not OSError. It is unsafe input, never a public traceback/path.
        raise _test_refusal() from exc
    if not path.is_absolute() or path != canonical:
        raise _test_refusal()
    chain = (path, *path.parents)
    observations = []
    for part in chain:
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise _test_refusal()
        observations.append((info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid))
    return _Geometry(path, tuple(observations))


def _overlaps(left: _Geometry, right: _Geometry) -> bool:
    a, b = left.ancestry[0][:2], right.ancestry[0][:2]
    return (
        left.path == right.path or left.path in right.path.parents or right.path in left.path.parents
        or a in {item[:2] for item in right.ancestry}
        or b in {item[:2] for item in left.ancestry}
    )


def _private_directory(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700):
        raise _test_refusal()


def require_test_controller(proof: DeploymentQuiescenceProof, roots: tuple[Path, ...]) -> None:
    inventory = importlib.import_module("scripts.instance_state_writer_inventory")
    try:
        if (
            proof.channel_id != "test" or proof.controller_pid is None
            or inventory.controller_token(proof.controller_pid) != proof.controller_start_token
            or proof.controller_namespace_digest is None
            or inventory.controller_namespace_digest(proof.controller_pid, roots) != proof.controller_namespace_digest
        ):
            raise _test_refusal()
    except (OSError, RuntimeError) as exc:
        raise _test_refusal() from exc


_TEST_INSTANCE_STATE_RECOVERY_SCHEMA = "test-instance-state-recovery.v2"


def validate_missing_test_instance_state_recovery_authority(
    *, host_global_root: Path, authority_binding_id: str, authority_root: str,
    owner_receipt_path: Path, expected_owner_receipt_sha256: str,
    quiescence_proof_path: Path, expected_quiescence_proof_sha256: str,
    expected_ledger_sha256: str | None = None,
) -> str:
    """Authenticate complete TEST owner/ledger evidence without writing state."""
    from app.instance.runtime import (
        _load_deployment_quiescence_proof,
        _load_legacy_owner_inventory,
    )

    host = Path(host_global_root).expanduser().resolve(strict=True)
    owner_receipt = Path(owner_receipt_path).expanduser().resolve(strict=True)
    proof_path = Path(quiescence_proof_path).expanduser().resolve(strict=True)
    if (owner_receipt != host / "legacy-owner-inventory.json"
            or proof_path != host / "deployment-quiescence-proof.json"):
        raise _test_refusal()
    _private_directory(host)
    owner_bytes = _read_private_bytes(owner_receipt)
    proof_bytes = _read_private_bytes(proof_path)
    if (_sha(owner_bytes) != expected_owner_receipt_sha256
            or _sha(proof_bytes) != expected_quiescence_proof_sha256):
        raise _test_refusal()
    proof = _load_deployment_quiescence_proof(proof_path)
    proof.require_canonical_authority(
        channel_id="test", host_global_root=host,
        owner_receipt_path=owner_receipt,
    )
    scratch = VaultRegistryStore(host / ".test-recovery-preflight-registry.json")
    owners = tuple(_load_legacy_owner_inventory(
        owner_receipt, registry=scratch._empty_snapshot(), channel="test",
        quiescence_proof=proof, expected_sha256=expected_owner_receipt_sha256,
        require_receipt_integrity=True,
    ))
    try:
        ledger = OwnershipLedger(host)
        resolved = ledger.resolve_live_owner_bindings(
            tuple(replace(owner, vault_binding_id="") for owner in owners),
            allow_legacy=True,
        )
        registrations = {
            owner.vault_binding_id: owner.root
            for owner in resolved if owner.channel_id == "test"
        }
        if (not registrations or len(registrations) != len([
            owner for owner in resolved if owner.channel_id == "test"
        ]) or registrations.get(authority_binding_id) is None
                or str(registrations[authority_binding_id].expanduser().resolve(strict=False))
                != authority_root):
            raise _test_refusal()
        ledger.require_scalar_rollback_ready(
            channel_id="test", registrations=registrations,
        )
        first = _read_private_bytes(ledger.path)
        ledger.require_scalar_rollback_ready(
            channel_id="test", registrations=registrations,
        )
        second = _read_private_bytes(ledger.path)
        if first != second:
            raise _test_refusal()
        digest = _sha(second)
        if expected_ledger_sha256 is not None and digest != expected_ledger_sha256:
            raise _test_refusal()
        return digest
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, LedgerError) as exc:
        raise _test_refusal() from exc


def reconstruct_missing_test_instance_state(
    *,
    channel: str,
    failed_operation_id: str,
    candidate_revision: str,
    candidate_image_digest: str,
    authority_binding_id: str,
    authority_root: str,
    authority_ownership_root: str,
    instance_state_root: Path,
    host_global_root: Path,
    recovery_receipt_path: Path,
    owner_receipt_path: Path,
    expected_owner_receipt_sha256: str,
    quiescence_proof_path: Path,
    expected_quiescence_proof_sha256: str,
    expected_ledger_sha256: str,
    source_operation_id: str,
    authority_ownership_mount_root: str | None = None,
) -> dict[str, object]:
    """Reconstruct only the already-lost TEST instance-state authority.

    This is an explicit producer for the one known TEST-only total-loss shape.
    It is deliberately separate from consumer preflight and ordinary startup:
    every input is authenticated before the state root is touched, and retries
    are admitted only when the durable recovery receipt and source evidence are
    byte-identical.  Ownership remains in the existing host-global ledger; the
    operation never creates or rotates a key, lease, binding, or vault.
    """

    try:
        canonical_operation_id = str(UUID(failed_operation_id))
        canonical_source_operation_id = str(UUID(source_operation_id))
    except (ValueError, TypeError, AttributeError):
        raise _test_refusal() from None
    if (
        channel != "test"
        or canonical_operation_id != failed_operation_id
        or canonical_source_operation_id != source_operation_id
        or source_operation_id == failed_operation_id
        or not isinstance(candidate_revision, str)
        or len(candidate_revision) != 40
        or any(char not in "0123456789abcdef" for char in candidate_revision)
        or not isinstance(candidate_image_digest, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", candidate_image_digest)
        or not authority_binding_id.strip()
        or not authority_root.startswith("/")
        or not authority_ownership_root.startswith("/")
        or str(Path(authority_root).expanduser().resolve(strict=False)) != authority_root
    ):
        raise _test_refusal()
    for digest in (
        expected_owner_receipt_sha256,
        expected_quiescence_proof_sha256,
        expected_ledger_sha256,
    ):
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise _test_refusal()

    state = Path(instance_state_root).expanduser()
    host = Path(host_global_root).expanduser()
    authority_mount = Path(
        authority_ownership_mount_root or host_global_root
    ).expanduser()
    recovery_receipt = Path(recovery_receipt_path).expanduser()
    owner_receipt = Path(owner_receipt_path).expanduser()
    proof_path = Path(quiescence_proof_path).expanduser()
    try:
        state = state.resolve(strict=False)
        host = host.resolve(strict=True)
        authority_mount = authority_mount.resolve(strict=True)
        recovery_receipt = recovery_receipt.resolve(strict=True)
        owner_receipt = owner_receipt.resolve(strict=True)
        proof_path = proof_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _test_refusal() from exc
    if (
        not state.is_absolute()
        or not host.is_absolute()
        or not authority_mount.is_absolute()
        or authority_mount != host
        or any(parent.is_symlink() for parent in (host, *host.parents))
        or any(parent.is_symlink() for parent in (state, *state.parents) if parent.exists())
        or owner_receipt != host / "legacy-owner-inventory.json"
        or proof_path != host / "deployment-quiescence-proof.json"
        or recovery_receipt.parent != host
        or recovery_receipt.name
        != "test-instance-state-recovery-" + failed_operation_id + ".json"
    ):
        raise _test_refusal()
    _private_directory(host)
    try:
        recovery = _read_private_json(recovery_receipt)
        if set(recovery) != {
            "schema",
            "channel",
            "source_operation_id",
            "failed_successor_operation_id",
            "candidate_revision",
            "candidate_image_digest",
            "authority_cutover",
            "disposition",
            "owner_receipt_sha256",
            "quiescence_proof_sha256",
            "ledger_sha256",
        }:
            raise ValueError
        expected_recovery = {
            "schema": _TEST_INSTANCE_STATE_RECOVERY_SCHEMA,
            "channel": "test",
            "source_operation_id": source_operation_id,
            "failed_successor_operation_id": failed_operation_id,
            "candidate_revision": candidate_revision,
            "candidate_image_digest": candidate_image_digest,
            "authority_cutover": {
                "binding_id": authority_binding_id,
                "root": authority_root,
                "ownership_root": authority_ownership_root,
            },
            "disposition": "complete",
            "owner_receipt_sha256": expected_owner_receipt_sha256,
            "quiescence_proof_sha256": expected_quiescence_proof_sha256,
            "ledger_sha256": expected_ledger_sha256,
        }
        if recovery != expected_recovery:
            raise ValueError
        owner_bytes = _read_private_bytes(owner_receipt)
        proof_bytes = _read_private_bytes(proof_path)
        if (
            _sha(owner_bytes) != expected_owner_receipt_sha256
            or _sha(proof_bytes) != expected_quiescence_proof_sha256
        ):
            raise ValueError
        proof = _read_private_json(proof_path)
        if proof.get("channel_id") != "test":
            raise ValueError
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise _test_refusal() from exc

    from app.instance.runtime import (
        _deployment_admission_locked,
        _load_deployment_quiescence_proof,
        _load_legacy_owner_inventory,
        _materialize_authenticated_channel_registrations,
        _producer_transition_locked,
    )

    layout = InstanceStateLayout.for_channel(state, "test")
    # The mounted root must already exist, but the explicit producer may create
    # only its managed app-local child.  No arbitrary path or symlink is adopted.
    if not state.is_dir():
        raise _test_refusal()
    try:
        _private_directory(state)
    except OSError as exc:
        raise _test_refusal() from exc

    ledger = OwnershipLedger(host)
    # Existing authority is a hard prerequisite.  Check artifact presence
    # before creating the recovered app-local lock directory; the authenticated
    # ledger read itself occurs after the deployment and producer locks below.
    try:
        if not ledger.path.is_file() or not ledger.key_path.is_file():
            raise _test_refusal()
        proof_object = _load_deployment_quiescence_proof(proof_path)
        proof_object.require_canonical_authority(
            channel_id="test", host_global_root=host, owner_receipt_path=owner_receipt
        )
        validate_missing_test_instance_state_recovery_authority(
            host_global_root=host,
            authority_binding_id=authority_binding_id,
            authority_root=authority_root,
            owner_receipt_path=owner_receipt,
            expected_owner_receipt_sha256=expected_owner_receipt_sha256,
            quiescence_proof_path=proof_path,
            expected_quiescence_proof_sha256=expected_quiescence_proof_sha256,
            expected_ledger_sha256=expected_ledger_sha256,
        )
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, LedgerError,
            InstanceStatePreflightError) as exc:
        raise _test_refusal() from exc

    from app.instance.vault_registry import VaultRegistryStore

    store = VaultRegistryStore(layout.registry_path)
    marker_result_path = host / (
        "test-instance-state-recovery-result-" + failed_operation_id + ".json"
    )
    # Parse and bind the immutable owner receipt before creating the recovered
    # app-local root.  A caller-supplied authority tuple that drifts from the
    # stopped-window receipt therefore leaves the missing state volume wholly
    # untouched.
    try:
        snapshot = store._empty_snapshot()
        owners = tuple(
            _load_legacy_owner_inventory(
                owner_receipt,
                registry=snapshot,
                channel="test",
                quiescence_proof=proof_object,
                expected_sha256=expected_owner_receipt_sha256,
                require_receipt_integrity=True,
            )
        )
        if not owners or any(
            owner.channel_id not in {"dev", "native", "prod", "test"}
            for owner in owners
        ):
            raise _test_refusal()
        selected_owners = [
            owner
            for owner in owners
            if str(owner.root.expanduser().resolve(strict=False)) == authority_root
            and owner.channel_id == "test"
        ]
        if len(selected_owners) != 1:
            raise _test_refusal()
        if (
            selected_owners[0].vault_binding_id
            and selected_owners[0].vault_binding_id != authority_binding_id
        ):
            raise _test_refusal()
    except (OSError, RuntimeError, ValueError, TypeError, KeyError,
            InstanceStatePreflightError) as exc:
        raise _test_refusal() from exc
    # The normal producer lock lives inside the managed app-local root.  The
    # immutable evidence and authority tuple have already been checked above;
    # only now may this explicit producer create that missing lock directory.
    try:
        layout.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _private_directory(layout.root)
    except OSError as exc:
        raise _test_refusal() from exc
    try:
        with _deployment_admission_locked(host), _producer_transition_locked(layout):
            validate_missing_test_instance_state_recovery_authority(
                host_global_root=host,
                authority_binding_id=authority_binding_id,
                authority_root=authority_root,
                owner_receipt_path=owner_receipt,
                expected_owner_receipt_sha256=expected_owner_receipt_sha256,
                quiescence_proof_path=proof_path,
                expected_quiescence_proof_sha256=expected_quiescence_proof_sha256,
                expected_ledger_sha256=expected_ledger_sha256,
            )
            # The existing runtime materializer uses the canonical store
            # transaction/snapshot/export APIs and validates every owner against
            # the established ledger.  The receipt was parsed above from an
            # in-memory dormant revision-zero snapshot, before any state write.
            try:
                # Resolve from physical identities rather than trusting a
                # caller- or receipt-supplied binding string.  The existing
                # ledger is the authority; returned bindings are the only
                # values allowed into the new dormant registry.
                resolved_owners = ledger.resolve_live_owner_bindings(
                    tuple(replace(owner, vault_binding_id="") for owner in owners),
                    allow_legacy=True,
                )
            except LedgerError as exc:
                raise _test_refusal() from exc
            selected_resolved = [
                owner
                for owner in resolved_owners
                if owner.channel_id == "test"
                and owner.vault_binding_id == authority_binding_id
                and str(owner.root.expanduser().resolve(strict=False)) == authority_root
            ]
            if len(selected_resolved) != 1:
                raise _test_refusal()

            # Recover an early transaction journal before inspecting the main
            # registry.  A crash can leave only the journal (or a partial
            # generation) while the main file is absent; the canonical store
            # recovery path must roll that back to an authenticated empty
            # materialization point instead of treating it as foreign state.
            materialized = None
            if os.path.lexists(store.transaction_path):
                with store._locked(recover_transactions=True):
                    if store.path.is_file():
                        materialized = store._read_current_locked(recover=False)

            # Existing artifacts are accepted only as the exact idempotent
            # result of this request.  A foreign or partial generation refuses
            # after any canonical journal recovery has completed.
            artifacts = (
                layout.registry_path,
                store.snapshot_path,
                store.snapshot_checksum_path,
                store.rollback_export_path,
            )
            has_artifacts = any(os.path.lexists(path) for path in artifacts)
            if marker_result_path.exists() and not has_artifacts and materialized is None:
                raise _test_refusal()
            if materialized is None and has_artifacts:
                if not store.path.is_file():
                    raise _test_refusal()
                with store._locked(recover_transactions=True):
                    materialized = store._read_current_locked(recover=False)
            # A durable result marker binds the exact already-validated
            # generation. Validate it before calling the materializer because
            # that path may resume partial state with registry writes.
            if marker_result_path.is_file():
                if materialized is None:
                    raise _test_refusal()
                prior = _read_private_json(marker_result_path)
                if (
                    prior.get("request") != recovery
                    or prior.get("registry_revision") != materialized.revision
                    or prior.get("registry_sha256")
                    != _sha(_read_private_bytes(store.path))
                    or prior.get("ledger_sha256") != expected_ledger_sha256
                ):
                    raise _test_refusal()
                validate_missing_test_instance_state_recovery_authority(
                    host_global_root=host,
                    authority_binding_id=authority_binding_id,
                    authority_root=authority_root,
                    owner_receipt_path=owner_receipt,
                    expected_owner_receipt_sha256=expected_owner_receipt_sha256,
                    quiescence_proof_path=proof_path,
                    expected_quiescence_proof_sha256=expected_quiescence_proof_sha256,
                    expected_ledger_sha256=expected_ledger_sha256,
                )
                return prior
            # Always route the current generation through the canonical
            # materializer. Besides resuming authenticated partial writes, it
            # validates complete recovery-provenance registrations against the
            # receipt-derived path/ref before an idempotent result is accepted.
            materialized = _materialize_authenticated_channel_registrations(
                channel="test",
                registry=store,
                ledger=ledger,
                owners=resolved_owners,
                owners_authenticated=True,
            )
            if (
                materialized.authority != "dormant"
                or materialized.revision < 1
                or not materialized.registrations
                or set(materialized.registrations)
                != {
                    owner.vault_binding_id
                    for owner in resolved_owners
                    if owner.channel_id == "test"
                }
                or any(
                    item.extensions.get("provenance")
                    != "authenticated_legacy_owner_inventory"
                    for item in materialized.registrations.values()
                )
            ):
                raise _test_refusal()
            result = {
                "schema": _TEST_INSTANCE_STATE_RECOVERY_SCHEMA,
                "channel": "test",
                "request": recovery,
                "registry_revision": materialized.revision,
                "registry_sha256": _sha(_read_private_bytes(store.path)),
                "ledger_sha256": expected_ledger_sha256,
                "activation": "inactive_fenced",
                "registered_bindings": sorted(materialized.registrations),
            }
            _atomic_private_write(
                marker_result_path,
                (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            )
            return result
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, LedgerError,
            InstanceStatePreflightError) as exc:
        raise _test_refusal() from exc


def qualify_test_native_source(
    *, channel: str, source_root: Path, expected_revision: str,
    instance_state_root: Path, host_global_root: Path, controller_pid: int,
    controller_start_token: str, runtime_uid: int, runtime_gid: int,
    native_launcher: Path | None = None,
) -> dict[str, object]:
    """Read-only qualification, not an installation, namespace grant or authority.

    The future preparation caller uses this same interpreter/source tree for
    every command; native proofs are produced directly with native paths.
    """
    context = capture_test_native_context(channel=channel, source_root=source_root,
        expected_revision=expected_revision, instance_state_root=instance_state_root,
        host_global_root=host_global_root, controller_pid=controller_pid,
        controller_start_token=controller_start_token, runtime_uid=runtime_uid,
        runtime_gid=runtime_gid, native_launcher=native_launcher or Path(sys.executable))
    return {"channel": "test", "qualified": True, "source_revision": expected_revision,
        "native_context_sha256": _sha(_bytes(context)), "activation": "inactive_fenced"}


def _native_file_identity(path: Path) -> dict[str, object]:
    path = path.absolute()
    resolved = path.resolve(strict=True)
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode):
        raise _test_refusal()
    # Retain lexical launcher symlinks as well as the actual executable bytes.
    chain = []
    for component in (path, *path.parents):
        value = component.lstat()
        chain.append([str(component), value.st_dev, value.st_ino, value.st_mode,
            value.st_uid, value.st_gid, os.readlink(component) if component.is_symlink() else None])
    return {"path": str(path), "resolved": str(resolved), "chain": chain,
        "file": [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns], "sha256": _sha(resolved.read_bytes())}


def capture_test_native_context(
    *, channel: str, source_root: Path, expected_revision: str,
    instance_state_root: Path, host_global_root: Path, controller_pid: int,
    controller_start_token: str, runtime_uid: int, runtime_gid: int, native_launcher: Path,
) -> dict[str, Any]:
    """Private original context, carried only in existing safety/proof formats."""
    inventory = importlib.import_module("scripts.instance_state_writer_inventory")
    roots = (source_root, instance_state_root, host_global_root)
    try:
        if (channel != "test" or os.geteuid() != runtime_uid or os.getegid() != runtime_gid
            or len(expected_revision) != 40
            or any(c not in "0123456789abcdef" for c in expected_revision)):
            raise _test_refusal()
        geometry = [_capture_geometry(root) for root in roots]
        for root in roots[1:]:
            _private_directory(root)
        source = Path(source_root)
        modules = {}
        for name in ("app.instance.runtime", "app.instance.legacy_owner_recovery",
            "app.instance.ownership_ledger", "app.instance.instance_state",
            "scripts.instance_state_writer_inventory"):
            module = __import__(name, fromlist=["__file__"])
            origin = Path(str(module.__file__)).resolve(strict=True)
            if origin != source / (name.replace(".", "/") + ".py"):
                raise _test_refusal()
            modules[name] = _native_file_identity(origin)
        # Every loaded repository dependency must belong to the reviewed tree,
        # not an editable install or a code-file mount over an unrelated image.
        for name, module in tuple(sys.modules.items()):
            if name.startswith(("app.", "scripts.")) and getattr(module, "__file__", None):
                if not Path(str(module.__file__)).resolve(strict=True).is_relative_to(source):
                    raise _test_refusal()
        def git(*args: str) -> str:
            git_environment = {key: value for key, value in os.environ.items()
                if not key.startswith("GIT_")}
            git_environment |= {"GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull}
            result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(source), *args],
                check=True, capture_output=True, text=True, env=git_environment)
            return result.stdout.strip()
        if git("rev-parse", "HEAD") != expected_revision or git("status", "--porcelain", "--untracked-files=normal"):
            raise _test_refusal()
        if inventory.controller_token(controller_pid) != controller_start_token:
            raise _test_refusal()
        namespace = inventory.controller_namespace_digest(controller_pid, roots)
        context = {"source_root": str(source), "source_revision": expected_revision,
            "instance_state_root": str(instance_state_root), "host_global_root": str(host_global_root),
            "geometry": [(str(g.path), g.ancestry) for g in geometry], "modules": modules,
            "launcher": _native_file_identity(native_launcher),
            "interpreter": _native_file_identity(Path(sys.executable)),
            "runtime_uid": runtime_uid, "runtime_gid": runtime_gid,
            "controller_pid": controller_pid, "controller_start_token": controller_start_token,
            "controller_namespace_digest": namespace}
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        raise _test_refusal() from exc
    return json.loads(_bytes(context))


def require_test_native_context(context: object) -> dict[str, Any]:
    try:
        if not isinstance(context, dict):
            raise _test_refusal()
        current = capture_test_native_context(channel="test", source_root=Path(context["source_root"]),
            expected_revision=context["source_revision"], instance_state_root=Path(context["instance_state_root"]),
            host_global_root=Path(context["host_global_root"]), controller_pid=context["controller_pid"],
            controller_start_token=context["controller_start_token"], runtime_uid=context["runtime_uid"],
            runtime_gid=context["runtime_gid"], native_launcher=Path(context["launcher"]["path"]))
        if current != context:
            raise _test_refusal()
        return current
    except (KeyError, TypeError, OSError, RuntimeError, ValueError) as exc:
        raise _test_refusal() from exc


@contextmanager
def native_operation_refusal(host: Path | None, *, required: bool = False) -> Iterator[Callable[[], None]]:
    """Keep expected private-input/durability errors inside the native envelope.

    Selection is sticky through cleanup: one intact native safety mirror (or
    explicit native helper mode) suffices even when another mirror is damaged.
    This only selects error presentation, never authorizes the operation. With
    no native selection, ordinary exceptions and CLI behavior remain unchanged.
    """
    native = required
    def observe() -> None:
        nonlocal native
        for path in _reservation_records(host) if host is not None else ():
            try:
                if _read_private_json(path).get(_NATIVE_CONTEXT) is not None:
                    native = True
            except (OSError, RuntimeError, ValueError):
                pass  # The operation still validates every authority read.
    observe()
    try:
        yield observe
    except (OSError, RuntimeError, ValueError) as exc:
        if native:
            raise _test_refusal() from exc
        raise


def require_native_window(host: Path, *, required: bool = False) -> dict[str, Any] | None:
    with native_operation_refusal(host, required=required):
        return _require_native_window(host, required=required)


def _require_native_window(host: Path, *, required: bool = False) -> dict[str, Any] | None:
    values = [_read_private_json(p).get(_NATIVE_CONTEXT)
        for p in _reservation_records(host) if os.path.lexists(p)]
    contexts = [value for value in values if value is not None]
    if not contexts and not required:
        return None
    if not contexts or any(value != contexts[0] for value in values):
        raise _test_refusal()
    context = require_test_native_context(contexts[0])
    if context["host_global_root"] != str(host):
        raise _test_refusal()
    public, _, compatibility = _reservation_records(host)
    lease = _read_private_json(public if os.path.lexists(public) else compatibility)
    nonce = lease.get("nonce")
    inventory_path = host / "deployment-quiescence-inventory.json"
    if os.path.lexists(inventory_path):
        inventory = _read_private_json(inventory_path)
        if inventory.get("deployment_nonce") != nonce or inventory.get(_NATIVE_CONTEXT) != context:
            raise _test_refusal()
    proof_path = host / "deployment-quiescence-proof.json"
    if os.path.lexists(proof_path):
        proof = _read_private_json(proof_path)
        if proof.get("nonce") != nonce or proof.get(_NATIVE_CONTEXT) != context:
            raise _test_refusal()
    return context


def require_native_begin_context(host: Path, context: dict[str, object] | None,
    *, retire_inventory: bool = False) -> None:
    """Admission-lock-held native begin; never adopt or upgrade another claim.

    A released window's private census is rebuildable, not authority. Retire it
    only before the first blocker of a genuinely fresh claim. Once any claim
    exists, every inventory/proof must instead match its exact original context
    and nonce, including a root-only crash retry. The caller repeats this check
    after setup and holds admission through retirement and first publication.
    """
    if context is None:
        if require_native_window(host) is not None:
            raise _test_refusal()
        return  # Ordinary begin remains unchanged when no native claim exists.
    records = _reservation_records(host)
    fences = tuple(host.glob("deployment-*-restart-fence.json"))
    if any(path != records[1] for path in fences):
        raise _test_refusal()
    if any(os.path.lexists(path) for path in records):
        if (require_native_window(host, required=True) != context
            or read_preparation_reservation(host) is not None):
            raise _test_refusal()
        return
    # lexists includes dangling symlinks: missing targets are not absence of
    # safety evidence. No proof/fence/pending mirror may be retired as census.
    if fences or os.path.lexists(host / "deployment-quiescence-proof.json"):
        raise _test_refusal()
    inventory_path = host / "deployment-quiescence-inventory.json"
    if os.path.lexists(inventory_path):
        from app.instance.runtime import _CONTROLLER_START_TOKEN_RE, _QUIESCENCE_INVENTORY_SCHEMA
        inventory = _read_private_json(inventory_path)
        domains: dict[str, list[object]] = {name: [] for name in ("dev", "native", "prod", "test")}
        digest = hashlib.sha256(json.dumps(domains, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        controller = inventory.get("controller")
        prior_context = inventory.get(_NATIVE_CONTEXT)
        prior_nonce = inventory.get("deployment_nonce")
        if (inventory.get("schema") != _QUIESCENCE_INVENTORY_SCHEMA
            or inventory.get("inventory_complete") is not True
            or inventory.get("all_consumers_stopped") is not True
            or inventory.get("probe_count") != 2 or inventory.get("domains") != domains
            or inventory.get("snapshot_digests") != [digest, digest]
            or not isinstance(controller, dict) or type(controller.get("pid")) is not int
            or controller["pid"] <= 0
            or _CONTROLLER_START_TOKEN_RE.fullmatch(str(controller.get("start_token") or "")) is None
            or (prior_context is None and prior_nonce is not None)
            or (prior_context is not None and (not isinstance(prior_context, dict)
                or not isinstance(prior_nonce, str) or len(prior_nonce) != 32
                or any(char not in "0123456789abcdef" for char in prior_nonce)))):
            raise _test_refusal()
        if retire_inventory:
            inventory_path.unlink()
            _fsync_directory(host)
    if retire_inventory:
        # Retirement's durability barrier is itself an observation gap. Never
        # mint the next nonce/root blocker from a context changed during it.
        require_test_native_context(context)


def _reservation_records(host: Path) -> tuple[Path, ...]:
    return (
        host / "deployment-public" / "deployment-host-global-lease.json",
        host / "deployment-test-restart-fence.json",
        host / "deployment-host-global-lease.json",
    )


def read_preparation_reservation(host: Path) -> dict[str, object] | None:
    """Read all mirrors; a partial reservation is pending, never absent."""
    found: list[dict[str, object]] = []
    for path in _reservation_records(host):
        if not os.path.lexists(path):
            continue
        value = _read_private_json(path)
        if _PREPARATION in value:
            reservation = value[_PREPARATION]
            if value.get("channel_id") != "test" or not isinstance(reservation, dict):
                raise _test_refusal()
            found.append(reservation)
    if not found:
        return None
    if any(item != found[0] for item in found):
        raise _test_refusal()
    return found[0]


def _authenticate_prepared_package(
    package: Path,
) -> tuple[dict[str, Any], dict[str, bytes], _KeyMaterial, LedgerSnapshot]:
    _private_directory(package)
    manifest: dict[str, Any] = _read_private_json(package / "manifest.json")
    op = manifest.get("dormant_ownership")
    checksums = manifest.get("checksums")
    if (manifest.get("schema") != "agentic-pkm.instance-state-backup.v1"
        or manifest.get("channel_id") != "test" or not isinstance(op, dict)
        or not isinstance(checksums, dict) or op.get("before") != {"key": None, "ledger": None}
        or op.get("decision") != "explicit-new-ownership-epoch"
        or op.get("activation") != "inactive_fenced"):
        raise _test_refusal()
    if set(p.name for p in package.iterdir()) != {*checksums, "manifest.json"}:
        raise _test_refusal()
    payloads = {name: _read_private_bytes(package / name) for name in checksums
        if isinstance(name, str) and Path(name).name == name}
    if len(payloads) != len(checksums) or any(_sha(raw) != checksums[name] for name, raw in payloads.items()):
        raise _test_refusal()
    parser = OwnershipLedger(package)
    key = parser._parse_key_value(json.loads(payloads["ownership-key.json"]))
    ledger = parser._parse_ledger_value(json.loads(payloads["ownership-ledger.json"]))
    signed = dict(manifest)
    auth = signed.pop("authentication", None)
    if (len(key.secret) != 32 or ledger.key_id != key.key_id or ledger.generation != key.generation
        or ledger.schema != LEDGER_SCHEMA or not ledger.legacy_bootstrap_complete
        or not isinstance(auth, str)
        or not hmac.compare_digest(auth, hmac.new(key.secret, _bytes(signed), hashlib.sha256).hexdigest())):
        raise _test_refusal()
    return manifest, payloads, key, ledger


def _reservation_for(package: Path, destination: Path, sibling: Path) -> dict[str, object]:
    manifest, payloads, _, _ = _authenticate_prepared_package(package)
    op = manifest["dormant_ownership"]
    return {"backup_root": str(destination), "sibling": str(sibling),
        "epoch_id": op["epoch_id"], "input_digest": op["input_digest"],
        "manifest_sha256": _sha(_read_private_bytes(package / "manifest.json")),
        "ledger_sha256": _sha(payloads["ownership-ledger.json"]),
        "key_sha256": _sha(payloads["ownership-key.json"])}


def require_completed_preparation(host: Path) -> None:
    """Ordinary callers may remove safety state only after exact pair durability.

    No TEST reservation means no changed behavior for ordinary/legacy consumers.
    This authenticates existing evidence; it cannot initialize or recover a pair.
    """
    require_native_window(host)
    reserved = read_preparation_reservation(host)
    if reserved is None:
        return
    try:
        destination = Path(str(reserved["backup_root"]))
        sibling = Path(str(reserved["sibling"]))
        _capture_geometry(destination)
        manifest, payloads, _, _ = _authenticate_prepared_package(destination)
        if _reservation_for(destination, destination, sibling) != reserved:
            raise _test_refusal()
        op = manifest["dormant_ownership"]
        if op["host_global_root"] != str(host):
            raise _test_refusal()
        context = require_native_window(host, required=True)
        proof_path = host / "deployment-quiescence-proof.json"
        # The existing authenticated backup retains the original proof bytes;
        # cleanup may already have unlinked the canonical copy before a crash.
        original_proof = payloads["deployment-quiescence-proof.json"]
        if (_sha(original_proof) != op["proof_sha256"]
            or json.loads(original_proof).get(_NATIVE_CONTEXT) != context
            or (os.path.lexists(proof_path) and _read_private_bytes(proof_path) != original_proof)):
            raise _test_refusal()
        for name in ("ownership-key.json", "ownership-ledger.json"):
            if _read_private_bytes(host / name) != payloads[name]:
                raise _test_refusal()
        # Repeat every publication/pair barrier even when bytes are visible.
        _fsync_directory(destination)
        _fsync_directory(destination.parent)
        _fsync_directory(host)
        _fsync_directory(host / "deployment-public")
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise _test_refusal() from exc


def initialize_dormant_ownership(
    *, channel: str, instance_state_root: Path, host_global_root: Path,
    vault_binding_id: str, expected_registry_sha256: str, owner_receipt_path: Path,
    expected_owner_receipt_sha256: str, quiescence_proof_path: Path,
    backup_root: Path, acknowledge_new_ownership_epoch: bool,
) -> dict[str, object]:
    """Prepare one explicitly acknowledged TEST epoch, leaving activation fenced."""
    from app.instance.runtime import (
        _deployment_admission_locked, _load_deployment_quiescence_proof,
        _legacy_owner_identity_evidence, _producer_transition_locked, _replace_private_json,
    )
    if channel != "test" or not acknowledge_new_ownership_epoch or not vault_binding_id:
        raise _test_refusal()
    for digest in (expected_registry_sha256, expected_owner_receipt_sha256):
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise _test_refusal()
    state, host = Path(instance_state_root), Path(host_global_root)
    state_geometry, host_geometry = _capture_geometry(state), _capture_geometry(host)
    _private_directory(state)
    _private_directory(host)
    if _overlaps(state_geometry, host_geometry):
        raise _test_refusal()
    layout = InstanceStateLayout.for_channel(state, channel)
    layout.require_existing()
    ledger, store = OwnershipLedger(host), VaultRegistryStore(layout.registry_path)
    if (quiescence_proof_path != host / "deployment-quiescence-proof.json"
        or owner_receipt_path != host / "legacy-owner-inventory.json"):
        raise _test_refusal()
    destination = Path(backup_root)
    parent_geometry = _capture_geometry(destination.parent)
    if not destination.is_absolute() or destination.name in {"", ".", ".."}:
        raise _test_refusal()
    witness: tuple[_Geometry, ...] = (state_geometry, host_geometry, _capture_geometry(layout.root),
        _capture_geometry(host / "deployment-public"), parent_geometry)
    if os.path.lexists(store.transaction_path) or os.path.lexists(ledger.rotation_path):
        raise _test_refusal()
    with _deployment_admission_locked(host), _producer_transition_locked(layout), \
        ledger._locked(recover_rotation=False), store._locked(recover_transactions=False):
        registry = store._read_current_locked(recover=False)
        if (registry.authority != "dormant" or registry.revision < 1
            or set(registry.registrations) != {vault_binding_id}
            or registry.removal_tombstones or registry.transfer_lineage
            or os.path.lexists(store.transaction_path) or os.path.lexists(ledger.rotation_path)):
            raise _test_refusal()
        registration = registry.registrations[vault_binding_id]
        if not registration.vault_id or not registration.local_instance_id:
            raise _test_refusal()
        content = Path(registration.path)
        content_geometry = _capture_geometry(content)
        if any(_overlaps(content_geometry, geo) for geo in (state_geometry, host_geometry)):
            raise _test_refusal()
        if any(destination == root.path or destination in root.path.parents
            or root.path in destination.parents for root in (content_geometry, state_geometry, host_geometry)):
            raise _test_refusal()
        # Prospective destinations have exactly one missing terminal component.
        # Comparing their nearest parent catches case/physical aliases while
        # permitting safe siblings beneath a common parent.
        if any(root.ancestry[0][:2] in {item[:2] for item in parent_geometry.ancestry}
            for root in (content_geometry, state_geometry, host_geometry)):
            raise _test_refusal()
        destination_geometry: _Geometry | None = None
        if os.path.lexists(destination):
            actual = _capture_geometry(destination)
            if any(_overlaps(actual, root) for root in (content_geometry, state_geometry, host_geometry)):
                raise _test_refusal()
            destination_geometry = actual
        witness += (content_geometry,)
        proof = _load_deployment_quiescence_proof(quiescence_proof_path)
        raw_proof = _read_private_bytes(quiescence_proof_path)
        raw_owner = _read_private_bytes(owner_receipt_path)
        registry_bytes = _read_private_bytes(store.path)
        if _sha(raw_owner) != expected_owner_receipt_sha256 or _sha(registry_bytes) != expected_registry_sha256:
            raise _test_refusal()
        owner_payload = proof.require_canonical_authority(channel_id="test", host_global_root=host,
            owner_receipt_path=owner_receipt_path)
        context = require_native_window(host, required=True)
        if context is None or proof.native_execution_context != context or context["instance_state_root"] != str(state):
            raise _test_refusal()
        require_test_controller(proof, (state, host, content, destination.parent))
        identities = _legacy_owner_identity_evidence(owner_payload)
        owners = owner_payload.get("owners")
        source_evidence = owner_payload.get("source_evidence")
        if (not isinstance(owners, list) or len(owners) != 1
            or len(identities) != 1 or not isinstance(source_evidence, dict)
            or source_evidence.get("retired_owner_identities")
            or not source_evidence.get("docker") or not source_evidence.get("config")):
            raise _test_refusal()
        owner_row = owners[0]
        if (owner_row.get("channel_id") != "test" or owner_row.get("root") != str(content)
            or owner_row.get("vault_binding_id") not in (None, "", vault_binding_id)):
            raise _test_refusal()
        identity, ancestors, physical = identities[("test", str(content))]
        expected_identity = f"inode:{content_geometry.ancestry[0][0]}:{content_geometry.ancestry[0][1]}"
        expected_physical = tuple(f"inode:{item[0]}:{item[1]}" for item in content_geometry.ancestry[1:])
        if (identity != expected_identity or set(ancestors) != {f"path:{p}" for p in content.parents}
            or len(ancestors) != len(content.parents) or physical != expected_physical):
            raise _test_refusal()
        # The explicit operator binding, not inventory order/path guessing,
        # establishes the association with the one physically attested owner.
        owner = LegacyOwner("test", vault_binding_id, content, identity, ancestors, physical,
            proof.owner_receipt_digest)
        payloads = {"deployment-quiescence-proof.json": raw_proof, "vault-registry.md": registry_bytes,
            "vault-registry.md.last-good": _read_private_bytes(store.snapshot_path),
            "vault-registry.md.last-good.sha256": _read_private_bytes(store.snapshot_checksum_path),
            "vault-registry.md.legacy-export": _read_private_bytes(store.rollback_export_path)}
        if (payloads["vault-registry.md.last-good"] != registry_bytes
            or payloads["vault-registry.md.last-good.sha256"].decode().strip() != _sha(registry_bytes)
            or payloads["vault-registry.md.legacy-export"] != store._rollback_export_payload(registry)):
            raise _test_refusal()
        inputs = {"state": str(state), "host": str(host), "destination": str(destination),
            "binding": vault_binding_id, "registry": expected_registry_sha256,
            "owner": expected_owner_receipt_sha256, "proof": _sha(raw_proof),
            "geometry": [(str(g.path), g.ancestry) for g in witness]}
        input_digest = _sha(_bytes(inputs))
        package_geometry: _Geometry | None = None

        def recheck() -> None:
            if require_native_window(host, required=True) != context:
                raise _test_refusal()
            if any(_capture_geometry(g.path) != g for g in witness):
                raise _test_refusal()
            if (_read_private_bytes(store.path) != registry_bytes
                or _read_private_bytes(owner_receipt_path) != raw_owner
                or _read_private_bytes(quiescence_proof_path) != raw_proof
                or os.path.lexists(store.transaction_path) or os.path.lexists(ledger.rotation_path)):
                raise _test_refusal()
            proof.require_canonical_authority(channel_id="test", host_global_root=host,
                owner_receipt_path=owner_receipt_path)
            require_test_controller(proof, (state, host, content, destination.parent))
            if destination_geometry is None:
                if os.path.lexists(destination):
                    raise _test_refusal()
            elif _capture_geometry(destination) != destination_geometry:
                raise _test_refusal()
            if package_geometry is not None:
                current_package = _capture_geometry(package_geometry.path)
                if current_package != package_geometry or any(_overlaps(current_package, root)
                    for root in (content_geometry, state_geometry, host_geometry)):
                    raise _test_refusal()

        recheck()
        reserved = read_preparation_reservation(host)
        if reserved is None:
            if os.path.lexists(destination) or os.path.lexists(ledger.key_path) or os.path.lexists(ledger.path):
                raise _test_refusal()
            key = _KeyMaterial(f"key-{uuid.uuid4()}", 1, secrets.token_bytes(32))
            candidate = LedgerSnapshot(LEDGER_SCHEMA, 1, key.key_id,
                leases={vault_binding_id: ledger._lease_for_legacy_owner(owner, key=key)},
                legacy_bootstrap_complete=True)
            payloads |= {"ownership-key.json": _bytes(ledger._key_value(key)),
                "ownership-ledger.json": _bytes(ledger._ledger_value(candidate))}
            manifest: dict[str, Any] = {"schema": "agentic-pkm.instance-state-backup.v1", "channel_id": "test",
                "registry_checksum": expected_registry_sha256,
                "ownership_key_id": key.key_id, "ownership_generation": 1,
                "checksums": {name: _sha(raw) for name, raw in payloads.items()},
                "dormant_ownership": {"epoch_id": str(uuid.uuid4()), "input_digest": input_digest,
                    "before": {"key": None, "ledger": None}, "instance_state_root": str(state),
                    "host_global_root": str(host), "registry_sha256": expected_registry_sha256,
                    "owner_receipt_sha256": expected_owner_receipt_sha256, "proof_sha256": _sha(raw_proof),
                    "deployment_nonce": proof.nonce, "decision": "explicit-new-ownership-epoch",
                    "activation": "inactive_fenced"}}
            manifest["authentication"] = hmac.new(key.secret, _bytes(manifest), hashlib.sha256).hexdigest()
            recheck()
            sibling = Path(tempfile.mkdtemp(prefix=f".{destination.name}-prepared-", dir=destination.parent))
            sibling_geometry = _capture_geometry(sibling)
            package_geometry = sibling_geometry
            # Before reservation, interrupted proposals have no authority. They
            # are left private for diagnosis; never guessed as resumable epochs.
            for name, raw in payloads.items():
                recheck()
                if _capture_geometry(sibling) != sibling_geometry:
                    raise _test_refusal()
                _atomic_private_write(sibling / name, raw)
            recheck()
            _atomic_private_write(sibling / "manifest.json", _bytes(manifest))
            recheck()
            _fsync_directory(sibling)
            recheck()
            _fsync_directory(sibling.parent)
            reserved = _reservation_for(sibling, destination, sibling)
        else:
            if reserved.get("backup_root") != str(destination) or reserved.get("input_digest") != input_digest:
                raise _test_refusal()
            sibling = Path(str(reserved.get("sibling")))
            if sibling.parent != destination.parent or not sibling.name.startswith(f".{destination.name}-prepared-"):
                raise _test_refusal()
            if os.path.lexists(sibling) == os.path.lexists(destination):
                raise _test_refusal()
            sibling_geometry = _capture_geometry(sibling if sibling.exists() else destination)
            package_geometry = sibling_geometry
        package = destination if destination.exists() else sibling
        manifest, payloads, _, _ = _authenticate_prepared_package(package)
        if (_reservation_for(package, destination, sibling) != reserved
            or manifest["dormant_ownership"]["input_digest"] != input_digest):
            raise _test_refusal()
        for name in ("ownership-key.json", "ownership-ledger.json"):
            if os.path.lexists(host / name) and _read_private_bytes(host / name) != payloads[name]:
                raise _test_refusal()
        for record in _reservation_records(host):
            recheck()
            value = _read_private_json(record)
            if value.get(_PREPARATION) not in (None, reserved):
                raise _test_refusal()
            if value.get(_PREPARATION) is None:
                _replace_private_json(record, value | {_PREPARATION: reserved})
            # Visible mirrors are not evidence of completed directory barriers.
            recheck()
            _fsync_directory(record.parent)
        recheck()
        if package == sibling:
            if _capture_geometry(sibling) != sibling_geometry or os.path.lexists(destination):
                raise _test_refusal()
            _fsync_directory(sibling)
            _fsync_directory(sibling.parent)
            recheck()
            os.rename(sibling, destination)
            package_geometry = replace(sibling_geometry, path=destination)
            destination_geometry = package_geometry
        recheck()
        _fsync_directory(destination)
        recheck()
        _fsync_directory(destination.parent)
        if _reservation_for(destination, destination, sibling) != read_preparation_reservation(host):
            raise _test_refusal()
        for name in ("ownership-key.json", "ownership-ledger.json"):
            recheck()
            if not os.path.lexists(host / name):
                _atomic_private_write(host / name, payloads[name])
            if _read_private_bytes(host / name) != payloads[name]:
                raise _test_refusal()
            recheck()
            _fsync_directory(host)
        recheck()
        require_completed_preparation(host)
        return {"channel": "test", "prepared": True,
            "epoch_id": manifest["dormant_ownership"]["epoch_id"],
            "activation": "inactive_fenced", "prior_effects": "not_inferred",
            "registry_sha256": expected_registry_sha256}


def reattest_legacy_owner(
    *, channel: str, instance_state_root: Path, host_global_root: Path,
    backup_root: Path, quiescence_proof_path: Path, owner_receipt_path: Path,
    vault_binding_id: str, expected_ledger_sha256: str, expected_registry_sha256: str,
    acknowledge_new_ownership_epoch: bool,
) -> dict[str, object]:
    # Import at the CLI boundary to avoid coupling normal admission to recovery.
    from app.instance.runtime import (
        _assert_mount_root,
        _deployment_admission_locked,
        _load_deployment_quiescence_proof,
        _load_legacy_owner_inventory,
        _producer_transition_locked,
    )

    if channel != "dev" or not acknowledge_new_ownership_epoch or not vault_binding_id:
        raise _refuse()
    for digest in (expected_ledger_sha256, expected_registry_sha256):
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise _refuse()
    state = _assert_mount_root(instance_state_root, "instance-state")
    ownership = _assert_mount_root(host_global_root, "host-global")
    layout = InstanceStateLayout.for_channel(state, channel)
    layout.require_existing()
    ledger = OwnershipLedger(ownership)
    store = VaultRegistryStore(layout.registry_path)
    proof = _load_deployment_quiescence_proof(quiescence_proof_path)

    # Same ordering as finalization/backup. No normal writer or key rotation can
    # interleave the captured generation or the final ledger replacement.
    with _deployment_admission_locked(ownership), _producer_transition_locked(layout):
        proof.require_canonical_authority(
            channel_id=channel, host_global_root=ownership,
            owner_receipt_path=owner_receipt_path,
        )
        ledger._assert_existing_artifacts()
        if os.path.lexists(ledger.rotation_path) or os.path.lexists(store.transaction_path):
            raise _refuse()
        with ledger._locked(recover_rotation=False), store._locked(recover_transactions=False):
            if os.path.lexists(ledger.rotation_path):
                raise _refuse()
            key = ledger._load_or_create_key_locked(allow_create=False)
            current = ledger._load_or_create_ledger_locked(
                key, allow_create=False, allow_legacy=True,
            )
            registry = store._read_current_locked(recover=False)
            registry_bytes = _read_private_bytes(store.path)
            if (
                _sha(registry_bytes) != expected_registry_sha256
                or registry.authority != "dormant" or registry.revision < 1
                or set(registry.registrations) != {vault_binding_id}
                or registry.removal_tombstones or registry.transfer_lineage
            ):
                raise _refuse()
            owners = _load_legacy_owner_inventory(
                owner_receipt_path, registry=registry, channel=channel,
                quiescence_proof=proof,
            )
            if len(owners) != 1:
                raise _refuse()
            owner = owners[0]
            registered_root = Path(registry.registrations[vault_binding_id].path)
            if (
                owner.channel_id != channel or owner.vault_binding_id != vault_binding_id
                or not owner.root_identity or not owner.root_identity.startswith("inode:")
                or owner.root != registered_root or not owner.root.is_absolute()
                or set(owner.ancestor_identities) != {f"path:{p}" for p in owner.root.parents}
                or len(owner.ancestor_identities) != len(owner.root.parents)
                or owner.receipt_digest != proof.owner_receipt_digest
            ):
                raise _refuse()
            destination = _backup_destination(backup_root, (state, ownership, owner.root))
            manifest_path = destination / "manifest.json"
            manifest = _read_private_json(manifest_path) if os.path.lexists(manifest_path) else None
            original_bytes = (
                _read_private_bytes(destination / "ownership-ledger.json")
                if manifest is not None else _read_private_bytes(ledger.path)
            )
            if _sha(original_bytes) != expected_ledger_sha256:
                raise _refuse()
            original = ledger._parse_ledger_value(json.loads(original_bytes))
            if (
                original.schema != LEGACY_LEDGER_SCHEMA
                or original.key_id != key.key_id or original.generation != key.generation
                or not original.legacy_bootstrap_complete
                or set(original.leases) != {vault_binding_id}
                or original.tombstones or original.transfer or original.transfer_lineage
            ):
                raise _refuse()
            lease = original.leases[vault_binding_id]
            expected = ledger._lease_for_legacy_owner(owner, key=key)
            if (
                lease.channel_id != channel or lease.vault_binding_id != vault_binding_id
                or lease.state != "active" or not lease.ancestor_fingerprints
                or ledger._open_root(lease.sealed_root, key) != str(owner.root)
                or not hmac.compare_digest(lease.root_fingerprint, expected.root_fingerprint)
            ):
                raise _refuse()
            # Preserve retained identity and sealed locator. Only current ancestry
            # and receipt provenance are newly attested; no old chain is invented.
            candidate = replace(original, schema=LEDGER_SCHEMA, leases={vault_binding_id: replace(
                lease, ancestor_fingerprints=expected.ancestor_fingerprints,
                owner_receipt_digest=owner.receipt_digest,
            )})
            candidate_bytes = _bytes(ledger._ledger_value(candidate))
            live_bytes = _read_private_bytes(ledger.path)
            if live_bytes not in (original_bytes, candidate_bytes):
                raise _refuse()
            if current.schema == LEDGER_SCHEMA and manifest is None:
                raise _refuse()
            payloads = {
                "vault-registry.md": registry_bytes,
                "ownership-ledger.json": original_bytes,
                "ownership-key.json": _read_private_bytes(ledger.key_path),
                "vault-registry.md.last-good": _read_private_bytes(store.snapshot_path),
                "vault-registry.md.last-good.sha256": _read_private_bytes(store.snapshot_checksum_path),
                "vault-registry.md.legacy-export": _read_private_bytes(store.rollback_export_path),
            }
            # Recovery must retain the original complete registry generation.
            # The no-recovery lock must never heal rollback evidence before this
            # admission or replace evidence that the backup is meant to preserve.
            if (
                payloads["vault-registry.md.last-good"] != registry_bytes
                or payloads["vault-registry.md.last-good.sha256"].decode("ascii").strip()
                != _sha(registry_bytes)
                or payloads["vault-registry.md.legacy-export"]
                != store._rollback_export_payload(registry)
            ):
                raise _refuse()
            checksums = {name: _sha(data) for name, data in payloads.items()}
            evidence = {
                "schema": _SCHEMA, "channel_id": channel,
                "vault_binding_id": vault_binding_id,
                "registry_revision": registry.revision,
                "checksums": checksums,
                "after_ledger_sha256": _sha(candidate_bytes),
                "deployment_nonce": proof.nonce,
                "owner_receipt_digest": proof.owner_receipt_digest,
                "quiescence_inventory_digest": proof.inventory_digest,
                "decision": "explicit-new-owner-epoch-retained-root-only",
                "prior_effects": "not_inferred", "activation": "inactive_fenced",
            }
            if manifest is not None:
                signed = {k: v for k, v in manifest.items() if k != "authentication"}
                if (
                    any(manifest.get(k) != v for k, v in evidence.items())
                    or not isinstance(manifest.get("epoch_id"), str)
                    or not hmac.compare_digest(str(manifest.get("authentication", "")),
                        hmac.new(key.secret, _bytes(signed), hashlib.sha256).hexdigest())
                ):
                    raise _refuse()
            else:
                manifest = evidence | {"epoch_id": str(uuid.uuid4())}
                manifest["authentication"] = hmac.new(
                    key.secret, _bytes(manifest), hashlib.sha256,
                ).hexdigest()
            # A partial backup is retryable only when every existing byte agrees.
            if destination.exists():
                if set(p.name for p in destination.iterdir()) - {*payloads, "manifest.json"}:
                    raise _refuse()
                for name, data in payloads.items():
                    target = destination / name
                    if os.path.lexists(target) and _read_private_bytes(target) != data:
                        raise _refuse()
            else:
                destination.mkdir(mode=0o700)
                parent_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            for name, data in payloads.items():
                target = destination / name
                if not target.exists():
                    _atomic_private_write(target, data)
                if _sha(_read_private_bytes(target)) != checksums[name]:
                    raise _refuse()
            if not manifest_path.exists():
                _atomic_private_write(manifest_path, _bytes(manifest))
            if _read_private_bytes(manifest_path) != _bytes(manifest):
                raise _refuse()
            # Re-prove under every mutation lock immediately before the sole
            # authority write. Even a receipt-backed retry cannot un-fence itself.
            proof.require_canonical_authority(
                channel_id=channel, host_global_root=ownership,
                owner_receipt_path=owner_receipt_path,
            )
            if live_bytes != candidate_bytes:
                ledger._write_ledger_locked(candidate, key)
            if (
                _read_private_bytes(ledger.path) != candidate_bytes
                or _sha(_read_private_bytes(store.path)) != expected_registry_sha256
            ):
                raise _refuse()
            return {"channel": channel, "reattested": True,
                    "epoch_id": manifest["epoch_id"], "backup_verified": True,
                    "activation": "inactive_fenced", "prior_effects": "not_inferred",
                    "ledger_sha256": _sha(candidate_bytes)}
