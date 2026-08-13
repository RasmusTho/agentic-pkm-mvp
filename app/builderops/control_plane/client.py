"""Versioned authenticated client for the BuilderOps control-plane API.

This is the single authority-bearing transport every MacBook workflow uses to
reach the independent BuilderOps service (BCP-02). It deliberately holds **no**
store, database driver, or filesystem authority: when the service is
unavailable, or a credential is rejected, or a fencing/epoch conflict occurs,
every method raises a typed fail-closed error and leaves no local authority,
SQLite database, JSONL/JSON ledger, or fabricated GitHub lease behind.

BCP-04 prepares the clients; BCP-06 chooses the authoritative cutover moment.
The base URL and scoped bearer credential come exclusively from host/user secret
configuration (environment variables and host secret files), never from files
checked into a repository, and the credential is never logged.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.builderops.control_plane.models import STALE_DETAIL_NAMES

API_VERSION = "v1"
_EPOCH_HEADER = "X-BuilderOps-Authority-Epoch"
_DEFAULT_TIMEOUT_SECONDS = 15.0
_DEFAULT_MAX_RETRIES = 2

# 409 details that mean "your lease/fence/epoch is no longer authoritative".
# Shared with the service's HTTP 409 classification via models.py so a
# server-side exception rename cannot silently desync from this matching
# (BCP-04 review finding H3).
_STALE_DETAILS = STALE_DETAIL_NAMES


class ControlPlaneClientError(RuntimeError):
    """Base class for every fail-closed control-plane client error."""


class ControlPlaneConfigError(ControlPlaneClientError):
    """Raised when the host-owned client configuration is missing or unusable."""


class ControlPlaneUnavailableError(ControlPlaneClientError):
    """Raised when the service is unreachable, timed out, or returned 5xx/429.

    Unavailability never degrades to a local store or fabricated lease.
    """


class ControlPlaneAuthError(ControlPlaneClientError):
    """Raised on 401: the credential is missing, invalid, or revoked."""


class ControlPlaneScopeError(ControlPlaneClientError):
    """Raised on 403: the credential lacks the scope or repository authority."""


class ControlPlaneConflictError(ControlPlaneClientError):
    """Raised on 409 idempotency/state conflict for a different request."""


class StaleLeaseError(ControlPlaneClientError):
    """Raised on 409 stale fencing token, stale authority epoch, or lost lease."""


class ControlPlaneNotFoundError(ControlPlaneClientError):
    """Raised on 404: the addressed authority object/receipt does not exist."""


class ControlPlaneProtocolError(ControlPlaneClientError):
    """Raised on a malformed response or an unmappable 4xx (e.g. 400/422)."""


@dataclass(frozen=True)
class ClientConfig:
    """Host-resolved base URL plus scoped bearer credential.

    The credential is kept out of ``repr`` and is never logged. It is resolved
    from a host secret file or a host environment variable, both outside the
    repository, matching the deployment's credential custody.
    """

    base_url: str
    token: str = field(repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ClientConfig":
        source = os.environ if env is None else env
        base_url = source.get("BUILDEROPS_API_URL", "").strip()
        if not base_url:
            raise ControlPlaneConfigError(
                "BUILDEROPS_API_URL is required to reach the BuilderOps control plane"
            )
        if not base_url.startswith(("http://", "https://")):
            raise ControlPlaneConfigError("BUILDEROPS_API_URL must be an http(s) URL")
        token_direct = source.get("BUILDEROPS_API_TOKEN", "").strip()
        token_file = source.get("BUILDEROPS_API_TOKEN_FILE", "").strip()
        if token_direct and token_file:
            raise ControlPlaneConfigError(
                "configure exactly one of BUILDEROPS_API_TOKEN or BUILDEROPS_API_TOKEN_FILE"
            )
        if token_file:
            try:
                token = Path(token_file).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ControlPlaneConfigError(
                    "BuilderOps API credential file is unavailable"
                ) from exc
        else:
            token = token_direct
        if not token:
            raise ControlPlaneConfigError(
                "a BuilderOps API credential is required "
                "(BUILDEROPS_API_TOKEN or BUILDEROPS_API_TOKEN_FILE)"
            )
        return cls(base_url=base_url.rstrip("/"), token=token)


class BuilderOpsControlPlaneClient:
    """Authenticated, versioned, fail-closed client for records, inquiries,
    tasks, leases, attempts, promotions, receipts, and status."""

    def __init__(
        self,
        config: ClientConfig,
        *,
        http_client: httpx.Client | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = 0.0,
    ) -> None:
        self._config = config
        self._max_retries = max(0, max_retries)
        self._retry_backoff = max(0.0, retry_backoff_seconds)
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=config.base_url, timeout=_DEFAULT_TIMEOUT_SECONDS
        )
        self._pinned_epoch: int | None = None

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "BuilderOpsControlPlaneClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- authority epoch -----------------------------------------------------
    @property
    def authority_epoch(self) -> int:
        """The single authority epoch this client operates under.

        Pinned from the first ``status`` read; every subsequent mutation carries
        it so a superseded (post-recovery) epoch is fenced server-side instead
        of silently mutating a new authority.
        """
        if self._pinned_epoch is None:
            snapshot = self.status()
            epoch = snapshot.get("authority_epoch")
            if not isinstance(epoch, int):
                raise ControlPlaneProtocolError(
                    "control plane returned no authority epoch"
                )
            self._pinned_epoch = epoch
        return self._pinned_epoch

    # -- reads ---------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return self._request("GET", f"/{API_VERSION}/status", pin_epoch=False)

    def get_receipt(
        self,
        *,
        repository: str,
        object_kind: str,
        object_id: str,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"repository": repository}
        if task_id is not None:
            params["task_id"] = task_id
        return self._request(
            "GET",
            f"/{API_VERSION}/receipts/{object_kind}/{object_id}",
            params=params,
            pin_epoch=False,
        )

    def get_task(self, *, repository: str, task_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/{API_VERSION}/tasks/{task_id}",
            params={"repository": repository},
            pin_epoch=False,
        )

    def list_tasks(
        self, *, repository: str, task_prefix: str | None = None
    ) -> list[dict[str, Any]]:
        params = {"repository": repository}
        if task_prefix is not None:
            params["task_prefix"] = task_prefix
        body = self._request(
            "GET", f"/{API_VERSION}/tasks", params=params, pin_epoch=False
        )
        tasks = body.get("tasks")
        if not isinstance(tasks, list) or any(
            not isinstance(task, dict) for task in tasks
        ):
            raise ControlPlaneProtocolError(
                "control plane returned malformed task collection"
            )
        return tasks

    def list_attempts(
        self, *, repository: str, task_id: str
    ) -> list[dict[str, Any]]:
        body = self._request(
            "GET",
            f"/{API_VERSION}/tasks/{task_id}/attempts",
            params={"repository": repository},
            pin_epoch=False,
        )
        attempts = body.get("attempts")
        if not isinstance(attempts, list) or any(
            not isinstance(attempt, dict) for attempt in attempts
        ):
            raise ControlPlaneProtocolError(
                "control plane returned malformed attempt collection"
            )
        return attempts

    # -- authority-bearing mutations ----------------------------------------
    def commit_record(
        self,
        *,
        envelope: Mapping[str, Any],
        record_id: str,
        record_type: str,
        state: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/records",
            json_body={
                "envelope": dict(envelope),
                "record_id": record_id,
                "record_type": record_type,
                "state": state,
                "payload": dict(payload),
                "idempotency_key": idempotency_key,
            },
        )

    def create_inquiry(
        self,
        *,
        envelope: Mapping[str, Any],
        inquiry_id: str,
        state: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/inquiries",
            json_body={
                "envelope": dict(envelope),
                "inquiry_id": inquiry_id,
                "state": state,
                "payload": dict(payload),
                "idempotency_key": idempotency_key,
            },
        )

    def claim_task(
        self,
        *,
        envelope: Mapping[str, Any],
        task_id: str,
        idempotency_key: str,
        request: Mapping[str, Any] | None = None,
        ttl_seconds: int = 5400,
        require_new_fence: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/tasks/claim",
            json_body={
                "envelope": dict(envelope),
                "task_id": task_id,
                "idempotency_key": idempotency_key,
                "request": dict(request or {}),
                "ttl_seconds": ttl_seconds,
                "require_new_fence": require_new_fence,
            },
        )

    def heartbeat_task(
        self,
        *,
        envelope: Mapping[str, Any],
        lease: Mapping[str, Any],
        idempotency_key: str,
        request: Mapping[str, Any] | None = None,
        ttl_seconds: int = 5400,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/tasks/heartbeat",
            json_body={
                "envelope": dict(envelope),
                "lease": dict(lease),
                "idempotency_key": idempotency_key,
                "request": dict(request or {}),
                "ttl_seconds": ttl_seconds,
            },
        )

    def complete_task(
        self,
        *,
        envelope: Mapping[str, Any],
        lease: Mapping[str, Any],
        idempotency_key: str,
        expected_version: int | None = None,
        request: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if expected_version is None:
            task = self.get_task(
                repository=str(envelope["repository"]),
                task_id=str(lease["resource_id"]),
            )
            expected_version = int(task["version"])
        return self._request(
            "POST",
            f"/{API_VERSION}/tasks/complete",
            json_body={
                "envelope": dict(envelope),
                "lease": dict(lease),
                "idempotency_key": idempotency_key,
                "request": dict(request or {}),
                "expected_version": expected_version,
            },
        )

    def release_task(
        self,
        *,
        envelope: Mapping[str, Any],
        lease: Mapping[str, Any],
        idempotency_key: str,
        expected_version: int | None = None,
        request: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if expected_version is None:
            task = self.get_task(
                repository=str(envelope["repository"]),
                task_id=str(lease["resource_id"]),
            )
            expected_version = int(task["version"])
        return self._request(
            "POST",
            f"/{API_VERSION}/tasks/release",
            json_body={
                "envelope": dict(envelope),
                "lease": dict(lease),
                "idempotency_key": idempotency_key,
                "request": dict(request or {}),
                "expected_version": expected_version,
            },
        )

    def transition_task(
        self,
        *,
        envelope: Mapping[str, Any],
        task_id: str,
        to_state: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        outbox: Mapping[str, Any] | None = None,
        lease: Mapping[str, Any] | None = None,
        expected_states: tuple[str, ...] | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/tasks/transition",
            json_body={
                "envelope": dict(envelope),
                "task_id": task_id,
                "to_state": to_state,
                "idempotency_key": idempotency_key,
                "request": dict(request),
                "outbox": dict(outbox) if outbox is not None else None,
                "lease": dict(lease) if lease is not None else None,
                "expected_states": (
                    list(expected_states) if expected_states is not None else None
                ),
                "expected_version": expected_version,
            },
        )

    def claim_lease(
        self,
        *,
        envelope: Mapping[str, Any],
        resource_id: str,
        idempotency_key: str,
        request: Mapping[str, Any] | None = None,
        ttl_seconds: int = 5400,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/leases/claim",
            json_body={
                "envelope": dict(envelope),
                "resource_id": resource_id,
                "idempotency_key": idempotency_key,
                "request": dict(request or {}),
                "ttl_seconds": ttl_seconds,
            },
        )

    def commit_attempt(
        self,
        *,
        envelope: Mapping[str, Any],
        task_id: str,
        attempt_id: str,
        state: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        lease: Mapping[str, Any],
        expected_task_version: int | None = None,
        expected_states: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        if expected_task_version is None:
            task = self.get_task(
                repository=str(envelope["repository"]), task_id=task_id
            )
            expected_task_version = int(task["version"])
        return self._request(
            "POST",
            f"/{API_VERSION}/attempts",
            json_body={
                "envelope": dict(envelope),
                "task_id": task_id,
                "attempt_id": attempt_id,
                "state": state,
                "payload": dict(payload),
                "idempotency_key": idempotency_key,
                "lease": dict(lease),
                "expected_states": (
                    list(expected_states) if expected_states is not None else None
                ),
                "expected_task_version": expected_task_version,
            },
        )

    def commit_promotion(
        self,
        *,
        envelope: Mapping[str, Any],
        promotion_id: str,
        status: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        lease: Mapping[str, Any] | None = None,
        expected_states: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/promotions",
            json_body={
                "envelope": dict(envelope),
                "promotion_id": promotion_id,
                "status": status,
                "payload": dict(payload),
                "idempotency_key": idempotency_key,
                "lease": dict(lease) if lease is not None else None,
                "expected_states": (
                    list(expected_states) if expected_states is not None else None
                ),
            },
        )

    def claim_outbox(
        self,
        *,
        envelope: Mapping[str, Any],
        operation_key: str,
        worker_id: str,
        claim_ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/executor/outbox/claim",
            json_body={
                "envelope": dict(envelope),
                "operation_key": operation_key,
                "worker_id": worker_id,
                "claim_ttl_seconds": claim_ttl_seconds,
            },
        )

    def mark_outbox_unknown(
        self,
        *,
        envelope: Mapping[str, Any],
        claim: Mapping[str, Any],
        detail: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/executor/outbox/unknown",
            json_body={
                "envelope": dict(envelope),
                "claim": dict(claim),
                "detail": detail,
            },
        )

    def recover_outbox(
        self,
        *,
        envelope: Mapping[str, Any],
        operation_key: str,
        worker_id: str,
        claim_ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/executor/outbox/recover",
            json_body={
                "envelope": dict(envelope),
                "operation_key": operation_key,
                "worker_id": worker_id,
                "claim_ttl_seconds": claim_ttl_seconds,
            },
        )

    def get_outbox_status(
        self, *, repository: str, operation_key: str
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/{API_VERSION}/executor/outbox/{operation_key}",
            params={"repository": repository},
        )

    def reconcile_outbox(
        self,
        *,
        envelope: Mapping[str, Any],
        claim: Mapping[str, Any],
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/executor/outbox/reconcile",
            json_body={
                "envelope": dict(envelope),
                "claim": dict(claim),
                "observed_applied": observed_applied,
                "terminal_unknown": terminal_unknown,
                "evidence": dict(evidence),
            },
        )

    def begin_post_effect_reconciliation(
        self,
        *,
        envelope: Mapping[str, Any],
        claim: Mapping[str, Any],
        identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/executor/outbox/post-effect/pending",
            json_body={
                "envelope": dict(envelope),
                "claim": dict(claim),
                "identity": dict(identity),
            },
        )

    def reconcile_post_effect(
        self,
        *,
        envelope: Mapping[str, Any],
        claim: Mapping[str, Any],
        identity: Mapping[str, Any],
        readback: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/{API_VERSION}/executor/outbox/post-effect/reconcile",
            json_body={
                "envelope": dict(envelope),
                "claim": dict(claim),
                "identity": dict(identity),
                "readback": dict(readback),
            },
        )

    # -- transport -----------------------------------------------------------
    def _headers(self, *, pin_epoch: bool) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._config.token}"}
        if pin_epoch:
            headers[_EPOCH_HEADER] = str(self.authority_epoch)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        pin_epoch: bool = True,
    ) -> dict[str, Any]:
        headers = self._headers(pin_epoch=pin_epoch)
        last_unavailable: Exception | None = None
        # Idempotent retry: reads and idempotency-keyed writes are safe to
        # repeat. Retries only cover transport loss and 5xx/429 — they never
        # construct a local authority substitute.
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.request(
                    method,
                    path,
                    json=json_body if json_body is not None else None,
                    params=dict(params) if params else None,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                last_unavailable = exc
                if attempt < self._max_retries:
                    self._sleep(attempt)
                    continue
                raise ControlPlaneUnavailableError(
                    f"BuilderOps control plane is unreachable: {type(exc).__name__}"
                ) from exc

            if response.status_code >= 500 or response.status_code == 429:
                last_unavailable = ControlPlaneUnavailableError(
                    f"BuilderOps control plane returned {response.status_code}"
                )
                if attempt < self._max_retries:
                    self._sleep(attempt)
                    continue
                raise last_unavailable

            return self._decode(response)

        # Unreachable in practice; the loop always returns or raises.
        raise ControlPlaneUnavailableError(
            "BuilderOps control plane is unreachable"
        ) from last_unavailable

    def _sleep(self, attempt: int) -> None:
        if self._retry_backoff:
            time.sleep(self._retry_backoff * (attempt + 1))

    def _decode(self, response: httpx.Response) -> dict[str, Any]:
        status_code = response.status_code
        if status_code == 401:
            raise ControlPlaneAuthError("BuilderOps credential is invalid or revoked")
        if status_code == 403:
            raise ControlPlaneScopeError(
                "BuilderOps credential lacks the required scope or repository authority"
            )
        if status_code == 404:
            raise ControlPlaneNotFoundError("BuilderOps authority object was not found")
        if status_code == 409:
            detail = self._detail(response)
            if detail in _STALE_DETAILS:
                raise StaleLeaseError(f"BuilderOps lease/epoch is stale: {detail}")
            raise ControlPlaneConflictError(f"BuilderOps request conflict: {detail}")
        if status_code >= 400:
            raise ControlPlaneProtocolError(
                f"BuilderOps request was rejected ({status_code})"
            )
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ControlPlaneProtocolError(
                "BuilderOps control plane returned a malformed response"
            ) from exc
        if not isinstance(body, dict):
            raise ControlPlaneProtocolError(
                "BuilderOps control plane returned an unexpected response shape"
            )
        return body

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        """Extract the 409 ``detail`` classification, consistent with ``_decode``.

        A truncated/non-JSON body (e.g. proxy interference) raises
        ``ControlPlaneProtocolError`` rather than silently returning an empty
        detail: a caller distinguishing ``StaleLeaseError`` (safe to retry
        after a lease refresh) from a generic ``ControlPlaneConflictError``
        must not have that signal silently downgraded by a malformed response.
        """
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ControlPlaneProtocolError(
                "BuilderOps control plane returned a malformed 409 response"
            ) from exc
        if not isinstance(body, dict):
            raise ControlPlaneProtocolError(
                "BuilderOps control plane returned an unexpected 409 response shape"
            )
        detail = body.get("detail")
        return detail if isinstance(detail, str) else ""


__all__ = [
    "API_VERSION",
    "BuilderOpsControlPlaneClient",
    "ClientConfig",
    "ControlPlaneAuthError",
    "ControlPlaneClientError",
    "ControlPlaneConfigError",
    "ControlPlaneConflictError",
    "ControlPlaneNotFoundError",
    "ControlPlaneProtocolError",
    "ControlPlaneScopeError",
    "ControlPlaneUnavailableError",
    "StaleLeaseError",
]
