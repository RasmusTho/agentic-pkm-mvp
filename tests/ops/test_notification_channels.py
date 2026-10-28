"""Tests for the shared host probe notification channel adapters."""

from __future__ import annotations

import json
import io
import logging
from email.message import Message
from pathlib import Path
import ssl
import sys
import urllib.request
import urllib.response
from unittest.mock import MagicMock, patch

import pytest

from app.ops.host_secret_bootstrap import materialize_consumer_environment

PROBE_MODULE_DIR = Path(__file__).parents[2] / "ops" / "host-setup" / "mac-mini"
sys.path.insert(0, str(PROBE_MODULE_DIR))

import notification_channels  # noqa: E402


DISCORD_WEBHOOK = "https://discord.com/api/webhooks/123456789/synthetic-token"


def _confirmation_bytes(**overrides: object) -> bytes:
    message: dict[str, object] = {
        "id": "123456790",
        "channel_id": "123456791",
        "webhook_id": "123456789",
    }
    message.update(overrides)
    return json.dumps(message).encode()


def _direct_https_transport(monkeypatch, responses):
    """Keep the real opener policy; replace only its final socket effect."""
    requests = []
    contexts = []
    replies = iter(responses)

    def https_open(handler, request):
        requests.append(request)
        contexts.append(handler._context)
        status, body = next(replies)
        headers = Message()
        headers["Location"] = "https://unapproved.invalid/redirected"
        response = urllib.response.addinfourl(
            io.BytesIO(body), headers, request.full_url, status
        )
        response.msg = "synthetic response"
        return response

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", https_open)
    monkeypatch.setattr(urllib.request, "_opener", None)
    return requests, contexts


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


def test_backup_install_copies_shared_channel_module() -> None:
    install_source = (PROBE_MODULE_DIR / "install.sh").read_text(encoding="utf-8")

    assert (
        'install -m 0644 "$HERE/notification_channels.py" '
        '"$HOME/bin/notification_channels.py"'
    ) in install_source


def test_operator_channel_comments_include_discord() -> None:
    for plist_name in (
        "com.yggdrasil.prod-probe.plist",
        "com.yggdrasil.prod-backup-probe.plist",
    ):
        plist_source = (PROBE_MODULE_DIR / plist_name).read_text(encoding="utf-8")
        assert "ntfy | telegram | mail | none | discord" in plist_source


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
    response = MagicMock(status=200)
    response.__enter__.return_value = response
    response.read.return_value = _confirmation_bytes()

    with (
        patch("urllib.request.OpenerDirector.open", return_value=response) as opener_open,
        caplog.at_level(logging.INFO, logger="notification_channels"),
    ):
        channel.send("Prod down - Yggdrasil", "readyz failed")

    request = opener_open.call_args.args[0]
    assert request.full_url == DISCORD_WEBHOOK + "?wait=true"
    assert request.get_header("User-agent") == (
        "DiscordBot (https://github.com/RasmusTho/agentic-pkm-mvp, 1.0)"
    )
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

    response = MagicMock(status=200)
    response.__enter__.return_value = response
    response.read.return_value = _confirmation_bytes()
    with materialize_consumer_environment(
        channel="test",
        consumer="heimdal-external-alerts",
        keychain_lookup=keychain_lookup,
        directory=tmp_path,
    ) as runtime_env:
        channel = notification_channels.build_channel(
            "discord", runtime_env_file=runtime_env
        )
        with patch("urllib.request.OpenerDirector.open", return_value=response) as opener_open:
            channel.send("subject", "body")
        assert opener_open.call_count == 1


def test_discord_missing_or_malformed_secret_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.env"
    with patch("urllib.request.OpenerDirector.open") as opener_open:
        with pytest.raises(notification_channels.NotificationConfigurationError):
            notification_channels.build_channel("discord", runtime_env_file=missing)
        opener_open.assert_not_called()

    malformed = _write_runtime_env(tmp_path, "not-a-discord-webhook")
    with patch("urllib.request.OpenerDirector.open") as opener_open:
        with pytest.raises(notification_channels.NotificationConfigurationError):
            notification_channels.build_channel("discord", runtime_env_file=malformed)
        opener_open.assert_not_called()


