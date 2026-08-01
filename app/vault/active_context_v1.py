"""Runtime-capable ActiveContextSet V1 (MVR-03).

Owner contract: `docs/contracts/ACTIVE_CONTEXT_SET.md :: Multi-Vault Runtime V1 Decision`.
Task specification: `docs/MULTI_VAULT_RUNTIME/VERSION_ACTIVE_CONTEXT_SELECTION.md`.

This module carries the *shape* of one immutable, generation-stamped context snapshot and
nothing else. It deliberately holds no store, no authorization decision, and no HTTP carrier:

- `app/instance/context_selection.py` owns the TTL-bound selection store and the resolver,
- `app/governance/binding_authority.py` owns the per-binding GOV verdict,
- MVR-05B (#3860) owns production request-header propagation, which stays sealed here.

The v0 adapter in `app/vault/active_context.py` remains the transitional projection for
callers that still only have a scalar `VaultContext`. This is the same seam versioned
forward, not a rival context type (`docs/MULTI_VAULT_RUNTIME/README.md` reconciliation note
for #2356).

Two invariants are structural rather than merely documented:

- **Selection never grants authority.** No field here names an action, a write class, or a
  permission. Those stay separate GOV decision inputs derived per call from the server-owned
  endpoint contract.
- **Raw bearer capability never lands in a snapshot.** Only
  `selection_capability_digest` -- a non-reversible digest -- may appear, so a snapshot can be
  logged, receipted, and used as cache-key material without leaking the bearer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

ACTIVE_CONTEXT_SET_V1 = "active_context_set.v1"

#: The server-owned canonical scope used when no narrower WSP scope is declared.
CANONICAL_DEFAULT_SCOPE = "default"

#: A no-workspace state is explicit and typed. It is never an empty/None workspace id,
#: because "no workspace" and "workspace unknown" must not be the same value.
WorkspaceStateKind = Literal["workspace", "no_workspace"]

WORKSPACE_STATE_BOUND: WorkspaceStateKind = "workspace"
WORKSPACE_STATE_NONE: WorkspaceStateKind = "no_workspace"

#: A healthy zero-binding no-vault context is distinct from a degraded one. A degraded
#: context cannot authorize an effect and must not masquerade as ordinary no-vault.
ContextPosture = Literal["healthy", "degraded"]

#: Bounded, machine-readable degradation reasons. Free-form strings are rejected so a
#: consumer can branch on posture without parsing prose.
DEGRADED_REASONS: frozenset[str] = frozenset(
    {
        "binding_unavailable",
        "binding_invalid",
        "binding_unauthorized",
        "binding_stale",
    }
)

#: Server-derived authentication subjects that may map to the local delegated role.
#: A client header can claim none of them; see `app/auth.py::resolve_auth_subject`.
AuthSubject = Literal["trusted_loopback", "trusted_companion_proxy", "api_key_credential"]

PrincipalKind = Literal["human", "delegated_operator_role"]


class ActiveContextError(RuntimeError):
    """Base class for fail-closed ActiveContextSet V1 errors."""


class DegradedContextError(ActiveContextError):
    """A degraded context was asked to authorize or carry an effect."""


@dataclass(frozen=True)
class WorkspaceState:
    """Explicit workspace identity or the typed no-workspace state.

    Workspace is never inferred from vault, path, scope, or principal. The constructor
    enforces that so a caller cannot smuggle "unknown" in as "no workspace".
    """

    state: WorkspaceStateKind
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        if self.state == WORKSPACE_STATE_BOUND:
            if not self.workspace_id:
                raise ActiveContextError("a bound workspace state requires a workspace id")
        elif self.state == WORKSPACE_STATE_NONE:
            if self.workspace_id is not None:
                raise ActiveContextError("the no_workspace state cannot carry a workspace id")
        else:  # pragma: no cover - Literal keeps this unreachable in typed callers
            raise ActiveContextError(f"unknown workspace state: {self.state!r}")

    @classmethod
    def none(cls) -> WorkspaceState:
        return cls(state=WORKSPACE_STATE_NONE)

    @classmethod
    def bound(cls, workspace_id: str) -> WorkspaceState:
        return cls(state=WORKSPACE_STATE_BOUND, workspace_id=workspace_id)

    @property
    def is_bound(self) -> bool:
        return self.state == WORKSPACE_STATE_BOUND

    def cache_component(self) -> str:
        return f"{self.state}:{self.workspace_id or ''}"


@dataclass(frozen=True)
class PrincipalContext:
    """The server-resolved principal for one snapshot.

    `principal_id` is either an authenticated human principal or the instance-scoped
    delegated operator role owned by the auth/GOV boundary. It is never derived from
    `appInstallId`, from an API key value, from a path, or from a client-supplied string.
    It carries no permission: GOV decides admissibility per call.
    """

    principal_id: str
    principal_kind: PrincipalKind
    subject: AuthSubject

    def __post_init__(self) -> None:
        if not self.principal_id:
            raise ActiveContextError("principal id is required; unresolved principals fail closed")

    def cache_component(self) -> str:
        return f"{self.principal_kind}:{self.principal_id}"


@dataclass(frozen=True)
class ActiveContextBinding:
    """One immutable source binding inside a snapshot.

    `binding_revision` is the monotonic path/device/authority-provenance revision of the
    registry entry. `authorization_epoch` is the non-secret fingerprint of the GOV verdict
    that admitted this binding. A change to either rotates the snapshot generation.
    """

    vault_binding_id: str
    binding_revision: int
    authorization_epoch: str
    vault_id: str | None = None
    local_instance_id: str | None = None
    label: str | None = None

    def cache_component(self) -> str:
        return f"{self.vault_binding_id}@{self.binding_revision}#{self.authorization_epoch}"


@dataclass(frozen=True)
class ActiveContextSetV1:
    """One immutable, generation-stamped active context snapshot.

    All downstream work for one request uses exactly one instance of this. Changing a
    session selection produces a *new* snapshot with a higher generation; in-flight work
    keeps the object it already holds, so no in-flight rebinding is possible by
    construction.
    """

    context_id: str
    generation: int
    workspace: WorkspaceState
    scope: str
    sphere_memberships: tuple[str, ...]
    situated_identity: str | None
    principal_context: PrincipalContext
    instance_identity: str
    source_bindings: tuple[ActiveContextBinding, ...]
    registry_revision: int
    authorization_epoch: str
    selection_provenance: str
    posture: ContextPosture = "healthy"
    degraded_reason: str | None = None
    selection_capability_digest: str | None = None
    topology_posture: str = "single-node"
    expires_at: float | None = None
    version: str = ACTIVE_CONTEXT_SET_V1
    #: Reserved for MVR-04. It stays sealed absent until a durable dimension registry
    #: exists; no endpoint may set it and no client string can become a dimension.
    dimension_filter: None = field(default=None)

    def __post_init__(self) -> None:
        if not self.context_id:
            raise ActiveContextError("context id is required")
        if self.generation < 1:
            raise ActiveContextError("generation is monotonic and starts at 1")
        if not self.scope:
            raise ActiveContextError(
                "scope is server-derived and always present; "
                f"use {CANONICAL_DEFAULT_SCOPE!r} when no narrower scope is declared"
            )
        if self.posture == "degraded":
            if self.degraded_reason not in DEGRADED_REASONS:
                raise ActiveContextError(
                    "a degraded context requires a bounded reason from DEGRADED_REASONS"
                )
        elif self.degraded_reason is not None:
            raise ActiveContextError("a healthy context cannot carry a degraded reason")
        if self.dimension_filter is not None:  # pragma: no cover - typed as None
            raise ActiveContextError("the dimension filter stays sealed absent until MVR-04")

    @property
    def is_no_vault(self) -> bool:
        """True for the healthy zero-binding no-vault state only.

        A degraded zero-binding snapshot is *not* no-vault; collapsing the two is the
        failure mode the contract names.
        """

        return self.posture == "healthy" and not self.source_bindings

    @property
    def binding_ids(self) -> tuple[str, ...]:
        return tuple(binding.vault_binding_id for binding in self.source_bindings)

    def require_effect_capable(self) -> None:
        """Fail closed before any effect runs on a degraded snapshot."""

        if self.posture == "degraded":
            raise DegradedContextError(
                f"degraded active context cannot authorize an effect: {self.degraded_reason}"
            )

    def context_identity_components(self) -> tuple[str, ...]:
        """Every context-affecting input, in a stable order.

        This is the full-context identity the contract requires for caches, receipts, and
        downstream context artifacts. Binding plus generation alone is deliberately *not*
        sufficient: two bearer selections may share both while carrying different
        workspace, scope, sphere, situated identity, capability digest, or filter.
        """

        return (
            f"version={self.version}",
            f"context_id={self.context_id}",
            f"generation={self.generation}",
            f"registry_revision={self.registry_revision}",
            f"authorization_epoch={self.authorization_epoch}",
            f"workspace={self.workspace.cache_component()}",
            f"principal={self.principal_context.cache_component()}",
            f"scope={self.scope}",
            "spheres=" + ",".join(self.sphere_memberships),
            f"situated_identity={self.situated_identity or ''}",
            f"selection_capability_digest={self.selection_capability_digest or ''}",
            f"dimension_filter={'' if self.dimension_filter is None else self.dimension_filter}",
            "bindings=" + "|".join(binding.cache_component() for binding in self.source_bindings),
            f"posture={self.posture}",
        )


def selection_capability_digest(raw_selection_id: str) -> str:
    """Non-reversible digest of a bearer selection id.

    The raw bearer is never logged, receipted, or used directly as cache-key material.
    Only this digest may appear in bounded context identity.
    """

    return hashlib.sha256(f"active-context-selection:{raw_selection_id}".encode()).hexdigest()


__all__ = [
    "ACTIVE_CONTEXT_SET_V1",
    "CANONICAL_DEFAULT_SCOPE",
    "DEGRADED_REASONS",
    "WORKSPACE_STATE_BOUND",
    "WORKSPACE_STATE_NONE",
    "ActiveContextBinding",
    "ActiveContextError",
    "ActiveContextSetV1",
    "AuthSubject",
    "ContextPosture",
    "DegradedContextError",
    "PrincipalContext",
    "PrincipalKind",
    "WorkspaceState",
    "selection_capability_digest",
]
