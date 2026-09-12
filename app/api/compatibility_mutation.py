"""MVR-05B compatibility mutation precondition and fail-closed guards."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, Header, HTTPException, Request, status

from app.api.routes.active_context_selection import build_selection_service, get_selection_store
from app.auth import api_key_header, resolve_auth_subject
from app.instance.settings_rebind import SettingsRebindStore, compatibility_ingress_window
from app.instance.vault_registry import VaultRegistryStore
from app.settings import settings

HEADER_COMPATIBILITY_PRECONDITION = "X-Compatibility-Write-Precondition"
CAPABILITY = "mvr05c_scoped_write"
_TOKEN_TTL_SECONDS = 600


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


def reject_scoped_vault_mutation(request: Request) -> None:
    """Seal every legacy vault mutation from consuming a scoped bearer."""

    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and (
        request.headers.get("X-Active-Context-Session")
        or request.headers.get("X-Active-Context-Override")
    ):
        raise _capability_not_ready()


def require_compatibility_mutation(
    request: Request,
    api_key: str | None = Depends(api_key_header),
    precondition: str | None = Header(default=None, alias=HEADER_COMPATIBILITY_PRECONDITION),
) -> Iterator[CompatibilityMutationProof]:
    """Hold the compatibility ingress window through the governed route effect."""

    if request.headers.get("X-Active-Context-Session") or request.headers.get(
        "X-Active-Context-Override"
    ) or not precondition:
        raise _capability_not_ready()
    try:
        registry = _registry()
    except Exception as exc:
        raise _capability_not_ready() from exc

    with compatibility_ingress_window(registry):
        try:
            proof = _current_proof(
                precondition,
                request=request,
                api_key=api_key,
                registry=registry,
            )
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise _capability_not_ready() from exc
        request.state.compatibility_mutation_proof = proof
        yield proof


__all__ = [
    "HEADER_COMPATIBILITY_PRECONDITION",
    "CompatibilityMutationProof",
    "issue_compatibility_precondition",
    "reject_scoped_vault_mutation",
    "require_compatibility_mutation",
]
