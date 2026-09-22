"""Dev-only CLI composition for the pragmatic YouTube Inbox V1 route."""

from __future__ import annotations

import json
import importlib
import secrets
from dataclasses import dataclass
from typing import Any

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.knowledge_acquisition.playlist_discovery import V1InboxConfigurationError
from app.knowledge_acquisition.youtube_account_binding import AccountBindingAdmissionError
from app.knowledge_acquisition.youtube_oauth import (
    DeviceAuthorizationPending,
    OAuthProviderError,
)
from app.knowledge_acquisition.youtube_token_store import OAuthWriterAdmissionError

youtube_cli = importlib.import_module("app.cli.youtube_inbox_dev")

pytestmark = pytest.mark.not_pg


@dataclass(frozen=True)
class _Connection:
    interval: int = 2
    expires_in: int = 30

    def public_view(self) -> dict[str, Any]:
        return {
            "user_code": "TEST-CODE",
            "verification_url": "https://www.google.com/device",
            "verification_url_complete": "https://www.google.com/device?user_code=TEST-CODE",
            "interval": self.interval,
            "expires_in": self.expires_in,
        }


class _Binder:
    def __init__(self, pending_codes: list[str] | None = None) -> None:
        self.started = 0
        self.finished = 0
        self.pending_codes = list(pending_codes or [])

    def start_device_connection(self) -> _Connection:
        self.started += 1
        return _Connection()

    def finish_device_connection(self, connection: _Connection) -> dict[str, Any]:
        del connection
        self.finished += 1
        if self.pending_codes:
            raise DeviceAuthorizationPending(self.pending_codes.pop(0))
        return {
            "status": "connected",
            "account": {"binding_id": "binding-test", "channel_title": "Synthetic channel"},
        }


class _Api:
    def list_my_playlists(self) -> Any:
        return type(
            "PlaylistResult",
            (),
            {
                "items": (
                    type(
                        "Playlist",
                        (),
                        {
                            "playlist_id": "PL_test_owned_inbox",
                            "title": "Synthetic Inbox",
                        },
                    )(),
                )
            },
        )()


class _Sync:
    def __init__(self) -> None:
        self.selected: list[tuple[str, str]] = []
        self.synced = 0

    def select_inbox(self, *, playlist_ref: str, title: str) -> Any:
        self.selected.append((playlist_ref, title))
        return type("Binding", (), {"binding_id": "source-test", "collection_ref": playlist_ref})()

    def sync_now(self) -> dict[str, Any]:
        self.synced += 1
        return {
            "status": "connected",
            "discovered": 1,
            "enqueued": 1,
            "deduped": 0,
            "not_modified": False,
            "reason_code": None,
        }

    def status(self) -> dict[str, Any]:
        return {"status": "connected", "last_success_at": None, "latest_error": None}


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def _dev_env() -> dict[str, str]:
    return {
        "PKM_ENVIRONMENT": "dev",
        "YOUTUBE_OAUTH_CLIENT_ID": "synthetic-client-id",
        "YOUTUBE_OAUTH_CLIENT_SECRET": "synthetic-client-secret",
        "YOUTUBE_TOKEN_STORE_KEY": "11" * 32,
    }


def test_connect_select_and_sync_compose_v1_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binder = _Binder(["authorization_pending", "slow_down"])
    sync = _Sync()
    builds: list[str | None] = []
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(youtube_cli.time, "sleep", fake_sleep)

    def fake_build(account_binding_id: str | None = None) -> youtube_cli.YouTubeInboxDevServices:
        builds.append(account_binding_id)
        return youtube_cli.YouTubeInboxDevServices(
            binder=binder,
            api_client=_Api(),
            sync=sync if account_binding_id is not None else None,
        )

    monkeypatch.setattr(youtube_cli, "build_youtube_inbox_dev_services", fake_build)
    runner = CliRunner()
    env = _dev_env()

    connect = runner.invoke(cli, ["youtube-inbox-dev", "connect"], env=env)
    select = runner.invoke(
        cli,
        [
            "youtube-inbox-dev",
            "select",
            "--account-binding-id",
            "binding-test",
            "--playlist-id",
            "PL_test_owned_inbox",
        ],
        env=env,
    )
    sync_now = runner.invoke(
        cli,
        ["youtube-inbox-dev", "sync", "--account-binding-id", "binding-test"],
        env=env,
    )

    assert connect.exit_code == select.exit_code == sync_now.exit_code == 0
    assert _json_lines(connect.output)[-1]["account"]["binding_id"] == "binding-test"
    assert _json_lines(select.output) == [
        {
            "status": "selected",
            "account_binding_id": "binding-test",
            "playlist_id": "PL_test_owned_inbox",
        }
    ]
    assert _json_lines(sync_now.output)[0]["enqueued"] == 1
    assert builds == [None, "binding-test", "binding-test"]
    assert binder.started == 1
    assert binder.finished == 3
    assert sleeps == [2, 2, 7]
    assert sync.selected == [("PL_test_owned_inbox", "Synthetic Inbox")]
    assert sync.synced == 1


