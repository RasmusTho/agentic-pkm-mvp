from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
sys.path.insert(0, str(REPOSITORY_ROOT / "ops/host-setup/linux"))

import host_probe_launcher  # noqa: E402
from install_host_probe import (
    CONTROLLER_STATE_DIRECTORY,
    _parse_remote_main_readback,
    installation_plan,
    render_probe_environment,
)  # noqa: E402


UNIT_PATH = REPOSITORY_ROOT / "config/systemd/yggdrasil-host-probe@.service"
MAC_INSTALLER_PATH = REPOSITORY_ROOT / "ops/host-setup/mac-mini/install.sh"
MAC_PLIST_PATH = REPOSITORY_ROOT / "ops/host-setup/mac-mini/com.yggdrasil.prod-probe.plist"


def _environment_values(channel: str) -> dict[str, str]:
    return {
        name: value
        for line in render_probe_environment(channel).splitlines()
        if line and not line.startswith("#")
        for name, separator, value in [line.partition("=")]
        if separator
    }


def test_systemd_template_and_channel_config_are_targeted() -> None:
    unit = UNIT_PATH.read_text(encoding="utf-8")
    prod = _environment_values("prod")
    test = _environment_values("test")

    assert prod["PROBE_ENVIRONMENT"] == "prod"
    assert prod["PROBE_BASE_URL"] == "http://127.0.0.1:18000"
    assert prod["WORKER_HEARTBEAT_PATH"].endswith(
        "/pkm-prod_runtime-tmp/_data/worker_heartbeat.json"
    )
    assert prod["PROBE_ALERT_CHANNEL"] == "discord"

    assert test["PROBE_ENVIRONMENT"] == "test"
    assert test["PROBE_BASE_URL"] == "http://127.0.0.1:18002"
    assert test["WORKER_HEARTBEAT_PATH"].endswith(
        "/pkm-test_runtime-tmp/_data/worker_heartbeat.json"
    )
    assert test["PROBE_STATE_FILE"].endswith("host-probe-test/alert-state.json")
    assert test["PROBE_ALERT_CHANNEL"] == "discord"
    assert "prod" not in test["PROBE_STATE_FILE"]

    assert "EnvironmentFile=/etc/yggdrasil/host-probe/%i.env" in unit
    assert "LoadCredentialEncrypted=bws-machine-account-token:/var/lib/yggdrasil/bws-tokens/%i/current" in unit
    assert "StartLimitIntervalSec=0" in unit
    assert "RestartSec=60" in unit
    assert "/opt/yggdrasil/host-probe/ops/host-setup/linux/host_probe_launcher.py --channel %i" in unit
    assert "Requires=docker.service" not in unit
    assert "After=docker.service" not in unit
    assert "ExecStart=" in unit


def test_channel_config_renderer_rejects_implicit_or_unknown_channel() -> None:
    import pytest

    with pytest.raises(ValueError, match="probe channel is invalid"):
        render_probe_environment("dev")


def test_plan_uses_the_shared_protected_secret_controller_state() -> None:
    plan = installation_plan("prod", "fixture-commit")

    assert plan["controller_state_directory"] == CONTROLLER_STATE_DIRECTORY
    assert CONTROLLER_STATE_DIRECTORY.endswith("/secret-controller")


def test_mac_installer_keeps_the_old_production_probe_as_legacy_only() -> None:
    installer = MAC_INSTALLER_PATH.read_text(encoding="utf-8")
    plist = MAC_PLIST_PATH.read_text(encoding="utf-8")

    assert "launchctl load \"$PROBE_PLIST\"" not in installer
    assert "mac-mini/install.sh no longer registers it" in plist


def test_remote_main_readback_requires_one_valid_main_ref() -> None:
    head = "0123456789abcdef0123456789abcdef01234567"

    assert _parse_remote_main_readback(f"{head}\trefs/heads/main\n") == head

    import pytest

    with pytest.raises(ValueError, match="live origin/main readback"):
        _parse_remote_main_readback(f"{head}\trefs/heads/main\n{head}\trefs/heads/dev\n")


def test_deploy_config_requires_root_private_single_link_file(
    tmp_path: Path, monkeypatch
) -> None:
    import stat

    config = tmp_path / "prod.json"
    config.write_text(
        '{"project_id":"prod-project","organization_id":"org"}',
        encoding="utf-8",
    )

    def fake_fstat(_descriptor: int) -> SimpleNamespace:
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1)

    monkeypatch.setattr(host_probe_launcher.os, "fstat", fake_fstat)
    assert host_probe_launcher._read_deploy_identifiers("prod", tmp_path) == (
        "prod-project",
        "org",
    )

    for mode, links in ((0o640, 1), (0o666, 1), (0o600, 2)):
        monkeypatch.setattr(
            host_probe_launcher.os,
            "fstat",
            lambda _descriptor, mode=mode, links=links: SimpleNamespace(
                st_mode=stat.S_IFREG | mode, st_uid=0, st_nlink=links
            ),
        )
        with pytest.raises(ValueError, match="BWS channel configuration is unavailable"):
            host_probe_launcher._read_deploy_identifiers("prod", tmp_path)
