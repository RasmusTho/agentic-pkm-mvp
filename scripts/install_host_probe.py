#!/usr/bin/env python3
"""Install the bounded Linux host probe from an exact merged repository head."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHANNEL_HOST = {"test": "ygg-test", "prod": "ygg-prod"}
CHANNEL_CONFIG = {
    "test": {"port": 18002, "heartbeat_volume": "pkm-test_runtime-tmp"},
    "prod": {"port": 18000, "heartbeat_volume": "pkm-prod_runtime-tmp"},
}
PACKAGE_PATHS = (
    "app/__init__.py",
    "app/ops",
    "config/secrets/host_secret_contract.json",
    "config/systemd/yggdrasil-host-probe@.service",
    "ops/host-setup/linux/host_probe_launcher.py",
    "ops/host-setup/mac-mini/notification_channels.py",
    "ops/host-setup/mac-mini/prod_probe.py",
)
INSTALL_ROOT = "/opt/yggdrasil/host-probe"
CONTROLLER_STATE_DIRECTORY = "/root/.local/state/yggdrasil/secret-controller"


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _parse_remote_main_readback(output: str) -> str:
    lines = output.splitlines()
    if len(lines) != 1:
        raise ValueError("live origin/main readback is unavailable")
    fields = lines[0].split("\t")
    if (
        len(fields) != 2
        or fields[1] != "refs/heads/main"
        or len(fields[0]) not in {40, 64}
        or any(character not in "0123456789abcdef" for character in fields[0])
    ):
        raise ValueError("live origin/main readback is malformed")
    return fields[0]


def _repository_head() -> tuple[str, str]:
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    remote_head = _git("rev-parse", "origin/main")
    live_main = _parse_remote_main_readback(
        _git("ls-remote", "--exit-code", "origin", "refs/heads/main")
    )
    if remote_head != live_main:
        raise ValueError("local origin/main does not match the live remote head")
    if branch != "main" or head != remote_head:
        raise ValueError("installation source must be the exact local origin/main head")
    if _git("status", "--porcelain"):
        raise ValueError("installation source must be clean")
    return branch, head


def installation_plan(channel: str, head: str) -> dict[str, object]:
    if channel not in CHANNEL_HOST:
        raise ValueError("probe channel is invalid")
    return {
        "schema": "probe_installation_plan.v1",
        "channel": channel,
        "target_host": CHANNEL_HOST[channel],
        "source_commit": head,
        "install_directory": INSTALL_ROOT,
        "unit": f"yggdrasil-host-probe@{channel}.service",
        "configuration": f"config/host-probe/{channel}.env",
        "controller_state_directory": CONTROLLER_STATE_DIRECTORY,
        "secret_binding": "heimdal-external-alerts / discord.webhook via BWS reader",
        "apply_required": True,
    }


def render_probe_environment(channel: str) -> str:
    if channel not in CHANNEL_CONFIG:
        raise ValueError("probe channel is invalid")
    config = CHANNEL_CONFIG[channel]
    values = {
        "PROBE_ENVIRONMENT": channel,
        "PROBE_BASE_URL": f"http://127.0.0.1:{config['port']}",
        "WORKER_HEARTBEAT_PATH": (
            f"/var/lib/docker/volumes/{config['heartbeat_volume']}/_data/worker_heartbeat.json"
        ),
        "WORKER_HEARTBEAT_STALE_SECONDS": "60",
        "PROBE_STATE_FILE": f"/var/lib/yggdrasil-host-probe-{channel}/alert-state.json",
        "PROBE_INTERVAL_SECONDS": "60",
        "PROBE_ALERT_CHANNEL": "discord",
        "PROBE_REMEDIATION_URL": (
            "https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/"
            "docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md"
        ),
    }
    return "".join(f"{name}={value}\n" for name, value in values.items())


def _archive(head: str) -> bytes:
    result = subprocess.run(
        [
            "git",
            "archive",
            "--format=tar",
            head,
            "--",
            *PACKAGE_PATHS,
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout


def _ssh(host: str, *remote_arguments: str, input_bytes: bytes | None = None) -> str:
    result = subprocess.run(
        ["ssh", host, *remote_arguments],
        cwd=REPOSITORY_ROOT,
        input=input_bytes,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8", errors="replace").strip()


def _install(channel: str, head: str) -> dict[str, object]:
    host = CHANNEL_HOST[channel]
    payload = _archive(head)
    _ssh(host, "sudo", "install", "-d", "-m", "0755", INSTALL_ROOT)
    _ssh(host, "sudo", "tar", "--no-same-owner", "-xf", "-", "-C", INSTALL_ROOT, input_bytes=payload)
    _ssh(
        host,
        "sudo",
        "install",
        "-d",
        "-m",
        "0755",
        "/etc/yggdrasil/host-probe",
    )
    _ssh(
        host,
        "sudo",
        "install",
        "-d",
        "-m",
        "0700",
        CONTROLLER_STATE_DIRECTORY,
    )
    _ssh(
        host,
        "sudo",
        "install",
        "-m",
        "0644",
        f"{INSTALL_ROOT}/config/systemd/yggdrasil-host-probe@.service",
        "/etc/systemd/system/yggdrasil-host-probe@.service",
    )
    config = render_probe_environment(channel).encode("utf-8")
    _ssh(
        host,
        "sudo",
        "install",
        "-m",
        "0644",
        "/dev/stdin",
        f"/etc/yggdrasil/host-probe/{channel}.env",
        input_bytes=config,
    )
    _ssh(host, "sudo", "systemctl", "daemon-reload")
    _ssh(host, "sudo", "systemctl", "restart", f"yggdrasil-host-probe@{channel}.service")
    active = _ssh(host, "sudo", "systemctl", "is-active", f"yggdrasil-host-probe@{channel}.service")
    if active != "active":
        raise RuntimeError("host probe service did not become active")
    _ssh(host, "sudo", "systemctl", "enable", f"yggdrasil-host-probe@{channel}.service")
    return {
        "schema": "probe_installation.v1",
        "channel": channel,
        "target_host": host,
        "source_commit": head,
        "unit": f"yggdrasil-host-probe@{channel}.service",
        "active": True,
        "enabled": True,
        "installed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=tuple(CHANNEL_HOST), required=True)
    parser.add_argument("--apply", action="store_true", help="perform the target host installation")
    args = parser.parse_args(argv)
    try:
        _, head = _repository_head()
        plan = installation_plan(args.channel, head)
        if args.apply:
            receipt = _install(args.channel, head)
            print(json.dumps(receipt, sort_keys=True))
        else:
            print(json.dumps(plan, sort_keys=True))
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        print(f"host probe installation refused or failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