def test_rejects_non_dev_and_redacts_secret_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planted_client_secret = "planted-client-secret-" + secrets.token_hex(8)
    planted_store_key = secrets.token_hex(32)
    build_calls = 0

    def forbidden_build(account_binding_id: str | None = None) -> Any:
        del account_binding_id
        nonlocal build_calls
        build_calls += 1
        raise AssertionError("composition must not run")

    monkeypatch.setattr(youtube_cli, "build_youtube_inbox_dev_services", forbidden_build)
    runner = CliRunner()
    non_dev = runner.invoke(
        cli,
        ["youtube-inbox-dev", "sync", "--account-binding-id", "binding-test"],
        env={
            "PKM_ENVIRONMENT": "prod",
            "YOUTUBE_OAUTH_CLIENT_ID": "client-id",
            "YOUTUBE_OAUTH_CLIENT_SECRET": planted_client_secret,
            "YOUTUBE_TOKEN_STORE_KEY": planted_store_key,
        },
    )

    assert non_dev.exit_code != 0
    assert "dev-only" in non_dev.output
    assert build_calls == 0
    assert planted_client_secret not in non_dev.output
    assert planted_store_key not in non_dev.output

    monkeypatch.setattr(
        youtube_cli,
        "build_youtube_inbox_dev_services",
        youtube_cli._build_youtube_inbox_dev_services,
    )
    for missing in (
        "YOUTUBE_OAUTH_CLIENT_ID",
        "YOUTUBE_OAUTH_CLIENT_SECRET",
        "YOUTUBE_TOKEN_STORE_KEY",
    ):
        env = {
            "PKM_ENVIRONMENT": "dev",
            "YOUTUBE_OAUTH_CLIENT_ID": "planted-client-id",
            "YOUTUBE_OAUTH_CLIENT_SECRET": planted_client_secret,
            "YOUTUBE_TOKEN_STORE_KEY": planted_store_key,
            "STORE_BACKEND": "memory",
        }
        del env[missing]
        result = runner.invoke(cli, ["youtube-inbox-dev", "connect"], env=env)
        assert result.exit_code != 0
        assert missing in result.output
        assert planted_client_secret not in result.output
        assert planted_store_key not in result.output

    reflected_provider_value = "reflected-provider-value-" + secrets.token_hex(8)

    class _ProviderFailureBinder:
        def start_device_connection(self) -> Any:
            raise OAuthProviderError(status=400, error_code=reflected_provider_value)

    monkeypatch.setattr(
        youtube_cli,
        "build_youtube_inbox_dev_services",
        lambda account_binding_id=None: youtube_cli.YouTubeInboxDevServices(
            binder=_ProviderFailureBinder(),
            api_client=None,
            sync=None,
        ),
    )
    provider_failure = runner.invoke(
        cli, ["youtube-inbox-dev", "connect"], env=_dev_env()
    )
    assert provider_failure.exit_code != 0
    assert "OAuth provider failed" in provider_failure.output
    assert reflected_provider_value not in provider_failure.output


