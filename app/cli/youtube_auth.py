"""Read-only YouTube account status for operators."""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from collections.abc import Iterator, Mapping

import click

from app.cli.youtube_inbox_dev import (
    _safe_cli_failure,
    build_youtube_inbox_dev_services,
)
from app.config.environment import ENV_DEV, ENV_TEST, active_environment
from app.knowledge_acquisition.youtube_account_binding import AccountBindingStore
from app.knowledge_acquisition.youtube_oauth import (
    DeviceAuthorizationPending,
    SCOPE,
    youtube_account_status,
)
from app.ops.host_secret_bootstrap import (
    HOST_SECRET_RUNTIME_ENV_FILE,
    materialize_consumer_environment,
)
from app.knowledge_acquisition.youtube_token_store import (
    YouTubeTokenStore,
    resolve_token_store_key,
)


_YOUTUBE_RUNTIME_BINDINGS = (
    "YOUTUBE_OAUTH_CLIENT_ID",
    "YOUTUBE_OAUTH_CLIENT_SECRET",
    "YOUTUBE_TOKEN_STORE_KEY",
)


def _require_connect_environment(target: str) -> None:
    if target not in {ENV_DEV, ENV_TEST}:
        raise click.ClickException("YouTube OAuth connect is limited to dev or test")
    try:
        current = active_environment()
    except ValueError as exc:
        raise click.ClickException(
            "youtube-auth connect requires PKM_ENVIRONMENT=dev or PKM_ENVIRONMENT=test"
        ) from exc
    if current != target:
        raise click.ClickException(
            f"youtube-auth connect target {target} does not match PKM_ENVIRONMENT={current}"
        )


@contextmanager
def _youtube_runtime_secret_environment(
    channel: str,
) -> Iterator[Mapping[str, str]]:
    """Build an isolated credential view without changing process globals."""
    inherited = dict(os.environ)
    present_bindings = [bool(inherited.get(binding)) for binding in _YOUTUBE_RUNTIME_BINDINGS]
    if any(present_bindings):
        if not all(present_bindings):
            raise click.ClickException(
                "YouTube runtime secret handoff is incomplete; refusing to connect"
            )
        # A running API/worker process already received the declared channel
        # handoff from native/BWS delivery. Reuse that exact boundary instead
        # of attempting a macOS Keychain lookup from a Linux TEST container.
        yield inherited
        return
    if inherited.get(HOST_SECRET_RUNTIME_ENV_FILE):
        # Native/Compose may provide the declared env-file pointer rather than
        # copying bindings into the process environment. The consumer loader
        # validates and resolves the file; do not replace it with Keychain.
        yield inherited
        return
    provider = (inherited.get("HOST_SECRET_PROVIDER") or "keychain").strip().lower()
    if provider != "keychain" or sys.platform != "darwin":
        raise click.ClickException(
            "YouTube OAuth runtime handoff is missing for the selected provider"
        )
    with materialize_consumer_environment(
        channel=channel,
        consumer="youtube-auth-cli",
        provider="keychain",
    ) as env_file:
        environment = dict(os.environ)
        for binding in _YOUTUBE_RUNTIME_BINDINGS:
            environment.pop(binding, None)
        environment[HOST_SECRET_RUNTIME_ENV_FILE] = str(env_file)
        yield environment


def _view() -> dict[str, object]:
    unavailable: dict[str, object] = {
        "status": "unavailable", "reason_code": "status_unavailable",
        "scopes": [], "token_store": "unavailable",
    }
    try:
        bindings = AccountBindingStore.for_runtime(read_only=True)
        rows = bindings.list_all()
        if not rows:
            return {"status": "absent", "reason_code": "auth_missing", "scopes": [], "token_store": "encrypted"}
        if len(rows) != 1:
            return {**unavailable, "reason_code": "ambiguous_bindings"}
        store = YouTubeTokenStore(read_only=True)
        result = youtube_account_status(rows[0].account_binding_id, binding_store=bindings, token_store=store)
        state = result.get("status")
        reason = result.get("reason_code")
        scopes = result.get("scopes")
        if state not in {"connected", "degraded", "absent"} or reason not in {
            None, "auth_missing", "auth_key_missing", "auth_expired", "auth_revoked", "auth_disconnected"
        } or not isinstance(scopes, list) or any(scope != SCOPE for scope in scopes) or (
            state == "connected" and (reason is not None or not scopes)
        ):
            return unavailable
        return {"status": state, "reason_code": reason, "scopes": scopes, "token_store": "encrypted"}
    except Exception:
        return unavailable


@click.group(name="youtube-auth", help="YouTube account authentication status.")
def youtube_auth() -> None:
    pass


@youtube_auth.command(name="status")
@click.option("--json", "as_json", is_flag=True, help="Emit stable JSON.")
def status(as_json: bool) -> None:
    """Show read-only, secret-free authentication status."""
    view = _view()
    if as_json:
        click.echo(json.dumps(view, sort_keys=True))
    else:
        click.echo(f"Status: {view['status']}\nReason: {view['reason_code'] or 'none'}\nScopes: {', '.join(view['scopes']) or 'none'}\nToken store: {view['token_store']}")
    if view["status"] in {"degraded", "unavailable"}:
        raise click.exceptions.Exit(1)


@youtube_auth.command(name="connect", help="Connect one non-production account with device OAuth.")
@click.option(
    "--environment",
    "target_environment",
    type=click.Choice([ENV_DEV, ENV_TEST], case_sensitive=True),
    required=True,
    help="The isolated non-production channel whose OAuth state is being changed.",
)
def connect(target_environment: str) -> None:
    """Run the existing device binder through the declared host-secret boundary."""
    _require_connect_environment(target_environment)
    connection = None
    services = None
    try:
        with _youtube_runtime_secret_environment(target_environment) as environment:
            # Fail before device consent when the delivered encryption boundary
            # is absent or malformed; otherwise the flow would only fail after
            # Google consent, when the account is first persisted.
            resolve_token_store_key(environment)
            services = build_youtube_inbox_dev_services(environment=environment)
            connection = services.binder.start_device_connection()
            click.echo(json.dumps({"status": "authorization_required", **connection.public_view()}, sort_keys=True))
            handle = getattr(connection, "handle", connection)
            interval = max(1, int(getattr(handle, "interval", 5)))
            delay = interval
            while True:
                time.sleep(delay)
                try:
                    receipt = services.binder.finish_device_connection(connection)
                    click.echo(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
                    return
                except DeviceAuthorizationPending as exc:
                    if exc.error_code == "slow_down":
                        delay += 5
    except click.ClickException:
        raise
    except Exception as exc:
        raise _safe_cli_failure(exc) from None
    finally:
        if connection is not None:
            try:
                cancel = getattr(services.binder, "cancel_device_connection", None)
                if callable(cancel):
                    cancel(connection)
                else:
                    connection.cancel()
            except BaseException:
                # The binder's own finish path releases admission on every
                # terminal provider result; this finalizer covers interruption
                # and output failures without replacing the original error.
                pass
