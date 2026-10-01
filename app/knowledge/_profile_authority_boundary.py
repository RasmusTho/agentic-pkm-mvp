"""Private identity capabilities for the governed profile contract.

The ProfileAgent runtime is the only production issuer of owner-confirmation and
ProfileAgent-write authority. Import access is protected by ``importlinter.ini``;
replaying serialized records does not create or recover one of these capabilities.
"""

from __future__ import annotations


class _CapabilityConstructionError(TypeError):
    """A private authority capability cannot be constructed by a caller."""


_CONSTRUCTION_SEAL = object()


class _OwnerConfirmationCapability:
    __slots__ = ()

    def __new__(cls, seal: object | None = None) -> _OwnerConfirmationCapability:
        if seal is not _CONSTRUCTION_SEAL:
            raise _CapabilityConstructionError(
                "owner confirmation capability is not caller-constructible"
            )
        return super().__new__(cls)

    def __init__(self, seal: object | None = None) -> None:
        if seal is not _CONSTRUCTION_SEAL:
            raise _CapabilityConstructionError(
                "owner confirmation capability is not caller-constructible"
            )


class _ProfileAgentWriteCapability:
    __slots__ = ()

    def __new__(cls, seal: object | None = None) -> _ProfileAgentWriteCapability:
        if seal is not _CONSTRUCTION_SEAL:
            raise _CapabilityConstructionError(
                "ProfileAgent write capability is not caller-constructible"
            )
        return super().__new__(cls)

    def __init__(self, seal: object | None = None) -> None:
        if seal is not _CONSTRUCTION_SEAL:
            raise _CapabilityConstructionError(
                "ProfileAgent write capability is not caller-constructible"
            )


class _DirectOwnerCorrectionCapability:
    __slots__ = ()

    def __new__(cls, seal: object | None = None) -> _DirectOwnerCorrectionCapability:
        if seal is not _CONSTRUCTION_SEAL:
            raise _CapabilityConstructionError(
                "owner correction capability is not caller-constructible"
            )
        return super().__new__(cls)

    def __init__(self, seal: object | None = None) -> None:
        if seal is not _CONSTRUCTION_SEAL:
            raise _CapabilityConstructionError(
                "owner correction capability is not caller-constructible"
            )


class _DirectOwnerReconciliationCapability:
    __slots__ = ()

    def __new__(cls, seal: object | None = None) -> _DirectOwnerReconciliationCapability:
        if seal is not _CONSTRUCTION_SEAL:
            raise _CapabilityConstructionError(
                "owner reconciliation capability is not caller-constructible"
            )
        return super().__new__(cls)

    def __init__(self, seal: object | None = None) -> None:
        if seal is not _CONSTRUCTION_SEAL:
            raise _CapabilityConstructionError(
                "owner reconciliation capability is not caller-constructible"
            )


_OWNER_CONFIRMATION_CAPABILITY = _OwnerConfirmationCapability(_CONSTRUCTION_SEAL)
_PROFILE_AGENT_WRITE_CAPABILITY = _ProfileAgentWriteCapability(_CONSTRUCTION_SEAL)
_DIRECT_OWNER_CORRECTION_CAPABILITY = _DirectOwnerCorrectionCapability(_CONSTRUCTION_SEAL)
_DIRECT_OWNER_RECONCILIATION_CAPABILITY = _DirectOwnerReconciliationCapability(_CONSTRUCTION_SEAL)


def _require_owner_confirmation_capability(capability: object | None) -> None:
    if capability is not _OWNER_CONFIRMATION_CAPABILITY:
        raise PermissionError("authenticated owner confirmation capability is required")


def _require_profile_agent_write_capability(capability: object | None) -> None:
    if capability is not _PROFILE_AGENT_WRITE_CAPABILITY:
        raise PermissionError("ProfileAgent write capability is required")


def _require_direct_owner_correction_capability(capability: object | None) -> None:
    if capability is not _DIRECT_OWNER_CORRECTION_CAPABILITY:
        raise PermissionError("direct-owner correction observation is required")


def _require_direct_owner_reconciliation_capability(capability: object | None) -> None:
    if capability is not _DIRECT_OWNER_RECONCILIATION_CAPABILITY:
        raise PermissionError("direct-owner write reconciliation is required")


__all__: list[str] = []
