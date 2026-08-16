"""Regression coverage for the lean Docker heartbeat probe (#3464)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from app.runtime import health_probe

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yaml"


def _probe(role: str, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "app.runtime.health_probe", role],
        cwd=REPO_ROOT,
        env=merged_env,
        capture_output=True,
        check=False,
        timeout=5,
    )


@pytest.mark.parametrize(
    ("role", "path_env", "extra_env"),
    [
        ("worker", "WORKER_HEARTBEAT_PATH", {"STORE_BACKEND": "pg", "WORKER_ENABLE": "true"}),
        ("watcher", "WATCHER_HEARTBEAT_PATH", {}),
    ],
)
def test_worker_probe_exit_codes(
    tmp_path: Path, role: str, path_env: str, extra_env: dict[str, str]
) -> None:
    heartbeat = tmp_path / f"{role}.json"
    base_env = {path_env: str(heartbeat), **extra_env}

    heartbeat.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
    assert _probe(role, base_env).returncode == 0

    heartbeat.write_text(json.dumps({"ts": time.time() - 120}), encoding="utf-8")
    assert _probe(role, base_env).returncode == 1


def test_worker_probe_fails_readiness_for_binding_blocked_heartbeat(
    tmp_path: Path,
) -> None:
    heartbeat = tmp_path / "worker.json"
    heartbeat.write_text(
        json.dumps(
            {
                "ts": time.time(),
                "status": "blocked_pending_mvr06",
                "binding_blocked_pending": 2,
            }
        ),
        encoding="utf-8",
    )

    result = _probe(
        "worker",
        {
            "WORKER_HEARTBEAT_PATH": str(heartbeat),
            "STORE_BACKEND": "pg",
            "WORKER_ENABLE": "true",
        },
    )

    assert result.returncode == 1


def test_watcher_probe_exit_codes(tmp_path: Path) -> None:
    # The parametrized test above keeps the named worker AC compact; this named
    # test is retained as the explicit issue Verify target for watcher.
    heartbeat = tmp_path / "watcher.json"
    env = {"WATCHER_HEARTBEAT_PATH": str(heartbeat)}
    heartbeat.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
    assert _probe("watcher", env).returncode == 0
    heartbeat.write_text(json.dumps({"ts": time.time() - 120}), encoding="utf-8")
    assert _probe("watcher", env).returncode == 1


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO timeout probe requires POSIX")
def test_probe_self_timeout_never_hangs(tmp_path: Path) -> None:
    fifo = tmp_path / "blocked-heartbeat"
    os.mkfifo(fifo)
    started = time.monotonic()
    result = _probe(
        "watcher",
        {
            "WATCHER_HEARTBEAT_PATH": str(fifo),
            "HEALTH_PROBE_TIMEOUT_SECONDS": "1",
        },
    )
    assert result.returncode == 2
    assert time.monotonic() - started < 2.5


def test_probe_import_graph_is_lean() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import app.runtime.health_probe; "
            "blocked={'app.cli','httpx','click','watchfiles'}; "
            "raise SystemExit(bool(blocked & set(sys.modules)))",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize(
    ("env_name", "resolver_name"),
    [
        ("WATCHER_HEARTBEAT_PATH", "_resolve_watcher_heartbeat_path"),
        ("WORKER_HEARTBEAT_PATH", "_resolve_worker_heartbeat_path"),
    ],
)
def test_unset_probe_path_preserves_host_resolver(
    monkeypatch: pytest.MonkeyPatch, env_name: str, resolver_name: str
) -> None:
    """An unset Compose env must retain the API's settings-backed host path."""
    monkeypatch.delenv(env_name, raising=False)
    resolver = getattr(health_probe, resolver_name)
    resolved = resolver()
    if env_name == "WATCHER_HEARTBEAT_PATH":
        from app.watcher.heartbeat import resolve_heartbeat_path

        assert resolved == resolve_heartbeat_path()
    else:
        from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path

        assert resolved == resolve_worker_heartbeat_path()


def test_compose_healthcheck_is_safe() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    for service_name in ("worker", "watcher"):
        service = compose["services"][service_name]
        assert service["init"] is True
        assert service["healthcheck"]["test"] == [
            "CMD", "python", "-m", "app.runtime.health_probe", service_name
        ]
        assert service["healthcheck"]["interval"] > service["healthcheck"]["timeout"]
