"""Read-only live fleet-model fitness guard for pinned-image cutover.

The guard inspects the running compose fleet for a channel and reports whether
it is still in checkout mode or has cut over to pinned images. Checkout mode is
informational and does not fail. Pinned-image mode fails loud when app services
retain a repo ``/app`` bind-mount, when service image tags diverge from the
channel pin, when live version endpoints diverge, or when the managed gateway is
not live. The deploy script runs the same guard with ``--require-pinned`` so a
post-deploy receipt cannot green-light a checkout/hot-reload fleet.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


APP_CODE_SERVICES = ("api", "worker", "watcher", "heimdal-capture-watch")
GATEWAY_SERVICE = "companion-ui"
ALL_SERVICES = (*APP_CODE_SERVICES, GATEWAY_SERVICE)

CHANNEL_SPECS = {
    "dev": {"compose_project": "pkm-dev", "api_port": 18001, "gateway_port": 8111},
    "test": {"compose_project": "pkm-test", "api_port": 18002, "gateway_port": 8112},
    "prod": {"compose_project": "pkm-prod", "api_port": 18000, "gateway_port": 8113},
}

DockerRunner = Callable[[list[str]], str]
HttpJsonGetter = Callable[[str], dict[str, Any]]


class FleetModelInspectionError(RuntimeError):
    """Raised when the live fleet cannot be inspected."""


@dataclass(frozen=True)
class ServiceFitness:
    service: str
    container_id: str
    image: str
    image_tag: str
    app_bind_mount_sources: tuple[str, ...] = ()
    state: str | None = None
    health: str | None = None

    @property
    def has_app_bind_mount(self) -> bool:
        return bool(self.app_bind_mount_sources)

    def to_receipt(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "container_id": self.container_id,
            "image": self.image,
            "image_tag": self.image_tag,
            "app_bind_mount_sources": list(self.app_bind_mount_sources),
            "state": self.state,
            "health": self.health,
        }


@dataclass(frozen=True)
class FleetModelFitnessResult:
    channel: str
    model: str
    pin: str
    services: tuple[ServiceFitness, ...]
    expected_model: str | None = None
    api_version_git_sha: str | None = None
    api_health_git_sha: str | None = None
    gateway_sha: str | None = None
    gateway_healthz_ok: bool | None = None
    violations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_receipt(self) -> dict[str, Any]:
        return {
            "guard": "fleet_model_fitness.v1",
            "channel": self.channel,
            "model": self.model,
            "expected_model": self.expected_model,
            "pin": self.pin,
            "ok": self.ok,
            "api_version_git_sha": self.api_version_git_sha,
            "api_health_git_sha": self.api_health_git_sha,
            "gateway_sha": self.gateway_sha,
            "gateway_healthz_ok": self.gateway_healthz_ok,
            "services": [service.to_receipt() for service in self.services],
            "violations": list(self.violations),
        }


def _default_docker_runner(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["docker", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - docker may be absent locally
        raise FleetModelInspectionError("docker executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise FleetModelInspectionError(
            f"docker {' '.join(args)} failed: {exc.stderr.strip()}"
        ) from exc
    return completed.stdout


def _default_http_get_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = response.read().decode("utf-8")
    except (OSError, urllib.error.URLError) as exc:
        raise FleetModelInspectionError(f"GET {url} failed: {exc}") from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise FleetModelInspectionError(f"GET {url} did not return JSON") from exc
    if not isinstance(data, dict):
        raise FleetModelInspectionError(f"GET {url} returned non-object JSON")
    return data


def _read_channel_pin(root: Path, channel: str) -> str:
    pin_file = root / "config" / "deploy" / f"{channel}.env"
    try:
        lines = pin_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FleetModelInspectionError(f"cannot read channel pin file {pin_file}") from exc
    for line in lines:
        if line.startswith("APP_IMAGE_TAG="):
            pin = line.split("=", 1)[1].strip()
            if pin:
                return pin
    raise FleetModelInspectionError(f"missing APP_IMAGE_TAG in {pin_file}")


def _image_tag(image: str) -> str:
    # ghcr.io/org/name:tag -> tag; sha-only pins may also be passed directly.
    tail = image.rsplit("/", 1)[-1]
    if ":" in tail:
        return tail.rsplit(":", 1)[1]
    return image


def _matches_pin(image: str, pin: str) -> bool:
    return image == pin or _image_tag(image) == pin


def _inspect_service(
    service: str,
    compose_project: str,
    *,
    docker_runner: DockerRunner,
) -> ServiceFitness:
    container_id = docker_runner(
        ["compose", "-p", compose_project, "ps", "-q", service]
    ).strip()
    if not container_id:
        raise FleetModelInspectionError(
            f"container for service '{service}' not found in project '{compose_project}'"
        )
    raw = docker_runner(["inspect", container_id])
    try:
        inspected = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FleetModelInspectionError(
            f"docker inspect for service '{service}' returned invalid JSON"
        ) from exc
    if not isinstance(inspected, list) or not inspected or not isinstance(inspected[0], dict):
        raise FleetModelInspectionError(
            f"docker inspect for service '{service}' returned no container data"
        )
    info = inspected[0]
    image = str((info.get("Config") or {}).get("Image") or info.get("Image") or "")
    mounts = info.get("Mounts") or []
    app_bind_sources = tuple(
        str(mount.get("Source") or "")
        for mount in mounts
        if isinstance(mount, dict)
        and mount.get("Type") == "bind"
        and mount.get("Destination") == "/app"
    )
    state = info.get("State") or {}
    health = state.get("Health") or {}
    return ServiceFitness(
        service=service,
        container_id=container_id,
        image=image,
        image_tag=_image_tag(image),
        app_bind_mount_sources=app_bind_sources,
        state=state.get("Status"),
        health=health.get("Status"),
    )


def _get_nested(payload: dict[str, Any], *keys: str) -> str | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, str) else None


def check_fleet_model_fitness(
    channel: str,
    *,
    root: Path | str = Path.cwd(),
    require_pinned: bool = False,
    docker_runner: DockerRunner = _default_docker_runner,
    http_get_json: HttpJsonGetter = _default_http_get_json,
) -> FleetModelFitnessResult:
    """Inspect the running fleet for ``channel`` without mutating it."""
    if channel not in CHANNEL_SPECS:
        raise FleetModelInspectionError(f"unsupported channel: {channel}")

    root_path = Path(root)
    spec = CHANNEL_SPECS[channel]
    pin = _read_channel_pin(root_path, channel)
    services = tuple(
        _inspect_service(
            service,
            spec["compose_project"],
            docker_runner=docker_runner,
        )
        for service in ALL_SERVICES
    )
    app_services = tuple(service for service in services if service.service in APP_CODE_SERVICES)
    bind_services = tuple(service for service in services if service.has_app_bind_mount)
    model = "checkout" if bind_services else "pinned-image"

    # The observed deployment model is physical: a live /app bind mount means
    # checkout/hot-reload, even when the image tag happens to equal the pin.
    # That keeps direct pre-cutover guard runs informative. Deploy receipts pass
    # require_pinned=True below, so checkout cannot become a green deploy receipt.
    if model == "checkout" and not require_pinned:
        return FleetModelFitnessResult(
            channel=channel,
            model="checkout",
            pin=pin,
            services=services,
        )

    violations: list[str] = []
    if model == "checkout" and require_pinned:
        names = ", ".join(service.service for service in bind_services)
        violations.append(
            f"expected pinned-image model for channel '{channel}', but live /app "
            f"bind-mount(s) show checkout model on: {names}"
        )
    for service in bind_services:
        sources = ", ".join(service.app_bind_mount_sources)
        violations.append(
            f"service '{service.service}' has a repo /app bind-mount in pinned-image mode: "
            f"{sources}"
        )
    for service in app_services:
        if not _matches_pin(service.image, pin):
            violations.append(
                f"service '{service.service}' runs image tag '{service.image_tag}', "
                f"expected channel pin '{pin}'"
            )

    gateway_service = next(service for service in services if service.service == GATEWAY_SERVICE)
    gateway_sha = gateway_service.image_tag
    if not _matches_pin(gateway_service.image, pin):
        violations.append(
            f"gateway service '{GATEWAY_SERVICE}' runs image tag '{gateway_sha}', "
            f"expected channel pin '{pin}'"
        )

    api_base = f"http://127.0.0.1:{spec['api_port']}"
    gateway_base = f"http://127.0.0.1:{spec['gateway_port']}"
    api_version_git_sha: str | None = None
    api_health_git_sha: str | None = None
    gateway_healthz_ok: bool | None = None

    try:
        api_version_git_sha = _get_nested(http_get_json(f"{api_base}/version"), "git_sha")
        if api_version_git_sha != pin:
            violations.append(
                f"API /version git_sha '{api_version_git_sha or ''}' does not match "
                f"channel pin '{pin}'"
            )
    except FleetModelInspectionError as exc:
        violations.append(str(exc))

    try:
        api_health_git_sha = _get_nested(
            http_get_json(f"{api_base}/api/health"), "version", "git_sha"
        )
        if api_health_git_sha != pin:
            violations.append(
                f"API /api/health version git_sha '{api_health_git_sha or ''}' "
                f"does not match channel pin '{pin}'"
            )
    except FleetModelInspectionError as exc:
        violations.append(str(exc))

    try:
        gateway_healthz = http_get_json(f"{gateway_base}/healthz")
        gateway_healthz_ok = gateway_healthz.get("ok") is True
        if not gateway_healthz_ok:
            violations.append(f"gateway /healthz is not ok: {gateway_healthz}")
    except FleetModelInspectionError as exc:
        gateway_healthz_ok = False
        violations.append(str(exc))

    return FleetModelFitnessResult(
        channel=channel,
        model=model,
        expected_model="pinned-image" if require_pinned else None,
        pin=pin,
        services=services,
        api_version_git_sha=api_version_git_sha,
        api_health_git_sha=api_health_git_sha,
        gateway_sha=gateway_sha,
        gateway_healthz_ok=gateway_healthz_ok,
        violations=tuple(violations),
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.release_channels.fleet_model_fitness",
        description="Read-only live fleet-model fitness guard for deploy channels.",
    )
    parser.add_argument("channel", choices=sorted(CHANNEL_SPECS))
    parser.add_argument(
        "--root",
        default=str(Path.cwd()),
        help="Repository root containing config/deploy/<channel>.env.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write the machine-readable receipt JSON to stdout.",
    )
    parser.add_argument(
        "--require-pinned",
        action="store_true",
        help="Fail when the observed fleet model is checkout. Used by deploy receipts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        result = check_fleet_model_fitness(
            args.channel,
            root=args.root,
            require_pinned=args.require_pinned,
        )
    except FleetModelInspectionError as exc:
        print(f"fleet-model-fitness: ERROR - {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_receipt(), sort_keys=True))
    elif result.ok:
        print(
            f"fleet-model-fitness: OK - channel={result.channel} "
            f"model={result.model} pin={result.pin}"
        )
    else:
        print(
            f"fleet-model-fitness: FAIL - channel={result.channel} "
            f"model={result.model} pin={result.pin}",
            file=sys.stderr,
        )
        for violation in result.violations:
            print(f"  - {violation}", file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
