"""Private capability for dormant MVR registry and ownership mutations."""

from __future__ import annotations


class RegistryError(RuntimeError):
    """Base class for fail-closed registry errors."""


class CapabilityNotReadyError(RegistryError):
    """A later delivery floor has not been installed."""


_CONSTRUCTION_SEAL = object()


class _StorageMutationCapability:
    """Identity capability whose constructor seal is private to this module."""

    __slots__ = ()

    def __new__(cls, construction_seal: object | None = None) -> _StorageMutationCapability:
        if construction_seal is not _CONSTRUCTION_SEAL:
            raise TypeError("storage mutation capability is not caller-constructible")
        return super().__new__(cls)

    def __init__(self, construction_seal: object | None = None) -> None:
        if construction_seal is not _CONSTRUCTION_SEAL:
            raise TypeError("storage mutation capability is not caller-constructible")


_STORAGE_MUTATION_CAPABILITY = _StorageMutationCapability(_CONSTRUCTION_SEAL)


def _require_storage_mutation_capability(
    capability: _StorageMutationCapability | None,
) -> None:
    if capability is not _STORAGE_MUTATION_CAPABILITY:
        raise CapabilityNotReadyError(
            "private MVR storage mutation capability is required"
        )


__all__: list[str] = []
