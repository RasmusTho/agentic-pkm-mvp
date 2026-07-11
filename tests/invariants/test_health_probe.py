"""Guards for the lean container healthcheck probe (`app.runtime.health_probe`).

Regression cover for the worker/watcher healthcheck resource leak: a heavy,
shell-wrapped probe that imported the whole `app.cli` stack, ran without an
init/reaper, and used `interval < timeout`, so timed-out probes were orphaned
and accumulated unbounded while the container falsely reported `unhealthy`.

The invariants below lock in the three structural properties that make the
probe safe:

* it exits fast with the right code from heartbeat freshness alone,
* it self-terminates on a hard deadline (never hangs/accumulates),
* its import graph is lean (no `app.cli` / httpx / click / watchfiles), and
* the compose healthcheck invokes it via the direct exec form with an init and
  `interval > timeout`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from app.runtime import health_probe

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yaml"


def _write_heartbeat(path: Path, *, ts: float, **extra: object) -> None:
    payload: dict[str, object] = {"ts": ts}
    payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_worker_probe_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    heartbeat = tmp_path / "worker_heartbeat.json"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(heartbeat))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("WORKER_ENABLE", "true")

    # Fresh heartbeat -> healthy (0).
    _write_heartbeat(heartbeat, ts=time.time(), status="running")
    assert health_probe.main(["worker"]) == 0

    # Stale heartbeat -> unhealthy (1), never a false ok.
    _write_heartbeat(heartbeat, ts=time.time() - 10_000, status="running")
    assert health_probe.main(["worker"]) == 1

    # Missing heartbeat -> unhealthy (1).
    heartbeat.unlink()
    assert health_probe.main(["worker"]) == 1


def test_watcher_probe_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    heartbeat = tmp_path / "watcher_heartbeat.json"
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(heartbeat))

    _write_heartbeat(heartbeat, ts=time.time(), paused=False)
    assert health_probe.main(["watcher"]) == 0

    _write_heartbeat(heartbeat, ts=time.time() - 10_000, paused=False)
    assert health_probe.main(["watcher"]) == 1


def test_unknown_target_returns_usage_error() -> None:
    assert health_probe.main(["nope"]) == 2
    assert health_probe.main([]) == 2


def test_probe_self_timeout_never_hangs() -> None:
    """A wedged status function must self-terminate within the deadline, not hang.

    Runs the probe in a subprocess with a tiny deadline against a status
    function that would otherwise block for 30s; the probe must return the
    unhealthy exit code promptly via its SIGALRM self-timeout. This is the
    property that makes stuck probes impossible regardless of Docker's (here
    unreliable) timeout enforcement.
    """
    import os

    started = time.monotonic()
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import time, app.runtime.health_probe as hp;"
                "hp._TARGETS['wedged'] = lambda: (time.sleep(30), {'ok': True})[1];"
                "raise SystemExit(hp.main(['wedged']))"
            ),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "HEALTHCHECK_PROBE_TIMEOUT_SECONDS": "0.3"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    elapsed = time.monotonic() - started
    assert proc.returncode == 1, proc.stderr
    assert elapsed < 10, f"probe did not self-terminate promptly ({elapsed:.1f}s)"


def test_main_disarms_self_timeout_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`main()` must leave no armed SIGALRM itimer after it returns.

    The self-timeout handler calls `os._exit(1)`. If `main` returned without
    disarming the itimer, a later firing would kill the *host* process — e.g.
    the pytest runner ~10s into a suite. This asserts the itimer is cleared on
    the normal return path.
    """
    import signal

    if not hasattr(signal, "SIGALRM"):
        pytest.skip("SIGALRM not available on this platform")

    heartbeat = tmp_path / "watcher_heartbeat.json"
    _write_heartbeat(heartbeat, ts=time.time(), paused=False)
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(heartbeat))

    assert health_probe.main(["watcher"]) == 0
    # (0.0, 0.0) means no interval timer is pending.
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_probe_import_graph_is_lean() -> None:
    """Importing the probe must NOT pull in the heavy `app.cli` / http stacks.

    This is the core regression guard: the whole point of the module is that a
    fresh healthcheck process imports a stdlib-scale graph. If someone adds a
    top-level `import httpx` (or an `app.cli.*` import) here, the probe becomes
    slow again under load and the leak can reappear.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.runtime.health_probe;"
                "heavy = [m for m in ('app.cli', 'httpx', 'click', 'watchfiles') "
                "if m in sys.modules];"
                "print(','.join(heavy));"
                "sys.exit(1 if heavy else 0)"
            ),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        "health_probe import pulled in heavy modules at module load: "
        f"{proc.stdout.strip()!r}"
    )


def test_compose_healthcheck_is_safe() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]

    for name in ("worker", "watcher"):
        svc = services[name]

        # init: true -> tini as PID 1 reaps exited probe processes.
        assert svc.get("init") is True, f"{name} must set init: true to reap probes"

        hc = svc["healthcheck"]
        test = hc["test"]
        # Direct exec form (["CMD", ...]) so Docker's timeout kill targets the
        # python process itself, not an orphan-leaving shell wrapper.
        assert test[0] == "CMD", f"{name} healthcheck must use CMD exec form, got {test[0]}"
        assert test[1:] == [
            "python",
            "-m",
            "app.runtime.health_probe",
            name,
        ], f"{name} healthcheck must invoke the lean probe module: {test}"

        # interval strictly greater than timeout so probes never overlap.
        interval = _duration_seconds(hc["interval"])
        timeout = _duration_seconds(hc["timeout"])
        assert interval > timeout, (
            f"{name} healthcheck interval ({hc['interval']}) must exceed "
            f"timeout ({hc['timeout']}) so probes never overlap"
        )


def _duration_seconds(value: str) -> float:
    raw = str(value).strip()
    if raw.endswith("ms"):
        return float(raw[:-2]) / 1000.0
    if raw.endswith("s"):
        return float(raw[:-1])
    if raw.endswith("m"):
        return float(raw[:-1]) * 60.0
    return float(raw)
