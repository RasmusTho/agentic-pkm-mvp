from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/deploy_channel.sh"
MAKEFILE = REPO_ROOT / "Makefile"


class _ComposeLoader(yaml.SafeLoader):
    pass


def _construct_override(loader: _ComposeLoader, node: yaml.Node) -> object:
    return loader.construct_sequence(node)


_ComposeLoader.add_constructor("!override", _construct_override)


def _compose(path: str) -> dict:
    return yaml.load((REPO_ROOT / path).read_text(encoding="utf-8"), Loader=_ComposeLoader)


def test_deploy_sequence_and_forward_only_ack_gate() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "migration_gate" in text
    assert "DEPLOY_ACK_FORWARD_ONLY" in text
    assert "--ack-forward-only" in text
    assert "forward-only migrations require" in text
    assert "migration gate blocked before recreate" in text
    run_block = text.split('echo "deploy plan:', 1)[1]
    assert run_block.index("migration_gate") < run_block.index("write_pin")
    assert run_block.index("write_pin") < run_block.index("compose pull")
    assert run_block.index("compose pull") < run_block.index("compose up -d --force-recreate")

    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_health_gate_blocks_and_triggers_rollback() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "health_gate" in text
    assert "http://127.0.0.1:${api_port}/healthz" in text
    assert "http://127.0.0.1:${ui_port}/healthz" in text
    assert "health gate failed; attempting rollback to previous pin" in text
    run_block = text.split('echo "deploy plan:', 1)[1]
    assert run_block.index("compose up -d --force-recreate") < run_block.index("health_gate")
    assert run_block.index("health_gate") < run_block.index("version_gate")


def test_rollback_uses_previous_pin_and_skips_forward_only_reversal() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "rollback" in text
    assert "previous_pin_file" in text
    assert "Do not auto-reverse forward-only migrations" not in text
    assert "forward_only" in text
    assert "ack_forward_only" in text
    assert "reverse" not in re.sub(r"reversibility|reversible", "", text)


def test_app_bind_mount_removed_and_version_authoritative() -> None:
    base = _compose("docker-compose.yaml")
    for service_name in ("api", "worker", "watcher", "companion-ui"):
        service = base["services"][service_name]
        mounts = [str(mount) for mount in service.get("volumes", [])]
        assert "./:/app" not in mounts

    api_mounts = [str(mount) for mount in base["services"]["api"]["volumes"]]
    assert '"/Users:/Users"' not in api_mounts
    assert "/Users:/Users" in api_mounts
    assert "/Volumes:/Volumes" in api_mounts

    text = SCRIPT.read_text(encoding="utf-8")
    assert "/version" in text
    assert "/api/health" in text
    assert "version_gate" in text

    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "APP_CODE_BIND_COMPOSE ?=" in makefile
    assert "APP_CODE_BIND_COMPOSE ?= docker-compose.app-bind.yml" not in makefile
    assert "deploy-dev" in makefile and "deploy-test" in makefile and "deploy-prod" in makefile
