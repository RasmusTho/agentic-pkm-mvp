"""Fail-closed deployment and native-host guards for MVR-01C scalar rollback."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from app.instance._storage_boundary import CapabilityNotReadyError, RegistryError


_GUARD_RECEIPT_AUTHORITY = object()


@dataclass(frozen=True)
class ScalarRollbackGuardReceipt:
    rollback_vault_binding_id: str
    selected_root: Path
    gateway_authenticated: bool
    mutation_filtering: bool
    direct_api_port_absent: bool
    selected_mount_only: bool
    native_guard_fail_closed: bool
    compose_policy_sha256: str
    gateway_policy_sha256: str
    native_launcher_sha256: str
    _authority: object = field(repr=False)

    def require_valid(self) -> None:
        if self._authority is not _GUARD_RECEIPT_AUTHORITY:
            raise CapabilityNotReadyError("authenticated scalar rollback guard receipt is required")


def preflight_scalar_rollback_guard(
    *,
    compose_overlay: Path,
    gateway_config: Path,
    native_launcher: Path,
    rollback_vault_binding_id: str,
    selected_root: Path,
) -> ScalarRollbackGuardReceipt:
    """Validate the repo-owned guard before registry authority can be activated."""

    binding_id = rollback_vault_binding_id.strip()
    root = selected_root.expanduser().resolve(strict=True)
    if not binding_id or not root.is_dir():
        raise RegistryError("one existing scalar rollback binding/root is required")
    compose = compose_overlay.read_text(encoding="utf-8")
    gateway = gateway_config.read_text(encoding="utf-8")
    required_compose = (
        "SCALAR_ROLLBACK_PREVIOUS_IMAGE:?",
        "SCALAR_ROLLBACK_GUARD_IMAGE:?",
        "SCALAR_ROLLBACK_VAULT_ROOT:?",
        "SCALAR_ROLLBACK_VAULT_BINDING_ID:?",
        "ports: !override []",
        "scalar-rollback-guard",
        "condition: service_completed_successfully",
        "scalar-rollback-gateway",
        "/app/selected-vault",
        "depends_on: !override",
    )
    if any(item not in compose for item in required_compose):
        raise RegistryError("scalar rollback compose guard is incomplete")
    if "/Users:/Users" in compose or "/Volumes:/Volumes" in compose:
        raise RegistryError("scalar rollback overlay exposes a broad host content root")
    required_gateway = (
        "auth_basic",
        "auth_basic_user_file",
        "proxy_pass http://api:8000",
        "return 403",
        "/api/vault/select",
        "/api/vault/initialize",
    )
    if any(item not in gateway for item in required_gateway):
        raise RegistryError("authenticated mutation-filtering gateway policy is incomplete")
    if not native_launcher.is_file():
        raise RegistryError("native scalar rollback launcher is missing")
    mode = native_launcher.stat().st_mode
    if mode & 0o022:
        raise RegistryError("native scalar rollback launcher is group/world writable")
    return ScalarRollbackGuardReceipt(
        rollback_vault_binding_id=binding_id,
        selected_root=root,
        gateway_authenticated=True,
        mutation_filtering=True,
        direct_api_port_absent=True,
        selected_mount_only=True,
        native_guard_fail_closed=True,
        compose_policy_sha256=hashlib.sha256(compose.encode("utf-8")).hexdigest(),
        gateway_policy_sha256=hashlib.sha256(gateway.encode("utf-8")).hexdigest(),
        native_launcher_sha256=hashlib.sha256(native_launcher.read_bytes()).hexdigest(),
        _authority=_GUARD_RECEIPT_AUTHORITY,
    )


def require_native_scalar_launcher(
    *,
    launcher: Path,
    selected_root: Path,
    effective_uid: int | None = None,
) -> str:
    """Return the available sandbox or fail before an old native runtime starts."""

    uid = os.geteuid() if effective_uid is None else effective_uid
    metadata = launcher.stat()
    if (
        uid != 0
        or metadata.st_uid != 0
        or metadata.st_mode & 0o777 != 0o755
        or not selected_root.resolve(strict=True).is_dir()
    ):
        raise CapabilityNotReadyError(
            "native scalar rollback requires a root-owned selected-binding launcher"
        )
    if Path("/usr/bin/sandbox-exec").is_file():
        return "sandbox-exec"
    for candidate in (Path("/usr/bin/bwrap"), Path("/bin/bwrap")):
        if candidate.is_file() and stat.S_ISREG(candidate.stat().st_mode):
            return "bwrap"
    raise CapabilityNotReadyError(
        "native scalar rollback sandbox posture is unavailable; refusing startup"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose-overlay", type=Path, required=True)
    parser.add_argument("--gateway-config", type=Path, required=True)
    parser.add_argument("--native-launcher", type=Path, required=True)
    parser.add_argument("--rollback-vault-binding-id", required=True)
    parser.add_argument("--selected-root", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = preflight_scalar_rollback_guard(
        compose_overlay=args.compose_overlay,
        gateway_config=args.gateway_config,
        native_launcher=args.native_launcher,
        rollback_vault_binding_id=args.rollback_vault_binding_id,
        selected_root=args.selected_root,
    )
    print(
        f"scalar rollback guard preflight passed for {receipt.rollback_vault_binding_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