def test_discord_delivery_error_does_not_disclose_webhook(tmp_path: Path) -> None:
    runtime_env = _write_runtime_env(tmp_path, DISCORD_WEBHOOK)
    channel = notification_channels.build_channel("discord", runtime_env_file=runtime_env)

    with patch(
        "urllib.request.OpenerDirector.open",
        side_effect=OSError(f"failed for {DISCORD_WEBHOOK}"),
    ):
        with pytest.raises(notification_channels.NotificationDeliveryError) as error:
            channel.send("subject", "body")

    assert str(error.value) == "discord webhook delivery failed"
    assert DISCORD_WEBHOOK not in str(error.value)


def test_discord_requires_confirmed_direct_delivery(tmp_path, monkeypatch, caplog):
    requests, contexts = _direct_https_transport(
        monkeypatch, [(200, _confirmation_bytes())]
    )
    monkeypatch.setenv("HTTPS_PROXY", "http://unapproved.invalid:1234")
    monkeypatch.setenv("HTTP_PROXY", "http://unapproved.invalid:1234")
    monkeypatch.setenv("ALL_PROXY", "http://unapproved.invalid:1234")

    def refuse_proxy_discovery():
        pytest.fail("Discord transport consulted ambient proxy configuration")

    monkeypatch.setattr(urllib.request, "getproxies", refuse_proxy_discovery)
    channel = notification_channels.DiscordChannel(
        _write_runtime_env(tmp_path, DISCORD_WEBHOOK)
    )
    with caplog.at_level(logging.INFO, logger="notification_channels"):
        channel.send("TEST down", "synthetic failure")

    assert len(requests) == 1
    assert requests[0].full_url == DISCORD_WEBHOOK + "?wait=true"
    assert requests[0].get_method() == "POST"
    assert requests[0].timeout == 10
    assert contexts[0].check_hostname is True
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert DISCORD_WEBHOOK not in caplog.text
    assert "synthetic-token" not in caplog.text


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_discord_refuses_redirect_through_actual_opener(tmp_path, monkeypatch, status):
    requests, _ = _direct_https_transport(
        monkeypatch, [(status, b""), (200, _confirmation_bytes())]
    )
    channel = notification_channels.DiscordChannel(
        _write_runtime_env(tmp_path, DISCORD_WEBHOOK)
    )

    with pytest.raises(notification_channels.NotificationDeliveryError) as error:
        channel.send("TEST down", "synthetic failure")

    assert len(requests) == 1
    assert str(error.value) == "discord webhook delivery failed"
    assert DISCORD_WEBHOOK not in str(error.value)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (204, b""),
        (200, b""),
        (200, b"not-json"),
        (200, b"[]"),
        (200, b"{}"),
        (200, _confirmation_bytes(webhook_id="987654321")),
        (200, _confirmation_bytes(id="")),
        (200, _confirmation_bytes(channel_id="not-a-channel")),
        (200, b"x" * (64 * 1024 + 1)),
    ],
    ids=["unconfirmed204", "empty", "malformed", "array", "missing-fields", "wrong-webhook", "invalid-message", "invalid-channel", "oversized"],
)
def test_discord_rejects_unconfirmed_response_without_secret_disclosure(
    tmp_path, monkeypatch, status, body
):
    requests, _ = _direct_https_transport(monkeypatch, [(status, body)])
    channel = notification_channels.DiscordChannel(
        _write_runtime_env(tmp_path, DISCORD_WEBHOOK)
    )

    with pytest.raises(notification_channels.NotificationDeliveryError) as error:
        channel.send("TEST down", "synthetic failure")

    assert len(requests) == 1
    assert str(error.value) == "discord webhook delivery failed"
    assert DISCORD_WEBHOOK not in str(error.value)
    assert "not-json" not in str(error.value)


def test_discord_tls_failure_is_redacted(tmp_path, monkeypatch, caplog):
    def refuse_tls(_handler, _request):
        raise ssl.SSLCertVerificationError(f"untrusted peer for {DISCORD_WEBHOOK}")

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", refuse_tls)
    channel = notification_channels.DiscordChannel(
        _write_runtime_env(tmp_path, DISCORD_WEBHOOK)
    )
    with pytest.raises(notification_channels.NotificationDeliveryError) as error:
        channel.send("TEST down", "synthetic failure")
    assert str(error.value) == "discord webhook delivery failed"
    assert DISCORD_WEBHOOK not in str(error.value)
    assert DISCORD_WEBHOOK not in caplog.text
