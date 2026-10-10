from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.release_channels.fleet_model_fitness import (
    FleetModelInspectionError,
    check_fleet_model_fitness,
)


PIN = "314632235404cae1c51dc92b5f37174aa02b5fb0"


def test_digest_pin_checks_actual_container_image_id(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    digest = 'sha256:' + 'b' * 64
    image_id = 'sha256:' + 'c' * 64
    reference = 'ghcr.io/rasmustho/pkm-app:' + PIN + '@' + digest
    (root / 'config/deploy/prod.env').write_text(
        f'APP_IMAGE_TAG={PIN}\nAPP_IMAGE_REPOSITORY=ghcr.io/rasmustho/pkm-app\nAPP_IMAGE_DIGEST_SUFFIX=@{digest}\n')
    inspections = _all_services()
    for inspection in inspections.values():
        inspection['Config']['Image'] = reference
        inspection['Image'] = image_id
    base = _docker_runner(inspections)

    def docker(args):
        if args == ['image', 'inspect', reference]:
            return json.dumps([{'Id': image_id}])
        return base(args)

    result = check_fleet_model_fitness('prod', root=root, require_pinned=True,
                                      docker_runner=docker, http_get_json=_http_runner())
    assert result.ok, result.violations
    inspections['worker']['Image'] = 'sha256:' + 'd' * 64
    result = check_fleet_model_fitness('prod', root=root, require_pinned=True,
                                      docker_runner=docker, http_get_json=_http_runner())
    assert not result.ok
    assert "service 'worker' differs from immutable channel image" in result.violations


def _root_with_pin(tmp_path: Path, channel: str = "prod", pin: str = PIN) -> Path:
    root = tmp_path
    deploy_dir = root / "config" / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / f"{channel}.env").write_text(f"APP_IMAGE_TAG={pin}\n", encoding="utf-8")
    return root


def _inspect(
    service: str,
    *,
    image_tag: str = PIN,
    app_bind: bool = False,
    state: str = "running",
    capture_watch_dir: str | None = "/fixture/capture-inbox",
) -> dict[str, Any]:
    mounts = [{"Type": "volume", "Source": "runtime-tmp", "Destination": "/app/tmp"}]
    if app_bind:
        mounts.append(
            {
                "Type": "bind",
                "Source": "/Users/rasmusthornberg/code/agentic-pkm-mvp",
                "Destination": "/app",
            }
        )
    return {
        "Name": f"/pkm-prod-{service}-1",
        "Config": {
            "Image": f"ghcr.io/rasmustho/pkm-app:{image_tag}",
            "Env": (
                [f"HEIMDAL_CAPTURE_WATCH_DIR={capture_watch_dir}"]
                if capture_watch_dir is not None
                else []
            ),
        },
        "State": {"Status": state, "Health": {"Status": "healthy"}},
        "Mounts": mounts,
    }


def _docker_runner(inspections: dict[str, dict[str, Any]]):
    cid_by_service = {service: f"{service}-cid" for service in inspections}
    service_by_cid = {cid: service for service, cid in cid_by_service.items()}

    def run(args: list[str]) -> str:
        if args[:3] == ["compose", "-p", "pkm-prod"] and args[3:5] == ["ps", "-q"]:
            service = args[5]
            return f"{cid_by_service[service]}\n" if service in cid_by_service else ""
        if args[:1] == ["inspect"]:
            service = service_by_cid[args[1]]
            return json.dumps([inspections[service]])
        raise AssertionError(f"unexpected docker args: {args}")

    return run


def _http_runner(api_sha: str = PIN, health_sha: str | None = None, gateway_ok: bool = True):
    def get_json(url: str) -> dict[str, Any]:
        if url.endswith(":18000/version"):
            return {"git_sha": api_sha, "built_at": "2026-07-08T00:00:00Z"}
        if url.endswith(":18000/api/health"):
            return {"version": {"git_sha": health_sha or api_sha}}
        if url.endswith(":8113/healthz"):
            return {"ok": gateway_ok, "service": "companion-ui"}
        raise AssertionError(f"unexpected URL: {url}")

    return get_json


def _http_runner_top_level_health_version(
    api_sha: str = PIN,
    gateway_ok: bool = True,
):
    def get_json(url: str) -> dict[str, Any]:
        if url.endswith(":18000/version"):
            return {"git_sha": api_sha, "built_at": "2026-07-08T00:00:00Z"}
        if url.endswith(":18000/api/health"):
            return {"version": api_sha}
        if url.endswith(":8113/healthz"):
            return {"ok": gateway_ok, "service": "companion-ui"}
        raise AssertionError(f"unexpected URL: {url}")

    return get_json


def _all_services(**overrides: dict[str, Any]) -> dict[str, dict[str, Any]]:
    services = ("api", "worker", "watcher", "heimdal-capture-watch", "companion-ui")
    return {service: _inspect(service, **overrides.get(service, {})) for service in services}