def test_v1_command_remains_single_inbox_and_manual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync = _Sync()

    def refuse_second(*, playlist_ref: str, title: str) -> Any:
        del playlist_ref, title
        raise V1InboxConfigurationError("V1 already has an enabled Inbox")

    sync.select_inbox = refuse_second  # type: ignore[method-assign]
    monkeypatch.setattr(
        youtube_cli,
        "build_youtube_inbox_dev_services",
        lambda account_binding_id=None: youtube_cli.YouTubeInboxDevServices(
            binder=_Binder(),
            api_client=_Api(),
            sync=sync,
        ),
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "youtube-inbox-dev",
            "select",
            "--account-binding-id",
            "binding-test",
            "--playlist-id",
            "PL_test_owned_inbox",
        ],
        env=_dev_env(),
    )
    help_result = runner.invoke(
        cli, ["youtube-inbox-dev", "--help"], env=_dev_env()
    )
    class _RefusingBinder:
        def start_device_connection(self) -> Any:
            raise AccountBindingAdmissionError("planted internal account detail")

    monkeypatch.setattr(
        youtube_cli,
        "build_youtube_inbox_dev_services",
        lambda account_binding_id=None: youtube_cli.YouTubeInboxDevServices(
            binder=_RefusingBinder(),
            api_client=_Api(),
            sync=sync,
        ),
    )
    second_account = runner.invoke(
        cli, ["youtube-inbox-dev", "connect"], env=_dev_env()
    )

    class _BusyBinder:
        def start_device_connection(self) -> Any:
            raise OAuthWriterAdmissionError("planted internal lease detail")

    monkeypatch.setattr(
        youtube_cli,
        "build_youtube_inbox_dev_services",
        lambda account_binding_id=None: youtube_cli.YouTubeInboxDevServices(
            binder=_BusyBinder(),
            api_client=_Api(),
            sync=sync,
        ),
    )
    overlapping_connect = runner.invoke(
        cli, ["youtube-inbox-dev", "connect"], env=_dev_env()
    )

    assert result.exit_code != 0
    assert "already has an enabled Inbox" in result.output
    assert second_account.exit_code != 0
    assert "already has one OAuth-connected account" in second_account.output
    assert "planted internal account detail" not in second_account.output
    assert overlapping_connect.exit_code != 0
    assert "already active" in overlapping_connect.output
    assert "planted internal lease detail" not in overlapping_connect.output
    assert help_result.exit_code == 0
    assert all(
        forbidden not in help_result.output.lower()
        for forbidden in ("schedule", "backfill", "multi-playlist", "public api key")
    )
    assert set(youtube_cli.youtube_inbox_dev.commands) == {
        "connect",
        "select",
        "sync",
        "status",
        "drain",
    }


@dataclass(frozen=True)
class _Row:
    """The fields `drain` reads off a claimed queue row."""

    request_id: str
    status: str = "in_progress"
    source_kind: str = "youtube_url"


class _Queue:
    """Stands in for `AcquisitionRequests`, handing out one claimed row per call."""

    def __init__(self, rows: list[_Row]) -> None:
        self._pending = list(rows)
        self.claim_limits: list[int] = []

    def claim_batch(self, limit: int, **kwargs: Any) -> list[_Row]:
        self.claim_limits.append(limit)
        if not self._pending:
            return []
        return [self._pending.pop(0)]


class _VaultManager:
    def __init__(self, context: Any) -> None:
        self._context = context

    def context(self) -> Any:
        return self._context


def _selected_vault() -> Any:
    from app.vault.manager import VaultContext

    return VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_name="Synthetic Vault",
        active_vault_path="/tmp/synthetic-vault",
    )


def _install_drain_doubles(
    monkeypatch: pytest.MonkeyPatch,
    *,
    queue: _Queue,
    vault_context: Any,
    outcome_for: Any,
) -> list[str]:
    drained: list[str] = []

    def fake_drain_one(request: Any, **kwargs: Any) -> Any:
        assert kwargs["queue"] is queue
        assert kwargs["vault_context"] is vault_context
        drained.append(request.request_id)
        return outcome_for(request)

    monkeypatch.setattr(youtube_cli, "drain_one", fake_drain_one)
    monkeypatch.setattr(
        youtube_cli, "AcquisitionRequests", type("Q", (), {"for_runtime": staticmethod(lambda: queue)})
    )
    monkeypatch.setattr(
        youtube_cli, "get_vault_manager", lambda: _VaultManager(vault_context)
    )
    return drained


