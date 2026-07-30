"""Regression tests for the prod-backup watcher and its alert state machine.

The failure this guards against is a nightly dump job that fails — or stops
firing entirely — without anyone noticing for three weeks (2026-07-06..07-29).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROBE_MODULE_DIR = Path(__file__).parent.parent.parent / "ops" / "host-setup" / "mac-mini"
sys.path.insert(0, str(PROBE_MODULE_DIR))

import prod_backup_probe  # noqa: E402

HOUR = 3600.0
NOW = 1_785_000_000.0  # fixed clock; the probe takes `now` explicitly


def _make_spy_channel() -> MagicMock:
    return MagicMock(spec=prod_backup_probe.NullChannel)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_dump(backup_dir: Path, name: str, age_hours: float) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / name
    path.write_bytes(b"PGDMP-fake")
    mtime = NOW - age_hours * HOUR
    os.utime(path, (mtime, mtime))
    return path


def _write_status(
    tmp_path: Path,
    verdict: str,
    detail: str,
    age_hours: float,
    name: str = "prod-pgdump.status",
) -> Path:
    path = tmp_path / name
    path.write_text(f"{_iso(NOW - age_hours * HOUR)} {verdict} {detail}\n")
    return path


@pytest.fixture()
def healthy_world(tmp_path: Path) -> tuple[Path, Path]:
    """A fresh dump plus a fresh OK status line."""
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-20260729-030000.dump", age_hours=6)
    status = _write_status(
        tmp_path, "OK", "/Volumes/T7/prod-db-backups/prod-20260729-030000.dump", age_hours=6
    )
    return backup_dir, status


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_file = tmp_path / "backup-probe.state"
    monkeypatch.setattr(prod_backup_probe, "ALERT_STATE_FILE", state_file)
    return state_file


def _run(
    backup_dir: Path,
    status: Path,
    channel: MagicMock,
    now: float = NOW,
) -> bool:
    return prod_backup_probe.run_probe(
        backup_dir=backup_dir,
        status_file=status,
        channel=channel,
        now=now,
    )


# ---------------------------------------------------------------------------
# Healthy baseline
# ---------------------------------------------------------------------------
def test_fresh_dump_and_ok_status_is_healthy_and_silent(
    healthy_world: tuple[Path, Path],
) -> None:
    backup_dir, status = healthy_world
    channel = _make_spy_channel()

    assert _run(backup_dir, status, channel) is True
    channel.send.assert_not_called()


# ---------------------------------------------------------------------------
# Staleness — the failure mode that produces no FAIL line at all
# ---------------------------------------------------------------------------
def test_stale_dump_alerts_even_when_status_says_ok(tmp_path: Path) -> None:
    """A job that stopped firing leaves a stale dump behind an OK verdict."""
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-20260711-092810.dump", age_hours=18 * 24)
    status = _write_status(tmp_path, "OK", "/Volumes/T7/…/prod-20260711.dump", age_hours=18 * 24)
    channel = _make_spy_channel()

    assert _run(backup_dir, status, channel) is False

    channel.send.assert_called_once()
    body = channel.send.call_args[0][1]
    assert "prod-20260711-092810.dump" in body
    assert "budget 48h" in body
    assert "did not fire" in body


def test_stale_status_file_alerts_even_when_dump_is_fresh(tmp_path: Path) -> None:
    """The status file itself going stale is its own signal."""
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-20260729-030000.dump", age_hours=2)
    status = _write_status(tmp_path, "OK", "/Volumes/T7/…/prod.dump", age_hours=40)
    channel = _make_spy_channel()

    assert _run(backup_dir, status, channel) is False
    assert "did not fire" in channel.send.call_args[0][1]


def test_missing_status_file_alerts(tmp_path: Path) -> None:
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-20260729-030000.dump", age_hours=2)
    channel = _make_spy_channel()

    assert _run(backup_dir, tmp_path / "absent.status", channel) is False
    assert "missing" in channel.send.call_args[0][1]


# ---------------------------------------------------------------------------
# Reported failure
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "reason",
    [
        "not_mounted",
        "permission_denied",
        "empty_dump",
        "pg_dump_failed",
        "missing_key",
        "ssh_hop_failed",
    ],
)
def test_every_documented_fail_reason_alerts(tmp_path: Path, reason: str) -> None:
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-20260729-030000.dump", age_hours=2)
    status = _write_status(tmp_path, "FAIL", reason, age_hours=1)
    channel = _make_spy_channel()

    assert _run(backup_dir, status, channel) is False
    assert reason in channel.send.call_args[0][1]


def test_prod_down_pg_dump_failed_against_stale_dumps_reports_both(tmp_path: Path) -> None:
    """Current mini reality (issue #4282): prod is gone, dumps are 18 days old.

    Both the stale-dump and the FAIL verdict must appear, in one alert.
    """
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-20260711-092810-preops2978.dump", age_hours=18 * 24)
    status = _write_status(tmp_path, "FAIL", "pg_dump_failed", age_hours=0.5)
    channel = _make_spy_channel()

    assert _run(backup_dir, status, channel) is False

    channel.send.assert_called_once()
    body = channel.send.call_args[0][1]
    assert "prod-20260711-092810-preops2978.dump" in body
    assert "pg_dump_failed" in body


# ---------------------------------------------------------------------------
# Unverifiable is never healthy
# ---------------------------------------------------------------------------
def test_unmounted_backup_volume_alerts_rather_than_passing(tmp_path: Path) -> None:
    """The probe must never report healthy on a signal it could not read."""
    status = _write_status(tmp_path, "OK", "/Volumes/T7/…/prod.dump", age_hours=2)
    channel = _make_spy_channel()

    assert _run(tmp_path / "not-mounted", status, channel) is False
    assert "not mounted" in channel.send.call_args[0][1]


def test_empty_backup_dir_alerts(tmp_path: Path) -> None:
    backup_dir = tmp_path / "prod-db-backups"
    backup_dir.mkdir()
    status = _write_status(tmp_path, "OK", "/Volumes/T7/…/prod.dump", age_hours=2)
    channel = _make_spy_channel()

    assert _run(backup_dir, status, channel) is False
    assert "no prod-*.dump" in channel.send.call_args[0][1]


def test_unparseable_status_line_alerts(tmp_path: Path) -> None:
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-20260729-030000.dump", age_hours=2)
    status = tmp_path / "prod-pgdump.status"
    status.write_text("garbage-not-a-status-line\n")
    channel = _make_spy_channel()

    assert _run(backup_dir, status, channel) is False
    assert "unparseable" in channel.send.call_args[0][1]


# ---------------------------------------------------------------------------
# Transition-based alerting
# ---------------------------------------------------------------------------
def test_sustained_failure_alerts_once_and_recovers(
    tmp_path: Path, isolated_state: Path
) -> None:
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-20260711-092810.dump", age_hours=18 * 24)
    status = _write_status(tmp_path, "FAIL", "pg_dump_failed", age_hours=0.5)
    channel = _make_spy_channel()

    assert _run(backup_dir, status, channel) is False
    assert channel.send.call_count == 1
    assert isolated_state.exists()

    # Three more hourly runs while the failure persists: silent.
    for _ in range(3):
        assert _run(backup_dir, status, channel) is False
    assert channel.send.call_count == 1

    # Backup starts working again: exactly one recovery signal.
    _write_dump(backup_dir, "prod-20260729-030000.dump", age_hours=1)
    good_status = _write_status(tmp_path, "OK", "/Volumes/T7/…/prod.dump", age_hours=1)
    assert _run(backup_dir, good_status, channel) is True
    assert channel.send.call_count == 2
    assert "recovered" in channel.send.call_args[0][0].lower()
    assert not isolated_state.exists()


def test_distinct_failure_after_recovery_realerts(tmp_path: Path) -> None:
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-20260729-030000.dump", age_hours=1)
    good_status = _write_status(
        tmp_path, "OK", "/Volumes/T7/…/prod.dump", age_hours=1, name="good.status"
    )
    channel = _make_spy_channel()

    assert _run(backup_dir, good_status, channel) is True
    assert channel.send.call_count == 0

    bad_status = _write_status(
        tmp_path, "FAIL", "not_mounted", age_hours=0.5, name="bad.status"
    )
    assert _run(backup_dir, bad_status, channel) is False
    assert channel.send.call_count == 1

    assert _run(backup_dir, good_status, channel) is True
    assert channel.send.call_count == 2  # recovery

    later_bad = _write_status(
        tmp_path, "FAIL", "empty_dump", age_hours=0.25, name="later-bad.status"
    )
    assert _run(backup_dir, later_bad, channel) is False
    assert channel.send.call_count == 3  # re-armed


def test_state_is_not_recorded_when_the_push_fails(
    tmp_path: Path, isolated_state: Path
) -> None:
    """A channel outage must not swallow the alert — stay armed, retry next run."""
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-20260711-092810.dump", age_hours=18 * 24)
    status = _write_status(tmp_path, "FAIL", "pg_dump_failed", age_hours=0.5)
    channel = _make_spy_channel()
    channel.send.side_effect = RuntimeError("ntfy unreachable")

    assert _run(backup_dir, status, channel) is False
    assert not isolated_state.exists()

    channel.send.side_effect = None
    assert _run(backup_dir, status, channel) is False
    assert channel.send.call_count == 2
    assert isolated_state.exists()


# ---------------------------------------------------------------------------
# TCC blindness (launchd cannot read the removable volume)
# ---------------------------------------------------------------------------
def test_permission_denied_alerts_and_is_not_reported_as_empty(tmp_path: Path) -> None:
    """Verified on the mini 2026-07-29: launchd can stat /Volumes/T7 but not list it.

    `Path.glob` swallows that PermissionError and yields nothing, which would
    make the watcher alert forever with the wrong reason ("no dumps") instead of
    the actionable one. The direct lister must surface the denial itself.
    """
    backup_dir = tmp_path / "prod-db-backups"
    backup_dir.mkdir()
    _write_dump(backup_dir, "prod-20260729-030000.dump", age_hours=1)
    backup_dir.chmod(0o000)
    try:
        entries, error = prod_backup_probe._list_dumps_direct(backup_dir)
    finally:
        backup_dir.chmod(0o755)

    assert entries is None
    assert "permission denied" in error


def test_blind_watcher_never_reports_healthy(tmp_path: Path) -> None:
    """A listing the probe could not perform is a failure, never a pass."""

    def blind_lister(_: Path) -> tuple[None, str]:
        return None, "permission denied reading /Volumes/T7/prod-db-backups"

    ok, reason = prod_backup_probe.check_dump_freshness(
        tmp_path, 48.0, now=NOW, lister=blind_lister
    )
    assert ok is False
    assert "cannot verify" in reason


@pytest.mark.parametrize(
    ("token", "expected"),
    [("MISSING", "not mounted"), ("DENIED", "permission denied")],
)
def test_ssh_hop_blind_tokens_map_to_distinct_reasons(
    tmp_path: Path, token: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The remote lister's blind states stay distinguishable to the operator."""
    monkeypatch.setattr(prod_backup_probe, "BACKUP_LIST_SSH_KEY", "/dev/null")

    class _Proc:
        returncode = 0
        stdout = f"{token}\n"
        stderr = ""

    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: _Proc()
    )
    entries, error = prod_backup_probe._list_dumps_via_ssh(tmp_path)
    assert entries is None
    assert expected in error


