"""Starlette-version-stable route introspection for tests.

Starlette wraps ``include_router``-registered sub-routers in an internal
representation that changes across versions (for example a private
``_IncludedRouter`` on Starlette >=1.3, replacing the flattened ``Route`` /
``APIRoute`` objects ``app.routes`` held on Starlette 1.2.x). Tests that
walked ``app.routes`` and read ``.path`` / ``.methods`` directly broke on
that change -- and one of them (the P-3 read-purity property) silently
enumerated only a handful of routes out of dozens, rather than failing
loudly.

``app.openapi()`` is FastAPI's own stable, public view of every registered
path and its declared HTTP operations, independent of how Starlette stores
included sub-routers internally. Use it instead of walking ``app.routes``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def openapi_paths(app: FastAPI) -> dict[str, dict[str, Any]]:
    """Every path in ``app``'s OpenAPI schema, mapped to its operations."""
    return app.openapi()["paths"]
