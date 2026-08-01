"""Production Companion endpoints for TTL-bound active-context selection (MVR-03, #3857).

Four commands drive the one `ContextSelectionStore`: create, replace, inspect, clear.

What these endpoints accept: **explicit binding-selection intent only.** A request body may
name `vault_binding_ids` and nothing else -- `extra="forbid"` makes a client-authored
workspace, scope, sphere membership, situated identity, principal, action, permission, or
dimension payload a 422 rather than a silently-ignored field. That matters: silently
ignoring such a field would let a caller believe it had set cognitive context.

What they never do:

- mutate process-global `VaultManager` state (this module does not import it),
- accept or resolve a dimension payload (sealed until MVR-04 supplies its registry),
- store operation authority in the selection.

The existing `/api/companion/vault/select` stays a named legacy-global adapter until task 05
migrates its production client. It is not the session-selection command and cannot mutate a
scoped selection implicitly.

Bearer handling: creation returns the server-minted id exactly once, in the response body.
Every later call presents it in `X-Active-Context-Session`. It is never logged, never echoed
into an error, and never placed in a receipt -- only its non-reversible digest appears in
bounded context identity.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import api_key_header, require_loopback_or_api_key, resolve_auth_subject
from app.instance.active_context_service import (
    ActiveContextSelectionService,
    ActiveContextServiceError,
    DerivedContext,
)
from app.instance.context_selection import (
    HEADER_ACTIVE_CONTEXT_SESSION,
    ContextSelectionRecord,
    ContextSelectionStore,
    ReselectionRequiredError,
    SelectionPrincipalMismatchError,
)
from app.instance.local_operator_principal import PrincipalPreflightError
from app.instance.runtime import open_local_operator_principal_store
from app.instance.vault_registry import RegistryError, VaultRegistryStore
from app.vault.active_context_v1 import AuthSubject

# The #2223 gate is a *router-level* dependency, not a per-handler one. FastAPI resolves
# router dependencies before a path operation's own parameter dependencies, so an
# unauthenticated caller is rejected before `get_selection_service` reads instance state from
# disk. With the gate inside the handler instead, an unauthenticated remote caller could
# observe a 503 that discloses whether a registry is bound and whether a principal is
# provisioned.
router = APIRouter(
    prefix="/companion/active-context",
    tags=["companion", "active-context"],
    dependencies=[Depends(require_loopback_or_api_key)],
)

_SELECTION_PATH = "/selection"

#: One process-wide ephemeral store. V1 session selection is deliberately not durable, so a
#: process restart legitimately loses every selection: an omitted id then resolves the
#: instance default or no-vault, while a presented pre-restart id fails closed.
_STORE = ContextSelectionStore()


def get_selection_store() -> ContextSelectionStore:
    return _STORE


def reset_selection_store_for_tests() -> ContextSelectionStore:
    """Rebuild the store, modelling a process restart. Test-support only."""

    global _STORE
    _STORE = ContextSelectionStore()
    return _STORE


class SelectionRequest(BaseModel):
    """Explicit binding-selection intent. Nothing else is accepted."""

    model_config = ConfigDict(extra="forbid")

    vault_binding_ids: list[str] = Field(default_factory=list)


class SelectionContext(BaseModel):
    """The server-derived context stored for a selection.

    Every field here was derived by the server. None of it can be supplied by a client, and
    the raw bearer is structurally absent -- only the digest appears.
    """

    context_id: str
    generation: int
    selection_capability_digest: str
    principal_kind: str
    principal_id: str
    instance_identity: str
    workspace: str
    scope: str
    sphere_memberships: list[str]
    situated_identity: str | None = None
    vault_binding_ids: list[str]
    expires_at: float


class SelectionCreatedResponse(BaseModel):
    """The only surface that ever carries the raw bearer."""

    context_selection_id: str
    context: SelectionContext


class SelectionResponse(BaseModel):
    context: SelectionContext


class SelectionClearedResponse(BaseModel):
    cleared: bool = True


def _registry_path() -> Path:
    value = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not value:
        raise HTTPException(
            status_code=503,
            detail="instance registry is not bound on this process",
        )
    return Path(value).expanduser().resolve(strict=False)


def get_selection_service(
    store: ContextSelectionStore = Depends(get_selection_store),
) -> ActiveContextSelectionService:
    registry_path = _registry_path()
    principal_store = open_local_operator_principal_store(registry_path)
    try:
        record = principal_store.require()
    except PrincipalPreflightError as exc:
        # No resolved principal/delegated role: a governed operation fails closed with the
        # explicit provisioning action rather than proceeding anonymously.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ActiveContextSelectionService(
        registry_store=VaultRegistryStore(registry_path),
        principal_record=record,
        selection_store=store,
    )


def _derive(
    request: Request,
    api_key: str | None,
    service: ActiveContextSelectionService,
) -> DerivedContext:
    subject: AuthSubject = resolve_auth_subject(request, api_key)  # type: ignore[assignment]
    try:
        return service.derive(subject, presented_credential=api_key)
    except PrincipalPreflightError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _require_bearer(value: str | None) -> str:
    if not value or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{HEADER_ACTIVE_CONTEXT_SESSION} is required for this selection command"
            ),
        )
    return value.strip()


def _context(record: ContextSelectionRecord) -> SelectionContext:
    return SelectionContext(**record.redacted())  # type: ignore[arg-type]


#: Every bearer-resolution failure returns exactly this, whatever went wrong. Expired,
#: unknown, pre-restart, and bound-to-another-principal are deliberately indistinguishable
#: over the wire: distinguishing them would make the endpoint a bearer-existence oracle.
#: The internal exception types stay distinct so a future audit log can tell them apart.
_RESELECTION_REQUIRED_DETAIL = "reselection_required: selection is not resolvable for this caller"


def _selection_failure(exc: Exception) -> HTTPException:
    """Map a selection failure to a response that contains no bearer material.

    The detail is a fixed constant rather than `str(exc)`, so neither the presented bearer
    nor the reason it failed can leak.
    """

    if isinstance(exc, (ReselectionRequiredError, SelectionPrincipalMismatchError)):
        return HTTPException(status_code=401, detail=_RESELECTION_REQUIRED_DETAIL)
    if isinstance(exc, ActiveContextServiceError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RegistryError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.post(_SELECTION_PATH, response_model=SelectionCreatedResponse, status_code=201)
def create_selection(
    request: Request,
    payload: SelectionRequest,
    api_key: str | None = Depends(api_key_header),
    service: ActiveContextSelectionService = Depends(get_selection_service),
) -> SelectionCreatedResponse:
    derived = _derive(request, api_key, service)
    try:
        raw_id, record = service.create(
            derived=derived, binding_ids=payload.vault_binding_ids
        )
    except (ActiveContextServiceError, RegistryError) as exc:
        raise _selection_failure(exc) from exc
    return SelectionCreatedResponse(context_selection_id=raw_id, context=_context(record))


@router.put(_SELECTION_PATH, response_model=SelectionResponse)
def replace_selection(
    request: Request,
    payload: SelectionRequest,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    service: ActiveContextSelectionService = Depends(get_selection_service),
) -> SelectionResponse:
    derived = _derive(request, api_key, service)
    bearer = _require_bearer(x_active_context_session)
    try:
        record = service.replace(
            bearer, derived=derived, binding_ids=payload.vault_binding_ids
        )
    except (
        ReselectionRequiredError,
        SelectionPrincipalMismatchError,
        ActiveContextServiceError,
        RegistryError,
    ) as exc:
        raise _selection_failure(exc) from exc
    return SelectionResponse(context=_context(record))


@router.get(_SELECTION_PATH, response_model=SelectionResponse)
def inspect_selection(
    request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    service: ActiveContextSelectionService = Depends(get_selection_service),
) -> SelectionResponse:
    derived = _derive(request, api_key, service)
    bearer = _require_bearer(x_active_context_session)
    try:
        record = service.inspect(bearer, derived=derived)
    except (ReselectionRequiredError, SelectionPrincipalMismatchError) as exc:
        raise _selection_failure(exc) from exc
    return SelectionResponse(context=_context(record))


@router.delete(_SELECTION_PATH, response_model=SelectionClearedResponse)
def clear_selection(
    request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    service: ActiveContextSelectionService = Depends(get_selection_service),
) -> SelectionClearedResponse:
    derived = _derive(request, api_key, service)
    bearer = _require_bearer(x_active_context_session)
    try:
        service.clear(bearer, derived=derived)
    except (ReselectionRequiredError, SelectionPrincipalMismatchError) as exc:
        raise _selection_failure(exc) from exc
    return SelectionClearedResponse()


__all__ = [
    "get_selection_service",
    "get_selection_store",
    "router",
]
