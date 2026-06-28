"""Container health signals tests (OBSSTAB-02 / #2599).

Verifies:
1. Worker freshness probe exits non-zero when the heartbeat JSON ``ts`` is stale.
2. Watcher freshness probe exits non-zero when the heartbeat JSON ``ts`` is stale.
3. The ollama service defines a healthcheck block in docker-compose.yaml.
4. api, worker, and watcher depend on db with ``condition: service_healthy``.

All four tests parse / execute the REAL artifacts (the actual probe command from
docker-compose.yaml and the actual compose YAML) — no stubs of the thing under test.

Docker is NOT required: the freshness tests invoke the probe as an in-process
Python call, and the compose tests parse the YAML statically.

Freshness is keyed on the heartbeat JSON ``ts`` field, NOT file mtime.
A ``touch`` on the heartbeat file would NOT register as stale because the probe
reads and compares the JSON ``ts`` timestamp. These tests backdate the JSON ``ts``
value explicitly.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yaml"

# How many seconds in the past to backdate the heartbeat ``ts`` to guarantee staleness.
# The default WORKER/WATCHER_HEARTBEAT_STALE_SECONDS is 60 s; we write a ts that is
# 3× that so the probe reliably sees it as stale regardless of clock skew.
_BACKDATE_SECONDS = 200


def _write_stale_heartbeat(path: Path) -> None:
    """Write a heartbeat JSON with a ``ts`` that is _BACKDATE_SECONDS in the past.

    This is the only correct way to simulate staleness for the probe: the probe
    reads the JSON ``ts`` field, NOT the file mtime. A ``touch`` would NOT make
    the probe detect staleness.
    """
    stale_ts = time.time() - _BACKDATE_SECONDS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts": stale_ts, "status": "running"}), encoding="utf-8")


def _run_probe(probe_snippet: str, env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    """Execute a probe Python snippet as a subprocess so we get the real exit code."""
    import os

    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", probe_snippet],
        env=env,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Extract probe commands from the compose file so tests stay in sync with it
# ---------------------------------------------------------------------------

def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _probe_snippet(service: str, compose: dict) -> str:
    """Return the Python snippet that the service healthcheck runs (strips CMD-SHELL prefix)."""
    test_cmd = compose["services"][service]["healthcheck"]["test"]
    # test_cmd is ["CMD-SHELL", "<snippet>"]
    assert test_cmd[0] == "CMD-SHELL", f"Expected CMD-SHELL for {service}, got {test_cmd[0]}"
    raw = test_cmd[1]
    # The snippet is a python -c "..." command; extract the Python body.
    # Format: python -c "..." or python3 -c "..."
    # We execute the full shell command as a Python snippet through subprocess,
    # but for the freshness probes the snippet IS Python, so we extract and run it directly.
    assert raw.startswith("python ") or raw.startswith("python3 "), (
        f"Expected probe to start with python[-c] for {service}; got: {raw[:60]}"
    )
    # Strip the `python -c "..."` wrapper to get the inner expression
    for prefix in ('python -c "', 'python3 -c "'):
        if raw.startswith(prefix):
            return raw[len(prefix) : -1]  # strip leading prefix and trailing "
    raise AssertionError(f"Could not parse probe snippet for {service}: {raw}")


# ---------------------------------------------------------------------------
# AC1: Worker freshness probe exits non-zero on stale heartbeat JSON ts
# ---------------------------------------------------------------------------

def test_worker_unhealthy_on_stale_heartbeat(tmp_path: pytest.TempPathFactory) -> None:
    """The worker probe exits non-zero when the heartbeat JSON ``ts`` is stale.

    Freshness is keyed on the JSON ``ts`` field — NOT file mtime.
    The test writes a heartbeat with an old ``ts`` (not a touch), then runs the
    exact probe snippet extracted from docker-compose.yaml.
    """
    compose = _load_compose()
    probe = _probe_snippet("worker", compose)

    heartbeat_path = tmp_path / "worker_heartbeat.json"
    _write_stale_heartbeat(heartbeat_path)

    result = _run_probe(
        probe,
        {
            "WORKER_HEARTBEAT_PATH": str(heartbeat_path),
            # Force worker enabled so the probe doesn't skip due to memory backend
            "STORE_BACKEND": "pg",
            "WORKER_ENABLE": "true",
        },
    )

    assert result.returncode != 0, (
        f"Expected non-zero exit for stale worker heartbeat (ts backdated {_BACKDATE_SECONDS}s); "
        f"got exit {result.returncode}. probe: {probe!r}\n"
        f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
    )


# ---------------------------------------------------------------------------
# AC2: Watcher freshness probe exits non-zero on stale heartbeat JSON ts
# ---------------------------------------------------------------------------

def test_watcher_unhealthy_on_stale_heartbeat(tmp_path: pytest.TempPathFactory) -> None:
    """The watcher probe exits non-zero when the heartbeat JSON ``ts`` is stale.

    Freshness is keyed on the JSON ``ts`` field — NOT file mtime.
    """
    compose = _load_compose()
    probe = _probe_snippet("watcher", compose)

    heartbeat_path = tmp_path / "watcher_heartbeat.json"
    _write_stale_heartbeat(heartbeat_path)

    result = _run_probe(
        probe,
        {
            "WATCHER_HEARTBEAT_PATH": str(heartbeat_path),
        },
    )

    assert result.returncode != 0, (
        f"Expected non-zero exit for stale watcher heartbeat (ts backdated {_BACKDATE_SECONDS}s); "
        f"got exit {result.returncode}. probe: {probe!r}\n"
        f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
    )


# ---------------------------------------------------------------------------
# AC3: ollama service defines a healthcheck block
# ---------------------------------------------------------------------------

def test_ollama_has_healthcheck() -> None:
    """The ollama service in docker-compose.yaml defines a healthcheck block."""
    compose = _load_compose()
    ollama = compose["services"].get("ollama")
    assert ollama is not None, "ollama service missing from docker-compose.yaml"

    hc = ollama.get("healthcheck")
    assert hc is not None, (
        "ollama service has no healthcheck block in docker-compose.yaml"
    )
    assert "test" in hc, "ollama healthcheck block is missing 'test' key"

    # The test command must reference the api/tags endpoint
    test_cmd = hc["test"]
    test_str = " ".join(test_cmd) if isinstance(test_cmd, list) else str(test_cmd)
    assert "11434" in test_str or "api/tags" in test_str, (
        f"ollama healthcheck does not reference port 11434 or /api/tags: {test_str!r}"
    )


# ---------------------------------------------------------------------------
# AC4: api, worker, watcher depend on db with condition: service_healthy
# ---------------------------------------------------------------------------

def test_db_dependents_gate_on_service_healthy() -> None:
    """api, worker, and watcher declare depends_on: db: condition: service_healthy."""
    compose = _load_compose()
    services = compose["services"]

    for svc_name in ("api", "worker", "watcher"):
        svc = services.get(svc_name)
        assert svc is not None, f"Service '{svc_name}' missing from docker-compose.yaml"

        depends_on = svc.get("depends_on")
        assert depends_on is not None, (
            f"Service '{svc_name}' has no depends_on entry"
        )
        assert isinstance(depends_on, dict), (
            f"Service '{svc_name}' depends_on must be a mapping (not a list) to declare "
            f"condition; got {type(depends_on).__name__}: {depends_on!r}"
        )
        assert "db" in depends_on, (
            f"Service '{svc_name}' does not list 'db' in depends_on"
        )

        db_dep = depends_on["db"]
        assert isinstance(db_dep, dict), (
            f"Service '{svc_name}' depends_on.db must be a mapping; got {db_dep!r}"
        )
        condition = db_dep.get("condition")
        assert condition == "service_healthy", (
            f"Service '{svc_name}' depends_on.db.condition must be 'service_healthy'; "
            f"got {condition!r}"
        )
