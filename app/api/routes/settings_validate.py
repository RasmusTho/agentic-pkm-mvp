from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.settings.validate import issues_to_json, validate_settings

router = APIRouter()


@router.get("/settings/validate")
async def settings_validate() -> dict[str, Any]:
    return issues_to_json(validate_settings())


__all__ = ["router"]
