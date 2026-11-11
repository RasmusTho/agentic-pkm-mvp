"""Read-only YouTube account status for operators."""

from __future__ import annotations

import json

import click

from app.knowledge_acquisition.youtube_account_binding import AccountBindingStore
from app.knowledge_acquisition.youtube_oauth import SCOPE, youtube_account_status
from app.knowledge_acquisition.youtube_token_store import YouTubeTokenStore


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
        ) or (state == "degraded" and reason is None):
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
