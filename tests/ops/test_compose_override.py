from __future__ import annotations

from pathlib import Path

import yaml


def test_compose_override_only_passes_through_openai_env() -> None:
    compose = yaml.safe_load(Path("docker-compose.override.yml").read_text(encoding="utf-8"))
    worker = (compose.get("services") or {}).get("worker") or {}
    env = worker.get("environment") or []
    assert env == ["OPENAI_BASE_URL", "OPENAI_API_KEY"]
