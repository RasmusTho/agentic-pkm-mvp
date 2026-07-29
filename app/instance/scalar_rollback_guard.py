"""Fail-closed deployment and native-host guards for MVR-01C scalar rollback."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from app.instance._storage_boundary import CapabilityNotReadyError, RegistryError


_GUARD_RECEIPT_AUTHORITY = object()
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL_COMPOSE_BASE = _REPO_ROOT / "docker-compose.yaml"
_CANONICAL_COMPOSE_OVERLAY = _REPO_ROOT / "docker-compose.scalar-rollback.yml"
_CANONICAL_GATEWAY_CONFIG = _REPO_ROOT / "ops/scalar-rollback/nginx.conf"
_CANONICAL_NATIVE_LAUNCHER = _REPO_ROOT / "scripts/scalar_rollback_native.sh"
_GATEWAY_POLICY = """server {
    listen 8080;
    auth_basic "scalar rollback";
    auth_basic_user_file /run/secrets/scalar-rollback.htpasswd;

    location = /api/companion/vault/select {
        return 403;
    }

    location = /api/companion/vault/initialize {
        return 403;
    }

    location / {
        proxy_pass http://api:8000;
        proxy_set_header Authorization "";
        proxy_set_header X-Scalar-Rollback-Gateway "authenticated";
    }
}
"""


class _ComposeLoader(yaml.SafeLoader):
    pass


def _construct_override(loader: _ComposeLoader, node: yaml.Node) -> object:
    if isinstance(node, SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, ScalarNode):
        return loader.construct_scalar(node)
    raise RegistryError("scalar rollback compose override is invalid")


_ComposeLoader.add_constructor("!override", _construct_override)


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
    compose_base: Path
    compose_overlay: Path
    gateway_config: Path
    native_launcher: Path
    _authority: object = field(repr=False)

    def require_valid(self) -> None:
        if self._authority is not _GUARD_RECEIPT_AUTHORITY:
            raise CapabilityNotReadyError("authenticated scalar rollback guard receipt is required")

    def revalidate(self) -> None:
        self.require_valid()
        current = preflight_scalar_rollback_guard(
            compose_overlay=self.compose_overlay,
            compose_base=self.compose_base,
            gateway_config=self.gateway_config,
            native_launcher=self.native_launcher,
            rollback_vault_binding_id=self.rollback_vault_binding_id,
            selected_root=self.selected_root,
        )
        if (
            current.compose_policy_sha256 != self.compose_policy_sha256
            or current.gateway_policy_sha256 != self.gateway_policy_sha256
            or current.native_launcher_sha256 != self.native_launcher_sha256
            or current.selected_root != self.selected_root
            or current.rollback_vault_binding_id != self.rollback_vault_binding_id
        ):
            raise CapabilityNotReadyError(
                "scalar rollback policy changed after preflight"
            )


def preflight_scalar_rollback_guard(
    *,
    compose_base: Path = _CANONICAL_COMPOSE_BASE,
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
    compose_base_path = compose_base.resolve(strict=True)
    compose_path = compose_overlay.resolve(strict=True)
    gateway_path = gateway_config.resolve(strict=True)
    launcher_path = native_launcher.resolve(strict=True)
    if launcher_path != _CANONICAL_NATIVE_LAUNCHER.resolve(strict=True):
        raise RegistryError("canonical scalar rollback native launcher is required")
    compose = compose_path.read_text(encoding="utf-8")
    compose_base_text = compose_base_path.read_text(encoding="utf-8")
    gateway = gateway_path.read_text(encoding="utf-8")
    try:
        base_model = yaml.load(compose_base_text, Loader=_ComposeLoader)
        overlay_model = yaml.load(compose, Loader=_ComposeLoader)
    except yaml.YAMLError as exc:
        raise RegistryError("scalar rollback compose guard is invalid") from exc
    _validate_compose_model(base_model, overlay_model)
    if gateway != _GATEWAY_POLICY:
        raise RegistryError("authenticated mutation-filtering gateway policy is incomplete")
    if not launcher_path.is_file():
        raise RegistryError("native scalar rollback launcher is missing")
    mode = launcher_path.stat().st_mode
    if mode & 0o022:
        raise RegistryError("native scalar rollback launcher is group/world writable")
    try:
        require_native_scalar_launcher(
            launcher=launcher_path,
            selected_root=root,
        )
    except CapabilityNotReadyError:
        # Unsupported native rollback is an accepted fail-closed posture.
        pass
    else:
        raise RegistryError(
            "native scalar rollback unexpectedly lacks an authenticated mutation filter stop"
        )
    return ScalarRollbackGuardReceipt(
        rollback_vault_binding_id=binding_id,
        selected_root=root,
        gateway_authenticated=True,
        mutation_filtering=True,
        direct_api_port_absent=True,
        selected_mount_only=True,
        native_guard_fail_closed=True,
        compose_policy_sha256=hashlib.sha256(
            compose_base_text.encode("utf-8") + b"\0" + compose.encode("utf-8")
        ).hexdigest(),
        gateway_policy_sha256=hashlib.sha256(gateway.encode("utf-8")).hexdigest(),
        native_launcher_sha256=hashlib.sha256(launcher_path.read_bytes()).hexdigest(),
        compose_base=compose_base_path,
        compose_overlay=compose_path,
        gateway_config=gateway_path,
        native_launcher=launcher_path,
        _authority=_GUARD_RECEIPT_AUTHORITY,
    )


def _validate_compose_model(base_model: object, overlay_model: object) -> None:
    if (
        not isinstance(base_model, dict)
        or not isinstance(base_model.get("services"), dict)
        or not isinstance(overlay_model, dict)
        or not isinstance(overlay_model.get("services"), dict)
    ):
        raise RegistryError("scalar rollback compose guard is incomplete")
    base_services = base_model["services"]
    services = overlay_model["services"]
    required = {
        "scalar-rollback-guard",
        "api",
        "scalar-rollback-gateway",
        "worker",
        "watcher",
        "heimdal-capture-watch",
        "companion-ui",
    }
    if set(services) != required:
        raise RegistryError("scalar rollback overlay service set is invalid")
    api = services["api"]
    guard = services["scalar-rollback-guard"]
    gateway = services["scalar-rollback-gateway"]
    if not all(isinstance(value, dict) for value in (api, guard, gateway)):
        raise RegistryError("scalar rollback service definitions are invalid")
    if api.get("ports") != [] or set((api.get("depends_on") or {})) != {
        "scalar-rollback-guard"
    }:
        raise RegistryError("scalar rollback API has a bypass port or dependency")
    api_targets = _volume_targets(api.get("volumes"))
    if api_targets != {
        "/app/tmp",
        "/app/instance-state",
        "/app/scalar-rollback",
        "/app/deployment-control",
        "/app/selected-vault",
    }:
        raise RegistryError("scalar rollback API mount set is not selected-binding-only")
    deployment_control = next(
        (
            mount
            for mount in api["volumes"]
            if isinstance(mount, dict)
            and mount.get("target") == "/app/deployment-control"
        ),
        None,
    )
    if (
        not isinstance(deployment_control, dict)
        or deployment_control.get("read_only") is not True
        or deployment_control.get("source")
        != (
            "${INSTANCE_OWNERSHIP_HOST_STATE_DIR:"
            "?absolute host-global state directory must be resolved by the launcher}"
            "/deployment-public"
        )
    ):
        raise RegistryError("scalar rollback deployment control mount is invalid")
    guard_targets = _volume_targets(guard.get("volumes"))
    if guard_targets != {
        "/app/instance-state",
        "/app/instance-ownership",
        "/app/scalar-rollback",
        "/app/selected-vault",
        "/run/scalar-rollback-policy/docker-compose.yaml",
        "/run/scalar-rollback-policy/docker-compose.scalar-rollback.yml",
        "/run/scalar-rollback-policy/nginx.conf",
    }:
        raise RegistryError("scalar rollback guard mount set is invalid")
    gateway_targets = _volume_targets(gateway.get("volumes"))
    if gateway_targets != {
        "/etc/nginx/conf.d/default.conf",
        "/run/secrets/scalar-rollback.htpasswd",
    }:
        raise RegistryError("scalar rollback gateway mount set is invalid")
    ports = gateway.get("ports")
    if not isinstance(ports, list) or len(ports) != 1 or "127.0.0.1" not in str(ports[0]):
        raise RegistryError("scalar rollback gateway must expose one loopback port")
    for name in ("worker", "watcher", "heimdal-capture-watch"):
        if services[name] != {"profiles": ["scalar-rollback-disabled"]}:
            raise RegistryError("scalar rollback background producer is not disabled")
    companion = services["companion-ui"]
    if companion != {
        "profiles": ["scalar-rollback-disabled"],
        "ports": [],
        "depends_on": [],
    }:
        raise RegistryError("scalar rollback companion API bypass is not disabled")
    api_dependents = {
        name
        for name, service in base_services.items()
        if isinstance(service, dict)
        and "api"
        in (
            set((service.get("depends_on") or {}).keys())
            if isinstance(service.get("depends_on"), dict)
            else set(service.get("depends_on") or [])
        )
    }
    if api_dependents != {"companion-ui"}:
        raise RegistryError("base Compose has an ungoverned scalar API dependent")
    init_service = base_services.get("instance-state-init")
    if not isinstance(init_service, dict):
        raise RegistryError("base Compose scalar rollback producer is missing")
    init_targets = _volume_targets(init_service.get("volumes"))
    if not {
        "/app/scalar-rollback",
        "/run/scalar-rollback-policy/docker-compose.yaml",
        "/run/scalar-rollback-policy/docker-compose.scalar-rollback.yml",
        "/run/scalar-rollback-policy/nginx.conf",
    }.issubset(init_targets):
        raise RegistryError(
            "base Compose scalar rollback producer lacks host policy/source mounts"
        )
    forbidden_current_targets = {
        "/app/scalar-rollback",
        "/run/scalar-rollback-policy/docker-compose.yaml",
        "/run/scalar-rollback-policy/docker-compose.scalar-rollback.yml",
        "/run/scalar-rollback-policy/nginx.conf",
    }
    for name in ("api", "worker", "watcher", "heimdal-capture-watch"):
        service = base_services.get(name)
        if not isinstance(service, dict):
            raise RegistryError("base Compose current producer set is invalid")
        if _volume_targets(service.get("volumes")) & forbidden_current_targets:
            raise RegistryError(
                "current long-lived service can access scalar rollback policy/source"
            )
    command = api.get("command")
    if (
        not isinstance(command, list)
        or len(command) != 3
        or command[:2] != ["python", "-c"]
    ):
        raise RegistryError("scalar rollback API admission command is invalid")
    api_command = str(command[2])
    if "scalar-rollback-session.json" not in api_command:
        raise RegistryError("scalar rollback API does not require the durable session")
    if (
        "deployment-control/deployment-host-global-lease.json"
        not in api_command
        or "deployment-control/scalar-rollback-runtime.lock"
        not in api_command
        or "fcntl.LOCK_SH" not in api_command
        or "os.set_inheritable" not in api_command
    ):
        raise RegistryError("scalar rollback API does not recheck deployment startup")


def _volume_targets(value: object) -> set[str]:
    if not isinstance(value, list):
        raise RegistryError("scalar rollback volumes must be a list")
    targets: set[str] = set()
    for item in value:
        if isinstance(item, str):
            parts = item.split(":")
            if len(parts) < 2:
                raise RegistryError("scalar rollback volume is invalid")
            targets.add(parts[1])
        elif isinstance(item, dict) and isinstance(item.get("target"), str):
            targets.add(item["target"])
        else:
            raise RegistryError("scalar rollback volume is invalid")
    if len(targets) != len(value):
        raise RegistryError("scalar rollback volume targets are ambiguous")
    return targets


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
        sandbox = "sandbox-exec"
    else:
        sandbox = ""
    for candidate in (Path("/usr/bin/bwrap"), Path("/bin/bwrap")):
        if candidate.is_file() and stat.S_ISREG(candidate.stat().st_mode):
            sandbox = "bwrap"
            break
    if not sandbox:
        raise CapabilityNotReadyError(
            "native scalar rollback sandbox posture is unavailable; refusing startup"
        )
    raise CapabilityNotReadyError(
        "native scalar rollback authenticated mutation filter is unavailable; refusing startup"
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
