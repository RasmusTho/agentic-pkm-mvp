from __future__ import annotations

import re
from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/app-image-build.yml")
COMPOSE_PATH = Path("docker-compose.yaml")
APP_BIND_OVERLAY_PATH = Path("docker-compose.app-bind.yml")
MAKEFILE_PATH = Path("Makefile")
START_FULL_SYSTEM_PATH = Path("scripts/start_full_system.sh")
DEPLOY_CONFIG_DIR = Path("config/deploy")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ci_pushes_sha_tag_to_ghcr() -> None:
    workflow = _read(WORKFLOW_PATH)

    assert "packages: write" in workflow
    assert "uses: docker/login-action@v3" in workflow
    assert "registry: ghcr.io" in workflow
    assert 'image="ghcr.io/${owner}/pkm-app:${vcs_ref}"' in workflow
    assert 'docker push "${{ steps.build-identity.outputs.image }}"' in workflow
    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    assert "push: false" in workflow


def test_per_channel_pin_files_present() -> None:
    for channel in ("dev", "test", "prod"):
        pin_path = DEPLOY_CONFIG_DIR / f"{channel}.env"
        lines = [
            line.strip()
            for line in _read(pin_path).splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        assert len(lines) == 1
        key, value = lines[0].split("=", 1)
        assert key == "APP_IMAGE_TAG"
        assert re.fullmatch(r"[0-9a-f]{40}", value)


def test_compose_image_uses_pinned_tag_and_mount_is_flagged() -> None:
    compose = _read(COMPOSE_PATH)
    overlay = _read(APP_BIND_OVERLAY_PATH)
    makefile = _read(MAKEFILE_PATH)
    start_full_system = _read(START_FULL_SYSTEM_PATH)

    assert "${APP_IMAGE_REPOSITORY:-ghcr.io/rasmustho/pkm-app}:${APP_IMAGE_TAG:-dev-local}" in compose
    assert "image: workspace-app" not in compose
    assert "- ./:/app" not in compose
    assert "- ./:/app" in overlay
    assert "APP_CODE_BIND_COMPOSE ?= docker-compose.app-bind.yml" in makefile
    assert "COMPOSE_UP_BUILD := $(if $(strip $(APP_CODE_BIND_COMPOSE)),--build,)" in makefile
    assert "--env-file config/deploy/dev.env" in makefile
    assert "COMPOSE_FILE=\"$(COMPOSE_DEV_FILES)\"" in makefile
    assert "-f $(APP_CODE_BIND_COMPOSE)" in makefile
    assert 'APP_CODE_BIND_MOUNT:-1' in start_full_system
    assert 'load_env_defaults_file "config/deploy/${_pkm_deploy_pin_channel}.env"' in start_full_system
    assert 'compose_up_build_args=("--build")' in start_full_system
    assert "compose_up_build_args=()" in start_full_system
    assert 'app_code_bind_overlay=":docker-compose.app-bind.yml"' in start_full_system
    assert 'docker-compose.yaml${app_code_bind_overlay}:docker-compose.dev.yml' in start_full_system
