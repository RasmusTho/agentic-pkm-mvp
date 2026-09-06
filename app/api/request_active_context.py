"""Server-owned ActiveContextSet request dependency (MVR-05B)."""

from __future__ import annotations

import os

from fastapi import Depends, Header, HTTPException, Request, status

from app.api.routes.active_context_selection import (
    _selection_failure,
    build_selection_service,
    get_selection_store,
)
from app.auth import api_key_header, resolve_auth_subject
from app.governance.binding_authority import BindingAuthorizationError
from app.instance.active_context_service import (
    ACTION_SELECTION_INSPECT,
    PERMISSION_SELECTION_READ,
    WRITE_CLASS_READ,
    ActiveContextServiceError,
)
from app.instance.context_selection import ReselectionRequiredError, SelectionPrincipalMismatchError
from app.instance.local_operator_principal import PrincipalPreflightError
from app.vault.active_context_v1 import ActiveContextSetV1


def resolve_read_context(
    request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None),
) -> ActiveContextSetV1 | None:
    """Resolve exactly one immutable context for a production read request."""
    # Preserve the explicit pre-registry/no-vault journey.  Once an instance
    # registry exists, every read resolves through the V1 seam below; no global
    # vault selection is consulted in either branch.
    if not os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip():
        return None
    try:
        service = build_selection_service(get_selection_store())
        derived = service.derive(
            resolve_auth_subject(request, api_key), presented_credential=api_key
        )
        context = service.resolve_request_context(
            derived=derived,
            session_bearer=x_active_context_session,
            override_bearer=x_active_context_override,
            action=ACTION_SELECTION_INSPECT,
            write_class=WRITE_CLASS_READ,
            required_permission=PERMISSION_SELECTION_READ,
        ).snapshot
        # Downstream read seams receive this exact immutable object, never a
        # re-resolved scalar/global selection.
        request.state.active_context_set = context
        return context
    except (
        ReselectionRequiredError,
        SelectionPrincipalMismatchError,
        ActiveContextServiceError,
        PrincipalPreflightError,
    ) as exc:
        raise _selection_failure(exc) from exc
    except BindingAuthorizationError as exc:
        # A selection never grants read authority.  Avoid leaking binding or
        # bearer details while refusing the request before retrieval/I/O.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="active_context_binding_denied",
        ) from exc


def require_scoped_read_context(
    request: Request,
    context: ActiveContextSetV1 | None = Depends(resolve_read_context),
) -> ActiveContextSetV1:
    """Require a carrier-bound context on a route advertised as scoped.

    A scoped route has a distinct identity from legacy compatibility reads. It
    therefore cannot silently turn a missing or stripped carrier into an
    instance-default/no-vault read.
    """

    if not (
        request.headers.get("X-Active-Context-Session")
        or request.headers.get("X-Active-Context-Override")
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="reselection_required")
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="instance registry is not bound on this process",
        )
    return context


def reject_scoped_vault_mutation(request: Request) -> None:
    """Keep legacy vault mutations unable to consume a read-selection bearer.

    MVR-05B deliberately ships only the read-side carrier.  Applying this at
    the Companion router boundary makes the seal cover every present and
    future vault-facing mutation, rather than relying on individual handlers
    to remember a guard before their legacy resolver or writer.  Selection
    itself is not a vault-content mutation and is the one required exception:
    a picker may replace its selection while it still presents the old bearer.
    """

    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    if request.url.path.endswith("/vault/select"):
        return
    if not (
        request.headers.get("X-Active-Context-Session")
        or request.headers.get("X-Active-Context-Override")
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": "capability_not_ready", "capability": "mvr05c_scoped_write"},
    )


__all__ = [
    "reject_scoped_vault_mutation",
    "require_scoped_read_context",
    "resolve_read_context",
]
