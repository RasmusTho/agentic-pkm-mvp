"""One dev-only operator command for the pragmatic YouTube Inbox V1 route.

This is deliberately a composition boundary, not the broad YSS-10 command
family.  It exposes only device connect, one owned Inbox selection, one manual
sync, and sanitized status.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import click
import httpx

from app.config.environment import ENV_DEV, active_environment
from app.knowledge_acquisition.acquisition_requests import AcquisitionRequests
from app.knowledge_acquisition.playlist_discovery import (
    V1InboxConfigurationError,
    YouTubeInboxSyncV1,
)
from app.knowledge_acquisition.source_registry import SourceRegistry
from app.knowledge_acquisition.youtube_account_binding import (
    AccountBindingAdmissionError,
    AccountBindingStore,
)
from app.knowledge_acquisition.youtube_api_client import YouTubeApiClient
from app.knowledge_acquisition.youtube_oauth import (
    AuthDegradedError,
    ChannelIdentity,
    DeviceAuthorizationError,
    DeviceAuthorizationPending,
    OAuthClient,
    OAuthClientCredentialsMissingError,
    OAuthProviderError,
    TokenProvider,
    YouTubeAccountBinder,
    resolve_oauth_client_credentials,
)
from app.knowledge_acquisition.youtube_token_store import (
    OAuthStateBoundaryError,
    OAuthWriterAdmissionError,
    TokenStoreKeyMissingError,
    YouTubeTokenStore,
    resolve_token_store_key,
)


@dataclass(frozen=True)
class YouTubeInboxDevServices:
    binder: Any
    api_client: Any
    sync: Any | None


@dataclass(frozen=True)
class _StaticTokenProvider:
    access_token: str

    def get_access_token(self) -> str:
        return self.access_token


def _emit(payload: dict[str, Any]) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _require_dev_and_secrets() -> None:
    try:
        environment = active_environment()
    except ValueError as exc:
        raise click.ClickException("youtube-inbox-dev requires PKM_ENVIRONMENT=dev") from exc
    if environment != ENV_DEV:
        raise click.ClickException(
            "youtube-inbox-dev is dev-only and requires PKM_ENVIRONMENT=dev"
        )

    # Resolve every credential before constructing stores or provider clients.
    # Only variable names and shape requirements may reach an error surface.
    try:
        resolve_oauth_client_credentials()
        resolve_token_store_key()
    except (OAuthClientCredentialsMissingError, TokenStoreKeyMissingError) as exc:
        raise click.ClickException(str(exc)) from None


def _identity_probe(access_token: str) -> ChannelIdentity:
    client = YouTubeApiClient(token_provider=_StaticTokenProvider(access_token))
    channel = client.get_my_channel()
    return ChannelIdentity(channel_id=channel.channel_id, channel_title=channel.title)


def _build_youtube_inbox_dev_services(
    account_binding_id: str | None = None,
) -> YouTubeInboxDevServices:
    """Compose only already-delivered V1 services after the dev/secret preflight."""

    http = httpx.Client()
    oauth_client = OAuthClient.from_env(http=http)
    token_store = YouTubeTokenStore()
    binding_store = AccountBindingStore.for_runtime()
    registry = SourceRegistry.for_runtime()
    binder = YouTubeAccountBinder(
        oauth_client=oauth_client,
        token_store=token_store,
        binding_store=binding_store,
        identity_probe=_identity_probe,
        source_registry=registry,
    )
    if account_binding_id is None:
        return YouTubeInboxDevServices(
            binder=binder,
            api_client=None,
            sync=None,
        )

    token_provider = TokenProvider(
        binding_id=account_binding_id,
        token_store=token_store,
        oauth_client=oauth_client,
        binding_store=binding_store,
        source_registry=registry,
    )
    api_client = YouTubeApiClient(token_provider=token_provider)
    sync = YouTubeInboxSyncV1(
        account_binding_id=account_binding_id,
        registry=registry,
        requests=AcquisitionRequests.for_runtime(),
        api_client=api_client,
        oauth_status=binder.status,
    )
    return YouTubeInboxDevServices(binder=binder, api_client=api_client, sync=sync)


# Public patch seam used by focused CLI tests; production calls this exact
# composition function rather than reimplementing any V1 service behavior.
build_youtube_inbox_dev_services = _build_youtube_inbox_dev_services


def _safe_cli_failure(exc: BaseException) -> click.ClickException:
    if isinstance(exc, V1InboxConfigurationError):
        return click.ClickException(str(exc))
    if isinstance(exc, AccountBindingAdmissionError):
        return click.ClickException(
            "V1 already has one OAuth-connected account; a second account is unavailable"
        )
    if isinstance(exc, OAuthWriterAdmissionError):
        return click.ClickException(
            "Another YouTube OAuth device connection is already active"
        )
    if isinstance(exc, OAuthStateBoundaryError):
        return click.ClickException("YouTube OAuth state is unavailable")
    if isinstance(exc, DeviceAuthorizationError):
        return click.ClickException("YouTube device authorization was denied or expired")
    if isinstance(exc, AuthDegradedError):
        return click.ClickException(f"YouTube authentication degraded: {exc.reason_code}")
    if isinstance(exc, OAuthProviderError):
        # ``error_code`` is provider-controlled input. The OAuth layer uses it
        # for local classification, but this final external boundary never
        # reflects it (or any provider body fragment) into terminal output.
        return click.ClickException("YouTube OAuth provider failed; retry device connection")
    if isinstance(exc, KeyError):
        return click.ClickException("The requested YouTube account binding was not found")
    return click.ClickException(
        "YouTube Inbox operation failed; inspect sanitized status and retry"
    )


@click.group(
    name="youtube-inbox-dev",
    help=(
        "Dev-only route for one OAuth account, one owned Inbox, one manual sync, "
        "and sanitized status."
    ),
)
def youtube_inbox_dev() -> None:
    _require_dev_and_secrets()


@youtube_inbox_dev.command(name="connect", help="Connect one account with device OAuth.")
def connect() -> None:
    try:
        services = build_youtube_inbox_dev_services()
        connection = services.binder.start_device_connection()
        _emit({"status": "authorization_required", **connection.public_view()})
        handle = getattr(connection, "handle", connection)
        interval = max(1, int(getattr(handle, "interval", 5)))
        delay = interval
        while True:
            time.sleep(delay)
            try:
                receipt = services.binder.finish_device_connection(connection)
                _emit(receipt)
                return
            except DeviceAuthorizationPending as exc:
                if exc.error_code == "slow_down":
                    delay += 5
    except click.ClickException:
        raise
    except Exception as exc:
        raise _safe_cli_failure(exc) from None


def _services_for_binding(account_binding_id: str) -> YouTubeInboxDevServices:
    services = build_youtube_inbox_dev_services(account_binding_id)
    if services.sync is None or services.api_client is None:
        raise RuntimeError("incomplete YouTube Inbox V1 composition")
    return services


@youtube_inbox_dev.command(name="select", help="Select the sole owned Inbox by stable playlist id.")
@click.option("--account-binding-id", required=True)
@click.option("--playlist-id", required=True)
def select(account_binding_id: str, playlist_id: str) -> None:
    try:
        services = _services_for_binding(account_binding_id)
        playlists = services.api_client.list_my_playlists().items
        playlist = next((row for row in playlists if row.playlist_id == playlist_id), None)
        if playlist is None:
            raise click.ClickException(
                "The playlist id is not an ordinary playlist owned by the connected account"
            )
        services.sync.select_inbox(playlist_ref=playlist.playlist_id, title=playlist.title)
        _emit(
            {
                "status": "selected",
                "account_binding_id": account_binding_id,
                "playlist_id": playlist.playlist_id,
            }
        )
    except click.ClickException:
        raise
    except Exception as exc:
        raise _safe_cli_failure(exc) from None


@youtube_inbox_dev.command(name="sync", help="Run the selected Inbox once, synchronously.")
@click.option("--account-binding-id", required=True)
def sync(account_binding_id: str) -> None:
    try:
        _emit(_services_for_binding(account_binding_id).sync.sync_now())
    except click.ClickException:
        raise
    except Exception as exc:
        raise _safe_cli_failure(exc) from None


@youtube_inbox_dev.command(name="status", help="Show secret-free account and Inbox status.")
@click.option("--account-binding-id", required=True)
def status(account_binding_id: str) -> None:
    try:
        services = _services_for_binding(account_binding_id)
        _emit(
            {
                "account": services.binder.status(account_binding_id),
                "inbox": services.sync.status(),
            }
        )
    except click.ClickException:
        raise
    except Exception as exc:
        raise _safe_cli_failure(exc) from None


__all__ = [
    "YouTubeInboxDevServices",
    "build_youtube_inbox_dev_services",
    "youtube_inbox_dev",
]
