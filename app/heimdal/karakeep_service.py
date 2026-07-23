"""Managed Karakeep service preconditions for Heimdal fetch (KMA-02, #3373).

Ratified by ``docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md``
§1 and specified by
``docs/KARAKEEP_MIMER_ACQUISITION/DEPLOY_KARAKEEP_AS_A_MANAGED_SERVICE.md`` (KMA-02).

The managed Karakeep service (``docker-compose.karakeep.yml``) is Heimdal's
external source dependency. This module is the fail-loud gate the Heimdal
acquisition worker calls *before* any source egress: acquisition must not run
when required configuration references are absent or the service health is red
(KMA-INV-5). It is deliberately narrow and side-effect-free -- it validates
config presence and probes health; it does not fetch, publish, or read the
observation log.

Secret containment (KMA-INV-6): configuration arrives only through the injected
environment mapping (default ``os.environ``); this module reads reference
*names* and never emits their values. A missing-config error names only the
absent variable names, and a health failure reports a status class, never the
endpoint URL or token.

Boundary (KMA-INV-4): this gate governs Heimdal *fetch* only. Mimer replay of
already-published evidence reads the durable observation log through its own
consumer seam and never calls this gate, so an unhealthy or absent Karakeep
service cannot stop Mimer from replaying evidence that is already durable.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Runtime configuration references the operator owns. Values live in the
# gitignored config/karakeep.env (template: config/karakeep.env.example); this
# module only checks that the references resolve to a non-empty value.
REQUIRED_CONFIG_ENV: tuple[str, ...] = ("KARAKEEP_BASE_URL", "KARAKEEP_API_TOKEN")

_DEFAULT_TIMEOUT_SECONDS = 5.0


class KarakeepServiceConfigError(RuntimeError):
    """Required Karakeep configuration references are absent (names only, no values)."""


class KarakeepServiceUnhealthyError(RuntimeError):
    """The managed Karakeep service is not healthy; Heimdal fetch is refused."""


@dataclass(frozen=True)
class HealthStatus:
    """Outcome of a Karakeep health probe. Carries no secret-bearing fields."""

    healthy: bool
    status: Optional[int]
    reason: str


def missing_config(env: Mapping[str, str] | None = None) -> list[str]:
    """Return the names (only) of required config references that are unset/empty."""
    resolved = env if env is not None else os.environ
    return [name for name in REQUIRED_CONFIG_ENV if not (resolved.get(name) or "").strip()]


def assert_required_config(env: Mapping[str, str] | None = None) -> None:
    """Fail loud if any required config reference is absent. Reports names only."""
    missing = missing_config(env)
    if missing:
        raise KarakeepServiceConfigError(
            "Karakeep acquisition config is incomplete; set the missing operator-owned "
            f"reference(s): {', '.join(sorted(missing))}"
        )


def check_service_health(
    base_url: str,
    *,
    http: httpx.Client | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> HealthStatus:
    """Probe the managed service's liveness without raising on an unhealthy result.

    A non-error 2xx/3xx from the web root is healthy. Any error status, timeout,
    or transport failure is reported as unhealthy with a secret-free reason (the
    endpoint URL and token are never included).
    """
    client = http or httpx.Client()
    owns_client = http is None
    try:
        response = client.get(base_url, timeout=timeout_seconds)
    except httpx.TimeoutException:
        return HealthStatus(False, None, "timeout")
    except httpx.InvalidURL:
        # A malformed operator-set endpoint. Report a status class only -- never
        # surface the URL (its exception text would embed base_url), KMA-INV-6.
        return HealthStatus(False, None, "invalid_endpoint")
    except httpx.HTTPError:
        # Any other transport/protocol failure (connect, read, protocol, ...).
        return HealthStatus(False, None, "transport_error")
    finally:
        if owns_client:
            client.close()

    status = response.status_code
    if status < 400:
        return HealthStatus(True, status, "ok")
    return HealthStatus(False, status, "unhealthy_status")


def assert_fetch_ready(
    env: Mapping[str, str] | None = None,
    *,
    http: httpx.Client | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Fail loud before Heimdal fetch when config is absent or health is red.

    This is the one gate the acquisition worker calls before source egress. It
    intentionally does not touch the observation log: Mimer replay of already
    published evidence stays available regardless of service health.
    """
    assert_required_config(env)
    resolved = env if env is not None else os.environ
    base_url = (resolved.get("KARAKEEP_BASE_URL") or "").strip()
    health = check_service_health(base_url, http=http, timeout_seconds=timeout_seconds)
    if not health.healthy:
        # Secret-safe: log the status class and reason only, never base_url/token.
        logger.warning(
            "Karakeep service health is red (reason=%s status=%s); refusing Heimdal fetch",
            health.reason,
            health.status,
        )
        raise KarakeepServiceUnhealthyError(
            f"Karakeep service is not healthy (reason={health.reason}, "
            f"status={health.status}); refusing Heimdal fetch"
        )


__all__ = [
    "HealthStatus",
    "KarakeepServiceConfigError",
    "KarakeepServiceUnhealthyError",
    "REQUIRED_CONFIG_ENV",
    "assert_fetch_ready",
    "assert_required_config",
    "check_service_health",
    "missing_config",
]
