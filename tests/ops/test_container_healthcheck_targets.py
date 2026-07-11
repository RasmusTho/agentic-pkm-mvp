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
# The base api healthcheck runs `urlopen(os.environ['API_HEALTHCHECK_URL'])`;
# base/dev/app-bind stacks don't set that env inline, so its effective default
# lives here. Scanning only inline compose env would miss a regression to this
# canonical default (#3461 review finding).
RUNTIME_DEFAULTS_ENV = REPO_ROOT / "config" / "runtime.defaults.env"


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


def _default_api_healthcheck_url() -> str | None:
    if not RUNTIME_DEFAULTS_ENV.exists():
        return None
    for raw in RUNTIME_DEFAULTS_ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("API_HEALTHCHECK_URL="):
            return line.split("=", 1)[1].strip()
    return None


def test_compose_files_present() -> None:
    assert COMPOSE_FILES, "no docker-compose files found at repo root"


def test_base_compose_parses_with_api_healthcheck() -> None:
    """Coverage guard: a silent parse skip must not let the offender scan pass green.

    `_load_compose` returns None on an empty/malformed doc and `_services`
    swallows non-mappings, so the offender scan below would vacuously pass if the
    base file stopped parsing. Assert the base file really yields an `api` service
    with a healthcheck, so a parse regression fails loudly here instead.
    """
    base = REPO_ROOT / "docker-compose.yaml"
    assert base in COMPOSE_FILES, "base docker-compose.yaml missing from scan set"
    services = _services(_load_compose(base))
    assert "api" in services, "base docker-compose.yaml has no `api` service"
    assert isinstance(services["api"].get("healthcheck"), dict), (
        "base api service lost its healthcheck definition"
    )


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


def test_default_api_healthcheck_url_does_not_target_api_health() -> None:
    """The canonical `API_HEALTHCHECK_URL` default must not be the heavy diagnostic.

    Base/dev/app-bind stacks inherit this default (they set no inline value), so a
    regression here would silently point every such container's liveness probe at
    `/api/health` while the inline-only compose scan stayed green (#3461).
    """
    default_url = _default_api_healthcheck_url()
    assert default_url is not None, (
        f"API_HEALTHCHECK_URL default missing from {RUNTIME_DEFAULTS_ENV}; the base "
        "api healthcheck would probe an unset env"
    )
    assert "/api/health" not in default_url, (
        f"Default API_HEALTHCHECK_URL must target /healthz or /readyz, not the heavy "
        f"/api/health diagnostic (#3461). Got: {default_url}"
    )
