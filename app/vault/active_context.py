"""Transitional adapter for `docs/contracts/ACTIVE_CONTEXT_SET.md`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.vault.manager import VaultContext


ActiveContextFieldStatus = Literal["known", "unknown"]


@dataclass(frozen=True)
class ActiveContextField:
    status: ActiveContextFieldStatus
    value: str | None = None
    reason: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class ActiveContextSourceBinding:
    kind: str
    binding_ref: str
    status: str
    label: str | None = None
    source_id: str | None = None
    implementation_detail: bool = True


@dataclass(frozen=True)
class ActiveContextSet:
    version: str
    context_id: ActiveContextField
    generation: ActiveContextField
    workspace: ActiveContextField
    scope: ActiveContextField
    sphere: ActiveContextField
    situated_identity: ActiveContextField
    principal_context: ActiveContextField
    topology_posture: ActiveContextField
    source_bindings: tuple[ActiveContextSourceBinding, ...]
    degraded_mode: bool


class ActiveContextResolver:
    """Transitional WSP adapter from VaultContext to ActiveContextSet.

    The current runtime still carries active-vault state. This resolver keeps
    that state as a source binding and explicitly marks the target context
    fields that the vault runtime cannot yet resolve.
    """

    version = "active_context_set.v0"

    def resolve(self, context: VaultContext) -> ActiveContextSet:
        return ActiveContextSet(
            version=self.version,
            context_id=_unknown(
                "No ActiveContextSet identifier exists yet; current runtime only exposes vault selection."
            ),
            generation=_unknown(
                "No atomic ActiveContextSet generation is emitted by the current vault runtime."
            ),
            workspace=_unknown(
                "Workspace is not yet separate from the transitional active-vault source binding."
            ),
            scope=_unknown("Scope is not resolved by the current active-vault runtime."),
            sphere=_unknown("Sphere is not resolved by the current active-vault runtime."),
            situated_identity=_unknown(
                "Situated identity is not yet resolved; VaultContext.local_instance_id is a local clone identity."
            ),
            principal_context=_unknown(
                "Principal context is not yet resolved; VaultContext.machine_role is a local clone posture."
            ),
            topology_posture=ActiveContextField(
                status="known",
                value="single-node",
                source="transitional active-vault runtime",
            ),
            source_bindings=_source_bindings(context),
            degraded_mode=context.status != "selected",
        )


def _unknown(reason: str) -> ActiveContextField:
    return ActiveContextField(status="unknown", reason=reason)


def _source_bindings(context: VaultContext) -> tuple[ActiveContextSourceBinding, ...]:
    if not context.active_vault_path:
        return ()
    return (
        ActiveContextSourceBinding(
            kind="vault",
            binding_ref=context.active_vault_path,
            status="bound" if context.status == "selected" else context.status,
            label=context.active_vault_name,
            source_id=context.active_vault_id,
        ),
    )


__all__ = [
    "ActiveContextField",
    "ActiveContextResolver",
    "ActiveContextSet",
    "ActiveContextSourceBinding",
]
