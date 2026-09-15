"""Independent FastAPI entrypoint for the BuilderOps control plane."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from collections.abc import Mapping
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from app.builderops.control_plane.api_models import (
    AttemptCommitRequest,
    InquiryCommitRequest,
    InquiryCommandPreviewRequest,
    InquiryCommandStartRequest,
    InquiryCommandAuthorityRequest,
    IssueDeliveryAuthorityRequest,
    IssueDeliveryOperationRecordRequest,
    IssueDeliveryPreviewRequest,
    IssueDeliveryStartRequest,
    LeaseClaimRequest,
    LeaseInput,
    OutboxClaimRequest,
    OutboxRecoverRequest,
    OutboxReconcileRequest,
    OutboxUnknownRequest,
    PromotionCommitRequest,
    RecordCommitRequest,
    OwnerOutcomeCommitRequest,
    OwnerAskCommitRequest,
    TaskClaimRequest,
    TaskCompleteRequest,
    TaskHeartbeatRequest,
    TaskReleaseRequest,
    TaskTransitionRequest,
    RowDerivedPostEffectPendingRequest,
    RowDerivedPostEffectReconcileRequest,
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
from app.builderops.control_plane.store import (
    _issue_delivery_admission_capability,
    _ISSUE_DELIVERY_OPERATION_RECORD_TYPE,
    _issue_delivery_operation_capability,
)
from app.middleware.trace import TraceIdMiddleware
from app.builderops.devui_conversation_port import canonical_context_pack_bytes, validate_context_pack_bytes
from app.builderops.devui_model_inquiry_command import approval_manifest, build_command_proposal, canonical_hash, validate_approval_identity, validate_command_proposal
from app.builderops.devui_sources import load_source_configuration, revalidate_inquiry_sources
from app.builderops.model_inquiry_workflow import SanctionedModelInquiryWorkflow, WorkflowUnavailable
from app.builderops.owner_fact_producers import (
    CONTRACT as OWNER_OUTCOME_CONTRACT, OwnerFactRefusal,
    OwnerOutcomeAdmission, outcome_record_id, outcome_request_hash, read_owner_binding,
    read_owner_profiles, strict_json, validate_current_binding, validate_outcome_request,
)
from app.builderops.models import normalize_record
from app.builderops.control_plane.issue_delivery import (
    CONTRACT_VERSION as ISSUE_DELIVERY_CONTRACT,
    IssueDeliveryContractError,
    OPERATION_TYPE as ISSUE_DELIVERY_OPERATION,
    approval_digest as issue_delivery_approval_digest,
    RECORD_TYPE as ISSUE_DELIVERY_RECORD_TYPE,
    assert_no_credential_fingerprint_fields,
    idempotency_key as issue_delivery_idempotency_key,
    manifest_hash as issue_delivery_manifest_hash,
    normalize_manifest as normalize_issue_delivery_manifest,
    receipt_ref as issue_delivery_receipt_ref,
    record_id as issue_delivery_record_id,
)

bearer = HTTPBearer(auto_error=False)
INQUIRY_CANDIDATE_ROOT = Path(__file__).resolve().parents[3] / "devui-candidate"

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
        {("lease", "fencing_token"), ("claim", "fencing_token"), ("minimum_fencing_token",)}
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
_ROW_DERIVED_FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "claim_lsn",
        "intent_lsn",
        "claim_receipt_sequence",
        "claim_fencing_token",
        "fencing_token",
        "worker_id",
        "claim_expires_at",
        "expires_at",
        "receipt_sequence",
        "recovery_lsn",
        "authority_envelope",
        "claim",
        "intent",
        "worker",
        "receipt",
        "fence",
    }
)
_ROW_DERIVED_AUTHORITY_TOKENS = (
    "claim",
    "intent",
    "worker",
    "receipt",
    "fence",
    "lsn",
    "expires_at",
    "authority_envelope",
)


def _contains_postgres_lsn_literal(value: str) -> bool:
    """Detect a bounded hexadecimal LSN without a backtracking regex."""

    hexadecimal = frozenset("0123456789abcdefABCDEF")
    for slash_index, character in enumerate(value):
        if character != "/" or slash_index == 0 or slash_index == len(value) - 1:
            continue
        left = slash_index - 1
        while left >= 0 and value[left] in hexadecimal:
            left -= 1
        right = slash_index + 1
        while right < len(value) and value[right] in hexadecimal:
            right += 1
        if left < slash_index - 1 and right > slash_index + 1:
            return True
    return False


def _canonical_durable_key(key: str) -> str:
    """Normalize common structured-key spellings before secret classification."""

    source = key.strip()
    normalized: list[str] = []
    for index, character in enumerate(source):
        if not character.isascii() or not character.isalnum():
            if normalized and normalized[-1] != "_":
                normalized.append("_")
            continue
        previous = source[index - 1] if index else ""
        following = source[index + 1] if index + 1 < len(source) else ""
        if character.isupper() and normalized and (
            previous.islower()
            or previous.isdigit()
            or (previous.isupper() and following.islower())
        ) and normalized[-1] != "_":
            normalized.append("_")
        normalized.append(character)
    return "".join(normalized).strip("_").lower()


def _row_derived_evidence_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return "".join(
            f"{key}{_row_derived_evidence_text(item)}"
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return "".join(_row_derived_evidence_text(item) for item in value)
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return ""


def _assert_row_derived_evidence_safe(value: Any) -> None:
    """Keep caller evidence from becoming dormant claim or LSN authority."""
    evidence_text = _row_derived_evidence_text(value)
    normalized_text = evidence_text.casefold().replace("-", "_").replace(" ", "_")
    if _contains_postgres_lsn_literal(evidence_text) or any(
        token in normalized_text for token in _ROW_DERIVED_AUTHORITY_TOKENS
    ):
        raise ValueError("row-derived reconciliation evidence cannot contain claim authority")
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _canonical_durable_key(str(key))
            if (
                normalized in _ROW_DERIVED_FORBIDDEN_EVIDENCE_KEYS
                or normalized.replace("_", "")
                in {item.replace("_", "") for item in _ROW_DERIVED_FORBIDDEN_EVIDENCE_KEYS}
                or any(
                    fragment in normalized.split("_")
                    for fragment in _ROW_DERIVED_FORBIDDEN_EVIDENCE_KEYS
                )
            ):
                raise ValueError("row-derived reconciliation evidence cannot contain claim authority")
            _assert_row_derived_evidence_safe(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_row_derived_evidence_safe(child)
    elif isinstance(value, str) and _contains_postgres_lsn_literal(value):
        raise ValueError("row-derived reconciliation evidence cannot contain durability LSNs")


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
    if request.scope in {"owner-outcome", "owner-ask"}:
        raise OwnerFactRefusal("owner_fact_scope_requires_source_admission", 403)
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
    if not _path and not key and isinstance(value, Mapping):
        operation_key = value.get("idempotency_key")
        if isinstance(operation_key, str) and operation_key.startswith(("owner-outcome:", "owner-ask:")):
            raise OwnerFactRefusal("owner_fact_key_requires_source_admission", 403)
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
    if isinstance(exc, OwnerFactRefusal):
        return HTTPException(status_code=exc.status, detail=exc.code)
    if isinstance(exc, WorkflowUnavailable):
        return HTTPException(status_code=503, detail="workflow_unavailable")
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
    issue_delivery_admission = _issue_delivery_admission_capability()
    health_service = health or HealthService(
        store,
        credentials,
        LiveOperationalStatusProvider(
            store,
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
    record_access = _credential_dependency(credentials, rate_limiter)
    inquiry_write = _credential_dependency(credentials, rate_limiter, "inquiries:write")
    inquiry_approve = _credential_dependency(credentials, rate_limiter, "inquiries:approve")
    inquiry_read = _credential_dependency(credentials, rate_limiter, "inquiries:read")
    inquiry_control = _credential_dependency(credentials, rate_limiter)
    issue_delivery_owner = _credential_dependency(
        credentials, rate_limiter, "issue_delivery:approve"
    )
    issue_delivery_read_scope = _credential_dependency(
        credentials, rate_limiter, "issue_delivery:read"
    )
    issue_delivery_execute = _credential_dependency(
        credentials, rate_limiter, "issue_delivery:execute"
    )
    issue_delivery_control = _credential_dependency(credentials, rate_limiter)
    # The actual production constructor has this complete concrete path. No
    # caller-supplied executor or no-op production port is accepted.
    inquiry_workflow = SanctionedModelInquiryWorkflow()
    task_write = _credential_dependency(credentials, rate_limiter, "tasks:write")
    attempt_write = _credential_dependency(credentials, rate_limiter, "attempts:write")
    promotion_write = _credential_dependency(credentials, rate_limiter, "promotions:write")
    receipt_read = _credential_dependency(credentials, rate_limiter, "receipts:read")
    # The outbox/executor scope is the privileged capability a normal MacBook
    # client credential never holds; only the host-privileged executor is
    # granted it.
    outbox_write = _credential_dependency(credentials, rate_limiter, "outbox:write")

    def current_sources(repository: str, pack: dict[str, Any]) -> dict[str, Any]:
        validate_context_pack_bytes(canonical_context_pack_bytes(pack), now=datetime.now(timezone.utc))
        # Reuse only the managed read configuration; database/host credentials
        # are not transported into a source reader or a command manifest.
        keys = ("DEVUI_REPOSITORY", "DEVUI_GITHUB_ENABLED", "GH_CONFIG_DIR", "GH_HOST")
        config = load_source_configuration({key: os.environ[key] for key in keys if key in os.environ}, candidate_root=INQUIRY_CANDIDATE_ROOT, source_sha=os.getenv("VCS_REF", "unknown"))
        return revalidate_inquiry_sources(config, repository=repository, context_pack=pack)

    def permission(credential: Credential) -> dict[str, Any]:
        return {
            "owner_principal": credential.principal,
            "permission_ref": f"credential:{credential.credential_id}",
            "permission_version": canonical_hash({"principal": credential.principal, "generation": credential.rotation_generation, "scopes": sorted(credential.scopes), "repositories": sorted(credential.repositories), "all_repositories": credential.all_repositories, "fingerprint": credential.fingerprint}),
            "authority_epoch": store.readiness()["authority_epoch"],
        }

    def current_material(material: dict[str, Any], *, check_workflow: bool) -> dict[str, Any]:
        current = {**material, **current_sources(material["repository"], material["context_pack"])}
        if check_workflow:
            current.update(inquiry_workflow.current_bindings())
        return current

    def exact_approval(repository: str, approval_id: str) -> dict[str, Any]:
        row = store.get_record(repository, "inquiry-approval:" + approval_id)
        approval = validate_approval_identity(row["payload"])
        envelope = row["authority_envelope"]
        if row["record_type"] != "ModelInquiryApproval" or row["state"] != "approved" or approval["proposal"]["repository"] != repository or approval["approval_id"] != approval_id or envelope["actor"] != approval["owner_principal"] or envelope["scope"] != "model-inquiry-approval":
            raise ValueError("exact service-owned inquiry approval required")
        return approval

    def issue_delivery_permission(credential: Credential, repository: str) -> dict[str, Any]:
        """Resolve the current, repository-scoped Issue approval grant."""

        if credential.principal_kind != "human" or not credentials.has_issue_delivery_approval_grant(
            repository, credential.principal
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="exact Issue-delivery owner grant required",
            )
        # Bind approval validity to public credential metadata only.  The
        # registry's bearer verifier is deliberately not part of the durable
        # permission or any Issue-delivery readback, where it would enable
        # offline guessing by a read-scoped client.
        permission = {
            "grant": "issue_delivery:approve",
            "credential_id": credential.credential_id,
            "principal": credential.principal,
            "rotation_generation": credential.rotation_generation,
            "scopes": sorted(credential.scopes),
            "repositories": sorted(credential.repositories),
            "all_repositories": credential.all_repositories,
        }
        permission["permission_version"] = canonical_hash(permission)
        return permission

    def _assert_issue_delivery_permission_safe(permission: Any) -> None:
        """Reject legacy or malformed approvals that would expose a verifier."""

        if isinstance(permission, Mapping) and "fingerprint" in permission:
            raise StateConflict("Issue-delivery approval contains a credential verifier")

    def _assert_issue_delivery_approval_integrity(payload: Mapping[str, Any]) -> None:
        """Authenticate the durable approval, including its grant timestamp."""

        assert_no_credential_fingerprint_fields(payload)
        if payload.get("approval_manifest_hash") != issue_delivery_manifest_hash(payload):
            raise StateConflict("Issue-delivery approval manifest is corrupt")
        if payload.get("approval_digest") != issue_delivery_approval_digest(payload):
            raise StateConflict("Issue-delivery approval digest is corrupt")

    def issue_delivery_manifest(
        manifest_input: Mapping[str, Any], credential: Credential
    ) -> dict[str, Any]:
        """Build one exact preview and bind only service-owned authority fields."""

        assert_no_credential_fingerprint_fields(manifest_input)
        if any(
            field in manifest_input
            for field in (
                "owner_principal",
                "permission",
                "authority_epoch",
                "approval_manifest_hash",
                "approval_receipt_ref",
                "approved_at",
                "state",
            )
        ):
            raise IssueDeliveryContractError("preview cannot supply service authority fields")
        normalized = normalize_issue_delivery_manifest(manifest_input)
        repository = normalized["repository"]
        _enforce_repo_scope(credential, repository)
        parent_evidence = normalized.get("parent_evidence")
        if isinstance(parent_evidence, Mapping) and parent_evidence.get("kind") == "issue":
            parent_repository = parent_evidence.get("repository")
            if not isinstance(parent_repository, str):
                raise IssueDeliveryContractError("parent evidence repository is required")
            _enforce_repo_scope(credential, parent_repository)
        permission = issue_delivery_permission(credential, repository)
        owner_profile = normalized.get("owner_profile")
        if isinstance(owner_profile, Mapping):
            profile_principal = owner_profile.get("principal", owner_profile.get("owner_principal"))
            if profile_principal is not None and profile_principal != credential.principal:
                raise HTTPException(status_code=403, detail="owner profile does not match authenticated owner")
        normalized.update(
            {
                "owner_principal": credential.principal,
                "permission": permission,
                "authority_epoch": int(store.readiness()["authority_epoch"]),
                "approval_receipt_ref": issue_delivery_receipt_ref(
                    repository, normalized["approval_id"]
                ),
                "previewed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        normalized["approval_manifest_hash"] = issue_delivery_manifest_hash(normalized)
        return normalized

    def validate_issue_delivery_approval(
        manifest_input: Mapping[str, Any], credential: Credential
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Validate an immutable preview and fresh current authority."""

        assert_no_credential_fingerprint_fields(manifest_input)
        supplied_hash = manifest_input.get("approval_manifest_hash")
        if not isinstance(supplied_hash, str) or supplied_hash != issue_delivery_manifest_hash(manifest_input):
            raise StateConflict("Issue-delivery approval manifest changed")
        # Start must re-check every addressed repository even when the caller
        # skips preview.  Do this after immutable-hash admission but before
        # contract normalization so a well-formed foreign parent is reported
        # as a typed scope denial rather than being downgraded to a generic
        # protocol rejection by a later validation branch.
        parent_evidence = manifest_input.get("parent_evidence")
        if isinstance(parent_evidence, Mapping) and parent_evidence.get("kind") == "issue":
            parent_repository = parent_evidence.get(
                "repository", parent_evidence.get("parent_repository")
            )
            if isinstance(parent_repository, str) and parent_repository.strip():
                _enforce_repo_scope(credential, canonical_repository(parent_repository.strip()))
        # Authenticate the owner profile before deeper contract normalization.
        # A caller cannot turn a foreign owner into a generic 400 by also
        # changing a dependent profile hash; identity remains a typed scope
        # decision on every Start path.
        raw_owner_profile = manifest_input.get("owner_profile")
        if isinstance(raw_owner_profile, Mapping):
            raw_profile_principal = raw_owner_profile.get(
                "principal", raw_owner_profile.get("owner_principal")
            )
            if isinstance(raw_profile_principal, str) and raw_profile_principal != credential.principal:
                raise HTTPException(
                    status_code=403,
                    detail="owner profile does not match authenticated owner",
                )
        manifest = normalize_issue_delivery_manifest(manifest_input)
        if issue_delivery_manifest_hash(manifest) != supplied_hash:
            raise StateConflict(
                "Issue-delivery approval hash changed during normalization"
            )
        if manifest.get("owner_principal") != credential.principal:
            raise HTTPException(status_code=403, detail="Issue-delivery approval owner mismatch")
        owner_profile = manifest.get("owner_profile")
        if (
            not isinstance(owner_profile, Mapping)
            or owner_profile.get("principal") != credential.principal
        ):
            raise HTTPException(status_code=403, detail="owner profile does not match authenticated owner")
        repository = manifest["repository"]
        expected_receipt_ref = issue_delivery_receipt_ref(
            repository, manifest["approval_id"]
        )
        if manifest.get("approval_receipt_ref") != expected_receipt_ref:
            raise StateConflict("Issue-delivery approval receipt reference is not service-owned")
        _enforce_repo_scope(credential, repository)
        parent_evidence = manifest.get("parent_evidence")
        if isinstance(parent_evidence, Mapping) and parent_evidence.get("kind") == "issue":
            parent_repository = parent_evidence.get("repository")
            if not isinstance(parent_repository, str):
                raise IssueDeliveryContractError("parent evidence repository is required")
            _enforce_repo_scope(credential, parent_repository)
        permission = issue_delivery_permission(credential, repository)
        if manifest.get("permission") != permission:
            raise StateConflict("Issue-delivery approval permission was revoked or rotated")
        readiness = store.readiness()
        if manifest.get("authority_epoch") != readiness.get("authority_epoch"):
            raise StateConflict("Issue-delivery approval authority epoch is stale")
        try:
            expiry = datetime.fromisoformat(str(manifest["expires_at"]))
        except (TypeError, ValueError) as exc:
            raise StateConflict("Issue-delivery approval expiry is invalid") from exc
        if expiry <= datetime.now(timezone.utc):
            raise StateConflict("Issue-delivery approval has expired")
        return manifest, permission

    def issue_delivery_existing_by_operation(
        repository: str, operation_key: str
    ) -> Mapping[str, Any] | None:
        getter = getattr(store, "get_issue_delivery_by_operation_key", None)
        if callable(getter):
            return getter(repository, operation_key)
        return None

    def issue_delivery_approval_payload(
        manifest: Mapping[str, Any], *, approved_at: str
    ) -> dict[str, Any]:
        payload = {
            **dict(manifest),
            "contract": ISSUE_DELIVERY_CONTRACT,
            "state": "approved",
            "approved_at": approved_at,
            "approval_receipt_ref": manifest["approval_receipt_ref"],
        }
        payload["approval_digest"] = issue_delivery_approval_digest(payload)
        return payload

    def issue_delivery_readback(repository: str, approval_id: str) -> dict[str, Any]:
        canonical = canonical_repository(repository)
        row = store.get_record(canonical, issue_delivery_record_id(approval_id))
        if row.get("record_type") != ISSUE_DELIVERY_RECORD_TYPE:
            raise StateConflict("record is not an Issue-delivery approval")
        if row.get("state") != "approved":
            raise StateConflict("Issue-delivery approval is not approved")
        payload = dict(row["payload"])
        _assert_issue_delivery_approval_integrity(payload)
        permission = payload.get("permission")
        _assert_issue_delivery_permission_safe(permission)
        operation_key = payload.get("operation_key")
        if not isinstance(operation_key, str):
            raise StateConflict("Issue-delivery approval operation key is missing")
        state = "approved"
        reason: str | None = None
        try:
            credential_id = permission.get("credential_id") if isinstance(permission, Mapping) else None
            current = credentials.current_credential(credential_id) if isinstance(credential_id, str) else None
            current_permission = issue_delivery_permission(current, canonical) if current is not None else None
            if (
                current is None
                or current.principal != payload.get("owner_principal")
                or current_permission != permission
                or not credentials.has_issue_delivery_approval_grant(canonical, payload.get("owner_principal", ""))
            ):
                state, reason = "invalidated", "permission_revoked_or_unavailable"
            else:
                expiry = datetime.fromisoformat(str(payload["expires_at"]))
                if expiry <= datetime.now(timezone.utc):
                    state, reason = "invalidated", "expired"
                elif payload.get("authority_epoch") != store.readiness().get("authority_epoch"):
                    state, reason = "invalidated", "authority_epoch_changed"
        except Exception:
            state, reason = "invalidated", "current_authority_unavailable"
        replay = store.replay(canonical, issue_delivery_idempotency_key(operation_key))
        return {
            "contract_version": ISSUE_DELIVERY_CONTRACT,
            "operation_type": ISSUE_DELIVERY_OPERATION,
            "approval_id": payload.get("approval_id", approval_id),
            "state": state,
            "invalidation_reason": reason,
            "manifest": payload,
            "approval": payload,
            "operation": {
                "operation_key": operation_key,
                "repository": canonical,
                "issue_number": payload.get("issue", {}).get("number") if isinstance(payload.get("issue"), Mapping) else None,
                "workflow": payload.get("workflow"),
                "destination": payload.get("destination"),
            },
            "receipt": {
                "id": payload.get("approval_receipt_ref"),
                "receipt_sequence": getattr(replay, "receipt_sequence", None),
                "approval_manifest_hash": payload.get("approval_manifest_hash"),
            },
            "replayed": bool(getattr(replay, "replayed", False)),
            "stop_support": "unsupported",
            "effects": [],
        }

    def command_preview(request: InquiryCommandPreviewRequest, credential: Credential) -> dict[str, Any]:
        _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
        repo = canonical_repository(request.repository)
        material = {"repository": repo, "question": request.question, "context_pack": request.context_pack, **current_sources(repo, request.context_pack), **inquiry_workflow.current_bindings()}
        proposal = build_command_proposal(approval_id=request.approval_id, material=material, **permission(credential), now=datetime.now(timezone.utc), expires_at=request.expires_at)
        approval_manifest(proposal, material, approved_at=datetime.now(timezone.utc))
        return {"proposal": proposal, "material": material, "choices": ["start", "hold"], "state": "preview"}

    def publish_owner_ask(request: OwnerAskCommitRequest, credential: Credential) -> dict[str, Any]:
        if not {"records:write", "inquiries:approve"}.issubset(credential.scopes):
            raise OwnerFactRefusal("owner_ask_not_authorized", 403)
        supplied = request.owner_ask
        if set(supplied) != {"proposal", "material"}:
            raise OwnerFactRefusal("invalid_owner_ask")
        _assert_durable_payload_safe(supplied, credentials)
        proposal, material = supplied["proposal"], supplied["material"]
        repo = canonical_repository(proposal["repository"])
        _enforce_repo_scope(credential, repo)
        exact = validate_command_proposal(proposal, current_material=current_material(material, check_workflow=True), **permission(credential), now=datetime.now(timezone.utc))
        record_id = "owner-ask:" + exact["proposal_hash"]
        body = {"contract": "builder_owner_ask.v1", "proposal": exact, "material": material, "choices": ["start", "hold"], "authority_class": "bounded_action_confirmation"}
        try:
            existing = store.get_record(repo, record_id)
        except KeyError:
            stamp = datetime.now(timezone.utc).isoformat()
            payload = normalize_record({"id": record_id, "object_type": "BuilderOpsReceipt", "lifecycle_state": "active",
                "authority_class": "receipt", "promotion_status": "not_promotable", "created_at": stamp, "updated_at": stamp,
                "created_by": {"actor_type": "service", "id": "builderops-control-plane"},
                "actor": {"actor_type": "service", "id": credential.principal}, "occurred_at": stamp,
                "source_refs": [{"ref_type": "proposal", "ref": exact["proposal_hash"], "authority_surface": "builderops"}],
                "target_refs": [{"ref_type": "subject", "ref": exact["subject_ref"]["stable_id"], "authority_surface": "github"}],
                "summary": "Exact owner action proposal published", "event_type": "owner_ask_published", "action": "publish_owner_ask",
                "receipt_body": body, "idempotency_key": record_id, "outcome": "succeeded"})
            try:
                store.commit_record(envelope=AuthorityEnvelope(repository=repo, scope="owner-ask", stack="builderops-control-plane", actor=credential.principal, source_refs=(exact["proposal_hash"],)), record_id=record_id, record_type="BuilderOpsReceipt", state="active", payload=payload, idempotency_key=record_id)
            except (IdempotencyConflict, StateConflict, LeaseRequired):
                pass
            existing = store.get_record(repo, record_id)
        if existing["payload"]["receipt_body"] != body or existing["authority_envelope"]["actor"] != credential.principal:
            raise OwnerFactRefusal("owner_ask_conflict", 409)
        return {"receipt": existing["payload"], "state": "published", "action_effects": []}

    def current_owner_asks(repository: str) -> list[dict[str, Any]]:
        asks = []
        for row in store.get_owner_asks(repository):
            payload = row["payload"]
            body = payload["receipt_body"]
            proposal, material = body["proposal"], body["material"]
            result = {"subject_ref": proposal["subject_ref"]["stable_id"], "receipt_id": payload["id"], "proposal_hash": proposal["proposal_hash"], "status": "withdrawn"}
            try:
                permission_ref = proposal["approval_rule"]["permission_ref"]
                if not permission_ref.startswith("credential:"):
                    raise ValueError
                owner = credentials.current_credential(permission_ref.removeprefix("credential:"))
                if owner is None or not {"records:write", "inquiries:approve"}.issubset(owner.scopes) or not owner.may_address(repository) or row["authority_envelope"]["scope"] != "owner-ask" or row["authority_envelope"]["actor"] != owner.principal:
                    raise ValueError
                validate_command_proposal(proposal, current_material=current_material(material, check_workflow=True), **permission(owner), now=datetime.now(timezone.utc))
                try:
                    exact_approval(repository, proposal["proposal_id"])
                except KeyError:
                    result.update(status="current", choices=body["choices"], authority_class=body["authority_class"],
                        proposal=proposal, observed_at=datetime.now(timezone.utc).isoformat())
            except Exception:
                result["reason"] = "source_or_permission_changed_or_unavailable"
            asks.append(result)
        return asks

    def command_start(request: InquiryCommandStartRequest, credential: Credential) -> dict[str, Any]:
        if request.decision == "hold":
            return {"state": "held", "effects": []}
        _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
        repo = request.proposal["repository"]
        _enforce_repo_scope(credential, repo)
        material = current_material(request.material, check_workflow=True)
        exact = validate_command_proposal(request.proposal, current_material=material, **permission(credential), now=datetime.now(timezone.utc))
        try:
            approved = exact_approval(repo, exact["proposal_id"])
        except KeyError:
            proposed = approval_manifest(exact, material, approved_at=datetime.now(timezone.utc))
            _assert_durable_payload_safe(proposed, credentials)
            try:
                store.commit_record(envelope=AuthorityEnvelope(repository=repo, scope="model-inquiry-approval", stack="builderops", actor=credential.principal, source_refs=(exact["context_pack_ref"]["content_hash"],)), record_id="inquiry-approval:" + exact["proposal_id"], record_type="ModelInquiryApproval", state="approved", payload=proposed, idempotency_key="inquiry-approval:" + exact["proposal_hash"])
            except (IdempotencyConflict, StateConflict, LeaseRequired):
                # A concurrent first writer may win with a different approval
                # timestamp. Only its exact immutable proposal can be reused.
                pass
            approved = exact_approval(repo, exact["proposal_id"])
        if approved["proposal"] != exact or approved["material"] != material or approved["owner_principal"] != credential.principal:
            raise StateConflict("inquiry approval already binds another proposal")
        return {"approval": approved, "operation": inquiry_workflow.start(approved)}

    def command_authority(request: InquiryCommandAuthorityRequest, credential: Credential) -> dict[str, Any]:
        _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
        supplied = validate_approval_identity(request.approval)
        repo = supplied["proposal"]["repository"]
        _enforce_repo_scope(credential, repo)
        required_scope = "inquiries:read" if request.purpose == "readback" else "inquiries:execute"
        if required_scope not in credential.scopes:
            raise HTTPException(status_code=403, detail="inquiry action permission required")
        approved = exact_approval(repo, supplied["approval_id"])
        if approved != supplied:
            raise StateConflict("inquiry approval manifest changed")
        epoch = store.readiness()["authority_epoch"]
        if request.purpose != "readback":
            permission_ref = approved["proposal"]["approval_rule"]["permission_ref"]
            if not permission_ref.startswith("credential:"):
                raise ValueError("current owner permission required")
            owner = credentials.current_credential(permission_ref.removeprefix("credential:"))
            if owner is None or "inquiries:approve" not in owner.scopes or not owner.may_address(repo):
                raise HTTPException(status_code=403, detail="inquiry owner approval was revoked")
            # Destination separately re-reads its actual configured profile;
            # querying it here would recurse through the same SSH invocation.
            validate_command_proposal(approved["proposal"], current_material=current_material(approved["material"], check_workflow=False), **permission(owner), now=datetime.now(timezone.utc))
        return {"approval": approved, "purpose": request.purpose, "authority_epoch": epoch, "observed_at": datetime.now(timezone.utc).isoformat()}

    @application.post("/v1/inquiries/command/preview")
    async def inquiry_command_preview(request: InquiryCommandPreviewRequest, credential: Credential = Depends(inquiry_approve)) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.repository)
        try:
            return await run_in_threadpool(command_preview, request, credential)
        except Exception as exc:
            raise _control_plane_error(exc) from exc

    @application.post("/v1/inquiries/command/start")
    async def inquiry_command_start(request: InquiryCommandStartRequest, credential: Credential = Depends(inquiry_approve)) -> dict[str, Any]:
        try:
            return await run_in_threadpool(command_start, request, credential)
        except HTTPException:
            raise
        except Exception as exc:
            raise _control_plane_error(exc) from exc

    @application.post("/v1/inquiries/command/authority")
    async def inquiry_command_authority(request: InquiryCommandAuthorityRequest, credential: Credential = Depends(inquiry_control)) -> dict[str, Any]:
        try:
            return await run_in_threadpool(command_authority, request, credential)
        except HTTPException:
            raise
        except Exception as exc:
            raise _control_plane_error(exc) from exc

    @application.get("/v1/inquiries/command/{approval_id}")
    async def inquiry_command_readback(approval_id: str, repository: str, credential: Credential = Depends(inquiry_read)) -> dict[str, Any]:
        _enforce_repo_scope(credential, repository)
        try:
            approved = await run_in_threadpool(exact_approval, canonical_repository(repository), approval_id)
            return await run_in_threadpool(inquiry_workflow.readback, approved)
        except Exception as exc:
            raise _control_plane_error(exc) from exc

    def issue_delivery_start_sync(
        request: IssueDeliveryStartRequest, credential: Credential
    ) -> dict[str, Any]:
        manifest, _permission = validate_issue_delivery_approval(request.manifest, credential)
        if request.decision == "hold":
            return {
                "contract_version": ISSUE_DELIVERY_CONTRACT,
                "operation_type": ISSUE_DELIVERY_OPERATION,
                "approval_id": manifest["approval_id"],
                "state": "held",
                "effects": [],
                "replayed": False,
            }
        repository = manifest["repository"]
        approval_id = manifest["approval_id"]
        key = issue_delivery_idempotency_key(manifest["operation_key"])
        record = issue_delivery_record_id(approval_id)

        def replay_existing(existing: Mapping[str, Any]) -> dict[str, Any]:
            existing_payload = existing.get("payload", {})
            if (
                existing.get("record_type") != ISSUE_DELIVERY_RECORD_TYPE
                or not isinstance(existing_payload, Mapping)
                or existing_payload.get("approval_manifest_hash")
                != manifest["approval_manifest_hash"]
                or existing_payload.get("operation_key") != manifest["operation_key"]
            ):
                raise StateConflict("Issue-delivery approval is immutable")
            _assert_issue_delivery_approval_integrity(existing_payload)
            _assert_issue_delivery_permission_safe(existing_payload.get("permission"))
            replay = store.replay(repository, key)
            if replay is None:
                raise ControlPlaneError("Issue-delivery approval replay is unavailable")
            payload = dict(existing_payload)
            return {
                "contract_version": ISSUE_DELIVERY_CONTRACT,
                "operation_type": ISSUE_DELIVERY_OPERATION,
                "approval_id": approval_id,
                "state": "approved",
                "approval": payload,
                "receipt": {
                    "id": payload.get("approval_receipt_ref"),
                    "receipt_sequence": replay.receipt_sequence,
                    "approval_manifest_hash": payload.get("approval_manifest_hash"),
                },
                "replayed": True,
                "effects": [],
            }

        try:
            existing = store.get_record(repository, record)
        except KeyError:
            existing = None
        if existing is not None:
            return replay_existing(existing)
        by_operation = issue_delivery_existing_by_operation(repository, manifest["operation_key"])
        if by_operation is not None:
            raise IdempotencyConflict("Issue-delivery operation key is already approved")
        approved_at = datetime.now(timezone.utc).isoformat()
        payload = issue_delivery_approval_payload(manifest, approved_at=approved_at)
        _assert_durable_payload_safe(payload, credentials)
        envelope = AuthorityEnvelope(
            repository=repository,
            scope="issue-delivery-approval",
            stack="builderops-control-plane",
            actor=credential.principal,
            source_refs=(
                f"github:issue:{manifest['issue']['number']}",
                f"source:{manifest['source']['revision']}",
                f"manifest:{manifest['approval_manifest_hash']}",
            ),
        )
        try:
            result = store.commit_record(
                envelope=envelope,
                record_id=record,
                record_type=ISSUE_DELIVERY_RECORD_TYPE,
                state="approved",
                payload=payload,
                idempotency_key=key,
                issue_delivery_admission=issue_delivery_admission,
            )
        except IdempotencyConflict as commit_conflict:
            # Two identical Starts can both pass the read-before-write checks.
            # The losing writer must project the winner's immutable approval as
            # a replay, not surface a false conflict to the owner.
            try:
                winner = store.get_record(repository, record)
            except KeyError as exc:
                if issue_delivery_existing_by_operation(repository, manifest["operation_key"]):
                    # A competing approval id won the operation-key race.  Keep
                    # the normal 409 conflict semantics instead of turning a
                    # timing-dependent collision into a generic 400 error.
                    raise commit_conflict
                raise ControlPlaneError(
                    "Issue-delivery approval commit raced without durable readback"
                ) from exc
            return replay_existing(winner)
        return {
            "contract_version": ISSUE_DELIVERY_CONTRACT,
            "operation_type": ISSUE_DELIVERY_OPERATION,
            "approval_id": approval_id,
            "state": "approved",
            "approval": payload,
            "receipt": {
                "id": payload["approval_receipt_ref"],
                "receipt_sequence": result.receipt_sequence,
                "recovery_lsn": result.recovery_lsn,
                "approval_manifest_hash": payload["approval_manifest_hash"],
            },
            "replayed": result.replayed,
            "effects": [],
        }

    def issue_delivery_operation_record_sync(
        request: IssueDeliveryOperationRecordRequest, credential: Credential
    ) -> dict[str, Any]:
        """Commit one exact destination reservation/attempt/entry receipt.

        This is intentionally a separate service path from generic record
        writes.  The approved manifest is loaded from the service-owned
        approval record and revalidated immediately before every destination
        write; a caller cannot turn a stale approval or worker-provided copy
        into launch authority.
        """

        def validate_operation_payload(
            *,
            kind: str,
            state: str,
            payload: Mapping[str, Any],
            approved: Mapping[str, Any],
            repository: str,
            operation_key: str,
            approval_id: str,
            approval_manifest_hash: str,
        ) -> None:
            common = {
                "schema",
                "repository",
                "operation_type",
                "operation_key",
                "approval_id",
                "approval_manifest_hash",
                "live_binding",
                "receipt_hash",
            }
            specific = {
                "reservation": {"destination", "proposed_run", "reserved_at"},
                "attempt": {"reservation_receipt_hash", "attempt_id", "attempted_at"},
                "entry": {"attempt_receipt_hash", "attempt_id", "session_id", "entered_at"},
                "terminal": {
                    "attempt_receipt_hash",
                    "entry_receipt_hash",
                    "session_id",
                    "worker_receipt",
                    "observed_at",
                },
            }
            if set(payload) != common | specific[kind]:
                raise IssueDeliveryContractError(
                    "Issue-delivery operation receipt fields are not closed"
                )
            if (
                payload["schema"] != f"builderops.issue-delivery-{kind}.v1"
                or payload["repository"] != repository
                or payload["operation_type"] != ISSUE_DELIVERY_OPERATION
                or payload["operation_key"] != operation_key
                or payload["approval_id"] != approval_id
                or payload["approval_manifest_hash"] != approval_manifest_hash
            ):
                raise IssueDeliveryContractError(
                    "Issue-delivery operation receipt binding is incomplete"
                )
            receipt_hash = payload["receipt_hash"]
            if (
                not isinstance(receipt_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", receipt_hash)
                or canonical_hash(
                    {key: value for key, value in payload.items() if key != "receipt_hash"}
                )
                != receipt_hash
            ):
                raise IssueDeliveryContractError(
                    "Issue-delivery operation receipt hash is invalid"
                )
            destination = approved.get("destination")
            workflow = approved.get("workflow")
            source = approved.get("source")
            if not isinstance(destination, Mapping) or not isinstance(workflow, Mapping) or not isinstance(source, Mapping):
                raise IssueDeliveryContractError(
                    "Issue-delivery approval bindings are incomplete"
                )
            expected_live_binding = {
                "checkout": str(destination["resolved_checkout"]),
                "worktree": str(destination["resolved_worktree"]),
                "branch": str(destination["branch"]),
                "source_revision": str(source["revision"]),
                "base_sha": str(destination["base_sha"]),
                "workflow_hash": str(workflow["content_hash"]),
                "workflow_artifacts": sorted(
                    [
                        {
                            "path": str(artifact["path"]),
                            "sha256": str(artifact["sha256"]),
                        }
                        for artifact in workflow["artifacts"]
                    ],
                    key=lambda item: item["path"],
                ),
            }
            if payload["live_binding"] != expected_live_binding:
                raise StateConflict(
                    "Issue-delivery source or workflow binding changed after approval"
                )
            for timestamp_name in (
                "reserved_at",
                "attempted_at",
                "entered_at",
                "observed_at",
            ):
                if timestamp_name in payload:
                    timestamp = payload[timestamp_name]
                    try:
                        parsed = datetime.fromisoformat(str(timestamp))
                    except (TypeError, ValueError) as exc:
                        raise IssueDeliveryContractError(
                            "Issue-delivery receipt timestamp is invalid"
                        ) from exc
                    if parsed.tzinfo is None:
                        raise IssueDeliveryContractError(
                            "Issue-delivery receipt timestamp must be timezone-aware"
                        )
            if kind == "reservation":
                if (
                    payload["destination"] != destination
                    or payload["proposed_run"] != {"run_id": destination["run_id"]}
                ):
                    raise StateConflict(
                        "Issue-delivery reservation does not match its approval"
                    )
            elif kind == "attempt":
                if (
                    payload["attempt_id"] != f"{operation_key}:attempt"
                    or not re.fullmatch(
                        r"[0-9a-f]{64}", str(payload["reservation_receipt_hash"])
                    )
                ):
                    raise IssueDeliveryContractError(
                        "Issue-delivery attempt receipt is malformed"
                    )
            elif kind == "entry":
                if (
                    payload["attempt_id"] != f"{operation_key}:attempt"
                    or not re.fullmatch(
                        r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}",
                        str(payload["session_id"]),
                    )
                    or not re.fullmatch(
                        r"[0-9a-f]{64}", str(payload["attempt_receipt_hash"])
                    )
                ):
                    raise IssueDeliveryContractError(
                        "Issue-delivery entry receipt is malformed"
                    )
            else:
                session_id = payload["session_id"]
                if session_id is not None and not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}", str(session_id)
                ):
                    raise IssueDeliveryContractError(
                        "Issue-delivery terminal session id is malformed"
                    )
                if not re.fullmatch(
                    r"[0-9a-f]{64}", str(payload["attempt_receipt_hash"])
                ):
                    raise IssueDeliveryContractError(
                        "Issue-delivery terminal attempt binding is malformed"
                    )
                if state == "terminal":
                    if not isinstance(payload["worker_receipt"], Mapping) or not isinstance(
                        session_id, str
                    ):
                        raise IssueDeliveryContractError(
                            "terminal receipt requires a worker and session"
                        )
                elif payload["worker_receipt"] is not None:
                    raise IssueDeliveryContractError(
                        "launch-unknown receipt cannot claim a worker outcome"
                    )

            if kind != "reservation":
                predecessor_kind = "reservation" if kind == "attempt" else "attempt"
                predecessor_id = f"issue-delivery-{predecessor_kind}:{operation_key}"
                try:
                    predecessor = store.get_record(repository, predecessor_id)
                except KeyError as exc:
                    raise StateConflict(
                        f"Issue-delivery {predecessor_kind} receipt is required first"
                    ) from exc
                predecessor_payload = predecessor.get("payload")
                if (
                    predecessor.get("record_type")
                    != _ISSUE_DELIVERY_OPERATION_RECORD_TYPE
                    or predecessor.get("state")
                    != {"reservation": "reserved", "attempt": "attempted"}[
                        predecessor_kind
                    ]
                    or not isinstance(predecessor_payload, Mapping)
                ):
                    raise StateConflict(
                        "Issue-delivery predecessor receipt is not authoritative"
                    )
                predecessor_hash = canonical_hash(
                    {
                        key: value
                        for key, value in predecessor_payload.items()
                        if key != "receipt_hash"
                    }
                )
                expected_hash = (
                    payload["reservation_receipt_hash"]
                    if kind == "attempt"
                    else payload["attempt_receipt_hash"]
                )
                if expected_hash != predecessor_hash:
                    raise StateConflict(
                        "Issue-delivery predecessor hash does not match"
                    )
            if kind == "terminal" and state == "terminal":
                try:
                    entry_record = store.get_record(
                        repository, f"issue-delivery-entry:{operation_key}"
                    )
                except KeyError as exc:
                    raise StateConflict(
                        "Issue-delivery terminal receipt requires an entry"
                    ) from exc
                entry_payload = entry_record.get("payload")
                if (
                    entry_record.get("state") != "active"
                    or not isinstance(entry_payload, Mapping)
                    or entry_payload.get("session_id") != payload["session_id"]
                    or payload["entry_receipt_hash"]
                    != canonical_hash(
                        {
                            key: value
                            for key, value in entry_payload.items()
                            if key != "receipt_hash"
                        }
                    )
                ):
                    raise StateConflict(
                        "Issue-delivery terminal entry predecessor does not match"
                    )
            elif kind == "terminal" and payload["entry_receipt_hash"] is not None:
                raise IssueDeliveryContractError(
                    "launch-unknown receipt cannot claim an unverified entry"
                )

        _enforce_repo_scope(credential, request.envelope.repository)
        if request.envelope.scope != "issue-delivery-operation":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Issue-delivery operation scope is required",
            )
        repository = canonical_repository(request.envelope.repository)
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}", request.operation_key
        ):
            raise IssueDeliveryContractError(
                "Issue-delivery operation key is malformed"
            )
        if not re.fullmatch(
            r"issue-delivery-(reservation|attempt|entry|terminal):[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}",
            request.record_id,
        ):
            raise IssueDeliveryContractError("Issue-delivery operation record id is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", request.approval_manifest_hash):
            raise IssueDeliveryContractError(
                "Issue-delivery operation manifest hash is invalid"
            )
        try:
            row = store.get_record(repository, issue_delivery_record_id(request.approval_id))
        except KeyError as exc:
            raise StateConflict("Issue-delivery approval is not durably admitted") from exc
        approved = dict(row.get("payload", {}))
        if (
            row.get("record_type") != ISSUE_DELIVERY_RECORD_TYPE
            or row.get("state") != "approved"
            or approved.get("approval_id") != request.approval_id
            or approved.get("operation_key") != request.operation_key
            or approved.get("approval_manifest_hash") != request.approval_manifest_hash
        ):
            raise StateConflict("Issue-delivery operation does not match its approval")
        _assert_issue_delivery_approval_integrity(approved)
        permission = approved.get("permission")
        _assert_issue_delivery_permission_safe(permission)
        owner_credential_id = (
            permission.get("credential_id")
            if isinstance(permission, Mapping)
            else None
        )
        owner = (
            credentials.current_credential(owner_credential_id)
            if isinstance(owner_credential_id, str)
            else None
        )
        if owner is None:
            raise StateConflict("Issue-delivery approval owner is unavailable")
        # This is the actual pre-effect permission/revocation/epoch/expiry and
        # source/profile check.  It deliberately runs for reservation, attempt,
        # entry and terminal evidence writes alike.
        validate_issue_delivery_approval(approved, owner)
        destination = approved.get("destination")
        if not isinstance(destination, Mapping):
            raise IssueDeliveryContractError("Issue-delivery destination is missing")
        if destination.get("identity") != credential.principal:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Issue-delivery destination does not match credential principal",
            )
        payload = dict(request.payload)
        if (
            payload.get("operation_key") != request.operation_key
            or payload.get("approval_id") != request.approval_id
            or payload.get("approval_manifest_hash") != request.approval_manifest_hash
            or payload.get("repository") != repository
        ):
            raise IssueDeliveryContractError(
                "Issue-delivery operation payload binding is incomplete"
            )
        kind_match = re.match(
            r"issue-delivery-(reservation|attempt|entry|terminal):(.+)$",
            request.record_id,
        )
        assert kind_match is not None
        kind, id_operation_key = kind_match.groups()
        if id_operation_key != request.operation_key:
            raise IssueDeliveryContractError(
                "Issue-delivery operation record id is not bound to its operation"
            )
        expected_states = {
            "reservation": "reserved",
            "attempt": "attempted",
            "entry": "active",
            "terminal": "terminal",
        }
        if expected_states[kind] != request.state and not (
            kind == "terminal" and request.state == "launch_unknown"
        ):
            raise IssueDeliveryContractError(
                "Issue-delivery operation record state does not match its kind"
            )
        validate_operation_payload(
            kind=kind,
            state=request.state,
            payload=request.payload,
            approved=approved,
            repository=repository,
            operation_key=request.operation_key,
            approval_id=request.approval_id,
            approval_manifest_hash=request.approval_manifest_hash,
        )
        _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
        result = store.commit_issue_delivery_operation_record(
            envelope=_envelope(request.envelope, credential),
            record_id=request.record_id,
            state=request.state,
            payload=payload,
            idempotency_key=request.idempotency_key,
            operation_key=request.operation_key,
            approval_id=request.approval_id,
            approval_manifest_hash=request.approval_manifest_hash,
            capability=_issue_delivery_operation_capability(),
        )
        return _authority_object_response(result)

    @application.post("/v1/issue-delivery/preview")
    @application.post("/v1/issues/command/preview")
    async def issue_delivery_preview(
        request: IssueDeliveryPreviewRequest,
        credential: Credential = Depends(issue_delivery_owner),
    ) -> dict[str, Any]:
        try:
            manifest = await run_in_threadpool(issue_delivery_manifest, request.manifest, credential)
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return {
            "contract_version": ISSUE_DELIVERY_CONTRACT,
            "operation_type": ISSUE_DELIVERY_OPERATION,
            "approval_id": manifest["approval_id"],
            "state": "previewed",
            "manifest": manifest,
            "choices": ["start", "hold"],
            "effects": [],
        }

    @application.post("/v1/issue-delivery/start")
    @application.post("/v1/issues/command/start")
    async def issue_delivery_start(
        request: IssueDeliveryStartRequest,
        credential: Credential = Depends(issue_delivery_owner),
    ) -> dict[str, Any]:
        try:
            return await run_in_threadpool(issue_delivery_start_sync, request, credential)
        except Exception as exc:
            raise _control_plane_error(exc) from exc

    @application.post("/v1/issue-delivery/operation-record")
    @application.post("/v1/issues/command/operation-record")
    async def issue_delivery_operation_record(
        request: IssueDeliveryOperationRecordRequest,
        credential: Credential = Depends(issue_delivery_execute),
    ) -> dict[str, Any]:
        try:
            return await run_in_threadpool(
                issue_delivery_operation_record_sync, request, credential
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc

    def issue_delivery_operation_record_read_sync(
        record_id: str, repository: str, credential: Credential
    ) -> dict[str, Any]:
        """Read one destination receipt through its narrow execute grant.

        The generic receipt route remains protected by ``receipts:read``.
        Destination reconciliation must also work for the selected launcher,
        whose credential is only granted ``issue_delivery:execute``.  This
        route therefore exposes no collection or arbitrary-record capability:
        it accepts only the finite FCA-ID-B record ids and verifies their
        durable approval/destination binding before returning the receipt.
        """

        _enforce_repo_scope(credential, repository)
        canonical = canonical_repository(repository)
        if not re.fullmatch(
            r"issue-delivery-(reservation|attempt|entry|terminal):[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}",
            record_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Issue-delivery operation receipt not found",
            )
        try:
            receipt = store.get_record(canonical, record_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Issue-delivery operation receipt not found",
            ) from exc
        payload = receipt.get("payload")
        if (
            receipt.get("record_type") != _ISSUE_DELIVERY_OPERATION_RECORD_TYPE
            or not isinstance(payload, Mapping)
            or payload.get("repository") != canonical
            or payload.get("operation_type") != ISSUE_DELIVERY_OPERATION
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Issue-delivery operation receipt not found",
            )
        operation_key = payload.get("operation_key")
        approval_id = payload.get("approval_id")
        approval_hash = payload.get("approval_manifest_hash")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (operation_key, approval_id, approval_hash)
        ):
            raise StateConflict("Issue-delivery operation receipt binding is malformed")
        if not isinstance(approval_id, str):
            raise StateConflict("Issue-delivery operation approval id is malformed")
        record_kind, id_operation_key = record_id.removeprefix(
            "issue-delivery-"
        ).split(":", 1)
        expected_record_id = f"issue-delivery-{record_kind}:{operation_key}"
        if expected_record_id != record_id or id_operation_key != operation_key:
            raise StateConflict("Issue-delivery operation receipt id is not bound")
        try:
            approval_row = store.get_record(
                canonical, issue_delivery_record_id(approval_id)
            )
        except KeyError as exc:
            raise StateConflict("Issue-delivery approval is not durably admitted") from exc
        approved = approval_row.get("payload")
        destination = approved.get("destination") if isinstance(approved, Mapping) else None
        if (
            approval_row.get("record_type") != ISSUE_DELIVERY_RECORD_TYPE
            or approval_row.get("state") != "approved"
            or not isinstance(approved, Mapping)
            or approved.get("repository") != canonical
            or approved.get("approval_id") != approval_id
            or approved.get("operation_key") != operation_key
            or approved.get("approval_manifest_hash") != approval_hash
            or not isinstance(destination, Mapping)
            or destination.get("identity") != credential.principal
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Issue-delivery destination does not match credential principal",
            )
        _assert_issue_delivery_approval_integrity(approved)
        _assert_issue_delivery_permission_safe(approved.get("permission"))
        return dict(receipt)

    @application.get("/v1/issue-delivery/operation-record/{record_id}")
    @application.get("/v1/issues/command/operation-record/{record_id}")
    async def issue_delivery_operation_record_read(
        record_id: str,
        repository: str,
        credential: Credential = Depends(issue_delivery_execute),
    ) -> dict[str, Any]:
        try:
            return await run_in_threadpool(
                issue_delivery_operation_record_read_sync,
                record_id,
                repository,
                credential,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc

    @application.post("/v1/issue-delivery/authority")
    @application.post("/v1/issues/command/authority")
    async def issue_delivery_authority(
        request: IssueDeliveryAuthorityRequest,
        credential: Credential = Depends(issue_delivery_control),
    ) -> dict[str, Any]:
        try:
            supplied = request.manifest
            if not isinstance(supplied, Mapping):
                raise StateConflict("Issue-delivery approval manifest is malformed")
            if supplied.get("approval_manifest_hash") != issue_delivery_manifest_hash(supplied):
                raise StateConflict("Issue-delivery approval manifest changed")
            if request.purpose == "readback":
                # Readback must remain available for reconciliation when the
                # current provider census or launcher assets have drifted. It
                # authenticates the supplied immutable hash against the
                # durable approval without rerunning launchability preflight.
                repository_value = supplied.get("repository")
                approval_id = supplied.get("approval_id")
                operation_key = supplied.get("operation_key")
                if (
                    not isinstance(repository_value, str)
                    or not repository_value.strip()
                    or not isinstance(approval_id, str)
                    or not approval_id.strip()
                    or not isinstance(operation_key, str)
                    or not operation_key.strip()
                ):
                    raise StateConflict("Issue-delivery readback identity is malformed")
                repository = canonical_repository(repository_value)
                _enforce_repo_scope(credential, repository)
                if "issue_delivery:read" not in credential.scopes:
                    raise HTTPException(
                        status_code=403,
                        detail="issue_delivery:read grant required",
                    )
                try:
                    row = store.get_record(
                        repository, issue_delivery_record_id(approval_id)
                    )
                except KeyError as exc:
                    raise StateConflict(
                        "Issue-delivery approval is not durably admitted"
                    ) from exc
                approved = dict(row.get("payload", {}))
                if (
                    row.get("record_type") != ISSUE_DELIVERY_RECORD_TYPE
                    or row.get("state") != "approved"
                    or approved.get("repository") != repository
                    or approved.get("approval_id") != approval_id
                    or approved.get("operation_key") != operation_key
                    or approved.get("approval_manifest_hash")
                    != supplied.get("approval_manifest_hash")
                ):
                    raise StateConflict(
                        "Issue-delivery approval does not match durable admission"
                    )
                _assert_issue_delivery_approval_integrity(approved)
                _assert_issue_delivery_permission_safe(approved.get("permission"))
                return {
                    "approval": approved,
                    "purpose": "readback",
                    "operation_key": operation_key,
                    "authority_epoch": store.readiness()["authority_epoch"],
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
            normalized = normalize_issue_delivery_manifest(supplied)
            repository = normalized["repository"]
            _enforce_repo_scope(credential, repository)
            try:
                row = store.get_record(repository, issue_delivery_record_id(normalized["approval_id"]))
            except KeyError as exc:
                raise StateConflict("Issue-delivery approval is not durably admitted") from exc
            approved = dict(row.get("payload", {}))
            if (
                row.get("record_type") != ISSUE_DELIVERY_RECORD_TYPE
                or row.get("state") != "approved"
                or approved.get("approval_id") != normalized["approval_id"]
                or approved.get("operation_key") != normalized["operation_key"]
                or approved.get("approval_manifest_hash") != supplied.get("approval_manifest_hash")
            ):
                raise StateConflict("Issue-delivery approval does not match durable admission")
            _assert_issue_delivery_approval_integrity(approved)
            owner_permission = approved.get("permission")
            _assert_issue_delivery_permission_safe(owner_permission)
            if request.purpose == "execute":
                owner_credential_id = (
                    owner_permission.get("credential_id")
                    if isinstance(owner_permission, Mapping)
                    else None
                )
                owner = (
                    credentials.current_credential(owner_credential_id)
                    if isinstance(owner_credential_id, str)
                    else None
                )
                if owner is None:
                    raise StateConflict("Issue-delivery approval owner is unavailable")
                validate_issue_delivery_approval(approved, owner)
                destination = approved.get("destination")
                destination_identity = (
                    destination.get("identity")
                    if isinstance(destination, Mapping)
                    else None
                )
                if destination_identity != credential.principal:
                    raise HTTPException(
                        status_code=403,
                        detail="Issue-delivery destination does not match credential principal",
                    )
            required_scope = (
                "issue_delivery:execute"
                if request.purpose == "execute"
                else "issue_delivery:read"
            )
            # Scope is checked on the authenticated credential itself.  A
            # principal-wide lookup would let a lower-privilege credential
            # borrow a sibling credential's grant when both share a principal.
            if required_scope not in credential.scopes:
                raise HTTPException(
                    status_code=403,
                    detail=f"{required_scope} grant required",
                )
            return {
                "approval": approved,
                "purpose": request.purpose,
                "operation_key": normalized["operation_key"],
                "authority_epoch": store.readiness()["authority_epoch"],
                "observed_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            raise _control_plane_error(exc) from exc

    @application.get("/v1/issue-delivery/{approval_id}")
    @application.get("/v1/issues/command/{approval_id}")
    async def issue_delivery_read(
        approval_id: str,
        repository: str,
        credential: Credential = Depends(issue_delivery_read_scope),
    ) -> dict[str, Any]:
        try:
            _enforce_repo_scope(credential, repository)
            return await run_in_threadpool(issue_delivery_readback, repository, approval_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Issue-delivery approval not found") from exc
        except Exception as exc:
            raise _control_plane_error(exc) from exc

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
        request: RecordCommitRequest | OwnerOutcomeCommitRequest | OwnerAskCommitRequest,
        raw_request: Request,
        credential: Credential = Depends(record_access),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        if isinstance(request, OwnerAskCommitRequest):
            try:
                strict_json(await raw_request.body())
                return await run_in_threadpool(publish_owner_ask, request, credential)
            except Exception as exc:
                raise _control_plane_error(exc) from exc
        if isinstance(request, OwnerOutcomeCommitRequest):
            try:
                # FastAPI's JSON parsing does not reject duplicate keys. Check
                # the actual bytes before any confirmation or durable effect.
                strict_json(await raw_request.body())
                return await run_in_threadpool(commit_owner_confirmation, request, credential)
            except Exception as exc:
                raise _control_plane_error(exc) from exc
        if "records:write" not in credential.scopes:
            raise HTTPException(status_code=403, detail="insufficient BuilderOps credential scope")
        _enforce_repo_scope(credential, request.envelope.repository)
        receipt_body = request.payload.get("receipt_body")
        if request.record_id.startswith("owner-ask:") or isinstance(receipt_body, Mapping) and receipt_body.get("contract") == "builder_owner_ask.v1":
            raise HTTPException(status_code=403, detail="owner asks require source admission")
        if request.record_type == "ModelInquiryApproval" or request.record_id.startswith("inquiry-approval:"):
            raise HTTPException(status_code=403, detail="inquiry approvals require owner command admission")
        if request.idempotency_key.startswith("issue-delivery:"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Issue-delivery idempotency keys require exact owner admission",
            )
        if (
            request.record_type == ISSUE_DELIVERY_RECORD_TYPE
            or request.record_id.startswith("issue-delivery-approval:")
            or request.payload.get("contract") == ISSUE_DELIVERY_CONTRACT
            or request.payload.get("operation_type") == ISSUE_DELIVERY_OPERATION
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Issue-delivery approvals require exact owner admission",
            )
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

    def commit_owner_confirmation(request: OwnerOutcomeCommitRequest, credential: Credential) -> dict[str, Any]:
        supplied = request.owner_outcome
        if set(supplied) != {"contract", "request", "request_sha256", "confirm"} or supplied.get("contract") != OWNER_OUTCOME_CONTRACT or supplied.get("confirm") != "confirm":
            raise OwnerFactRefusal("owner_confirmation_required")
        confirmed_at = datetime.now(timezone.utc).isoformat()
        immutable = validate_outcome_request(supplied["request"], confirmed_at=confirmed_at)
        # The finite policy reference is source metadata. Scan its values and
        # every other request value with the existing durable-secret guard;
        # do not extend generic ingestion's forbidden-field exemptions.
        scan = dict(immutable)
        scan["policy_reference"] = scan.pop("authorization_ref")
        _assert_durable_payload_safe({"request": scan, "request_key": request.idempotency_key}, credentials)
        request_hash = outcome_request_hash(immutable)
        if supplied["request_sha256"] != request_hash:
            raise OwnerFactRefusal("owner_request_hash_mismatch")
        repo, subject = immutable["repository"], immutable["subject_ref"]
        _enforce_repo_scope(credential, repo)
        if "receipts:read" not in credential.scopes or credential.principal_kind != "human" or not isinstance(immutable["owner_actor"], Mapping) or credential.principal != immutable["owner_actor"].get("id"):
            raise OwnerFactRefusal("owner_principal_mismatch", 403)

        def revalidate(epoch: int) -> dict[str, Any]:
            current = credentials.current_credential(credential.credential_id)
            if current != credential or current is None or not {"records:write", "owner_outcomes:confirm"}.issubset(current.scopes) or not current.may_address(repo) or current.principal_kind != "human":
                raise OwnerFactRefusal("owner_confirmation_not_authorized", 403)
            binding = read_owner_binding(repo, subject, authority_epoch=epoch,
                allow_withdrawn_readiness=immutable["outcome"] == "unable_to_try")
            if binding["owner_actor"] != immutable["owner_actor"] or binding["owner_actor"]["id"] != current.principal:
                raise OwnerFactRefusal("owner_principal_mismatch", 403)
            validate_current_binding(immutable, binding)
            return binding

        admission = OwnerOutcomeAdmission(immutable, request_hash, confirmed_at, revalidate)
        refs = [subject, "git:" + immutable["source_revision"], immutable["readiness_receipt_ref"]["id"],
                immutable["acceptance_profile_ref"]["id"] + ":" + immutable["acceptance_profile_ref"]["sha256"],
                immutable["authorization_ref"]["ref"] + ":" + immutable["authorization_ref"]["version"],
                immutable["retention_policy_ref"]["ref"] + ":" + immutable["retention_policy_ref"]["version"]]
        refs.extend(item["id"] + ":" + item["sha256"] for item in immutable["criterion_refs"] + immutable["limitation_refs"])
        refs.extend(ref for ref in (immutable["trial_receipt_ref"], immutable["supersedes_receipt_id"]) if ref is not None)
        envelope = AuthorityEnvelope(repository=repo, scope="owner-outcome", stack="builderops-control-plane", actor=credential.principal, source_refs=tuple(refs))
        result = store.commit_record(envelope=envelope, record_id=outcome_record_id(repo, request.idempotency_key), record_type="BuilderOpsReceipt", state="active", payload={}, idempotency_key=request.idempotency_key, owner_outcome=admission)
        receipt = dict(store.get_record(repo, result.object_id))["payload"]
        try:
            readback = store.get_owner_outcomes(repo, subject, idempotency_key=request.idempotency_key, grant_reader=credentials.has_owner_outcome_grant)
            projection = readback["projection"]
        except Exception:
            projection = {"status": "unavailable", "reason": "source_readback_required"}
        return {**_authority_object_response(result), "receipt": receipt, "projection": projection}

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
        subject_ref: str | None = None,
        idempotency_key: str | None = None,
        credential: Credential = Depends(receipt_read),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, repository)
        canonical = canonical_repository(repository)
        try:
            if object_kind == "owner-outcomes" and object_id == "current":
                if subject_ref is None:
                    raise OwnerFactRefusal("owner_subject_required")
                return await run_in_threadpool(store.get_owner_outcomes, canonical, subject_ref, idempotency_key=idempotency_key, grant_reader=credentials.has_owner_outcome_grant)
            if object_kind == "owner-facts" and object_id == "current":
                asks = await run_in_threadpool(current_owner_asks, canonical)
                outcome_source_status = "available"
                try:
                    profiles = await run_in_threadpool(read_owner_profiles)
                except OwnerFactRefusal:
                    if not any(ask["status"] == "current" for ask in asks):
                        raise
                    profiles = []
                    outcome_source_status = "unavailable"
                subjects = [p["subject_ref"] for p in profiles if p["repository"] == canonical]
                if not subjects and not asks:
                    raise OwnerFactRefusal("owner_source_unavailable", 503)
                items = []
                for subject in subjects:
                    try:
                        items.append(await run_in_threadpool(store.get_owner_outcomes, canonical, subject, grant_reader=credentials.has_owner_outcome_grant))
                    except Exception as exc:
                        items.append({"subject_ref": subject, "status": "unavailable", "reason": type(exc).__name__})
                return {"contract": "builder_owner_fact_collection.v1", "repository": canonical, "subjects": items, "owner_asks": asks, "owner_outcomes_status": outcome_source_status}
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

    @application.post("/v1/executor/outbox/post-effect/pending")
    async def begin_row_derived_post_effect_pending(
        request: RowDerivedPostEffectPendingRequest,
        credential: Credential = Depends(outbox_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            intent = await run_in_threadpool(
                store.outbox_intent, request.envelope.repository, request.operation_key
            )
            _enforce_outbox_principal(intent, credential)
            pending = await run_in_threadpool(
                store.begin_post_effect_pending,
                repository=request.envelope.repository,
                operation_key=request.operation_key,
                minimum_fencing_token=request.minimum_fencing_token,
                expected_principal=credential.principal,
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return dict(pending)

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

    @application.post("/v1/executor/outbox/post-effect/reconcile")
    async def reconcile_row_derived_post_effect(
        request: RowDerivedPostEffectReconcileRequest,
        credential: Credential = Depends(outbox_write),
        _epoch: None = Depends(require_authority_epoch),
    ) -> dict[str, Any]:
        _enforce_repo_scope(credential, request.envelope.repository)
        try:
            _assert_row_derived_evidence_safe(request.evidence)
            _assert_durable_payload_safe(request.model_dump(mode="json"), credentials)
            intent = await run_in_threadpool(
                store.outbox_intent, request.envelope.repository, request.operation_key
            )
            _enforce_outbox_principal(intent, credential)
            result = await run_in_threadpool(
                store.reconcile_post_effect,
                repository=request.envelope.repository,
                operation_key=request.operation_key,
                minimum_fencing_token=request.minimum_fencing_token,
                expected_principal=credential.principal,
                observed_applied=request.observed_applied,
                terminal_unknown=request.terminal_unknown,
                evidence=request.evidence.model_dump(mode="json"),
            )
        except Exception as exc:
            raise _control_plane_error(exc) from exc
        return dict(result)

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
