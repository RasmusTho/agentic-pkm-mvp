"""Independent FastAPI entrypoint for the BuilderOps control plane."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from collections.abc import Mapping
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from app.builderops.control_plane.api_models import LeaseClaimRequest, RecordCommitRequest
from app.builderops.control_plane.auth import (
    Credential,
    CredentialConfigurationError,
    CredentialRateLimiter,
    CredentialRegistry,
)
from app.builderops.control_plane.health import HealthService, LiveOperationalStatusProvider
from app.builderops.control_plane.models import (
    AuthorityEnvelope,
    ControlPlaneError,
    IdempotencyConflict,
    LeaseUnavailable,
    StorePort,
)
from app.builderops.control_plane.selection import database_environment, production_store
from app.middleware.trace import TraceIdMiddleware

bearer = HTTPBearer(auto_error=False)

_FORBIDDEN_DURABLE_KEYS = re.compile(
    r"(^|_)(authorization|bearer|credential|password|passwd|secret|token|api_key|"
    r"private_key|session_cookie|database_url|dsn)($|_)",
    re.IGNORECASE,
)
_ALLOWED_SECRET_METADATA_KEYS = frozenset(
    {"secret_ref", "fingerprint", "scopes", "rotation_generation", "credential_id"}
)
_SECRET_VALUE_PREFIXES = ("bearer ", "ghp_", "github_pat_", "sk-")
_EMBEDDED_SECRET_VALUE = re.compile(
    r"(?:bearer\s+\S+|ghp_[A-Za-z0-9_=-]+|github_pat_[A-Za-z0-9_=-]+|"
    r"sk-[A-Za-z0-9_=-]+|bcp-(?:client|db|github|model|recovery)-[A-Za-z0-9._~+/=-]+|"
    r"postgres(?:ql)?://[^\s]+@[^\s]+)",
    re.IGNORECASE,
)


def _canonical_durable_key(key: str) -> str:
    """Normalize common structured-key spellings before secret classification."""

    acronym_split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", key.strip())
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", acronym_split)
    return re.sub(r"[^A-Za-z0-9]+", "_", camel_split).strip("_").lower()


def _assert_secret_metadata_shape(key: str, value: Any) -> None:
    """Allow only non-secret reference/fingerprint/scope/rotation metadata."""

    if key == "secret_ref":
        if not isinstance(value, str) or re.fullmatch(
            r"(?:host-secret|keychain):[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}", value
        ) is None:
            raise ValueError("secret_ref must use a supported opaque host-secret provider")
    elif key == "fingerprint":
        if not isinstance(value, str) or re.fullmatch(
            r"(?:sha256:)?[0-9a-fA-F]{64}", value
        ) is None:
            raise ValueError("fingerprint must be a SHA-256 digest")
    elif key == "scopes":
        if not isinstance(value, (list, tuple)) or not all(
            isinstance(scope, str)
            and re.fullmatch(r"[a-z][a-z0-9_-]*:[a-z][a-z0-9_-]*", scope)
            for scope in value
        ):
            raise ValueError("scopes must contain bounded scope identifiers")
    elif key == "rotation_generation":
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("rotation_generation must be a positive integer")
    elif key == "credential_id":
        if not isinstance(value, str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}", value
        ) is None:
            raise ValueError("credential_id must be an opaque identifier")


def _envelope(request: Any, credential: Credential) -> AuthorityEnvelope:
    return AuthorityEnvelope(
        repository=request.repository,
        scope=request.scope,
        stack=request.stack,
        actor=credential.principal,
        source_refs=tuple(request.source_refs),
        schema_version=request.schema_version,
    )


def _credential_dependency(
    registry: CredentialRegistry,
    rate_limiter: CredentialRateLimiter,
    *required_scopes: str,
) -> Callable[..., Credential]:
    def require_credential(
        authorization: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> Credential:
        token = authorization.credentials if authorization and authorization.scheme.lower() == "bearer" else None
        try:
            credential = registry.authenticate(token)
        except CredentialConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="BuilderOps authentication is unavailable",
            ) from exc
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid BuilderOps credential",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not rate_limiter.allow(credential.principal):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="BuilderOps credential rate limit exceeded",
            )
        if not set(required_scopes).issubset(credential.scopes):
            registry.record_failure()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient BuilderOps credential scope",
            )
        return credential

    return require_credential


def _assert_durable_payload_safe(value: Any, registry: CredentialRegistry, *, key: str = "") -> None:
    """Reject credential-shaped material before it can enter PostgreSQL/WAL/backups."""
    normalized_key = _canonical_durable_key(key)
    if normalized_key in _ALLOWED_SECRET_METADATA_KEYS:
        _assert_secret_metadata_shape(normalized_key, value)
    if (
        normalized_key
        and normalized_key not in _ALLOWED_SECRET_METADATA_KEYS
        and _FORBIDDEN_DURABLE_KEYS.search(normalized_key)
    ):
        raise ValueError("raw credential fields are forbidden in durable BuilderOps payloads")
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            _assert_durable_payload_safe(child, registry, key=str(child_key))
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            # The collection shape above owns metadata validation. Children
            # still receive the value scan without being mistaken for a whole
            # `scopes` collection.
            child_key = "" if normalized_key in _ALLOWED_SECRET_METADATA_KEYS else key
            _assert_durable_payload_safe(child, registry, key=child_key)
        return
    if not isinstance(value, str):
        return
    lowered = value.strip().lower()
    if (
        lowered.startswith(_SECRET_VALUE_PREFIXES)
        or _EMBEDDED_SECRET_VALUE.search(value)
        or registry.contains_registered_secret(value)
    ):
        raise ValueError("raw credential values are forbidden in durable BuilderOps payloads")


def _control_plane_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (IdempotencyConflict, LeaseUnavailable)):
        return HTTPException(status_code=409, detail=type(exc).__name__)
    if isinstance(exc, (ControlPlaneError, ValueError)):
        return HTTPException(status_code=400, detail=type(exc).__name__)
    return HTTPException(status_code=503, detail="BuilderOps store unavailable")


def create_app(
    *,
    store: StorePort,
    credentials: CredentialRegistry,
    health: HealthService | None = None,
) -> FastAPI:
    """Create the service without initializing or migrating its database."""
    rate_limiter = CredentialRateLimiter(
        int(os.getenv("BUILDEROPS_RATE_LIMIT_PER_MINUTE", "120"))
    )
    health_service = health or HealthService(
        store,
        credentials,
        LiveOperationalStatusProvider(
            store,
            recovery_target_file=os.getenv(
                "BUILDEROPS_RECOVERY_TARGET_FILE", "/run/secrets/builderops_recovery_target"
            ),
            worker_heartbeat_file=os.getenv(
                "BUILDEROPS_WORKER_HEARTBEAT_FILE", "/run/builderops/worker.json"
            ),
        ),
        rate_limiter,
    )
    application = FastAPI(title="BuilderOps Control Plane", docs_url=None, redoc_url=None)
    application.add_middleware(TraceIdMiddleware)

    health_read = _credential_dependency(credentials, rate_limiter, "health:read")
    status_read = _credential_dependency(credentials, rate_limiter, "status:read")
    metrics_read = _credential_dependency(credentials, rate_limiter, "metrics:read")
    lease_write = _credential_dependency(credentials, rate_limiter, "leases:write")
    record_write = _credential_dependency(credentials, rate_limiter, "records:write")

    @application.get("/healthz")
    async def healthz(_credential: Credential = Depends(health_read)) -> dict[str, bool]:
        return health_service.liveness()

    @application.get("/readyz")
    async def readyz(_credential: Credential = Depends(health_read)) -> dict[str, Any]:
        snapshot = await run_in_threadpool(health_service.status)
        if not snapshot["ready"]:
            raise HTTPException(status_code=503, detail={"ready": False})
        return snapshot

    @application.get("/status")
    async def service_status(_credential: Credential = Depends(status_read)) -> dict[str, Any]:
        return await run_in_threadpool(health_service.status)

    @application.get("/metrics", response_class=Response)
    async def metrics(_credential: Credential = Depends(metrics_read)) -> Response:
        snapshot = await run_in_threadpool(health_service.status)
        lines = [
            f"builderops_ready {1 if snapshot['ready'] else 0}",
            f"builderops_outbox_pending {snapshot['outbox']['pending']}",
            f"builderops_dead_letters {snapshot['outbox']['dead_letters']}",
            f"builderops_active_leases {snapshot['leases']['active']}",
            f"builderops_auth_failures_total {snapshot['auth']['failures_total']}",
            f"builderops_rate_limit_rejections_total "
            f"{snapshot['rate_limit']['rejections_total']}",
        ]
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    @application.post("/v1/leases/claim")
    async def claim_lease(
        request: LeaseClaimRequest,
        credential: Credential = Depends(lease_write),
    ) -> dict[str, Any]:
        try:
            # Every client-controlled field below becomes durable authority,
            # idempotency, or lease state. Validate the complete request before
            # constructing any store arguments so credentials cannot escape the
            # payload boundary through identifiers or envelope metadata.
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            result, lease = await run_in_threadpool(
                store.claim_lease,
                envelope=_envelope(request.envelope, credential),
                resource_id=request.resource_id,
                holder=credential.principal,
                idempotency_key=request.idempotency_key,
                request=request.request,
                ttl_seconds=request.ttl_seconds,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {
            "result": {
                "repository": result.repository,
                "task_id": result.task_id,
                "state": result.state,
                "receipt_sequence": result.receipt_sequence,
                "recovery_lsn": result.recovery_lsn,
                "operation_key": result.operation_key,
                "replayed": result.replayed,
            },
            "lease": {
                "repository": lease.repository,
                "resource_id": lease.resource_id,
                "holder": lease.holder,
                "fencing_token": lease.fencing_token,
                "expires_at": lease.expires_at.isoformat(),
                "lease_kind": lease.lease_kind,
            },
        }

    @application.post("/v1/records")
    async def commit_record(
        request: RecordCommitRequest,
        credential: Credential = Depends(record_write),
    ) -> dict[str, Any]:
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            result = await run_in_threadpool(
                store.commit_record,
                envelope=_envelope(request.envelope, credential),
                record_id=request.record_id,
                record_type=request.record_type,
                state=request.state,
                payload=request.payload,
                idempotency_key=request.idempotency_key,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {
            "repository": result.repository,
            "object_kind": result.object_kind,
            "object_id": result.object_id,
            "state": result.state,
            "receipt_sequence": result.receipt_sequence,
            "recovery_lsn": result.recovery_lsn,
            "replayed": result.replayed,
        }

    return application


def production_app() -> FastAPI:
    manifest = os.getenv("BUILDEROPS_CREDENTIAL_MANIFEST_FILE", "").strip()
    if not manifest:
        raise RuntimeError("BUILDEROPS_CREDENTIAL_MANIFEST_FILE is required")
    # Deliberately does not call initialize(): the dedicated migration gate owns
    # schema changes before the API process may become ready.
    store = production_store(database_environment(os.environ))
    credentials = CredentialRegistry(manifest)
    return create_app(store=store, credentials=credentials)


__all__ = [
    "create_app",
    "database_environment",
    "production_app",
]
