from __future__ import annotations

from fastapi import APIRouter

from app.version import get_runtime_version

router = APIRouter()


@router.get("/version")
async def version() -> dict[str, str]:
    """Return the git SHA and build timestamp baked into this image at build time.

    Values originate from the ``VCS_REF`` and ``BUILT_AT`` environment variables
    set via ``ENV`` in the ``Dockerfile``.  Outside Docker (local dev) ``VCS_REF``
    falls back to a live ``git rev-parse HEAD`` call.
    """
    return get_runtime_version()


__all__ = ["router"]
