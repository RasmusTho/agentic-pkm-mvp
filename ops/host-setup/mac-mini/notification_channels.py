#!/usr/bin/env python3
"""Shared notification transports for the host-side Yggdrasil probes.

The probes are separate one-shot entrypoints, but their delivery capability is
one replaceable boundary.  Discord is deliberately downstream-only: its
webhook is supplied through the host-secret bootstrap runtime file and is
never accepted from ordinary probe configuration or ambient environment.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import stat
from typing import Protocol
from urllib.parse import urlsplit


log = logging.getLogger("notification_channels")

HOST_SECRET_RUNTIME_ENV_FILE = "HOST_SECRET_RUNTIME_ENV_FILE"
DISCORD_WEBHOOK_BINDING = "DISCORD_WEBHOOK"
_DISCORD_WEBHOOK_SECRET = "discord.webhook"
_DISCORD_HOSTS = frozenset({"discord.com", "discordapp.com"})
_DISCORD_WEBHOOK_PATH = re.compile(r"^/api/webhooks/[0-9]+/[A-Za-z0-9._-]+$")


class NotificationConfigurationError(RuntimeError):
    """Raised when a configured notification transport is not usable."""


class NotificationDeliveryError(RuntimeError):
    """Raised without provider details when delivery fails."""


class NotificationChannel(Protocol):
    def send(self, subject: str, body: str) -> None:
        ...


def ascii_header(value: str) -> str:
    """Make a string safe for an HTTP header."""
    replacements = {"—": "-", "–": "-", "‘": "'", "’": "'", "…": "..."}
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    return value.encode("latin-1", "replace").decode("latin-1")


def _runtime_secret_file_from_environment() -> Path | None:
    raw_path = os.environ.get(HOST_SECRET_RUNTIME_ENV_FILE, "").strip()
    return Path(raw_path) if raw_path else None


def _read_runtime_secret_binding(path: Path | None, binding: str) -> str:
    """Read one exact binding from a bootstrap-owned 0600 regular file.

    The bootstrap file is a short-lived host-native secret handoff.  This
    reader repeats the descriptor checks at the consumer boundary and rejects
    any extra binding so a file for another consumer cannot be reused.
    """
    if path is None or not path.is_absolute():
        raise NotificationConfigurationError(
            f"{_DISCORD_WEBHOOK_SECRET} host-secret binding is unavailable"
        )

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK

    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise NotificationConfigurationError(
            f"{_DISCORD_WEBHOOK_SECRET} host-secret binding is unavailable"
        ) from None

    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_nlink != 1
        ):
            raise NotificationConfigurationError(
                f"{_DISCORD_WEBHOOK_SECRET} host-secret binding is unavailable"
            )
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 65536):
            total += len(chunk)
            if total > 65536:
                raise NotificationConfigurationError(
                    f"{_DISCORD_WEBHOOK_SECRET} host-secret binding is malformed"
                )
            chunks.append(chunk)
        try:
            content = b"".join(chunks).decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise NotificationConfigurationError(
                f"{_DISCORD_WEBHOOK_SECRET} host-secret binding is malformed"
            ) from None
    finally:
        os.close(descriptor)

    values: dict[str, str] = {}
    for line in content.splitlines():
        name, separator, value = line.partition("=")
        if not separator or name in values:
            raise NotificationConfigurationError(
                f"{_DISCORD_WEBHOOK_SECRET} host-secret binding is malformed"
            )
        values[name] = value
    if set(values) != {binding} or not values[binding]:
        raise NotificationConfigurationError(
            f"{_DISCORD_WEBHOOK_SECRET} host-secret binding is unavailable"
        )
    return values[binding]


def _is_discord_webhook_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in _DISCORD_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.query == ""
        and parsed.fragment == ""
        and _DISCORD_WEBHOOK_PATH.fullmatch(parsed.path) is not None
    )


class NtfyChannel:
    """ntfy.sh push via HTTP POST."""

    def __init__(self, tags: str = "warning,robot") -> None:
        self.topic = os.environ.get("NTFY_TOPIC", "yggdrasil-prod-alerts")
        self.server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        self.tags = tags

    def send(self, subject: str, body: str) -> None:
        import urllib.request

        url = f"{self.server}/{self.topic}"
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            headers={
                "Title": ascii_header(subject),
                "Priority": "high",
                "Tags": self.tags,
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


class DiscordChannel:
    """One-way Discord webhook push using a host-secret runtime binding."""

    def __init__(self, runtime_env_file: Path | None = None) -> None:
        source = runtime_env_file or _runtime_secret_file_from_environment()
        webhook_url = _read_runtime_secret_binding(source, DISCORD_WEBHOOK_BINDING)
        if not _is_discord_webhook_url(webhook_url):
            raise NotificationConfigurationError(
                f"{_DISCORD_WEBHOOK_SECRET} host-secret binding is malformed"
            )
        self._webhook_url = webhook_url

    def send(self, subject: str, body: str) -> None:
        import urllib.request

        payload = json.dumps(
            {"content": f"**{subject}**\n{body}"},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self._webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                log.info("discord webhook push sent: %s", response.status)
        except Exception:
            raise NotificationDeliveryError("discord webhook delivery failed") from None


def build_channel(
    name: str,
    *,
    runtime_env_file: Path | None = None,
    ntfy_tags: str = "warning,robot",
) -> NotificationChannel:
    """Return the shared adapter selected by a probe channel name."""
    mapping: dict[str, type[NotificationChannel]] = {
        "ntfy": NtfyChannel,
        "telegram": TelegramChannel,
        "mail": MailChannel,
        "none": NullChannel,
        "discord": DiscordChannel,
    }
    cls = mapping.get(name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown notification channel={name!r}. Choose one of: {list(mapping)}"
        )
    if cls is DiscordChannel:
        return cls(runtime_env_file=runtime_env_file)
    if cls is NtfyChannel:
        return cls(tags=ntfy_tags)
    return cls()
