"""Guard: no container healthcheck may target the heavy `/api/health` diagnostic.

Regression rail for #3461. `/api/health` runs the full `run_health()` diagnostic
(bounded provider probes, obsidian subprocess, DB/index checks). It must stay the
rich operator surface, never a container liveness probe — provider slowness on that
path must never flip container health or trigger restart loops. Container liveness
must target `/healthz` (trivial) or `/readyz` (bounded readiness).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = sorted(REPO_ROOT.glob("docker-compose*.y*ml"))


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader that tolerates Docker Compose merge tags (`!override`, `!reset`)."""


def _construct_compose_tag(loader: yaml.Loader, tag_suffix: str, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_ComposeLoader.add_multi_constructor("!", _construct_compose_tag)


def _load_compose(compose_file: Path) -> object:
    return yaml.load(compose_file.read_text(encoding="utf-8"), Loader=_ComposeLoader)


def _services(doc: object) -> dict:
    if isinstance(doc, dict) and isinstance(doc.get("services"), dict):
        return doc["services"]
    return {}


def _healthcheck_test_strings(doc: object) -> Iterator[tuple[str, str]]:
    for name, svc in _services(doc).items():
        if not isinstance(svc, dict):
            continue
        hc = svc.get("healthcheck")
        if not isinstance(hc, dict):
            continue
        test = hc.get("test")
        if isinstance(test, list):
            yield name, " ".join(str(part) for part in test)
        elif isinstance(test, str):
            yield name, test


def _api_healthcheck_urls(doc: object) -> Iterator[tuple[str, str]]:
    """The api service healthcheck probes `API_HEALTHCHECK_URL`; check its value."""
    for name, svc in _services(doc).items():
        if not isinstance(svc, dict):
            continue
        env = svc.get("environment")
        if isinstance(env, dict):
            value = env.get("API_HEALTHCHECK_URL")
            if value:
                yield name, str(value)
        elif isinstance(env, list):
            for item in env:
                if isinstance(item, str) and item.startswith("API_HEALTHCHECK_URL="):
                    yield name, item.split("=", 1)[1]


def test_compose_files_present() -> None:
    assert COMPOSE_FILES, "no docker-compose files found at repo root"


def test_no_container_healthcheck_targets_api_health() -> None:
    offenders: list[str] = []
    for compose_file in COMPOSE_FILES:
        doc = _load_compose(compose_file)
        for name, test in _healthcheck_test_strings(doc):
            if "/api/health" in test:
                offenders.append(f"{compose_file.name}::{name} healthcheck.test")
        for name, url in _api_healthcheck_urls(doc):
            if "/api/health" in url:
                offenders.append(f"{compose_file.name}::{name} API_HEALTHCHECK_URL={url}")

    assert not offenders, (
        "Container healthchecks must target /healthz or /readyz, never the heavy "
        f"/api/health diagnostic (#3461). Offenders: {offenders}"
    )
