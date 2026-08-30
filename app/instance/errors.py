"""Public exception types shared by instance and runtime boundaries."""

from __future__ import annotations


class RegistryError(RuntimeError):
    """Base class for fail-closed registry errors."""
