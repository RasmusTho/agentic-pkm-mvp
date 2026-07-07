"""Cross-container heartbeat visibility for `/api/health` (#2991).

Root cause fixed: `app/cli/health.py::_watcher_runtime_status` /
`_worker_runtime_status` and the watcher/worker heartbeat writers
(`app/watcher/heartbeat.py`, `app/runtime/worker_heartbeat.py`) all resolve the
identical *absolute* path from `WATCHER_HEARTBEAT_PATH` / `WORKER_HEARTBEAT_PATH`
(`config/runtime.defaults.env`), but the api/worker/watcher containers had no
shared filesystem surface backing that path — each container did its own
`mkdir -p /app/tmp`, so the api container always read its own empty local file
and reported "not running (no heartbeat)" even while watcher/worker were alive
and heartbeating in their own containers.

The fix adds a shared named volume (`runtime-tmp`, declared once in the base
`docker-compose.yaml`, namespaced per compose project so dev/test/prod stay
isolated) mounted at `/app/tmp` (and `/app/tmp-test` for the test channel
override) across api/worker/watcher.

A full multi-container docker topology is not exercised here (no docker
required for this suite). Per the issue's own instruction, this test suite
verifies the two contracts that actually decide the AC:

1. The compose topology genuinely declares a *shared* volume mounted into all
   three services at the path the heartbeat env vars resolve to (parses the
   real `docker-compose.yaml`, no stub of the artifact under test) — this is
   the structural half of "runtime.watcher / runtime.worker report ok when
   watcher/worker are running in their own containers": if this volume/mount
   is absent, cross-container visibility cannot exist regardless of what the
   Python-level status functions do.
2. The Python-level path-resolution + staleness contract: a heartbeat file
   written at the shared, env-resolved path is read as fresh/ok, and a missing
   or stale file is honestly reported as not running — never a false "ok" from
   a stale artifact (see `_heartbeat_status` staleness logic in
   `app/cli/health.py:473-498`).
"""

from __future__ import annotations

import json
import logging
import os
import stat
import time
from pathlib import Path

import pytest
import yaml

from app.cli.health import _watcher_runtime_status, _worker_runtime_status
from app.runtime.worker_heartbeat import write_worker_heartbeat
from app.watcher.heartbeat import write_runtime_heartbeat

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yaml"


def _load_compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _mount_targets(service: dict) -> set[str]:
    targets: set[str] = set()
    for entry in service.get("volumes", []):
        if isinstance(entry, str):
            # short syntax: "source:target" or "source:target:mode"
            parts = entry.split(":")
            if len(parts) >= 2:
                targets.add(parts[1])
        elif isinstance(entry, dict):
            target = entry.get("target")
            if target:
                targets.add(target)
    return targets


def _named_volume_sources(service: dict) -> set[str]:
    sources: set[str] = set()
    for entry in service.get("volumes", []):
        if isinstance(entry, str):
            parts = entry.split(":")
            if len(parts) >= 2 and not parts[0].startswith((".", "/")):
                sources.add(parts[0])
        elif isinstance(entry, dict) and entry.get("type") == "volume":
            source = entry.get("source")
            if source:
                sources.add(source)
    return sources


