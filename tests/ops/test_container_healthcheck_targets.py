"""Guard compose healthchecks away from the expensive operator diagnostic route."""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


class _ComposeLoader(yaml.SafeLoader):
    pass


def _construct_unknown_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_ComposeLoader.add_multi_constructor("", _construct_unknown_tag)


def test_no_container_healthcheck_targets_api_health() -> None:
    for compose_path in REPO_ROOT.glob("docker-compose*.yml"):
        compose = yaml.load(compose_path.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}
        for service_name, service in (compose.get("services") or {}).items():
            healthcheck = service.get("healthcheck") or {}
            command = healthcheck.get("test")
            if command is None:
                continue
            rendered = " ".join(command) if isinstance(command, list) else str(command)
            assert "/api/health" not in rendered.lower(), (
                f"{compose_path.name}:{service_name} healthcheck must use /healthz or /readyz, "
                "not /api/health"
            )
