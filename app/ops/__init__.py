"""Operational harness helpers (test/promotion channel self-verification).

This package holds the *harness* preflight + bootstrap machinery that keeps the
test/promotion channel self-consistent and fail-loud (issue #1997). It carries
no product runtime behaviour: it validates and brings up the test channel that
the product runs inside, never the product data path itself.
"""

from __future__ import annotations

__all__: list[str] = []