def test_drain_runs_claimed_requests_through_drain_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Enforcement: the production `drain` command must reach the real
    # `drain_one` adapter for every claimed row, and stop when the queue is
    # empty rather than burning the whole --max budget.
    queue = _Queue([_Row("req-1"), _Row("req-2")])
    context = _selected_vault()
    drained = _install_drain_doubles(
        monkeypatch,
        queue=queue,
        vault_context=context,
        outcome_for=lambda row: _Row(row.request_id, status="completed"),
    )

    result = CliRunner().invoke(
        cli, ["youtube-inbox-dev", "drain", "--max", "5"], env=_dev_env()
    )

    assert result.exit_code == 0
    assert drained == ["req-1", "req-2"]
    receipt = _json_lines(result.output)[-1]
    assert receipt["status"] == "drained"
    assert receipt["claimed"] == 2
    assert receipt["outcomes"] == {"completed": 2}
    # Claimed one at a time, and the empty claim ends the pass before --max.
    assert queue.claim_limits == [1, 1, 1]


def test_drain_refuses_without_selected_vault_before_claiming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No writable target means no row may be claimed: a claimed row would sit
    # `in_progress` until the stale reset, blocking the next drain.
    from app.vault.manager import VaultContext

    queue = _Queue([_Row("req-1")])
    drained = _install_drain_doubles(
        monkeypatch,
        queue=queue,
        vault_context=VaultContext(status="none"),
        outcome_for=lambda row: row,
    )

    result = CliRunner().invoke(cli, ["youtube-inbox-dev", "drain"], env=_dev_env())

    assert result.exit_code != 0
    assert "no vault is selected" in result.output
    assert queue.claim_limits == []
    assert drained == []


def test_drain_isolates_per_item_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # A row that `drain_one` returns to retryable state must not end the pass;
    # the remaining claimed rows still run and the receipt counts each outcome.
    queue = _Queue([_Row("req-1"), _Row("req-2"), _Row("req-3")])
    context = _selected_vault()
    outcomes = {
        "req-1": "pending",
        "req-2": "dead_lettered",
        "req-3": "completed",
    }
    drained = _install_drain_doubles(
        monkeypatch,
        queue=queue,
        vault_context=context,
        outcome_for=lambda row: _Row(row.request_id, status=outcomes[row.request_id]),
    )

    result = CliRunner().invoke(cli, ["youtube-inbox-dev", "drain"], env=_dev_env())

    assert result.exit_code == 0
    assert drained == ["req-1", "req-2", "req-3"]
    receipt = _json_lines(result.output)[-1]
    assert receipt["claimed"] == 3
    assert receipt["outcomes"] == {"pending": 1, "dead_lettered": 1, "completed": 1}


def test_drain_output_is_secret_free(monkeypatch: pytest.MonkeyPatch) -> None:
    planted_client_secret = "planted-client-secret-" + secrets.token_hex(8)
    planted_store_key = secrets.token_hex(32)
    env = {
        "PKM_ENVIRONMENT": "dev",
        "YOUTUBE_OAUTH_CLIENT_ID": "synthetic-client-id",
        "YOUTUBE_OAUTH_CLIENT_SECRET": planted_client_secret,
        "YOUTUBE_TOKEN_STORE_KEY": planted_store_key,
    }
    context = _selected_vault()

    queue = _Queue([_Row("req-1")])
    _install_drain_doubles(
        monkeypatch,
        queue=queue,
        vault_context=context,
        outcome_for=lambda row: _Row(row.request_id, status="completed"),
    )
    success = CliRunner().invoke(cli, ["youtube-inbox-dev", "drain"], env=env)

    reflected = "reflected-internal-detail-" + secrets.token_hex(8)

    def failing_drain_one(request: Any, **kwargs: Any) -> Any:
        del request, kwargs
        raise V1InboxConfigurationError(reflected)

    failing_queue = _Queue([_Row("req-1")])
    _install_drain_doubles(
        monkeypatch,
        queue=failing_queue,
        vault_context=context,
        outcome_for=lambda row: row,
    )
    monkeypatch.setattr(youtube_cli, "drain_one", failing_drain_one)
    failure = CliRunner().invoke(cli, ["youtube-inbox-dev", "drain"], env=env)

    assert success.exit_code == 0
    assert failure.exit_code != 0
    for output in (success.output, failure.output):
        assert planted_client_secret not in output
        assert planted_store_key not in output
