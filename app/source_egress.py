"""Context-local source-egress policy shared by acquisition boundaries.

Replay disables source acquisition only in its own execution context. ``ContextVar`` keeps
overlapping replay scopes independent and leaves concurrent acquisition threads/tasks untouched;
no module function is replaced or restored process-wide.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar, Token


class SourceEgressBlockedError(RuntimeError):
    """The current execution context reached source egress while it was forbidden."""


_SOURCE_EGRESS_ALLOWED: ContextVar[bool] = ContextVar(
    "source_egress_allowed", default=True
)


def assert_source_egress_allowed(seam_name: str) -> None:
    if not _SOURCE_EGRESS_ALLOWED.get():
        raise SourceEgressBlockedError(
            f"replay reached source-egress seam {seam_name!r}: replay must reproduce "
            "derived artifacts from the existing raw record without contacting the source"
        )


@contextlib.contextmanager
def block_source_egress() -> Iterator[None]:
    token: Token[bool] = _SOURCE_EGRESS_ALLOWED.set(False)
    try:
        yield
    finally:
        _SOURCE_EGRESS_ALLOWED.reset(token)


__all__ = [
    "SourceEgressBlockedError",
    "assert_source_egress_allowed",
    "block_source_egress",
]
