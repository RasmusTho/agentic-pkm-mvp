"""BuilderOps cockpit registry API: a read-time join, never a second truth.

The cockpit reads the dispatcher store, verification runs, and deploy receipts
at request time and returns a payload that names its own per-source freshness.
There are no mutation endpoints here by design (see
docs/BUILDEROPS_COCKPIT/README.md): the surface owns no attention state, no
approvals, and no persistence.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.builderops.cockpit_registry import build_registry
from app.dispatcher.config import load_paths

router = APIRouter(prefix="/cockpit", tags=["cockpit"])

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _deploy_receipt_dir() -> Path:
    override = os.environ.get("COCKPIT_DEPLOY_RECEIPT_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "ops" / "deployments"


@router.get("/registry")
async def registry() -> dict[str, Any]:
    """Recompute the registry from the authorities. Nothing is cached."""
    paths = load_paths()
    return build_registry(
        db_path=paths.db_path,
        deploy_receipt_dir=_deploy_receipt_dir(),
    )


__all__ = ["router"]
