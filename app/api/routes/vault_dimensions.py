"""Authenticated Companion API for MVR-04 vault dimensions (#3858).

This router is one of the two production producers named by MVR-04; the other is the
headless ``python -m app.instance.runtime dimension-*`` CLI. Both go through
:class:`~app.instance.vault_dimensions.VaultDimensionService`, so they converge on the same
locked registry state, the same validation, and the same redacted receipt. No test seeds the
store: these are the commands the tests drive.

Two responses in this router look similar and are emphatically not the same thing.

``GET /instance/dimensions/{id}``
    **Stored membership.** Registry administration. It reports what is stored, *including*
    members that are stale or unauthorized, so an operator can see and repair them. It is
    not an ActiveContextSet and it is not a permission result.

``GET /instance/dimensions/{id}/resolve``
    **Context resolution.** All-or-nothing. Every member is authorized independently by
    GOV, and one unknown, stale, or unauthorized member fails the entire call. It never
    returns an authorized subset.

Responses carry opaque binding identity, display metadata, and revisions only -- never a
content-root path, note content, or any other raw binding payload.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes.active_context_selection import get_selection_store
from app.auth import api_key_header, require_loopback_or_api_key, resolve_auth_subject
from app.instance.active_context_service import (
    ActiveContextSelectionService,
    DerivedContext,
)
from app.instance.local_operator_principal import PrincipalPreflightError
from app.instance.runtime import (
    open_local_operator_principal_store,
    open_vault_dimension_service,
)
from app.instance.vault_dimensions import (
    REASON_DIMENSION_UNKNOWN,
    REASON_MEMBER_UNAUTHORIZED,
    DimensionReceipt,
    DimensionResolutionError,
    VaultDimensionService,
)
from app.instance.vault_registry import (
    RegistryError,
    RegistryRevisionConflict,
    VaultRegistryStore,
)
from app.vault.active_context_v1 import AuthSubject

# Router-level #2223 gate, matching the selection router: an unauthenticated caller is
# rejected before any instance state is read from disk, so the endpoint cannot disclose
# whether a registry is bound or a principal is provisioned.
router = APIRouter(
    prefix="/instance/dimensions",
    tags=["instance", "dimensions"],
    dependencies=[Depends(require_loopback_or_api_key)],
)


class DimensionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    vault_binding_ids: list[str] = Field(default_factory=list)


class DimensionRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=128)


class DimensionMembersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vault_binding_ids: list[str] = Field(default_factory=list)


class DimensionView(BaseModel):
    """Stored grouping metadata. Deliberately carries no authority field."""

    dimension_id: str
    display_name: str
    dimension_revision: int
    vault_binding_ids: list[str]
    last_repair: dict | None = None


class DimensionListResponse(BaseModel):
    dimensions: list[DimensionView]


class DimensionReceiptResponse(BaseModel):
    dimension_id: str
    changed: bool
    registry_revision: int
    previous_vault_binding_ids: list[str] = Field(default_factory=list)
    removed_vault_binding_ids: list[str] = Field(default_factory=list)
    deleted: bool = False
    display_name: str | None = None
    dimension_revision: int | None = None
    vault_binding_ids: list[str] = Field(default_factory=list)
    last_repair: dict | None = None


class ResolvedMemberView(BaseModel):
    """One resolved member with its own provenance and its own GOV verdict epoch.

    Per-binding identity survives grouping: each member keeps its own binding id, logical
    vault id, local instance id, revision, and authorization epoch. Nothing is merged.
    """

    vault_binding_id: str
    binding_revision: int
    authorization_epoch: str
    vault_id: str | None = None
    local_instance_id: str | None = None
    label: str | None = None


class DimensionResolutionResponse(BaseModel):
    dimension_id: str
    dimension_revision: int
    members: list[ResolvedMemberView]


def _registry_path() -> Path:
    value = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not value:
        raise HTTPException(
            status_code=503,
            detail="instance registry is not bound on this process",
        )
    return Path(value).expanduser().resolve(strict=False)


def get_dimension_service() -> VaultDimensionService:
    # The sealed storage-mutation capability is handed over by the sanctioned
    # instance-runtime factory; this route never touches the seal itself.
    return open_vault_dimension_service(_registry_path())


def _derived(request: Request, api_key: str | None) -> DerivedContext:
    """Resolve the principal the same way the selection endpoints do.

    Resolution needs a real principal because GOV authorizes every member against it. An
    unresolved principal fails closed; there is no anonymous resolution path.
    """

    registry_path = _registry_path()
    principal_store = open_local_operator_principal_store(registry_path)
    try:
        record = principal_store.require()
    except PrincipalPreflightError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    service = ActiveContextSelectionService(
        registry_store=VaultRegistryStore(registry_path),
        principal_record=record,
        # The one process-wide selection store. Nothing here mints a selection; reusing
        # it rather than constructing a throwaway keeps a single store in the process.
        selection_store=get_selection_store(),
    )
    subject: AuthSubject = resolve_auth_subject(request, api_key)  # type: ignore[assignment]
    try:
        return service.derive(subject, presented_credential=api_key)
    except PrincipalPreflightError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _fail(exc: RegistryError) -> HTTPException:
    if isinstance(exc, DimensionResolutionError):
        if exc.reason == REASON_DIMENSION_UNKNOWN:
            return HTTPException(status_code=404, detail=str(exc))
        if exc.reason == REASON_MEMBER_UNAUTHORIZED:
            return HTTPException(status_code=403, detail=str(exc))
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, RegistryRevisionConflict):
        # Optimistic concurrency: another writer committed between this command's read
        # and its locked write, so the write was refused rather than applied over stale
        # state. A conflict is retryable after a reload, which a 400 would not convey.
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _view(payload: dict) -> DimensionView:
    return DimensionView(**payload)


def _receipt(receipt: DimensionReceipt) -> DimensionReceiptResponse:
    return DimensionReceiptResponse(**receipt.as_dict())


@router.get("", response_model=DimensionListResponse)
def list_dimensions(
    service: VaultDimensionService = Depends(get_dimension_service),
) -> DimensionListResponse:
    try:
        stored = service.list()
    except RegistryError as exc:
        raise _fail(exc) from exc
    return DimensionListResponse(
        dimensions=[_view(dimension.redacted()) for dimension in stored]
    )


@router.post("", response_model=DimensionReceiptResponse, status_code=status.HTTP_201_CREATED)
def create_dimension(
    payload: DimensionCreateRequest,
    service: VaultDimensionService = Depends(get_dimension_service),
) -> DimensionReceiptResponse:
    try:
        receipt = service.create(
            payload.dimension_id,
            display_name=payload.display_name,
            members=payload.vault_binding_ids,
        )
    except RegistryError as exc:
        raise _fail(exc) from exc
    return _receipt(receipt)


@router.get("/{dimension_id}", response_model=DimensionView)
def inspect_dimension(
    dimension_id: str,
    service: VaultDimensionService = Depends(get_dimension_service),
) -> DimensionView:
    """Stored membership, including stale or unauthorized rows. Not a resolution."""

    try:
        return _view(service.inspect(dimension_id).redacted())
    except RegistryError as exc:
        raise _fail(exc) from exc


@router.patch("/{dimension_id}", response_model=DimensionReceiptResponse)
def rename_dimension(
    dimension_id: str,
    payload: DimensionRenameRequest,
    service: VaultDimensionService = Depends(get_dimension_service),
) -> DimensionReceiptResponse:
    try:
        receipt = service.rename(dimension_id, display_name=payload.display_name)
    except RegistryError as exc:
        raise _fail(exc) from exc
    return _receipt(receipt)


@router.put("/{dimension_id}/members", response_model=DimensionReceiptResponse)
def set_dimension_members(
    dimension_id: str,
    payload: DimensionMembersRequest,
    service: VaultDimensionService = Depends(get_dimension_service),
) -> DimensionReceiptResponse:
    """Replace membership. Every proposed member must be a current registration."""

    try:
        receipt = service.set_members(dimension_id, payload.vault_binding_ids)
    except RegistryError as exc:
        raise _fail(exc) from exc
    return _receipt(receipt)


@router.delete("/{dimension_id}/members/{vault_binding_id}", response_model=DimensionReceiptResponse)
def remove_dimension_member(
    dimension_id: str,
    vault_binding_id: str,
    service: VaultDimensionService = Depends(get_dimension_service),
) -> DimensionReceiptResponse:
    """Instance-authorized repair: clear one stored member without resolving it."""

    try:
        receipt = service.remove_member(dimension_id, vault_binding_id)
    except RegistryError as exc:
        raise _fail(exc) from exc
    return _receipt(receipt)


@router.delete("/{dimension_id}", response_model=DimensionReceiptResponse)
def delete_dimension(
    dimension_id: str,
    service: VaultDimensionService = Depends(get_dimension_service),
) -> DimensionReceiptResponse:
    """Delete the grouping. Registrations and vault content are untouched."""

    try:
        receipt = service.delete(dimension_id)
    except RegistryError as exc:
        raise _fail(exc) from exc
    return _receipt(receipt)


@router.get("/{dimension_id}/resolve", response_model=DimensionResolutionResponse)
def resolve_dimension(
    dimension_id: str,
    request: Request,
    api_key: str | None = Depends(api_key_header),
    service: VaultDimensionService = Depends(get_dimension_service),
) -> DimensionResolutionResponse:
    """Resolve a dimension into explicit bindings, authorizing every member independently.

    All-or-nothing: one unknown, stale, or unauthorized member fails the whole call with a
    bounded member-specific error. An authorized subset is never returned.
    """

    from app.instance.active_context_service import (
        ACTION_DIMENSION_RESOLVE,
        PERMISSION_SELECTION_MANAGE,
        WRITE_CLASS_READ,
        build_authorizer,
    )

    derived = _derived(request, api_key)
    snapshot = service.store.load()
    try:
        resolution = service.resolve(
            dimension_id,
            principal=derived.principal,
            action=ACTION_DIMENSION_RESOLVE,
            write_class=WRITE_CLASS_READ,
            required_permission=PERMISSION_SELECTION_MANAGE,
            authorizer=build_authorizer(snapshot),
            snapshot=snapshot,
        )
    except RegistryError as exc:
        raise _fail(exc) from exc
    return DimensionResolutionResponse(
        dimension_id=resolution.dimension_id,
        dimension_revision=resolution.dimension_revision,
        members=[
            ResolvedMemberView(
                vault_binding_id=member.vault_binding_id,
                binding_revision=member.binding_revision,
                authorization_epoch=member.authorization_epoch,
                vault_id=member.vault_id,
                local_instance_id=member.local_instance_id,
                label=member.label,
            )
            for member in resolution.members
        ],
    )


__all__ = ["get_dimension_service", "router"]
