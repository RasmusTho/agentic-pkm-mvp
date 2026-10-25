"""Server-owned ActiveContextSet request dependency (MVR-05B)."""

from __future__ import annotations

import functools
import inspect
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

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
from app.instance.context_bound_read import ContextBoundReadError, context_bound_read_window
from app.instance.local_operator_principal import PrincipalPreflightError
from app.instance.vault_registry import VaultRegistryStore
from app.api.routes.vault_resolution import (
    compatibility_vault_root_or_selection_required,
    vault_selection_required_json,
)
from app.vault.active_context_v1 import ActiveContextSetV1
from app.vault.manager import nearest_enclosing_vault_root

from app.api.compatibility_mutation import reject_scoped_vault_mutation


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


def resolve_optional_scoped_read_context(
    request: Request,
    api_key: str | None = Depends(api_key_header),
    x_active_context_session: str | None = Header(default=None),
    x_active_context_override: str | None = Header(default=None),
) -> ActiveContextSetV1 | None:
    """Bind a carrier-bearing read to its own context; leave carrier-free reads legacy.

    MVR-05B2 migrates companion read routes in place, so one URL serves two
    separately identified journeys. A request that presents a selection carrier
    is resolved with exactly the scoped-route semantics above (never downgraded
    to an instance-default or no-vault read). A carrier-free request returns
    ``None`` *without* resolving anything, so the shipped client keeps its
    legacy single-binding journey until MVR-05B5 activates the carrier.
    """

    if x_active_context_session is None and x_active_context_override is None:
        # Only an absent carrier is the legacy journey. A present-but-blank one is
        # an invalid scoped carrier and fails closed below, never falls back.
        return None
    context = resolve_read_context(
        request,
        api_key=api_key,
        x_active_context_session=x_active_context_session,
        x_active_context_override=x_active_context_override,
    )
    return require_scoped_read_context(request, context)


def reject_carrier_on_legacy_read(request: Request) -> None:
    """The separately identified legacy twin of a scoped route never serves a carrier.

    ``/api/ask`` and ``/search`` are the legacy compatibility reads beside their
    distinct ``/scoped`` routes. A request presenting a selection carrier (even a
    blank one) is a migrated client; serving it from the process-wide selection
    would downgrade it to the default binding, so it fails before any resolution.
    """

    if "X-Active-Context-Session" in request.headers or "X-Active-Context-Override" in request.headers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="active_context_scoped_route_required",
        )


# --- MVR-05B3: in-place scoped reads for the remaining API route modules -----
#
# Same journey split as the MVR-05B2 companion reads: a carrier-bearing request
# resolves its own immutable ActiveContextSet and the whole route (including
# response serialization) runs inside ``context_bound_read_window``; a
# carrier-free request keeps the legacy single-binding journey through the named
# compatibility adapter in ``app/api/routes/vault_resolution.py``.


@dataclass(frozen=True)
class ScopedRouteRead:
    """The one binding a scoped route read is bound to, under its shared lease."""

    # ``None`` for a healthy explicit zero-binding selection (scoped no-vault).
    vault_binding_id: str | None
    root: Path | None
    context_generation: int
    # The immutable request context, for a read that queries by binding set
    # (MVR-05B4c5 query-backed context bundles).
    context: ActiveContextSetV1 | None = None


_SCOPED_ROUTE_READ: ContextVar[ScopedRouteRead | None] = ContextVar(
    "mvr05b3_scoped_route_read", default=None
)
_SCOPED_ROUTE_READ_PARAMETER = "mvr05b3_active_context"


def current_scoped_route_read() -> ScopedRouteRead | None:
    """The binding of the scoped read in progress, or ``None`` for a legacy request."""

    return _SCOPED_ROUTE_READ.get()


