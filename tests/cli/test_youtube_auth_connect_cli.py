"""Non-production YouTube connect uses the existing binder and host boundary."""

from __future__ import annotations

from contextlib import contextmanager
import importlib
from pathlib import Path
from typing import Any, Iterator

from click.testing import CliRunner

from app.cli import cli

auth_cli = importlib.import_module("app.cli.youtube_auth")


class _Connection:
    interval = 1

    def __init__(self) -> None:
        self.cancelled = False

    def public_view(self) -> dict[str, Any]:
        return {
            "user_code": "SAFE-CODE",
            "verification_url": "https://www.google.com/device",
            "interval": 1,
            "expires_in": 30,
        }

    def cancel(self) -> None:
        self.cancelled = True


class _Binder:
    def __init__(self) -> None:
        self.connection: _Connection | None = None

    def start_device_connection(self) -> _Connection:
        self.connection = _Connection()
        return self.connection

    def finish_device_connection(self, connection: _Connection) -> dict[str, Any]:
        del connection
        return {
            "status": "connected",
            "account": {"binding_id": "binding-test", "channel_title": "Synthetic"},
        }

    def cancel_device_connection(self, connection: _Connection) -> None:
        connection.cancel()


def test_nonprod_connect_uses_existing_binder_and_refuses_prod(monkeypatch, tmp_path: Path) -> None:
    contexts: list[tuple[str, str]] = []
    environments: list[dict[str, str]] = []
    monkeypatch.setattr(auth_cli.sys, "platform", "darwin")

    @contextmanager
    def fake_materialize(*, channel: str, consumer: str, provider: str) -> Iterator[Path]:
        contexts.append((channel, consumer))
        assert provider == "keychain"
        path = tmp_path / "youtube-runtime.env"
        path.write_text(
            "YOUTUBE_OAUTH_CLIENT_ID=client\n"
            "YOUTUBE_OAUTH_CLIENT_SECRET=secret\n"
            "YOUTUBE_TOKEN_STORE_KEY=" + "00" * 32 + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        yield path

    calls: list[str] = []

    class _Services:
        binder = _Binder()

    services = _Services()

    monkeypatch.setattr(auth_cli, "materialize_consumer_environment", fake_materialize)
    monkeypatch.setattr(
        auth_cli,
        "build_youtube_inbox_dev_services",
        lambda **kwargs: environments.append(dict(kwargs["environment"]))
        or calls.append("existing-binder-composition")
        or services,
    )
    monkeypatch.setattr(auth_cli.time, "sleep", lambda _seconds: None)
    runner = CliRunner()

    connected = runner.invoke(
        cli,
        ["youtube-auth", "connect", "--environment", "dev"],
        env={"PKM_ENVIRONMENT": "dev"},
    )
    assert connected.exit_code == 0, connected.output
    assert "authorization_required" in connected.output
    assert "binding-test" in connected.output
    assert contexts == [("dev", "youtube-auth-cli")]
    assert calls == ["existing-binder-composition"]
    assert "YOUTUBE_OAUTH_CLIENT_ID" not in environments[0]
    assert "YOUTUBE_OAUTH_CLIENT_SECRET" not in environments[0]
    assert "YOUTUBE_TOKEN_STORE_KEY" not in environments[0]
    assert environments[0]["HOST_SECRET_RUNTIME_ENV_FILE"].endswith("youtube-runtime.env")
    assert services.binder.connection is not None and services.binder.connection.cancelled

    refused = runner.invoke(
        cli,
        ["youtube-auth", "connect", "--environment", "dev"],
        env={"PKM_ENVIRONMENT": "prod"},
    )
    assert refused.exit_code != 0
    assert "target dev" in refused.output
    assert len(contexts) == 1
    assert calls == ["existing-binder-composition"]


def test_nonprod_connect_reuses_declared_runtime_handoff(monkeypatch) -> None:
    environments: list[dict[str, str]] = []

    def materialize_unexpected(**_kwargs):
        raise AssertionError("TEST runtime must reuse its delivered handoff")

    class _Services:
        binder = _Binder()

    monkeypatch.setattr(auth_cli, "materialize_consumer_environment", materialize_unexpected)
    monkeypatch.setattr(
        auth_cli,
        "build_youtube_inbox_dev_services",
        lambda **kwargs: environments.append(dict(kwargs["environment"])) or _Services(),
    )
    monkeypatch.setattr(auth_cli.time, "sleep", lambda _seconds: None)

    result = CliRunner().invoke(
        cli,
        ["youtube-auth", "connect", "--environment", "test"],
        env={
            "PKM_ENVIRONMENT": "test",
            "HOST_SECRET_PROVIDER": "bws",
            "YOUTUBE_OAUTH_CLIENT_ID": "delivered-client",
            "YOUTUBE_OAUTH_CLIENT_SECRET": "delivered-secret",
            "YOUTUBE_TOKEN_STORE_KEY": "00" * 32,
        },
    )

    assert result.exit_code == 0, result.output
    assert environments[0]["YOUTUBE_OAUTH_CLIENT_ID"] == "delivered-client"
    assert environments[0]["YOUTUBE_OAUTH_CLIENT_SECRET"] == "delivered-secret"
    assert environments[0]["YOUTUBE_TOKEN_STORE_KEY"] == "00" * 32


def test_nonprod_connect_validates_token_store_key_before_device_flow(monkeypatch) -> None:
    started = False

    class _Services:
        class binder:
            @staticmethod
            def start_device_connection():
                nonlocal started
                started = True
                raise AssertionError("device flow must not start")

    monkeypatch.setattr(
        auth_cli,
        "build_youtube_inbox_dev_services",
        lambda **_kwargs: _Services(),
    )
    result = CliRunner().invoke(
        cli,
        ["youtube-auth", "connect", "--environment", "test"],
        env={
            "PKM_ENVIRONMENT": "test",
            "HOST_SECRET_PROVIDER": "bws",
            "YOUTUBE_OAUTH_CLIENT_ID": "delivered-client",
            "YOUTUBE_OAUTH_CLIENT_SECRET": "delivered-secret",
            "YOUTUBE_TOKEN_STORE_KEY": "not-a-key",
        },
    )

    assert result.exit_code != 0
    assert "YouTube Inbox operation failed" in result.output
    assert not started


def test_nonprod_connect_rejects_partial_runtime_handoff(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_cli,
        "materialize_consumer_environment",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("partial handoff must not fall back to Keychain")
        ),
    )

    result = CliRunner().invoke(
        cli,
        ["youtube-auth", "connect", "--environment", "test"],
        env={
            "PKM_ENVIRONMENT": "test",
            "HOST_SECRET_PROVIDER": "bws",
            "YOUTUBE_OAUTH_CLIENT_ID": "delivered-client",
        },
    )

    assert result.exit_code != 0
    assert "handoff is incomplete" in result.output


def test_nonprod_connect_does_not_select_keychain_on_linux(monkeypatch) -> None:
    monkeypatch.setattr(auth_cli.sys, "platform", "linux")
    monkeypatch.setattr(
        auth_cli,
        "materialize_consumer_environment",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Linux runtime must not select Keychain")
        ),
    )

    result = CliRunner().invoke(
        cli,
        ["youtube-auth", "connect", "--environment", "test"],
        env={"PKM_ENVIRONMENT": "test"},
    )

    assert result.exit_code != 0
    assert "runtime handoff is missing" in result.output