@pytest.mark.uat_integrated_runtime
@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATED_RUNTIME_UAT", "").strip().lower()
    not in {"1", "true", "yes", "on"},
    reason="opt-in integrated runtime UAT; set RUN_INTEGRATED_RUNTIME_UAT=1",
)
def test_health_sees_cross_container_heartbeats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/api/health`-equivalent status functions report ok from a shared surface.

    Structural half: api/worker/watcher declare a genuinely SHARED named
    volume (not three independent container-local dirs) mounted at the same
    target path the heartbeat env vars resolve to in the base compose file.
    Behavioral half: given that shared path, a live heartbeat written by
    "watcher"/"worker" is visible to the "api" reader — modeled here as three
    logical roles all resolving the identical absolute path, exactly as they
    do inside containers sharing the `runtime-tmp` volume.
    """
    compose = _load_compose()
    services = compose["services"]
    api_svc, worker_svc, watcher_svc = services["api"], services["worker"], services["watcher"]

    api_volume_sources = _named_volume_sources(api_svc)
    worker_volume_sources = _named_volume_sources(worker_svc)
    watcher_volume_sources = _named_volume_sources(watcher_svc)
    shared_sources = api_volume_sources & worker_volume_sources & watcher_volume_sources
    assert shared_sources, (
        "api, worker, and watcher must share at least one named volume so the "
        "api container can see watcher/worker heartbeat writes; got "
        f"api={api_volume_sources} worker={worker_volume_sources} watcher={watcher_volume_sources}"
    )

    # The shared volume must actually be mounted at the path the heartbeat env
    # vars resolve to by default (/app/tmp), not at some unrelated path.
    assert "/app/tmp" in _mount_targets(api_svc)
    assert "/app/tmp" in _mount_targets(worker_svc)
    assert "/app/tmp" in _mount_targets(watcher_svc)

    heartbeat_dir = tmp_path / "app-tmp"
    heartbeat_dir.mkdir()
    watcher_heartbeat = heartbeat_dir / "watcher_heartbeat.json"
    worker_heartbeat = heartbeat_dir / "worker_heartbeat.json"

    now = time.time()
    watcher_heartbeat.write_text(
        json.dumps({"ts": now, "paused": False}), encoding="utf-8"
    )
    worker_heartbeat.write_text(
        json.dumps({"ts": now, "status": "running"}), encoding="utf-8"
    )

    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(watcher_heartbeat))
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(worker_heartbeat))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("WORKER_ENABLE", "true")

    watcher_status = _watcher_runtime_status(now=now)
    worker_status = _worker_runtime_status(now=now)

    assert watcher_status["ok"] is True, watcher_status
    assert worker_status["ok"] is True, worker_status


def test_stopped_watcher_reported_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing or stale heartbeat file is never reported as ok (no false positive).

    Covers both legs of the constraint "Health must fail loud if the heartbeat
    surface is missing, not report a false 'ok'": (a) the file never existed
    (watcher never started / container never wrote anything to the shared
    surface), and (b) the file exists but its `ts` is older than the staleness
    threshold (watcher process died without cleaning up).
    """
    heartbeat_dir = tmp_path / "app-tmp"
    heartbeat_dir.mkdir()
    watcher_heartbeat = heartbeat_dir / "watcher_heartbeat.json"

    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(watcher_heartbeat))
    monkeypatch.setenv("WATCHER_HEARTBEAT_STALE_SECONDS", "60")

    # (a) missing file entirely.
    assert not watcher_heartbeat.exists()
    missing_status = _watcher_runtime_status()
    assert missing_status["ok"] is False, missing_status

    # (b) stale file — watcher wrote once, then stopped/died.
    stale_ts = time.time() - 200
    watcher_heartbeat.write_text(json.dumps({"ts": stale_ts, "paused": False}), encoding="utf-8")
    stale_status = _watcher_runtime_status()
    assert stale_status["ok"] is False, stale_status


# ---------------------------------------------------------------------------
# #3118 — self-heal past a root-owned, permission-denied heartbeat file, and
# make the write failure visible instead of silently swallowed.
#
# A real cross-uid root-owned file cannot be constructed in this sandbox
# (no root / no docker), and POSIX sticky-bit "restricted deletion" rules
# mean a genuinely root-owned file inside a sticky (mode 1777) directory is
# NOT unprivileged-recoverable in the first place (verified against
# `unlink(2)`/`rename(2)` semantics — see the `_write_payload` docstrings in
# `app/watcher/heartbeat.py` / `app/runtime/worker_heartbeat.py`). What these
# tests verify is the writer's *reaction* to the OS raising `PermissionError`
# on the truncate-write and/or the unlink: the recoverable case (this process
# owns the file, e.g. a stale non-sticky-dir or same-uid mode-drift artifact)
# self-heals; the unrecoverable case is logged loudly rather than discarded.
# ---------------------------------------------------------------------------


def test_heartbeat_writable_after_ownership_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A stale, permission-denied heartbeat file is removed and rewritten.

    Simulates ownership drift by making the existing file's own write bit
    denied to this process (mode 0o444) — reproducing the `PermissionError`
    a real root-owned `rw-r--r--` file raises against a non-owner uid on
    `Path.write_text`'s O_TRUNC open. Since this test process still owns the
    file (it created it), `unlink` on it succeeds under POSIX rules even
    inside a sticky-bit-equivalent directory — this is exactly the
    "recoverable" half of the self-heal (self-owned stale mode drift, or a
    non-sticky parent dir); the genuinely-root-owned-in-a-sticky-dir case is
    an unprivileged dead end by construction (see module docstring) and is
    covered separately by `test_unrecoverable_permission_error_is_logged_not_silent`.
    """
    caplog.set_level(logging.INFO)

    heartbeat_dir = tmp_path / "runtime-tmp"
    heartbeat_dir.mkdir()
    watcher_heartbeat = heartbeat_dir / "watcher_heartbeat.json"
    worker_heartbeat = heartbeat_dir / "worker_heartbeat.json"

    # Simulate a prior write context leaving a permission-denied file behind.
    watcher_heartbeat.write_text(json.dumps({"ts": 1.0, "stale": True}), encoding="utf-8")
    watcher_heartbeat.chmod(stat.S_IREAD)
    worker_heartbeat.write_text(json.dumps({"ts": 1.0, "stale": True}), encoding="utf-8")
    worker_heartbeat.chmod(stat.S_IREAD)

    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(watcher_heartbeat))
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(worker_heartbeat))

    # Container recreation after the drift: the writer ticks again and must
    # not require any manual chown to produce a fresh, readable heartbeat.
    write_runtime_heartbeat(ticks=1, changed=0, errors=0)
    write_worker_heartbeat(
        path=worker_heartbeat,
        ticks_total=1,
        errors_total=0,
        outbox_path=tmp_path / "outbox.jsonl",
    )

    watcher_payload = json.loads(watcher_heartbeat.read_text(encoding="utf-8"))
    worker_payload = json.loads(worker_heartbeat.read_text(encoding="utf-8"))
    assert watcher_payload.get("ticks") == 1
    assert worker_payload.get("ticks_total") == 1

    # The freshly (re)created file must be world-writable so a FUTURE uid
    # change on the same shared volume cannot reproduce the trap.
    assert stat.S_IMODE(watcher_heartbeat.stat().st_mode) == 0o666
    assert stat.S_IMODE(worker_heartbeat.stat().st_mode) == 0o666

    # No manual chown was performed anywhere in this test — self-heal was
    # entirely internal to the writer.
    assert any("self-heal succeeded" in record.message for record in caplog.records)

    # Reader confirms cross-container visibility is restored (the original
    # AC's own health-status contract), not just "the file exists."
    now = time.time()
    watcher_ts_payload = json.loads(watcher_heartbeat.read_text(encoding="utf-8"))
    watcher_ts_payload["ts"] = now
    watcher_heartbeat.write_text(json.dumps(watcher_ts_payload), encoding="utf-8")
    status = _watcher_runtime_status(now=now)
    assert status["ok"] is True, status


def test_unrecoverable_permission_error_is_logged_not_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A write failure that cannot self-heal is logged loudly, never silent.

    Models the genuinely unrecoverable case (root-owned file inside a
    sticky-bit dir, non-root non-owner writer) by making BOTH the truncate
    write and the unlink raise `PermissionError` — the writer must not
    swallow this into a bare `return` (the pre-#3118 behavior that produced
    the silent, permanently-stale health status).
    """
    caplog.set_level(logging.ERROR)

    heartbeat_dir = tmp_path / "runtime-tmp"
    heartbeat_dir.mkdir()
    watcher_heartbeat = heartbeat_dir / "watcher_heartbeat.json"
    watcher_heartbeat.write_text(json.dumps({"ts": 1.0, "stale": True}), encoding="utf-8")

    def _deny_write(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied", str(self))

    def _deny_unlink(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "write_text", _deny_write)
    monkeypatch.setattr(Path, "unlink", _deny_unlink)
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(watcher_heartbeat))

    # Must not raise — the caller (watcher tick loop) cannot crash-loop on a
    # heartbeat write failure.
    write_runtime_heartbeat(ticks=1, changed=0, errors=0)

    assert any(
        record.levelno >= logging.ERROR and "self-heal FAILED" in record.message
        for record in caplog.records
    ), [r.message for r in caplog.records]
