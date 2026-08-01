"""Per-binding GOV authorization for the MVR-03 active-context seam.

`docs/MULTI_VAULT_RUNTIME/README.md :: Cross-Task Invariants / Interaction Safety`:
"Selection cannot upgrade authority. Every binding is independently authorized by GOV."

This module is the seam that makes that enforceable. It is deliberately small: one request
type, one verdict type, one protocol, and one shipped implementation whose policy is exactly
what the current single-user runtime can truthfully decide. It does not invent a policy
engine the contract never asked for.

The important structural property is the *shape*, not the policy: action, write class, and
required permission arrive here as separate GOV decision inputs derived per call from the
server-owned endpoint/command contract. They are never read off the stored selection, and
they never enter WSP `scope`. That is what lets one selection support a separately authorized
read and a separately authorized write without either an over-broad stored scope or a scope
mismatch.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Protocol

from app.vault.active_context_v1 import PrincipalContext

VerdictStatus = Literal["allow", "deny"]

#: Bounded deny reasons. A consumer branches on these; it never parses prose.
DENY_BINDING_UNKNOWN = "binding_unknown"
DENY_PRINCIPAL_UNRESOLVED = "principal_unresolved"
DENY_REVOKED = "binding_revoked"


class BindingAuthorizationError(RuntimeError):
    """A resolved binding was denied by GOV.

    Raised instead of returning a snapshot, so no `ActiveContextSet` containing the denied
    binding is ever reissued.
    """

    def __init__(self, verdict: BindingVerdict) -> None:
        super().__init__(f"binding {verdict.vault_binding_id} denied: {verdict.reason}")
        self.verdict = verdict


@dataclass(frozen=True)
class BindingAuthorizationRequest:
    """One GOV decision input set for exactly one binding.

    `action`, `write_class`, and `required_permission` are supplied by the caller's
    server-owned endpoint/command contract for *this* call. They are not stored in, and
    cannot be read from, the selection record.
    """

    principal: PrincipalContext
    vault_binding_id: str
    action: str
    write_class: str
    required_permission: str


@dataclass(frozen=True)
class BindingVerdict:
    """The GOV answer for one binding, plus the non-secret epoch it was decided under.

    `epoch` is a fingerprint, not a secret and not a capability. It exists so a later
    resolution can detect that the verdict changed and rotate the context generation
    (or invalidate the selection) before downstream work starts.
    """

    vault_binding_id: str
    status: VerdictStatus
    reason: str
    epoch: str

    @property
    def allowed(self) -> bool:
        return self.status == "allow"


class BindingAuthorizer(Protocol):
    """The GOV seam every active-context resolution calls once per binding."""

    def authorize(self, request: BindingAuthorizationRequest) -> BindingVerdict: ...


def authorization_epoch(
    *,
    principal: PrincipalContext,
    vault_binding_id: str,
    binding_revision: int,
    status: VerdictStatus,
    policy_revision: str,
) -> str:
    """Derive a stable, non-secret epoch fingerprint for one verdict.

    Nothing secret goes in: the principal *id* is an opaque server-minted role id, never a
    credential. The fingerprint changes whenever the decision inputs change, which is
    exactly the signal the resolver needs to rotate a generation.
    """

    material = "|".join(
        (
            "gov.binding-authority.v1",
            policy_revision,
            principal.principal_kind,
            principal.principal_id,
            vault_binding_id,
            str(binding_revision),
            status,
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def snapshot_authorization_epoch(verdicts: tuple[BindingVerdict, ...]) -> str:
    """Fold per-binding epochs into the snapshot-wide authorization epoch."""

    material = "|".join(f"{v.vault_binding_id}:{v.epoch}" for v in verdicts)
    return hashlib.sha256(f"gov.snapshot-epoch.v1|{material}".encode()).hexdigest()[:32]


@dataclass(frozen=True)
class _KnownBinding:
    vault_binding_id: str
    binding_revision: int
    available: bool = True
    revoked: bool = False


class RegistryBindingAuthorizer:
    """The shipped GOV policy for the current single-user runtime.

    It authorizes a binding when, and only when, both of the following hold:

    - a principal was resolved by the auth/GOV boundary (an unresolved principal fails
      closed -- there is no anonymous admission),
    - the binding is a known, registered, non-revoked registry entry.

    **Availability is deliberately not an authorization input.** A binding whose content root
    is temporarily unreachable is still a binding this principal is *allowed* to use; it is
    an unhealthy one. Denying it here would collapse two different states the contract keeps
    apart: `deny` raises and reissues nothing, while unavailable produces a **degraded**
    snapshot with a bounded reason. Folding availability into GOV would make the degraded
    posture unreachable through production wiring, so the resolver owns it instead.

    This is honest about what the runtime can decide today. It is a real decision point, not
    a rubber stamp: each deny branch is exercised by
    `tests/api/test_active_context_resolution.py::test_each_binding_is_authorized_independently`.

    Later slices replace the policy without changing this seam's shape.
    """

    policy_revision = "single-user-registry.v1"

    def __init__(
        self,
        known: dict[str, int] | None = None,
        *,
        unavailable: frozenset[str] = frozenset(),
        revoked: frozenset[str] = frozenset(),
    ) -> None:
        self._known: dict[str, _KnownBinding] = {
            binding_id: _KnownBinding(
                vault_binding_id=binding_id,
                binding_revision=revision,
                available=binding_id not in unavailable,
                revoked=binding_id in revoked,
            )
            for binding_id, revision in (known or {}).items()
        }

    def set_binding(
        self,
        vault_binding_id: str,
        binding_revision: int,
        *,
        available: bool = True,
        revoked: bool = False,
    ) -> None:
        """Record current registry truth for one binding.

        Callers hand the authorizer the binding revision they resolved from the registry so
        the verdict epoch is bound to that exact revision.
        """

        self._known[vault_binding_id] = _KnownBinding(
            vault_binding_id=vault_binding_id,
            binding_revision=binding_revision,
            available=available,
            revoked=revoked,
        )

    def binding_revision(self, vault_binding_id: str) -> int:
        known = self._known.get(vault_binding_id)
        return known.binding_revision if known is not None else 0

    def authorize(self, request: BindingAuthorizationRequest) -> BindingVerdict:
        known = self._known.get(request.vault_binding_id)
        revision = known.binding_revision if known is not None else 0

        def _verdict(status: VerdictStatus, reason: str) -> BindingVerdict:
            return BindingVerdict(
                vault_binding_id=request.vault_binding_id,
                status=status,
                reason=reason,
                epoch=authorization_epoch(
                    principal=request.principal,
                    vault_binding_id=request.vault_binding_id,
                    binding_revision=revision,
                    status=status,
                    policy_revision=self.policy_revision,
                ),
            )

        if not request.principal.principal_id:
            return _verdict("deny", DENY_PRINCIPAL_UNRESOLVED)
        if known is None:
            return _verdict("deny", DENY_BINDING_UNKNOWN)
        if known.revoked:
            return _verdict("deny", DENY_REVOKED)
        # Availability is intentionally absent here; see the class docstring.
        return _verdict("allow", "registered_binding_for_resolved_principal")


__all__ = [
    "DENY_BINDING_UNKNOWN",
    "DENY_PRINCIPAL_UNRESOLVED",
    "DENY_REVOKED",
    "BindingAuthorizationError",
    "BindingAuthorizationRequest",
    "BindingAuthorizer",
    "BindingVerdict",
    "RegistryBindingAuthorizer",
    "authorization_epoch",
    "snapshot_authorization_epoch",
]
