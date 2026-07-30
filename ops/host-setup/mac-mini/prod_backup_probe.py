#!/usr/bin/env python3
"""Scheduled prod-backup watcher — transition-based stale/failed-backup alert.

The nightly prod dump job (`local.prod-pgdump`) writes a human log and a
machine-readable status line, but nothing reads either one. Between 2026-07-06
and 2026-07-29 every run failed and the gap went unseen for three weeks. This
probe closes that detection gap.

Independence
------------
This probe never invokes the backup job and never trusts it to report its own
failure. The load-bearing signal is the *dump directory itself*: if the newest
`prod-*.dump` is older than the freshness budget, the operator is alerted even
when the backup job stopped firing entirely and therefore wrote no FAIL line.
The status file is a secondary signal that adds a reason, not a precondition.

Checks (all three run; every failure is reported):
  1. Dump freshness — newest `prod-*.dump` in BACKUP_DIR younger than
     BACKUP_MAX_AGE_HOURS. A missing or unmounted backup volume is a failure,
     never a pass: an unverifiable backup is treated as a broken backup.
  2. Status verdict — the status file's last line reports OK, not FAIL.
  3. Status freshness — the status file's own timestamp is younger than
     BACKUP_STATUS_MAX_AGE_HOURS. A job that silently stops firing leaves a
     stale-but-OK status line; this is what catches it.

Alerting is transition-based, mirroring `prod_probe.py`: one alert on entering
a bad state, suppressed while it persists, one recovery signal on the first
healthy run, then re-armed for a later distinct failure.

Channel selection
-----------------
Set PROD_BACKUP_PROBE_CHANNEL to one of:
  - "ntfy"      (default) — posts to ntfy.sh topic $NTFY_TOPIC
  - "telegram"  — sends via Telegram Bot $TELEGRAM_BOT_TOKEN / $TELEGRAM_CHAT_ID
  - "mail"      — sends via Python's smtplib (requires SMTP_* env vars)
  - "none"      — dry-run; logs but does not push

The channel is swappable without changing the launchd job.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [prod-backup-probe] %(levelname)s %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("prod_backup_probe")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Ground truth: the dumps themselves, on the external SSD the backup job
# refuses to write around.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/Volumes/T7/prod-db-backups"))
BACKUP_GLOB = os.environ.get("BACKUP_GLOB", "prod-*.dump")

# launchd has no TCC grant for the removable volume holding the dumps, so a
# direct read returns EPERM. When this key is configured the probe re-reads the
# directory through a loopback ssh hop, which does hold that access. Its own
# key, its own read-only lister — nothing shared with the backup job.
BACKUP_LIST_SSH_KEY = os.environ.get("BACKUP_LIST_SSH_KEY", "")
BACKUP_LIST_REMOTE_CMD = os.environ.get(
    "BACKUP_LIST_REMOTE_CMD", str(Path.home() / "bin" / "prod-backup-list.sh")
)

# The machine-readable single-line status the backup job writes (added
# 2026-07-29): "<iso-ts> OK <path>" or "<iso-ts> FAIL <reason>".
BACKUP_STATUS_FILE = Path(
    os.environ.get(
        "BACKUP_STATUS_FILE",
        str(Path.home() / "Library" / "Logs" / "prod-pgdump.status"),
    )
)

# The job runs nightly. 48h tolerates one missed night without paging; 2 missed
# nights is a real signal.
BACKUP_MAX_AGE_HOURS = float(os.environ.get("BACKUP_MAX_AGE_HOURS", "48"))
# A status file older than ~1.25 nightly cycles means the job did not fire.
BACKUP_STATUS_MAX_AGE_HOURS = float(os.environ.get("BACKUP_STATUS_MAX_AGE_HOURS", "30"))

ALERT_STATE_FILE = Path(
    os.environ.get(
        "PROD_BACKUP_PROBE_STATE_FILE", "/tmp/yggdrasil-prod-backup-probe.state"
    )
)

PROD_BACKUP_PROBE_CHANNEL = os.environ.get("PROD_BACKUP_PROBE_CHANNEL", "ntfy")

_HOUR = 3600.0


# ---------------------------------------------------------------------------
# Notification channel protocol + adapters
# ---------------------------------------------------------------------------
class NotificationChannel(Protocol):
    def send(self, subject: str, body: str) -> None:
        ...


def ascii_header(value: str) -> str:
    """Make a string safe for an HTTP header.

    httplib encodes headers as latin-1, so a single em-dash in the title raises
    UnicodeEncodeError and the alert is lost — the exact failure that kept this
    channel from ever delivering. The body is a UTF-8 payload and is unaffected.
    """
    replacements = {"—": "-", "–": "-", "‘": "'", "’": "'", "…": "..."}
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    return value.encode("latin-1", "replace").decode("latin-1")


class NtfyChannel:
    """ntfy.sh push via HTTP POST."""

    def __init__(self) -> None:
        self.topic = os.environ.get("NTFY_TOPIC", "yggdrasil-prod-alerts")
        self.server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

    def send(self, subject: str, body: str) -> None:
        import urllib.request

        url = f"{self.server}/{self.topic}"
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            headers={
                "Title": ascii_header(subject),
                "Priority": "high",
                "Tags": "floppy_disk,warning",
                "Content-Type": "text/plain; charset=utf-8",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.info("ntfy push sent: %s %s", resp.status, url)


class TelegramChannel:
    """Telegram Bot API push."""

    def __init__(self) -> None:
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    def send(self, subject: str, body: str) -> None:
        import urllib.parse
        import urllib.request

        text = f"*{subject}*\n{body}"
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = urllib.parse.urlencode(
            {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        ).encode()
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.info("telegram push sent: %s", resp.status)


class MailChannel:
    """SMTP mail push."""

    def send(self, subject: str, body: str) -> None:
        import smtplib
        from email.mime.text import MIMEText

        smtp_host = os.environ.get("SMTP_HOST", "localhost")
        smtp_port = int(os.environ.get("SMTP_PORT", "25"))
        from_addr = os.environ.get("SMTP_FROM", "probe@yggdrasil.local")
        to_addr = os.environ.get("SMTP_TO", "operator@yggdrasil.local")
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.sendmail(from_addr, [to_addr], msg.as_string())
        log.info("mail push sent to %s", to_addr)


class NullChannel:
    """Dry-run: log only."""

    def send(self, subject: str, body: str) -> None:
        log.info("[dry-run] would push: %s — %s", subject, body)


def build_channel(name: str) -> NotificationChannel:
    """Return the appropriate channel adapter by name (env-selected)."""
    mapping: dict[str, type] = {
        "ntfy": NtfyChannel,
        "telegram": TelegramChannel,
        "mail": MailChannel,
        "none": NullChannel,
    }
    cls = mapping.get(name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown PROD_BACKUP_PROBE_CHANNEL={name!r}. Choose one of: {list(mapping)}"
        )
    return cls()


# ---------------------------------------------------------------------------
# Alert state (transition-based; mirrors prod_probe.py)
# ---------------------------------------------------------------------------
def _load_alert_state() -> dict[str, Any] | None:
    """Return the persisted alert state, or None if absent/invalid."""
    if not ALERT_STATE_FILE.exists():
        return None
    try:
        payload = json.loads(ALERT_STATE_FILE.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _alert_state_is_active(state: dict[str, Any] | None) -> bool:
    return bool(state and state.get("status") == "down")


def _record_alert_state(failures: list[str]) -> None:
    """Persist the current bad state after a successful alert."""
    ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERT_STATE_FILE.write_text(
        json.dumps(
            {"status": "down", "ts": int(time.time()), "failures": failures},
            sort_keys=True,
        )
    )


def _clear_alert_state() -> None:
    try:
        ALERT_STATE_FILE.unlink()
    except FileNotFoundError:
        pass


def _send_down_alert(channel: NotificationChannel, failures: list[str]) -> bool:
    subject = "Prod backup unhealthy - Yggdrasil"
    body = (
        "The nightly prod DB dump is failing or stale:\n"
        + "\n".join(f"  - {f}" for f in failures)
        + f"\n\nLog: {BACKUP_STATUS_FILE.parent / 'prod-pgdump.log'}"
        + f"\nDumps: {BACKUP_DIR}"
    )
    try:
        channel.send(subject, body)
    except Exception as exc:
        log.error("failed to send prod-backup alert: %s", exc)
        return False
    _record_alert_state(failures)
    log.warning("prod-backup alert sent and state recorded. failures=%s", failures)
    return True


def _send_recovery_alert(channel: NotificationChannel) -> bool:
    subject = "Prod backup recovered - Yggdrasil"
    body = "A fresh prod dump landed and the status file reports OK."
    try:
        channel.send(subject, body)
    except Exception as exc:
        log.error("failed to send prod-backup recovery alert: %s", exc)
        return False
    _clear_alert_state()
    log.info("prod-backup recovery alert sent; state cleared")
    return True


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def _parse_iso_utc(token: str) -> float | None:
    """Parse an ISO-8601 UTC timestamp into an epoch float, or None."""
    text = token.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _format_age(seconds: float) -> str:
    return f"{seconds / _HOUR:.1f}h"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def _list_dumps_direct(backup_dir: Path) -> tuple[list[tuple[float, str]] | None, str]:
    """List dumps by reading the filesystem. Returns (entries, error).

    `entries is None` means the listing could not be performed at all; the
    error string says why. Note that under macOS TCC a removable volume can be
    `stat`-able while `listdir` raises PermissionError, so the two conditions
    are separated deliberately — `Path.glob` silently swallows that
    PermissionError and would otherwise report a readable-but-empty directory.
    """
    if not backup_dir.is_dir():
        return None, f"backup directory {backup_dir} is missing or not mounted"
    try:
        with os.scandir(backup_dir) as it:
            entries = [
                (entry.stat().st_mtime, entry.name)
                for entry in it
                if entry.is_file() and fnmatch(entry.name, BACKUP_GLOB)
            ]
    except PermissionError:
        return None, f"permission denied reading {backup_dir}"
    except OSError as exc:
        return None, f"backup directory {backup_dir} unreadable: {exc}"
    return entries, ""


def _list_dumps_via_ssh(backup_dir: Path) -> tuple[list[tuple[float, str]] | None, str]:
    """List dumps through a loopback ssh hop. Returns (entries, error).

    launchd starts unattributed processes with no TCC grants, so macOS refuses
    them access to the removable volume holding the dumps (verified on this
    host 2026-07-29: `stat` succeeds, `listdir` returns EPERM). An sshd session
    does hold that access. This mirrors the mechanism the backup job itself
    uses, but through this watcher's own key and its own read-only lister — it
    shares no credential or code path with the backup job.

    Configure with BACKUP_LIST_SSH_KEY; the remote lister emits `<mtime> <name>`
    lines, or a bare MISSING / DENIED / EMPTY token.
    """
    import subprocess

    if not BACKUP_LIST_SSH_KEY:
        return None, "no BACKUP_LIST_SSH_KEY configured for the loopback hop"
    if not os.access(BACKUP_LIST_SSH_KEY, os.R_OK):
        return None, (
            f"loopback hop key {BACKUP_LIST_SSH_KEY} is missing or unreadable — "
            "run the one-time watcher key setup"
        )

    argv = [
        "/usr/bin/ssh",
        "-F",
        "/dev/null",
        "-i",
        BACKUP_LIST_SSH_KEY,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={Path.home() / '.ssh' / 'known_hosts'}",
        "-l",
        os.environ.get("USER") or Path.home().name,
        "localhost",
        BACKUP_LIST_REMOTE_CMD,
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return None, f"loopback ssh hop failed: {type(exc).__name__}: {exc}"

    if proc.returncode == 255:
        return None, (
            "loopback ssh to localhost failed (Remote Login disabled, key "
            "rejected, or host key changed)"
        )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        return None, f"remote dump lister failed: {detail[-1] if detail else 'no output'}"

    entries: list[tuple[float, str]] = []
    for line in proc.stdout.splitlines():
        token = line.strip()
        if not token:
            continue
        if token == "MISSING":
            return None, f"backup directory {backup_dir} is missing or not mounted"
        if token == "DENIED":
            return None, f"permission denied reading {backup_dir} even over the ssh hop"
        if token == "EMPTY":
            return [], ""
        mtime, _, name = token.partition(" ")
        try:
            entries.append((float(mtime), Path(name).name))
        except ValueError:
            return None, f"remote dump lister emitted an unparseable line: {token!r}"
    return entries, ""


def check_dump_freshness(
    backup_dir: Path = BACKUP_DIR,
    max_age_hours: float = BACKUP_MAX_AGE_HOURS,
    now: float | None = None,
    lister: Any = None,
) -> tuple[bool, str]:
    """Ground truth: is there a recent dump on disk? Returns (ok, reason).

    An absent or unreadable backup directory is a failure, not a pass — the
    probe never reports healthy on a signal it could not read.
    """
    now = time.time() if now is None else now

    if lister is not None:
        entries, error = lister(backup_dir)
    else:
        entries, error = _list_dumps_direct(backup_dir)
        # Under launchd the direct read is TCC-denied; retry through the hop
        # when one is configured, so the watcher is not permanently blind.
        if entries is None and "permission denied" in error and BACKUP_LIST_SSH_KEY:
            entries, error = _list_dumps_via_ssh(backup_dir)

    if entries is None:
        reason = f"cannot verify any prod dump exists: {error}"
        if "permission denied" in error and not BACKUP_LIST_SSH_KEY:
            # launchd has no TCC grant for the removable volume. This fires
            # exactly once (transition-based) and tells the operator how to
            # finish installing the watcher.
            reason += (
                "; launchd cannot read the dump volume — set BACKUP_LIST_SSH_KEY "
                "to enable the loopback hop (see docs/OPERATIONS.md :: Prod backup watcher)"
            )
        return False, reason

    if not entries:
        return False, f"no {BACKUP_GLOB} files in {backup_dir}"

    newest_mtime, newest_name = max(entries)
    age = now - newest_mtime
    if age > max_age_hours * _HOUR:
        return False, (
            f"newest dump {newest_name} is {_format_age(age)} old "
            f"(budget {max_age_hours:.0f}h)"
        )
    return True, f"newest dump {newest_name} is {_format_age(age)} old"


def check_status_file(
    status_file: Path = BACKUP_STATUS_FILE,
    max_age_hours: float = BACKUP_STATUS_MAX_AGE_HOURS,
    now: float | None = None,
) -> list[str]:
    """Read the machine-readable status line. Returns a list of failure reasons.

    Two distinct failure modes are separated deliberately:
      - the job ran and reported FAIL (a verdict), and
      - the job did not run at all (a stale or missing status file).
    The second is the one that went unnoticed for three weeks.
    """
    now = time.time() if now is None else now
    failures: list[str] = []

    if not status_file.exists():
        return [f"status file {status_file} missing — backup job may never have run"]

    try:
        raw = status_file.read_text().strip()
    except OSError as exc:
        return [f"status file {status_file} unreadable: {exc}"]

    if not raw:
        return [f"status file {status_file} is empty"]

    # Tolerate a multi-line file: the last non-empty line is the current verdict.
    line = [ln for ln in raw.splitlines() if ln.strip()][-1].strip()
    parts = line.split(None, 2)
    ts_token = parts[0] if parts else ""
    verdict = parts[1].upper() if len(parts) > 1 else ""
    detail = parts[2] if len(parts) > 2 else ""

    ts = _parse_iso_utc(ts_token)
    if ts is None:
        failures.append(f"status file timestamp unparseable: {line!r}")
        # Fall back to mtime so a garbled line still yields a staleness verdict.
        ts = status_file.stat().st_mtime

    age = now - ts
    if age > max_age_hours * _HOUR:
        failures.append(
            f"status file is {_format_age(age)} old (budget {max_age_hours:.0f}h) — "
            "the nightly job did not fire"
        )

    if verdict == "FAIL":
        failures.append(f"last backup run reported FAIL: {detail or 'no reason given'}")
    elif verdict != "OK":
        failures.append(f"status file verdict unrecognised: {line!r}")

    return failures


# ---------------------------------------------------------------------------
# Core probe logic
# ---------------------------------------------------------------------------
def run_probe(
    backup_dir: Path = BACKUP_DIR,
    status_file: Path = BACKUP_STATUS_FILE,
    max_age_hours: float = BACKUP_MAX_AGE_HOURS,
    status_max_age_hours: float = BACKUP_STATUS_MAX_AGE_HOURS,
    channel: NotificationChannel | None = None,
    now: float | None = None,
) -> bool:
    """Run the full backup probe. Return True if the backup is healthy.

    This function is the unit-testable boundary: tests call it directly with a
    temp backup dir, a temp status file, and an injected channel.
    """
    if channel is None:
        channel = build_channel(PROD_BACKUP_PROBE_CHANNEL)

    failures: list[str] = []

    ok_dump, reason_dump = check_dump_freshness(backup_dir, max_age_hours, now=now)
    if not ok_dump:
        failures.append(reason_dump)

    failures.extend(check_status_file(status_file, status_max_age_hours, now=now))

    if not failures:
        log.info("backup probe ok: %s", reason_dump)
        state = _load_alert_state()
        if _alert_state_is_active(state):
            _send_recovery_alert(channel)
        elif state is not None:
            _clear_alert_state()
        return True

    state = _load_alert_state()
    if _alert_state_is_active(state):
        log.info(
            "backup unhealthy but alert already recorded; suppressing duplicate. failures=%s",
            failures,
        )
        return False

    _send_down_alert(channel, failures)
    return False


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    healthy = run_probe()
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
