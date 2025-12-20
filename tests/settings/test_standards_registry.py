from __future__ import annotations

import pytest

from app.components.settings.standards_loader import load_standards_registry

pytestmark = pytest.mark.not_pg


def test_standards_registry_loads_and_contains_core_ids() -> None:
    reg = load_standards_registry()
    ids = {s.id for s in reg.standards}
    for required in ["json_schema", "openapi", "asyncapi", "mcp", "a2a", "langgraph", "otel"]:
        assert required in ids
