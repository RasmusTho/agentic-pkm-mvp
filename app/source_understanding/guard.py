"""Enforcement guards for source-understanding non-mutation flags.

Source understanding is a read-only projection seam. The flags ``durable_writes``
and ``memory_writes`` on ``SourceUnderstandingPacket`` (and related objects)
declare that *no* durable or memory write has occurred or is permitted.

Previously these flags were advisory: nothing enforced that a code path actually
respected them. This module adds a fail-closed guard: any code path that is about
to perform a durable or memory write *must* call the corresponding assert before
doing so. If the flag is ``False``, the assert raises immediately.

Usage (hypothetical future write path)::

    from app.source_understanding.guard import assert_durable_write_allowed
    assert_durable_write_allowed(packet)   # raises if durable_writes is False
    # ... proceed with the write ...

Today (2026-06-13) no write path exists in source understanding, so these guards
will never be reached in normal execution. They are defensive infrastructure that
makes the non-mutation contract fail-closed if a write path is ever added.

Issue: #1946
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


class SourceUnderstandingMutationError(RuntimeError):
    """Raised when a write is attempted while the corresponding mutation flag is False."""

    def __init__(self, flag_name: str) -> None:
        self.flag_name = flag_name
        super().__init__(
            f"Source-understanding mutation blocked: '{flag_name}' is False. "
            "Source understanding is a read-only projection seam. "
            "Set the flag to True only through a governed mutation path."
        )


@runtime_checkable
class _HasDurableWritesFlag(Protocol):
    durable_writes: bool


@runtime_checkable
class _HasMemoryWritesFlag(Protocol):
    memory_writes: bool


def assert_durable_write_allowed(obj: _HasDurableWritesFlag) -> None:
    """Raise ``SourceUnderstandingMutationError`` if ``obj.durable_writes`` is False.

    Call this guard at the entry of any code path that would perform a durable
    (vault) write originating from a source-understanding object.
    """
    if not obj.durable_writes:
        raise SourceUnderstandingMutationError("durable_writes")


def assert_memory_write_allowed(obj: _HasMemoryWritesFlag) -> None:
    """Raise ``SourceUnderstandingMutationError`` if ``obj.memory_writes`` is False.

    Call this guard at the entry of any code path that would perform an
    agentic-memory write originating from a source-understanding object.
    """
    if not obj.memory_writes:
        raise SourceUnderstandingMutationError("memory_writes")


__all__ = [
    "SourceUnderstandingMutationError",
    "assert_durable_write_allowed",
    "assert_memory_write_allowed",
]
