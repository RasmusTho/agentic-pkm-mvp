"""Yggdrasil runtime vertical slice 1 — capture to bounded context.

A clean, corpus-backed conformance harness implementing the first executable Yggdrasil
architecture chain:

    capture -> MetadataBundle -> DRI segment -> retrieval prefilter -> RetrievalResult -> ContextEnvelope

This package is intentionally NOT a rewire of the legacy ``app/`` capture/index/retrieval
pipeline (see ``docs/YGGDRASIL_RUNTIME_SLICE_1/INTEGRATION_MAP.md``). It operates over the
synthetic anti-contamination corpus under ``tests/evals/fixtures/`` and an in-memory object
store — no real vault, no durable mutation, no WriteGuard write path.

Only the in-slice submodules exist here (``metadata``, ``capture``, and — as later tasks land —
``dri``, ``corpus``, ``cross_scope``, ``retrieval``, ``context``). Future-slice modules
(``authority``, ``storage``, ``execution``, ``memory``, ``agent``, ``scope``, ``sync``,
``projection``, ``observability``) are deliberately absent so their invariant skeletons keep
xfail-ing until their slice is built.
"""

from __future__ import annotations

__all__ = ["metadata", "capture"]
