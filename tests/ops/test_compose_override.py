from __future__ import annotations

from pathlib import Path

import yaml


class _ComposeLoader(yaml.SafeLoader):
    pass


def _passthrough(loader: yaml.SafeLoader, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_ComposeLoader.add_constructor("!override", _passthrough)
_ComposeLoader.add_constructor("!reset", _passthrough)


def test_compose_override_only_passes_through_openai_env() -> None:
    compose = yaml.safe_load(Path("docker-compose.override.yml").read_text(encoding="utf-8"))
    worker = (compose.get("services") or {}).get("worker") or {}
    env = worker.get("environment") or []
    assert env == ["OPENAI_BASE_URL", "OPENAI_API_KEY"]


def test_test_compose_uses_prod_runtime_selector_for_test_channel() -> None:
    compose = yaml.load(Path("docker-compose.test.yml").read_text(encoding="utf-8"), Loader=_ComposeLoader)
    services = (compose.get("services") or {})
    assert ((services.get("db") or {}).get("ports") or []) == ["15434:5432"]
    assert ((services.get("api") or {}).get("ports") or []) == ["18002:8000"]
