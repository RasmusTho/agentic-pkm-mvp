from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.knowledge.contracts import WriteReceipt


class KnowledgeError(RuntimeError):
    """Base error for knowledge-port operations."""


class KnowledgeConfigError(KnowledgeError):
    """Raised when knowledge-port policy/config is invalid."""


class KnowledgeCapabilityError(KnowledgeError):
    """Raised when a selected adapter cannot perform an operation."""


class KnowledgeDependencyError(KnowledgeError):
    """Raised when runtime dependencies for the selected adapter are missing."""


class KnowledgeTransportError(KnowledgeCapabilityError):
    """Raised when an adapter transport fails but a fallback may still be viable."""


class KnowledgeWriteConflict(KnowledgeError):
    """Raised when a write precondition cannot be satisfied safely."""

    def __init__(self, message: str, *, receipt: WriteReceipt | None = None) -> None:
        super().__init__(message)
        self.receipt = receipt


__all__ = [
    "KnowledgeError",
    "KnowledgeConfigError",
    "KnowledgeCapabilityError",
    "KnowledgeDependencyError",
    "KnowledgeTransportError",
    "KnowledgeWriteConflict",
]