def test_ssh_hop_parses_stat_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prod_backup_probe, "BACKUP_LIST_SSH_KEY", "/dev/null")

    class _Proc:
        returncode = 0
        stdout = (
            f"{NOW - 2 * HOUR:.0f} /Volumes/T7/prod-db-backups/prod-20260729-030000.dump\n"
            f"{NOW - 400 * HOUR:.0f} /Volumes/T7/prod-db-backups/prod-20260711-092810.dump\n"
        )
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Proc())

    ok, reason = prod_backup_probe.check_dump_freshness(
        tmp_path, 48.0, now=NOW, lister=prod_backup_probe._list_dumps_via_ssh
    )
    assert ok is True
    assert "prod-20260729-030000.dump" in reason


def test_missing_hop_key_names_the_setup_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """install.sh wires a key path before the operator has generated the key."""
    monkeypatch.setattr(
        prod_backup_probe, "BACKUP_LIST_SSH_KEY", str(tmp_path / "absent_key")
    )
    entries, error = prod_backup_probe._list_dumps_via_ssh(tmp_path)
    assert entries is None
    assert "one-time watcher key setup" in error


def test_ssh_transport_failure_alerts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prod_backup_probe, "BACKUP_LIST_SSH_KEY", "/dev/null")

    class _Proc:
        returncode = 255
        stdout = ""
        stderr = "Permission denied (publickey)."

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Proc())
    entries, error = prod_backup_probe._list_dumps_via_ssh(tmp_path)
    assert entries is None
    assert "Remote Login disabled" in error