@contextmanager
def scoped_route_read_window(context: ActiveContextSetV1) -> Iterator[ScopedRouteRead]:
    """Bind one route read to ``context`` under its shared binding lease."""

    if len(context.source_bindings) > 1:
        # These surfaces render exactly one vault; a many-binding selection is
        # refused rather than silently narrowed to one of its bindings.
        raise HTTPException(status_code=409, detail="active_context_single_binding_required")
    registry_path = (os.getenv("INSTANCE_VAULT_REGISTRY_PATH") or "").strip()
    if not registry_path:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="instance registry is not bound on this process",
        )
    registry = VaultRegistryStore(Path(registry_path).expanduser().resolve(strict=False))
    try:
        with context_bound_read_window(context, registry_store=registry) as roots:
            if roots:
                scoped = ScopedRouteRead(
                    vault_binding_id=roots[0].vault_binding_id,
                    root=roots[0].root,
                    context_generation=roots[0].context_generation,
                    context=context,
                )
            else:
                scoped = ScopedRouteRead(
                    vault_binding_id=None,
                    root=None,
                    context_generation=context.generation,
                    context=context,
                )
            token = _SCOPED_ROUTE_READ.set(scoped)
            try:
                yield scoped
            finally:
                _SCOPED_ROUTE_READ.reset(token)
    except ContextBoundReadError as exc:
        raise HTTPException(status_code=409, detail="active_context_read_unavailable") from exc


def scoped_route_read(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """Migrate one read route in place onto the per-request ActiveContextSet.

    Adds the optional carrier dependency. A carrier-bearing request (a blank
    carrier included) runs the route inside :func:`scoped_route_read_window` and
    serializes the response before the lease is released; it is never downgraded
    to the legacy journey. A carrier-free request runs the unchanged legacy body.
    """

    # Evaluate the endpoint's (possibly postponed) annotations in its own module:
    # FastAPI would otherwise resolve them against this wrapper's globals.
    signature = inspect.signature(endpoint, eval_str=True)
    carrier = inspect.Parameter(
        _SCOPED_ROUTE_READ_PARAMETER,
        inspect.Parameter.KEYWORD_ONLY,
        default=Depends(resolve_optional_scoped_read_context),
        annotation=ActiveContextSetV1 | None,
    )

    @functools.wraps(endpoint)
    def route(*args: Any, **kwargs: Any) -> Any:
        context = kwargs.pop(_SCOPED_ROUTE_READ_PARAMETER, None)
        if context is None:
            return endpoint(*args, **kwargs)
        with scoped_route_read_window(context):
            result = endpoint(*args, **kwargs)
            if isinstance(result, Response):
                return result
            return JSONResponse(content=jsonable_encoder(result))

    setattr(
        route,
        "__signature__",
        signature.replace(parameters=[*signature.parameters.values(), carrier]),
    )
    return route


def scoped_note_path_owned_by_binding(scoped: ScopedRouteRead, resolved: Path) -> bool:
    """Whether a resolved note path is owned by the scoped binding itself.

    A note inside an initialized nested child vault belongs to that child, not
    to the parent binding the request selected (#2313 / MVR-05B2 nested rule).
    """

    if scoped.root is None:
        return False
    root = Path(os.path.realpath(scoped.root))
    target = Path(os.path.realpath(resolved))
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return nearest_enclosing_vault_root(target, search_root=root) == root


def route_read_vault_root_or_selection_required(
    *,
    requested_note_path: str | None = None,
) -> Path | JSONResponse:
    """The vault root a migrated route read renders: the bound binding, else legacy.

    A scoped zero-binding selection renders the same no-vault picker state as a
    carrier-free request with nothing selected, without consulting the process
    selection.
    """

    scoped = _SCOPED_ROUTE_READ.get()
    if scoped is not None:
        if scoped.root is None:
            return vault_selection_required_json(requested_note_path=requested_note_path)
        return scoped.root
    return compatibility_vault_root_or_selection_required(requested_note_path=requested_note_path)


__all__ = [
    "ScopedRouteRead",
    "current_scoped_route_read",
    "reject_carrier_on_legacy_read",
    "reject_scoped_vault_mutation",
    "require_scoped_read_context",
    "resolve_optional_scoped_read_context",
    "resolve_read_context",
    "route_read_vault_root_or_selection_required",
    "scoped_note_path_owned_by_binding",
    "scoped_route_read",
    "scoped_route_read_window",
]
