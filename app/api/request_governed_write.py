"""HTTP selection resolution with the capture contract's separate GOV inputs."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException, Request

from app.api.routes.active_context_selection import (
    _selection_failure,
    build_selection_service,
    get_selection_store,
)
from app.auth import api_key_header, resolve_auth_subject
from app.governance.binding_authority import BindingAuthorizationError
from app.instance.active_context_service import ActiveContextServiceError
from app.instance.context_selection import ReselectionRequiredError, SelectionPrincipalMismatchError
from app.instance.local_operator_principal import PrincipalPreflightError
from app.vault.active_context_v1 import ActiveContextSetV1


def governed_context_write(endpoint: Any) -> Any:
    setattr(endpoint, "__governed_context_write__", True)
    return endpoint


def require_capture_context(
    request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None),
) -> ActiveContextSetV1:
    if not (x_active_context_session or x_active_context_override):
        raise HTTPException(status_code=401, detail="reselection_required")
    try:
        service = build_selection_service(get_selection_store())
        derived = service.derive(
            resolve_auth_subject(request, api_key), presented_credential=api_key
        )
        context = service.resolve_request_context(
            derived=derived,
            session_bearer=x_active_context_session,
            override_bearer=x_active_context_override,
            action="companion.capture.append",
            write_class="vault_capture_append",
            required_permission="write",
        ).snapshot
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
        raise HTTPException(status_code=403, detail="active_context_binding_denied") from exc
