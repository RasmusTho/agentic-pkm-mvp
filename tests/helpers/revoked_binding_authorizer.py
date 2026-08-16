"""Test-only GOV authorizer for exercising revoked-verdict consumers.

Production MVR-05A deliberately has no revocation producer or revocation-bearing authority
state. Tests that pin how consumers react to a future revoked verdict use this protocol
implementation instead of opening a production mutation capability.
"""

from __future__ import annotations

from app.governance.binding_authority import (
    DENY_REVOKED,
    BindingAuthorizationRequest,
    BindingVerdict,
    RegistryBindingAuthorizer,
    authorization_epoch,
)


class RevokedBindingAuthorizer:
    __test__ = False

    def __init__(self, delegate: RegistryBindingAuthorizer) -> None:
        self._delegate = delegate
        self._revoked: set[str] = set()

    def revoke_for_test(self, vault_binding_id: str) -> None:
        self._revoked.add(vault_binding_id)

    def restore_for_test(self, vault_binding_id: str) -> None:
        self._revoked.discard(vault_binding_id)

    def set_binding(
        self,
        vault_binding_id: str,
        binding_revision: int,
        *,
        available: bool = True,
    ) -> None:
        self._delegate.set_binding(
            vault_binding_id,
            binding_revision,
            available=available,
        )

    def binding_revision(self, vault_binding_id: str) -> int:
        return self._delegate.binding_revision(vault_binding_id)

    def authorize(self, request: BindingAuthorizationRequest) -> BindingVerdict:
        if request.vault_binding_id not in self._revoked:
            return self._delegate.authorize(request)
        revision = self._delegate.binding_revision(request.vault_binding_id)
        return BindingVerdict(
            vault_binding_id=request.vault_binding_id,
            status="deny",
            reason=DENY_REVOKED,
            epoch=authorization_epoch(
                principal=request.principal,
                vault_binding_id=request.vault_binding_id,
                binding_revision=revision,
                status="deny",
                policy_revision=self._delegate.policy_revision,
            ),
        )
