from __future__ import annotations

from pathlib import Path

import yaml


OPENAPI_DOCUMENT = Path(__file__).resolve().parents[2] / "api" / "openapi.yaml"


def test_static_openapi_yaml_parses() -> None:
    document = yaml.safe_load(OPENAPI_DOCUMENT.read_text(encoding="utf-8"))

    assert isinstance(document, dict)