def test_bind_mount_in_pinned_mode_fails_naming_service(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services(api={"app_bind": True})

    result = check_fleet_model_fitness(
        "prod",
        root=root,
        require_pinned=True,
        docker_runner=_docker_runner(inspections),
        http_get_json=_http_runner(),
    )

    assert result.model == "mixed"
    assert result.expected_model == "pinned-image"
    assert not result.ok
    assert any("api" in violation and "/app" in violation for violation in result.violations)


def test_pin_version_and_gateway_sha_must_agree(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services(
        worker={"image_tag": "worker-drift"},
        **{"companion-ui": {"image_tag": "gateway-drift"}},
    )

    result = check_fleet_model_fitness(
        "prod",
        root=root,
        docker_runner=_docker_runner(inspections),
        http_get_json=_http_runner(api_sha="version-drift", health_sha="health-drift"),
    )

    assert result.model == "pinned-image"
    assert not result.ok
    joined = "\n".join(result.violations)
    assert "worker" in joined and "worker-drift" in joined
    assert "/version" in joined and "version-drift" in joined
    assert "/api/health" in joined and "health-drift" in joined
    assert "gateway" in joined and "gateway-drift" in joined


def test_api_health_top_level_version_string_is_accepted(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services()

    result = check_fleet_model_fitness(
        "prod",
        root=root,
        docker_runner=_docker_runner(inspections),
        http_get_json=_http_runner_top_level_health_version(),
    )

    assert result.ok
    assert result.api_health_git_sha == PIN


def test_checkout_model_reports_without_failing(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services(
        api={"image_tag": "dev-local", "app_bind": True},
        worker={"image_tag": "dev-local", "app_bind": True},
        watcher={"image_tag": "dev-local", "app_bind": True},
        **{"heimdal-capture-watch": {"image_tag": "dev-local", "app_bind": True}},
    )

    result = check_fleet_model_fitness(
        "prod",
        root=root,
        docker_runner=_docker_runner(inspections),
        http_get_json=_http_runner(api_sha="not-checked"),
    )

    assert result.ok
    assert result.model == "checkout"
    assert result.to_receipt()["model"] == "checkout"


def test_unconfigured_capture_watch_is_optional(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services(api={"capture_watch_dir": ""})
    inspections.pop("heimdal-capture-watch")

    result = check_fleet_model_fitness(
        "prod",
        root=root,
        require_pinned=True,
        capture_watch_configured=False,
        docker_runner=_docker_runner(inspections),
        http_get_json=_http_runner(),
    )

    assert result.ok
    assert {service.service for service in result.services} == {
        "api",
        "worker",
        "watcher",
        "companion-ui",
    }


def test_configured_capture_watch_remains_required(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services()
    inspections.pop("heimdal-capture-watch")

    with pytest.raises(FleetModelInspectionError, match="heimdal-capture-watch.*not found"):
        check_fleet_model_fitness(
            "prod",
            root=root,
            capture_watch_configured=True,
            docker_runner=_docker_runner(inspections),
            http_get_json=_http_runner(),
        )


def test_direct_guard_infers_capture_from_api_env(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services(api={"capture_watch_dir": "/fixture/capture-inbox"})
    inspections.pop("heimdal-capture-watch")

    with pytest.raises(FleetModelInspectionError, match="heimdal-capture-watch.*not found"):
        check_fleet_model_fitness(
            "prod",
            root=root,
            docker_runner=_docker_runner(inspections),
            http_get_json=_http_runner(),
        )


def test_checkout_model_uses_selected_app_services(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services(
        api={"image_tag": "dev-local", "app_bind": True, "capture_watch_dir": ""},
        worker={"image_tag": "dev-local", "app_bind": True, "capture_watch_dir": ""},
        watcher={"image_tag": "dev-local", "app_bind": True, "capture_watch_dir": ""},
    )
    inspections.pop("heimdal-capture-watch")

    result = check_fleet_model_fitness(
        "prod",
        root=root,
        capture_watch_configured=False,
        docker_runner=_docker_runner(inspections),
        http_get_json=_http_runner(api_sha="not-checked"),
    )

    assert result.ok
    assert result.model == "checkout"


def test_mixed_pinned_checkout_fleet_fails(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services(api={"app_bind": True})

    result = check_fleet_model_fitness(
        "prod",
        root=root,
        docker_runner=_docker_runner(inspections),
        http_get_json=_http_runner(),
    )

    assert not result.ok
    assert result.model == "mixed"
    assert result.to_receipt()["ok"] is False
    joined = "\n".join(result.violations)
    assert "mixed pinned/checkout fleet" in joined
    assert "api" in joined


def test_mixed_fleet_cannot_greenlight_pinned_deploy_receipt(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services(
        api={"image_tag": "dev-local", "app_bind": True},
        worker={"image_tag": "worker-drift"},
    )

    result = check_fleet_model_fitness(
        "prod",
        root=root,
        require_pinned=True,
        docker_runner=_docker_runner(inspections),
        http_get_json=_http_runner(),
    )

    receipt = result.to_receipt()
    assert result.model == "mixed"
    assert not result.ok
    assert receipt["ok"] is False
    assert receipt["model"] == "mixed"
    assert receipt["expected_model"] == "pinned-image"
    joined = "\n".join(result.violations)
    assert "mixed pinned/checkout fleet" in joined
    assert "worker-drift" in joined


def test_gateway_app_bind_mount_is_rejected(tmp_path: Path) -> None:
    root = _root_with_pin(tmp_path)
    inspections = _all_services(**{"companion-ui": {"app_bind": True}})

    result = check_fleet_model_fitness(
        "prod",
        root=root,
        docker_runner=_docker_runner(inspections),
        http_get_json=_http_runner(),
    )

    receipt = result.to_receipt()
    assert not result.ok
    assert result.model == "mixed"
    assert receipt["ok"] is False
    joined = "\n".join(result.violations)
    assert "mixed pinned/checkout fleet" in joined
    assert "companion-ui" in joined
    assert "/app" in joined
