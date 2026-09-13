"""Tests for the shared host probe notification channel adapters."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.ops.host_secret_bootstrap import materialize_consumer_environment

PROBE_MODULE_DIR = Path(__file__).parents[2] / "ops" / "host-setup" / "mac-mini"
sys.path.insert(0, str(PROBE_MODULE_DIR))

import notification_channels  # noqa: E402


DISCORD_WEBHOOK = "https://discord.com/api/webhooks/123456789/synthetic-token"


def _write_runtime_env(tmp_path: Path, value: str) -> Path:
    path = tmp_path / "runtime-secrets.env"
    path.write_text(f"DISCORD_WEBHOOK={value}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_probes_use_shared_channel_module() -> None:
    prod_source = (PROBE_MODULE_DIR / "prod_probe.py").read_text(encoding="utf-8")
    backup_source = (PROBE_MODULE_DIR / "prod_backup_probe.py").read_text(encoding="utf-8")

    assert "from notification_channels import" in prod_source
    assert "from notification_channels import" in backup_source
    assert "class NtfyChannel" not in prod_source
    assert "class NtfyChannel" not in backup_source
    assert "class NotificationChannel" not in prod_source
    assert "class NotificationChannel" not in backup_source


def test_existing_channel_names_are_compatible() -> None:
    for name in ("ntfy", "telegram", "mail", "none"):
        adapter = notification_channels.build_channel(name)
        assert adapter.__class__.__module__ == "notification_channels"


def test_ntfy_supports_the_backup_probe_legacy_tags() -> None:
    default = notification_channels.build_channel("ntfy")
    backup = notification_channels.build_channel(
        "ntfy", ntfy_tags="floppy_disk,warning"
    )

    response = MagicMock(status=200)
    response.__enter__.return_value = response
    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        default.send("subject", "body")
        backup.send("subject", "body")

    assert urlopen.call_args_list[0].args[0].headers["Tags"] == "warning,robot"
    assert urlopen.call_args_list[1].args[0].headers["Tags"] == "floppy_disk,warning"


def test_discord_posts_redacted_webhook_payload(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    runtime_env = _write_runtime_env(tmp_path, DISCORD_WEBHOOK)
    channel = notification_channels.build_channel("discord", runtime_env_file=runtime_env)
    response = MagicMock(status=204)
    response.__enter__.return_value = response

    with (
        patch("urllib.request.urlopen", return_value=response) as urlopen,
        caplog.at_level(logging.INFO, logger="notification_channels"),
    ):
        channel.send("Prod down - Yggdrasil", "readyz failed")

    request = urlopen.call_args.args[0]
    assert request.full_url == DISCORD_WEBHOOK
    assert json.loads(request.data.decode("utf-8")) == {
        "content": "**Prod down - Yggdrasil**\nreadyz failed"
    }
    assert DISCORD_WEBHOOK not in caplog.text
    assert "synthetic-token" not in caplog.text


def test_discord_reads_declared_bootstrap_binding(tmp_path: Path) -> None:
    def keychain_lookup(service: str, account: str) -> str:
        assert service == "yggdrasil.host-secrets"
        assert account == "test:heimdal-external-alerts:discord.webhook"
        return DISCORD_WEBHOOK

    response = MagicMock(status=204)
    response.__enter__.return_value = response
    with materialize_consumer_environment(
        channel="test",
        consumer="heimdal-external-alerts",
        keychain_lookup=keychain_lookup,
        directory=tmp_path,
    ) as runtime_env:
        channel = notification_channels.build_channel(
            "discord", runtime_env_file=runtime_env
        )
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            channel.send("subject", "body")
        assert urlopen.call_count == 1


def test_discord_missing_or_malformed_secret_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.env"
    with patch("urllib.request.urlopen") as urlopen:
        with pytest.raises(notification_channels.NotificationConfigurationError):
            notification_channels.build_channel("discord", runtime_env_file=missing)
        urlopen.assert_not_called()

    malformed = _write_runtime_env(tmp_path, "not-a-discord-webhook")
    with patch("urllib.request.urlopen") as urlopen:
        with pytest.raises(notification_channels.NotificationConfigurationError):
            notification_channels.build_channel("discord", runtime_env_file=malformed)
        urlopen.assert_not_called()


def test_discord_delivery_error_does_not_disclose_webhook(tmp_path: Path) -> None:
    runtime_env = _write_runtime_env(tmp_path, DISCORD_WEBHOOK)
    channel = notification_channels.build_channel("discord", runtime_env_file=runtime_env)

    with patch(
        "urllib.request.urlopen",
        side_effect=OSError(f"failed for {DISCORD_WEBHOOK}"),
    ):
        with pytest.raises(notification_channels.NotificationDeliveryError) as error:
            channel.send("subject", "body")

    assert str(error.value) == "discord webhook delivery failed"
    assert DISCORD_WEBHOOK not in str(error.value)
