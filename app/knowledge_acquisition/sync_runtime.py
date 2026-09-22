"""YSS-06 (#3921): production composition for the scheduled source-sync tick.

The watcher registry loop calls :func:`run_scheduled_sync_tick` once per cycle.
Everything decision-shaped lives in :mod:`app.knowledge_acquisition.sync_scheduler`;
this module only resolves the runtime collaborators and the two gates, so the
scheduler stays testable without a vault, a database, or an OAuth binding.

The gates are checked here rather than inside the scheduler because a disabled
runner must do *nothing*: no lease claim, no registry read, no provider client
construction, no egress. Checking later would still be correct, but it would
mean a machine that opted out still touched shared state every minute.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.knowledge_acquisition.sync_scheduler import (
    DEFAULT_MAX_CONCURRENT_ACQUISITIONS,
    SyncScheduler,
    TickOutcome,
)

logger = logging.getLogger(__name__)

#: Whether this process has already run the post-start catch-up pass. The
#: scheduler is rebuilt every tick so it always sees current settings and vault
#: binding, which means the catch-up marker cannot live on the instance: it
#: would reset every minute and defeat every per-source cadence. Module state
#: dies with the process, which is exactly the lifetime this marker wants.
_RECONCILED = False

ENABLED_KEY = "youtubeSync.enabled"
RUNNER_ENABLED_KEY = "youtubeSync.runnerEnabled"
MAX_CONCURRENT_KEY = "youtubeSync.maxConcurrentAcquisitions"


def _setting(effective: dict[str, Any], key: str, default: Any) -> Any:
    entry = effective.get(key)
    if entry is None:
        return default
    value = getattr(entry, "value", None)
    return default if value is None else value


def _both_gates_open(effective: dict[str, Any]) -> bool:
    return bool(_setting(effective, ENABLED_KEY, False)) and bool(
        _setting(effective, RUNNER_ENABLED_KEY, False)
    )


def _build_api_client() -> Any:
    """Compose the YouTube API client for the single connected account.

    Returns ``None`` when no account is bound: that is a normal not-yet-set-up
    state, not a failure, and the caller reports it as a reason code rather
    than raising into the watcher loop.
    """
    import httpx

    from app.knowledge_acquisition.source_registry import SourceRegistry
    from app.knowledge_acquisition.youtube_account_binding import AccountBindingStore
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiClient
    from app.knowledge_acquisition.youtube_oauth import OAuthClient, TokenProvider
    from app.knowledge_acquisition.youtube_token_store import YouTubeTokenStore

    binding_store = AccountBindingStore.for_runtime()
    # Prefer a healthy binding; a degraded one still gets a chance, because the
    # token provider is what re-establishes it and refusing here would make
    # "degraded" permanent.
    bindings = sorted(
        binding_store.list_all(), key=lambda row: 0 if row.state == "connected" else 1
    )
    if not bindings:
        return None

    token_provider = TokenProvider(
        binding_id=bindings[0].account_binding_id,
        token_store=YouTubeTokenStore(),
        oauth_client=OAuthClient.from_env(http=httpx.Client()),
        binding_store=binding_store,
        source_registry=SourceRegistry.for_runtime(),
    )
    return YouTubeApiClient(token_provider=token_provider)


def run_scheduled_sync_tick(
    *,
    vault_context: Any,
    now: datetime | None = None,
    scheduler: SyncScheduler | None = None,
) -> TickOutcome:
    """One scheduled sync pass, or a reason code explaining why none ran."""

    global _RECONCILED

    from app.vault.settings_service import SettingsService

    service = SettingsService()
    # The two gates come from the governed accessor, never the ordinary
    # resolver: `resolve_accepted_runtime_gating` fails closed to the
    # registered safe default for first-seen, denied, cross-file, or otherwise
    # unreceipted disk input, so an unreviewed settings edit cannot switch a
    # runner on. `effective_settings` is the operator-facing view and is used
    # only for the non-gating tuning value below.
    if not _both_gates_open(service.resolve_accepted_runtime_gating(vault_context)):
        return TickOutcome(reason="disabled")
    effective = service.effective_settings(vault_context)

    owns_process_marker = scheduler is None
    if scheduler is None:
        from app.knowledge_acquisition.acquisition_requests import AcquisitionRequests
        from app.knowledge_acquisition.source_registry import SourceRegistry
        from app.knowledge_acquisition.sync_state import for_runtime as state_for_runtime

        api_client = _build_api_client()
        if api_client is None:
            return TickOutcome(reason="not_connected")

        scheduler = SyncScheduler(
            registry=SourceRegistry.for_runtime(),
            requests=AcquisitionRequests.for_runtime(),
            state=state_for_runtime(),
            vault_context=vault_context,
            api_client=api_client,
            clock=(lambda: now) if now is not None else None,
            max_concurrent=int(
                _setting(effective, MAX_CONCURRENT_KEY, DEFAULT_MAX_CONCURRENT_ACQUISITIONS)
            ),
            holder="watcher",
            reconciled=_RECONCILED,
        )

    outcome = scheduler.tick()
    if owns_process_marker:
        # Only a scheduler this function built speaks for this process; an
        # injected one belongs to its caller and must not rewrite the marker.
        _RECONCILED = scheduler.reconciled
    return outcome


__all__ = [
    "ENABLED_KEY",
    "MAX_CONCURRENT_KEY",
    "RUNNER_ENABLED_KEY",
    "run_scheduled_sync_tick",
]