# ---------------------------------------------------------------------------
# Push encoding — the defect that silently swallowed every alert
# ---------------------------------------------------------------------------
def test_alert_subjects_survive_latin1_header_encoding() -> None:
    """HTTP headers are latin-1. An em-dash in the title lost the whole alert.

    Observed live on the mini 2026-07-29 the first time this channel was ever
    exercised: `'latin-1' codec can't encode character '\\u2014'`.
    """
    import prod_probe

    for module in (prod_backup_probe, prod_probe):
        source = (PROBE_MODULE_DIR / f"{module.__name__}.py").read_text()
        for line in source.splitlines():
            if line.strip().startswith("subject = "):
                line.encode("latin-1")  # raises if a non-latin-1 char sneaks back in


@pytest.mark.parametrize("module_name", ["prod_backup_probe", "prod_probe"])
def test_ascii_header_neutralises_non_latin1_titles(module_name: str) -> None:
    import importlib

    module = importlib.import_module(module_name)
    cleaned = module.ascii_header("Prod backup unhealthy — Yggdrasil … ’")
    cleaned.encode("latin-1")
    assert "—" not in cleaned


def test_ntfy_send_does_not_raise_on_unicode(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end guard: a unicode subject must reach the request unbroken."""
    captured: dict[str, object] = {}

    class _Resp:
        status = 200

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    def fake_urlopen(req: object, timeout: int = 10) -> _Resp:
        # Mirrors what httplib does to headers; raises on the original bug.
        for key, value in req.headers.items():  # type: ignore[attr-defined]
            str(value).encode("latin-1")
        captured["ok"] = True
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    prod_backup_probe.NtfyChannel().send("Prod backup unhealthy — Yggdrasil", "body — ok")
    assert captured["ok"] is True


# ---------------------------------------------------------------------------
# Independence from the backup job
# ---------------------------------------------------------------------------
def test_probe_never_invokes_the_backup_job() -> None:
    """The watcher reads signals; it must never run, trigger, or import the job.

    The loopback ssh hop is allowed — it is this watcher's own key and its own
    read-only lister — but nothing that could make a broken backup hide behind
    a broken watcher.
    """
    source = (PROBE_MODULE_DIR / "prod_backup_probe.py").read_text()
    for forbidden in ("prod-pgdump-run.sh", "prod-pgdump.sh", "pg_dump(", "pg_dump "):
        assert forbidden not in source, f"probe must not depend on {forbidden}"


def test_remote_lister_is_read_only() -> None:
    """The forced-command lister must not be able to write or run the backup."""
    raw = (PROBE_MODULE_DIR / "prod_backup_list.sh").read_text()
    # Scan executable lines only; the header comment legitimately explains what
    # the lister deliberately does *not* do.
    code = "\n".join(
        line for line in raw.splitlines() if not line.lstrip().startswith("#")
    )
    for forbidden in ("pg_dump", "prod-pgdump", "rm ", 'echo "$', "mv ", "cp "):
        assert forbidden not in code, f"lister must not contain {forbidden}"


def test_alert_state_file_defaults_outside_the_repo() -> None:
    """launchd runs with cwd=/; a relative state path would be unwritable."""
    assert prod_backup_probe.ALERT_STATE_FILE.is_absolute()


def test_stale_dump_boundary_is_the_configured_budget(tmp_path: Path) -> None:
    backup_dir = tmp_path / "prod-db-backups"
    _write_dump(backup_dir, "prod-recent.dump", age_hours=47)
    ok, reason = prod_backup_probe.check_dump_freshness(backup_dir, 48.0, now=NOW)
    assert ok, reason

    _write_dump(backup_dir, "prod-recent.dump", age_hours=49)
    ok, reason = prod_backup_probe.check_dump_freshness(backup_dir, 48.0, now=NOW)
    assert not ok
    assert "49.0h" in reason
