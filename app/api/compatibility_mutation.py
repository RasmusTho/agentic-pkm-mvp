"""MVR-05B compatibility mutation precondition and fail-closed guards."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from fastapi import Depends, Header, HTTPException, Request, status

from app.api.routes.active_context_selection import build_selection_service, get_selection_store
from app.api.routes.vault_resolution import compatibility_selected_vault_root
from app.auth import api_key_header, resolve_auth_subject
from app.instance.filesystem_identity import (
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.instance.settings_rebind import SettingsRebindStore, compatibility_ingress_window
from app.instance.vault_registry import RegistryError, VaultRegistryStore
from app.settings import settings

HEADER_COMPATIBILITY_PRECONDITION = "X-Compatibility-Write-Precondition"
HEADER_ACTIVE_CONTEXT_SESSION = "X-Active-Context-Session"
HEADER_ACTIVE_CONTEXT_OVERRIDE = "X-Active-Context-Override"
CAPABILITY = "mvr05c_scoped_write"
_TOKEN_TTL_SECONDS = 600
_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_SELECTOR_BRIDGE_ATTRIBUTE = "__mvr05b3_compatibility_selector_bridge__"
_SEALS_INSIDE_ATTRIBUTE = "__mvr05b3_seals_write_window_inside_endpoint__"

_Endpoint = TypeVar("_Endpoint", bound=Callable[..., Any])


class CompatibilityMutationError(ValueError):
    """A migrated compatibility mutation cannot safely proceed."""


@dataclass(frozen=True)
class CompatibilityMutationProof:
    binding_id: str
    compatibility_revision: int
    principal_id: str


def _secret(instance_identity: str) -> bytes:
    configured = settings.api_key or os.getenv("COMPATIBILITY_PRECONDITION_SECRET", "")
    return (configured or f"active-context:{instance_identity}").encode("utf-8")


def _encode(payload: dict[str, object], *, secret: bytes) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=")
    signature = hmac.new(secret, body, hashlib.sha256).digest()
    return body.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def _decode(value: str, *, secret: bytes) -> dict[str, object]:
    try:
        body_text, signature_text = value.split(".", 1)
        body = body_text.encode()
        padding = "=" * (-len(signature_text) % 4)
        signature = base64.urlsafe_b64decode((signature_text + padding).encode())
        expected = hmac.new(secret, body, hashlib.sha256).digest()
        payload = json.loads(base64.urlsafe_b64decode(body + b"=" * (-len(body) % 4)))
    except (ValueError, TypeError, json.JSONDecodeError, base64.binascii.Error):
        raise CompatibilityMutationError("invalid compatibility precondition") from None
    if not hmac.compare_digest(signature, expected) or not isinstance(payload, dict):
        raise CompatibilityMutationError("invalid compatibility precondition")
    return payload


def _registry() -> VaultRegistryStore:
    raw_path = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not raw_path:
        raise CompatibilityMutationError("compatibility registry is not bound")
    return VaultRegistryStore(Path(raw_path).expanduser().resolve(strict=False))


def issue_compatibility_precondition(*, binding_id: str, principal_id: str, registry: VaultRegistryStore) -> str:
    snapshot = registry.load()
    rebind = SettingsRebindStore(registry).read()
    payload = {
        "v": 1,
        "binding": binding_id,
        "revision": rebind.desired_revision,
        "principal": principal_id,
        "expires": int(time.time()) + _TOKEN_TTL_SECONDS,
    }
    return _encode(payload, secret=_secret(snapshot.app_install_id))


def _current_proof(
    value: str,
    *,
    request: Request,
    api_key: str | None,
    registry: VaultRegistryStore,
) -> CompatibilityMutationProof:
    snapshot = registry.load()
    service = build_selection_service(get_selection_store())
    principal = service.derive(
        resolve_auth_subject(request, api_key), presented_credential=api_key
    ).principal.principal_id
    payload = _decode(value.strip(), secret=_secret(snapshot.app_install_id))
    if payload.get("expires", 0) <= int(time.time()):
        raise CompatibilityMutationError("stale compatibility precondition")
    binding_id = payload.get("binding")
    revision = payload.get("revision")
    token_principal = payload.get("principal")
    rebind = SettingsRebindStore(registry).read()
    if (
        not isinstance(binding_id, str)
        or not isinstance(revision, int)
        or not isinstance(token_principal, str)
        or token_principal != principal
        or rebind.candidate_binding_id != binding_id
        or rebind.desired_revision != revision
        or rebind.phase == "prepared"
        or rebind.reload_revision not in {None, rebind.desired_revision}
    ):
        raise CompatibilityMutationError("compatibility precondition no longer matches")
    return CompatibilityMutationProof(binding_id, revision, principal)


def _capability_not_ready() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error": "capability_not_ready", "capability": CAPABILITY},
    )


def _carrier_present(request: Request) -> bool:
    """A selection carrier is present even when its value is blank.

    Only an *absent* carrier is the legacy journey; a present-but-blank (or
    intermediary-emptied) carrier still identifies a scoped request.
    """

    return (
        HEADER_ACTIVE_CONTEXT_SESSION in request.headers
        or HEADER_ACTIVE_CONTEXT_OVERRIDE in request.headers
    )


def _route_dependency_calls(request: Request) -> tuple[Any, ...]:
    route = request.scope.get("route")
    return tuple(
        getattr(dependency, "dependency", None)
        for dependency in getattr(route, "dependencies", ()) or ()
    )


def _is_compatibility_route(request: Request) -> bool:
    """The distinct compatibility-scoped mutation route, identified by its guard."""

    return require_compatibility_mutation in _route_dependency_calls(request)


def compatibility_selector_bridge(endpoint: _Endpoint) -> _Endpoint:
    """Mark a legacy picker/initialize/reload/settings route as the selector bridge.

    These routes *move* the single compatibility binding (they run the
    SETTINGS-05C rebind activation, which takes the ingress lock exclusively),
    so they cannot themselves run inside the shared compatibility write window.
    They still refuse every scoped carrier and every migrated precondition.
    """

    setattr(endpoint, _SELECTOR_BRIDGE_ATTRIBUTE, True)
    return endpoint


def is_compatibility_selector_bridge(endpoint: object) -> bool:
    return bool(getattr(endpoint, _SELECTOR_BRIDGE_ATTRIBUTE, False))


def seals_write_window_inside(endpoint: _Endpoint) -> _Endpoint:
    """Mark a legacy write route that opens its own write-target window.

    A route that must also pin the process selection (``compatibility_selection_window``)
    takes the selection lock *first* and the shared ingress window inside it -- the
    same order ``/vault/select`` uses (selection lock, then exclusive ingress for the
    rebind). Holding the router-level window around such a route would invert that
    order and can deadlock against a concurrent picker. The router seal still
    refuses every scoped carrier and migrated precondition for it.
    """

    setattr(endpoint, _SEALS_INSIDE_ATTRIBUTE, True)
    return endpoint


def _seals_inside(endpoint: object) -> bool:
    return bool(getattr(endpoint, _SEALS_INSIDE_ATTRIBUTE, False))


def reject_scoped_vault_mutation(request: Request) -> None:
    """Seal every legacy vault mutation from consuming a scoped bearer.

    A mutation carrying a selection carrier (present even when blank) fails
    ``capability_not_ready`` until MVR-05C. A migrated client's precondition on
    any route other than the distinct compatibility-scoped mutation route is a
    stripped-carrier downgrade attempt and fails the same way, so a migrated
    write can never retry through the old single-binding route.
    """

    if request.method.upper() not in _MUTATION_METHODS:
        return
    if _carrier_present(request):
        raise _capability_not_ready()
    if HEADER_COMPATIBILITY_PRECONDITION in request.headers and not _is_compatibility_route(request):
        raise _capability_not_ready()


def _registry_or_none() -> VaultRegistryStore | None:
    raw_path = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not raw_path:
        return None
    registry = VaultRegistryStore(Path(raw_path).expanduser().resolve(strict=False))
    if not registry.path.exists():
        # Registry configured but not provisioned yet (no-vault idle boot): the
        # legacy scalar selection is still the only binding authority.
        return None
    return registry


def _registered_root(registry: VaultRegistryStore, binding_id: str) -> Path:
    registration = registry.load().registrations.get(binding_id)
    if registration is None:
        raise CompatibilityMutationError("compatibility binding is not registered")
    return Path(registration.path)


def _same_root(left: Path, right: Path) -> bool:
    return same_filesystem_root(
        resolve_filesystem_root_identity(left),
        resolve_filesystem_root_identity(right),
    )


SelectedRootResolver = Callable[[], "Path | None"]


@contextmanager
def compatibility_write_target_window(
    request: Request | None = None,
    *,
    selected_root: SelectedRootResolver = compatibility_selected_vault_root,
) -> Iterator[Path | None]:
    """Hold compatibility ingress and prove the legacy write target is the sole binding.

    The pre-05C seal for a carrier/precondition-free legacy write: once the
    SETTINGS-05C rebind floor is installed, the process-selected vault the write
    resolves to must be the freshly revalidated compatibility binding, read under
    the shared ingress lock that a rebind must take exclusively. A handoff in
    flight, an unregistered binding, or a process selection that differs from the
    durable compatibility binding (another process moved the picker) fails
    ``capability_not_ready`` before any filesystem, store, or outbox effect.

    Yields the binding root, or ``None`` on the pre-registry / pre-floor journey,
    where the process selection is the only binding there is. ``selected_root``
    is the router's own legacy selection accessor, so the proof is about the
    selection its routes actually resolve.
    """

    try:
        registry = _registry_or_none()
        snapshot = registry.load() if registry is not None else None
    except Exception as exc:  # an unreadable registry fails closed
        raise _capability_not_ready() from exc
    if registry is None or snapshot is None or snapshot.settings_rebind is None:
        yield None
        return
    # Resolve (and lazily load) the process selection *before* the shared lock:
    # lazy loading may itself run a rebind activation, which needs the lock
    # exclusively and would otherwise wait on this very request forever.
    selected = selected_root()
    with compatibility_ingress_window(registry):
        try:
            binding_id = SettingsRebindStore(registry).compatibility_binding_id()
            binding_root = _registered_root(registry, binding_id)
        except (RegistryError, CompatibilityMutationError) as exc:
            raise _capability_not_ready() from exc
        if selected is not None and not _same_root(selected, binding_root):
            raise _capability_not_ready()
        if request is not None:
            request.state.compatibility_write_root = binding_root
        yield binding_root


def make_vault_mutation_seal(
    selected_root: SelectedRootResolver = compatibility_selected_vault_root,
) -> Callable[[Request], Iterator[None]]:
    """Build the router dependency that is the pre-05C seal on vault-bound mutations.

    It refuses scoped carriers and misrouted migrated preconditions, then holds
    the compatibility write-target window through the route effect. The distinct
    compatibility route revalidates its own precondition inside
    :func:`require_compatibility_mutation`; the selector bridge moves the binding
    and is exempt from the window only, never from the carrier refusal.
    """

    def seal(request: Request) -> Iterator[None]:
        reject_scoped_vault_mutation(request)
        if (
            request.method.upper() in _MUTATION_METHODS
            and _seals_inside(request.scope.get("endpoint"))
        ):
            # Fail a misrouted legacy write before request parsing or any effect,
            # holding the window only momentarily (no selection lock is held here,
            # so nothing nests); the endpoint then re-proves the target inside its
            # own selection-then-ingress window.
            with compatibility_write_target_window(request, selected_root=selected_root):
                pass
            yield
            return
        if (
            request.method.upper() not in _MUTATION_METHODS
            or _is_compatibility_route(request)
            or is_compatibility_selector_bridge(request.scope.get("endpoint"))
            or _seals_inside(request.scope.get("endpoint"))
        ):
            yield
            return
        with compatibility_write_target_window(request, selected_root=selected_root):
            yield

    seal.__name__ = "seal_vault_mutation"
    seal.__qualname__ = "seal_vault_mutation"
    return seal


seal_vault_mutation = make_vault_mutation_seal()


def require_compatibility_write_root(request: Request, root: Path) -> None:
    """Fail closed when a route's own target differs from the sealed binding.

    Routes whose target is not the process selection (a canvas session pinned to
    the root it was opened on) call this after resolving that target.
    """

    expected = getattr(getattr(request, "state", None), "compatibility_write_root", None)
    if expected is not None and not _same_root(Path(root), Path(expected)):
        raise _capability_not_ready()


def capability_not_ready() -> HTTPException:
    """The structured pre-05C refusal, for routes that fail closed themselves."""

    return _capability_not_ready()


def require_compatibility_write_target(request: Request, target: Path) -> None:
    """Fail closed when a route writes a path outside the sealed binding root.

    For routes whose effect lands on a path they resolve themselves (a staged
    proposal's note file) rather than on the binding root as a whole.
    """

    expected = getattr(getattr(request, "state", None), "compatibility_write_root", None)
    if expected is None:
        return
    try:
        Path(target).expanduser().resolve().relative_to(Path(expected).expanduser().resolve())
    except ValueError as exc:
        raise _capability_not_ready() from exc


def require_compatibility_mutation(
    request: Request,
    api_key: str | None = Depends(api_key_header),
    precondition: str | None = Header(default=None, alias=HEADER_COMPATIBILITY_PRECONDITION),
) -> Iterator[CompatibilityMutationProof]:
    """Hold the compatibility ingress window through the governed route effect."""

    if _carrier_present(request) or not (precondition or "").strip():
        raise _capability_not_ready()
    try:
        registry = _registry()
    except Exception as exc:
        raise _capability_not_ready() from exc

    # Lazily loading the process selection may run a rebind activation, which
    # needs the ingress lock exclusively: load it before taking the lock.
    compatibility_selected_vault_root()
    with compatibility_ingress_window(registry):
        try:
            proof = _current_proof(
                precondition or "",
                request=request,
                api_key=api_key,
                registry=registry,
            )
            binding_root = _registered_root(registry, proof.binding_id)
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise _capability_not_ready() from exc
        # The precondition never selects a target: the route still resolves the
        # process selection and must prove (``require_compatibility_write_root``)
        # that it is exactly the precondition's binding before any effect.
        request.state.compatibility_mutation_proof = proof
        request.state.compatibility_write_root = binding_root
        yield proof


__all__ = [
    "HEADER_ACTIVE_CONTEXT_OVERRIDE",
    "HEADER_ACTIVE_CONTEXT_SESSION",
    "HEADER_COMPATIBILITY_PRECONDITION",
    "CompatibilityMutationProof",
    "capability_not_ready",
    "compatibility_selector_bridge",
    "compatibility_write_target_window",
    "is_compatibility_selector_bridge",
    "issue_compatibility_precondition",
    "make_vault_mutation_seal",
    "reject_scoped_vault_mutation",
    "seals_write_window_inside",
    "require_compatibility_mutation",
    "require_compatibility_write_root",
    "require_compatibility_write_target",
    "seal_vault_mutation",
]
