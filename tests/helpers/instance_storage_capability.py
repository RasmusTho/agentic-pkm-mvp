"""Explicit test-only access to the private MVR storage capability."""

from app.instance._storage_boundary import (
    _STORAGE_MUTATION_CAPABILITY,
    _StorageMutationCapability,
)


def storage_mutation_capability() -> _StorageMutationCapability:
    return _STORAGE_MUTATION_CAPABILITY


STORAGE_MUTATION_CAPABILITY = storage_mutation_capability()
