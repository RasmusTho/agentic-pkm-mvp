"""Independent FastAPI entrypoint for the BuilderOps control plane."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from collections.abc import Mapping
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from app.builderops.control_plane.api_models import (
    AttemptCommitRequest,
    InquiryCommitRequest,
    LeaseClaimRequest,
    LeaseInput,
    OutboxClaimRequest,
    OutboxRecoverRequest,
    OutboxReconcileRequest,
    OutboxUnknownRequest,
    PromotionCommitRequest,
    RecordCommitRequest,
    TaskClaimRequest,
    TaskCompleteRequest,
    TaskHeartbeatRequest,
    TaskReleaseRequest,
    TaskTransitionRequest,
)
from app.builderops.control_plane.auth import (
    Credential,
    CredentialConfigurationError,
    CredentialRateLimiter,
    CredentialRegistry,
)
from app.builderops.control_plane.health import HealthService, LiveOperationalStatusProvider
from app.builderops.control_plane.models import (
    STALE_AUTHORITY_EPOCH_DETAIL,
    AuthorityEnvelope,
    ControlPlaneError,
    IdempotencyConflict,
    Lease,
    LeaseRequired,
    LeaseUnavailable,
    OutboxClaim,
    StaleFencingToken,
    StateConflict,
    StorePort,
    canonical_repository,
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
    {
        "secret_ref",
        "fingerprint",
        "scopes",
        "rotation_generation",
        "credential_id",
        "token_length",
    }
)
# Structural authority fields whose names collide with the credential-key
# heuristic (``fencing_token`` ends in ``_token``) but which are never secrets.
# The exemption is scoped to BOTH the FULL ancestor path from the request
# root (not merely the immediate parent key — a "lease" object nested at any
# depth inside free-form payload/request content must not qualify) AND a
# strict int value type — never the bare key name anywhere in the tree. Every
# request model that carries a real lease puts it at the top level
# (``TaskHeartbeatRequest.lease``, ``TaskCompleteRequest.lease``,
# ``AttemptCommitRequest.lease``, ``PromotionCommitRequest.lease``), so the
# only legitimate path is exactly ``("lease", "fencing_token")``. As a second,
# independent layer, the value-type gate rejects a string even if some future
# path were added here by mistake: no BuilderOps credential/secret in this
# system is ever numeric (they are opaque strings from secret files), so a
# raw credential can never satisfy the int check regardless of path.
_STRUCTURAL_SAFE_KEYS = frozenset({"fencing_token"})
_STRUCTURAL_SAFE_FIELD_PATHS: dict[str, frozenset[tuple[str, ...]]] = {
    "fencing_token": frozenset(
        {("lease", "fencing_token"), ("claim", "fencing_token")}
    )
}
_FORBIDDEN_COMPACT_DURABLE_KEYS = frozenset(
    {
        "authorization",
        "bearer",
        "credential",
        "password",
        "passwd",
        "secret",
        "token",
        "apikey",
        "privatekey",
        "sessioncookie",
        "databaseurl",
        "dsn",
    }
)
_SECRET_VALUE_PREFIXES = ("bearer ", "ghp_", "github_pat_", "sk-")
_EMBEDDED_SECRET_VALUE = re.compile(
    r"(?:bearer\s+\S+|ghp_[A-Za-z0-9_=-]+|github_pat_[A-Za-z0-9_=-]+|"
    r"sk-[A-Za-z0-9_=-]+|bcp-(?:client|db|github|model|recovery)-[A-Za-z0-9._~+/=-]+|"
    r"postgres(?:ql)?://[^\s]+@[^\s]+)",
    re.IGNORECASE,
)
_MAX_DURABLE_TEXT_LENGTH = 16_384
_MAX_DURABLE_TEXT_SCAN_CHARS = 262_144
_MAX_DURABLE_VALUE_NODES = 10_000


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
    elif key == "token_length":
        if type(value) is not int or not 8 <= value <= 512:
            raise ValueError("token_length must be a bounded positive integer")


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


def _assert_durable_payload_safe(
    value: Any,
    registry: CredentialRegistry,
    *,
    key: str = "",
    _path: tuple[str, ...] = (),
    _remaining_chars: list[int] | None = None,
    _remaining_nodes: list[int] | None = None,
) -> None:
    """Reject credential-shaped material before it can enter PostgreSQL/WAL/backups."""
    remaining_chars = (
        [_MAX_DURABLE_TEXT_SCAN_CHARS]
        if _remaining_chars is None
        else _remaining_chars
    )
    remaining_nodes = (
        [_MAX_DURABLE_VALUE_NODES]
        if _remaining_nodes is None
        else _remaining_nodes
    )
    remaining_nodes[0] -= 1
    if remaining_nodes[0] < 0:
        raise ValueError("durable BuilderOps request exceeds the value node limit")
    normalized_key = _canonical_durable_key(key)
    # The full ancestor chain from the request root down to and including
    # this node's own key — not just the immediate parent. ``_path`` is the
    # chain ABOVE this node, threaded in from the caller.
    current_path = (*_path, normalized_key) if normalized_key else _path
    if normalized_key in _ALLOWED_SECRET_METADATA_KEYS:
        _assert_secret_metadata_shape(normalized_key, value)
    # The structural exemption requires the EXACT full path from the request
    # root (not just an immediate parent name — a "lease" object nested at
    # ANY depth inside free-form payload/request content must not qualify)
    # plus a strict int value type. A free-form payload/request field named
    # "fencing_token" is only exempt if BOTH its full path matches the one
    # genuine top-level lease field AND its value is literally an int; a raw
    # secret string can never satisfy the type gate, so it always falls
    # through to the forbidden-key check below regardless of path.
    is_exempt_structural_field = (
        normalized_key in _STRUCTURAL_SAFE_KEYS
        and current_path in _STRUCTURAL_SAFE_FIELD_PATHS.get(normalized_key, frozenset())
        and isinstance(value, int)
        and not isinstance(value, bool)
    )
    if (
        normalized_key
        and normalized_key not in _ALLOWED_SECRET_METADATA_KEYS
        and not is_exempt_structural_field
        and (
            _FORBIDDEN_DURABLE_KEYS.search(normalized_key)
            or normalized_key.replace("_", "") in _FORBIDDEN_COMPACT_DURABLE_KEYS
        )
    ):
        raise ValueError("raw credential fields are forbidden in durable BuilderOps payloads")
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            durable_key = str(child_key)
            # JSON object keys are durable client-controlled text too. Scan the
            # key as a value before using it to classify its child value.
            _assert_durable_payload_safe(
                durable_key,
                registry,
                _remaining_chars=remaining_chars,
                _remaining_nodes=remaining_nodes,
            )
            _assert_durable_payload_safe(
                child,
                registry,
                key=durable_key,
                _path=current_path,
                _remaining_chars=remaining_chars,
                _remaining_nodes=remaining_nodes,
            )
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            # The collection shape above owns metadata validation. Children
            # still receive the value scan without being mistaken for a whole
            # `scopes` collection. A list does not introduce its own path
            # segment: its items reuse this node's key (as `child_key` does
            # below) and inherit the SAME ancestor path this node received
            # (not `current_path`, which already includes this node's own
            # key) so the item's own path computation adds exactly one
            # segment, matching the non-list case instead of duplicating it.
            child_key = "" if normalized_key in _ALLOWED_SECRET_METADATA_KEYS else key
            _assert_durable_payload_safe(
                child,
                registry,
                key=child_key,
                _path=_path,
                _remaining_chars=remaining_chars,
                _remaining_nodes=remaining_nodes,
            )
        return
    if not isinstance(value, str):
        return
    if len(value) > _MAX_DURABLE_TEXT_LENGTH:
        raise ValueError("durable BuilderOps text field exceeds the size limit")
    remaining_chars[0] -= len(value)
    if remaining_chars[0] < 0:
        raise ValueError("durable BuilderOps request exceeds the text scan limit")
    lowered = value.strip().lower()
    if (
        lowered.startswith(_SECRET_VALUE_PREFIXES)
        or _EMBEDDED_SECRET_VALUE.search(value)
        or registry.contains_registered_secret(value)
    ):
        raise ValueError("raw credential values are forbidden in durable BuilderOps payloads")


def _control_plane_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        # A scope/auth/epoch rejection raised inside the handler body must keep
        # its typed status code instead of collapsing into a 503.
        return exc
    if isinstance(
        exc,
        (
            IdempotencyConflict,
            LeaseUnavailable,
            StaleFencingToken,
            StateConflict,
            LeaseRequired,
        ),
    ):
        return HTTPException(status_code=409, detail=type(exc).__name__)
    if isinstance(exc, (ControlPlaneError, ValueError)):
        return HTTPException(status_code=400, detail=type(exc).__name__)
    return HTTPException(status_code=503, detail="BuilderOps store unavailable")


def _enforce_repo_scope(credential: Credential, repository: str) -> None:
    """Fail closed when a credential addresses a repository outside its scope.

    The mandatory single-``RepoRef`` rule (BCP-04) is enforced here so that no
    credential granted authority for one repository can mutate another. The
    repository is canonicalized first so scope checks are not bypassable by
    case or owner/name spelling.
    """
    try:
        canonical = canonical_repository(repository)
    except Exception as exc:  # EnvelopeValidationError and any parse failure
        raise HTTPException(status_code=400, detail="invalid repository reference") from exc
    if not credential.may_address(canonical):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="credential is not scoped to the addressed repository",
        )


def _enforce_outbox_principal(
    intent: Mapping[str, Any], credential: Credential
) -> None:
    """Bind recovery and reconciliation to the credential that claimed it."""

    envelope = intent.get("authority_envelope")
    if (
        not isinstance(envelope, Mapping)
        or envelope.get("actor") != credential.principal
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "outbox claim does not belong to the authenticated principal"
            ),
        )


def _lease_from_input(
    repository: str, lease: LeaseInput, credential: Credential
) -> Lease:
    """Reconstruct a fenced :class:`Lease` from client-echoed lease fields."""
    if lease.holder != credential.principal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="lease holder is not the authenticated principal",
        )
    return Lease(
        repository=repository,
        resource_id=lease.resource_id,
        holder=credential.principal,
        fencing_token=lease.fencing_token,
        expires_at=lease.expires_at,
        lease_kind=lease.lease_kind,
    )


def _outbox_claim_from_input(
    request: Any, *, repository: str
) -> OutboxClaim:
    canonical = canonical_repository(repository)
    if canonical_repository(request.repository) != canonical:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="outbox claim repository does not match authenticated envelope",
        )
    return OutboxClaim(
        repository=canonical,
        operation_key=request.operation_key,
        worker_id=request.worker_id,
        fencing_token=request.fencing_token,
        intent_lsn=request.intent_lsn,
        claim_lsn=request.claim_lsn,
        receipt_sequence=request.receipt_sequence,
        expires_at=request.expires_at,
    )


def _transition_response(result: Any) -> dict[str, Any]:
    return {
        "repository": result.repository,
        "task_id": result.task_id,
        "state": result.state,
        "receipt_sequence": result.receipt_sequence,
        "recovery_lsn": result.recovery_lsn,
        "operation_key": result.operation_key,
        "replayed": result.replayed,
    }


def _authority_object_response(result: Any) -> dict[str, Any]:
    return {
        "repository": result.repository,
        "object_kind": result.object_kind,
        "object_id": result.object_id,
        "state": result.state,
        "receipt_sequence": result.receipt_sequence,
        "recovery_lsn": result.recovery_lsn,
        "replayed": result.replayed,
    }


def _lease_response(lease: Lease) -> dict[str, Any]:
    return {
        "repository": lease.repository,
        "resource_id": lease.resource_id,
        "holder": lease.holder,
        "fencing_token": lease.fencing_token,
        "expires_at": lease.expires_at.isoformat(),
        "lease_kind": lease.lease_kind,
    }


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
    inquiry_write = _credential_dependency(credentials, rate_limiter, "inquiries:write")
    task_write = _credential_dependency(credentials, rate_limiter, "tasks:write")
    attempt_write = _credential_dependency(credentials, rate_limiter, "attempts:write")
    promotion_write = _credential_dependency(credentials, rate_limiter, "promotions:write")
    receipt_read = _credential_dependency(credentials, rate_limiter, "receipts:read")
    # The outbox/executor scope is the privileged capability a normal MacBook
    # client credential never holds; only the host-privileged executor is
    # granted it.
    outbox_write = _credential_dependency(credentials, rate_limiter, "outbox:write")

    async def require_authority_epoch(
        x_builderops_authority_epoch: str | None = Header(default=None),
    ) -> None:
        """Fence a client pinned to a superseded authority epoch (fail closed).

        The header is optional so read-only probes and legacy callers still
        work, but a client that pins an epoch is rejected when a recovery epoch
        has advanced past it, rather than silently mutating the new authority.
        """
        if x_builderops_authority_epoch is None:
            return
        try:
            pinned = int(x_builderops_authority_epoch)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid authority epoch header",
            ) from exc
        try:
            readiness = await run_in_threadpool(store.readiness)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="BuilderOps store unavailable",
            ) from exc
        if pinned != readiness.get("authority_epoch"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=STALE_AUTHORITY_EPOCH_DETAIL,
            )

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
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
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
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
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
        return _authority_object_response(result)

    @application.post("/v1/inquiries")
    async def commit_inquiry(
        request: InquiryCommitRequest,
        credential: Credential = Depends(inquiry_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            result = await run_in_threadpool(
                store.commit_record,
                envelope=_envelope(request.envelope, credential),
                record_id=request.inquiry_id,
                record_type="ModelInquiry",
                state=request.state,
                payload=request.payload,
                idempotency_key=request.idempotency_key,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return _authority_object_response(result)

    @application.post("/v1/tasks/claim")
    async def claim_task(
        request: TaskClaimRequest,
        credential: Credential = Depends(task_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            result, lease = await run_in_threadpool(
                store.claim_task,
                envelope=_envelope(request.envelope, credential),
                task_id=request.task_id,
                holder=credential.principal,
                idempotency_key=request.idempotency_key,
                request=request.request,
                ttl_seconds=request.ttl_seconds,
                require_new_fence=request.require_new_fence,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {"result": _transition_response(result), "lease": _lease_response(lease)}

    @application.get("/v1/tasks/{task_id}")
    async def read_task(
        task_id: str,
        repository: str,
        credential: Credential = Depends(receipt_read),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, repository)
        try:
            row = await run_in_threadpool(
                store.get_task, canonical_repository(repository), task_id
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="task not found"
            ) from exc
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return dict(row)

    @application.get("/v1/tasks")
    async def list_tasks(
        repository: str,
        task_prefix: str | None = None,
        credential: Credential = Depends(receipt_read),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, repository)
        try:
            rows = await run_in_threadpool(
                store.list_tasks,
                canonical_repository(repository),
                task_prefix=task_prefix,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {"tasks": [dict(row) for row in rows]}

    @application.post("/v1/tasks/heartbeat")
    async def heartbeat_task(
        request: TaskHeartbeatRequest,
        credential: Credential = Depends(task_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            envelope = _envelope(request.envelope, credential)
            result, lease = await run_in_threadpool(
                store.heartbeat_lease,
                envelope=envelope,
                lease=_lease_from_input(
                    envelope.repository, request.lease, credential
                ),
                idempotency_key=request.idempotency_key,
                request=request.request,
                ttl_seconds=request.ttl_seconds,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {"result": _transition_response(result), "lease": _lease_response(lease)}

    @application.post("/v1/tasks/release")
    async def release_task(
        request: TaskReleaseRequest,
        credential: Credential = Depends(task_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            envelope = _envelope(request.envelope, credential)
            result = await run_in_threadpool(
                store.release_task,
                envelope=envelope,
                lease=_lease_from_input(
                    envelope.repository, request.lease, credential
                ),
                expected_version=request.expected_version,
                idempotency_key=request.idempotency_key,
                request=request.request,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {"result": _transition_response(result)}

    @application.post("/v1/tasks/transition")
    async def transition_task(
        request: TaskTransitionRequest,
        credential: Credential = Depends(task_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            if request.lease is None:
                if (
                    request.to_state != "ready"
                    or request.outbox is not None
                    or request.expected_states is not None
                    or request.expected_version is not None
                ):
                    raise StateConflict(
                        "unleased task transition is restricted to initial ready creation"
                    )
            elif (
                request.to_state != "claimed"
                or request.expected_states != ["claimed"]
                or request.expected_version is None
            ):
                raise StateConflict(
                    "leased generic transition must retain claimed state with "
                    "exact state and version guards"
                )
            envelope = _envelope(request.envelope, credential)
            result = await run_in_threadpool(
                store.commit_transition,
                envelope=envelope,
                task_id=request.task_id,
                to_state=request.to_state,
                idempotency_key=request.idempotency_key,
                request=request.request,
                outbox=request.outbox,
                lease=(
                    _lease_from_input(
                        envelope.repository, request.lease, credential
                    )
                    if request.lease is not None
                    else None
                ),
                expected_states=(
                    tuple(request.expected_states)
                    if request.expected_states is not None
                    else None
                ),
                expected_version=request.expected_version,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {"result": _transition_response(result)}

    @application.post("/v1/tasks/complete")
    async def complete_task(
        request: TaskCompleteRequest,
        credential: Credential = Depends(task_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            envelope = _envelope(request.envelope, credential)
            result = await run_in_threadpool(
                store.complete_task,
                envelope=envelope,
                lease=_lease_from_input(
                    envelope.repository, request.lease, credential
                ),
                expected_version=request.expected_version,
                idempotency_key=request.idempotency_key,
                request=request.request,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {"result": _transition_response(result)}

    @application.post("/v1/attempts")
    async def commit_attempt(
        request: AttemptCommitRequest,
        credential: Credential = Depends(attempt_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            envelope = _envelope(request.envelope, credential)
            result = await run_in_threadpool(
                store.commit_attempt,
                envelope=envelope,
                task_id=request.task_id,
                attempt_id=request.attempt_id,
                state=request.state,
                payload=request.payload,
                idempotency_key=request.idempotency_key,
                lease=_lease_from_input(
                    envelope.repository, request.lease, credential
                ),
                expected_states=(
                    tuple(request.expected_states)
                    if request.expected_states is not None
                    else None
                ),
                expected_task_version=request.expected_task_version,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return _authority_object_response(result)

    @application.get("/v1/tasks/{task_id}/attempts")
    async def list_attempts(
        task_id: str,
        repository: str,
        credential: Credential = Depends(receipt_read),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, repository)
        try:
            rows = await run_in_threadpool(
                store.list_attempts, canonical_repository(repository), task_id
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {"attempts": [dict(row) for row in rows]}

    @application.post("/v1/promotions")
    async def commit_promotion(
        request: PromotionCommitRequest,
        credential: Credential = Depends(promotion_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            envelope = _envelope(request.envelope, credential)
            result = await run_in_threadpool(
                store.commit_promotion,
                envelope=envelope,
                promotion_id=request.promotion_id,
                status=request.status,
                payload=request.payload,
                idempotency_key=request.idempotency_key,
                lease=(
                    _lease_from_input(
                        envelope.repository, request.lease, credential
                    )
                    if request.lease is not None
                    else None
                ),
                expected_states=(
                    tuple(request.expected_states)
                    if request.expected_states is not None
                    else None
                ),
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return _authority_object_response(result)

    @application.get("/v1/status")
    async def authority_status(
        _credential: Credential = Depends(status_read),
    ) -> dict[str, Any]:
        try:
            readiness = await run_in_threadpool(store.readiness)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="BuilderOps store unavailable",
            ) from exc
        return {
            "authority_epoch": readiness.get("authority_epoch"),
            "schema_version": readiness.get("schema_version"),
        }

    @application.get("/v1/receipts/{object_kind}/{object_id}")
    async def read_receipt(
        object_kind: str,
        object_id: str,
        repository: str,
        task_id: str | None = None,
        credential: Credential = Depends(receipt_read),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, repository)
        canonical = canonical_repository(repository)
        try:
            if object_kind == "records":
                receipt = await run_in_threadpool(store.get_record, canonical, object_id)
            elif object_kind == "promotions":
                receipt = await run_in_threadpool(store.get_promotion, canonical, object_id)
            elif object_kind == "attempts":
                if not task_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="attempt receipts require task_id",
                    )
                receipt = await run_in_threadpool(
                    store.get_attempt, canonical, task_id, object_id
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="unknown receipt object kind",
                )
        except HTTPException:
            raise
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="receipt not found"
            ) from exc
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return dict(receipt)

    @application.post("/v1/executor/outbox/claim")
    async def claim_outbox(
        request: OutboxClaimRequest,
        credential: Credential = Depends(outbox_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            claim = await run_in_threadpool(
                store.claim_outbox,
                envelope=_envelope(request.envelope, credential),
                operation_key=request.operation_key,
                worker_id=request.worker_id,
                claim_ttl_seconds=request.claim_ttl_seconds,
            )
            intent = await run_in_threadpool(
                store.outbox_intent,
                request.envelope.repository,
                claim.operation_key,
            )
            eligible = await run_in_threadpool(store.effect_eligible, claim)
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {
            "repository": claim.repository,
            "operation_key": claim.operation_key,
            "worker_id": claim.worker_id,
            "fencing_token": claim.fencing_token,
            "intent_lsn": claim.intent_lsn,
            "claim_lsn": claim.claim_lsn,
            "receipt_sequence": claim.receipt_sequence,
            "expires_at": claim.expires_at.isoformat(),
            "task_id": intent["task_id"],
            "effect_type": intent["effect_type"],
            "payload": intent["payload"],
            "effect_eligible": eligible,
        }

    @application.post("/v1/executor/outbox/unknown")
    async def mark_outbox_unknown(
        request: OutboxUnknownRequest,
        credential: Credential = Depends(outbox_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            claim = _outbox_claim_from_input(
                request.claim, repository=request.envelope.repository
            )
            intent = await run_in_threadpool(
                store.outbox_intent,
                request.envelope.repository,
                claim.operation_key,
            )
            _enforce_outbox_principal(intent, credential)
            await run_in_threadpool(
                store.mark_effect_unknown,
                claim,
                detail=request.detail,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {"status": "unknown"}

    @application.post("/v1/executor/outbox/recover")
    async def recover_outbox(
        request: OutboxRecoverRequest,
        credential: Credential = Depends(outbox_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(
                request.model_dump(mode="json"), credentials
            )
            intent = await run_in_threadpool(
                store.outbox_intent,
                request.envelope.repository,
                request.operation_key,
            )
            _enforce_outbox_principal(intent, credential)
            claim = await run_in_threadpool(
                store.outbox_claim,
                envelope=_envelope(request.envelope, credential),
                operation_key=request.operation_key,
                worker_id=request.worker_id,
                claim_ttl_seconds=request.claim_ttl_seconds,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {
            "repository": claim.repository,
            "operation_key": claim.operation_key,
            "worker_id": claim.worker_id,
            "fencing_token": claim.fencing_token,
            "intent_lsn": claim.intent_lsn,
            "claim_lsn": claim.claim_lsn,
            "receipt_sequence": claim.receipt_sequence,
            "expires_at": claim.expires_at.isoformat(),
            "task_id": intent["task_id"],
            "effect_type": intent["effect_type"],
            "payload": intent["payload"],
        }

    @application.get("/v1/executor/outbox/{operation_key}")
    async def read_outbox_status(
        operation_key: str,
        repository: str,
        credential: Credential = Depends(outbox_write),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, repository)
        try:
            canonical = canonical_repository(repository)
            outbox_status = await run_in_threadpool(
                store.outbox_status, canonical, operation_key
            )
            intent = await run_in_threadpool(
                store.outbox_intent, canonical, operation_key
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="outbox intent not found",
            ) from exc
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {
            "repository": canonical,
            "operation_key": operation_key,
            "status": outbox_status,
            "task_id": intent["task_id"],
            "effect_type": intent["effect_type"],
            "payload": intent["payload"],
            "reconciliation_evidence": intent.get("reconciliation_evidence"),
            "reconciliation_receipt_sequence": intent.get(
                "reconciliation_receipt_sequence"
            ),
        }

    @application.post("/v1/executor/outbox/reconcile")
    async def reconcile_outbox(
        request: OutboxReconcileRequest,
        credential: Credential = Depends(outbox_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            claim = _outbox_claim_from_input(
                request.claim, repository=request.envelope.repository
            )
            intent = await run_in_threadpool(
                store.outbox_intent,
                request.envelope.repository,
                claim.operation_key,
            )
            _enforce_outbox_principal(intent, credential)
            result = await run_in_threadpool(
                store.reconcile_outbox,
                claim,
                observed_applied=request.observed_applied,
                terminal_unknown=request.terminal_unknown,
                evidence=request.evidence,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {
            "repository": result.repository,
            "operation_key": result.operation_key,
            "task_id": result.task_id,
            "status": result.status,
            "worker_id": result.worker_id,
            "fencing_token": result.fencing_token,
            "claim_receipt_sequence": result.claim_receipt_sequence,
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
