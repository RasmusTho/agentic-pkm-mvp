"""Guard compose healthchecks away from the expensive operator diagnostic route."""

from __future__ import annotations

from pathlib import Path
import subprocess

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


def _committed_compose_paths() -> list[Path]:
    """Return every tracked compose file, including nested YAML variants."""
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [
        REPO_ROOT / relative_path
        for relative_path in completed.stdout.decode().split("\0")
        if relative_path
        and Path(relative_path).suffix in {".yml", ".yaml"}
        and "compose" in Path(relative_path).name.lower()
    ]


def test_no_container_healthcheck_targets_api_health() -> None:
    compose_paths = _committed_compose_paths()
    assert compose_paths, "expected at least one committed Compose file"
    for compose_path in compose_paths:
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
