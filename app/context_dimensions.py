from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ContextDimensions(BaseModel):
    """Canonical runtime contract for separated context dimensions."""

    scope: str = "default"
    sphere_memberships: list[str] = Field(default_factory=list)
    situated_identity: str | None = None

    @field_validator("scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value: object) -> str:
        if value is None:
            return "default"
        if not isinstance(value, str):
            raise TypeError("scope must be a string")
        stripped = value.strip()
        return stripped or "default"

    @field_validator("sphere_memberships", mode="before")
    @classmethod
    def _normalize_spheres(cls, value: object) -> list[str]:
        if value is None:
            raise TypeError("sphere_memberships must be a list")
        if isinstance(value, list):
            return [str(item) for item in value]
        raise TypeError("sphere_memberships must be a list")


def from_legacy_domain(domain: str | None) -> ContextDimensions:
    """Map legacy single-domain context into canonical dimensions."""

    return ContextDimensions(
        scope=domain,
        sphere_memberships=[],
        situated_identity=None,
    )
