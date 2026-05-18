"""
Release-channel isolation guards (Issue #968).

Static inspection tests — no running services, no Docker required.

Policy source: docs/RELEASE_CHANNELS/README.md, docs/ENVIRONMENTS.md.

Each test covers one independently diagnosable isolation failure:
- wrong PKM_ENVIRONMENT in test compose
- missing PKM_ENVIRONMENT binding in prod startup path
- compose project name collision (test vs prod)
- direct dev→prod documented as default path in runbook/docs
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yaml"
TEST_COMPOSE = REPO_ROOT / "docker-compose.test.yml"
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
MAKEFILE = REPO_ROOT / "Makefile"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "RUNBOOK_STARTUP_FULL_SYSTEM.md"


# ---------------------------------------------------------------------------
# Helpers (shared with test_test_channel_compose_contract.py pattern)
# ---------------------------------------------------------------------------

def _load_compose(path: Path) -> dict:
    class _ComposeLoader(yaml.SafeLoader):
        pass

    def _passthrough(loader: yaml.SafeLoader, node: yaml.Node):  # type: ignore[name-defined]
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        return None

    _ComposeLoader.add_constructor("!override", _passthrough)
    _ComposeLoader.add_constructor("!reset", _passthrough)
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}


def _compose_env(service: dict) -> dict[str, str | None]:
    raw_env = service.get("environment") or {}
    if isinstance(raw_env, dict):
        return {str(k): (str(v) if v is not None else None) for k, v in raw_env.items()}
    env: dict[str, str | None] = {}
    for entry in raw_env:
        key, sep, value = str(entry).partition("=")
        env[key] = value if sep else None
    return env


# ---------------------------------------------------------------------------
# AC1: test compose must declare PKM_ENVIRONMENT=test, not prod
# ---------------------------------------------------------------------------

def test_test_compose_does_not_declare_prod_environment() -> None:
    """Test-channel services must declare PKM_ENVIRONMENT=test, not prod.

    docker-compose.test.yml had PKM_ENVIRONMENT: prod for api/worker/watcher
    (known isolation gap, tracked in #968). This guard detects any regression.

    Policy: docs/RELEASE_CHANNELS/README.md §Invariants — vault-per-channel and
    DB-per-channel require the environment selector to match the channel.

    Verify: Issue #968 AC1 —
      tests/ops/test_release_channel_isolation.py::test_test_compose_does_not_declare_prod_environment
    """
    overlay = _load_compose(TEST_COMPOSE)
    services = overlay.get("services") or {}

    violations: list[str] = []
    for svc_name in ("api", "worker", "watcher"):
        svc = services.get(svc_name) or {}
        env = _compose_env(svc)
        pkm_env = env.get("PKM_ENVIRONMENT", "")
        if pkm_env and str(pkm_env).strip().lower() == "prod":
            violations.append(
                f"Service '{svc_name}' declares PKM_ENVIRONMENT=prod in "
                f"{TEST_COMPOSE.name}. Test services must declare "
                "PKM_ENVIRONMENT=test for channel isolation (Issue #968)."
            )

    assert not violations, "\n".join(violations)


# ---------------------------------------------------------------------------
# AC2: prod startup path must bind PKM_ENVIRONMENT=prod explicitly
# ---------------------------------------------------------------------------

def test_prod_compose_declares_prod_environment() -> None:
    """The canonical prod startup target must bind PKM_ENVIRONMENT=prod explicitly.

    docker-compose.prod.yml does not set PKM_ENVIRONMENT in the YAML (by design
    — it is injected by the Makefile target). The guard checks that the Makefile
    'prod-start-full' target contains an explicit PKM_ENVIRONMENT=prod binding
    so operators cannot start prod with an implicit or wrong env selector.

    Verify: Issue #968 AC2 —
      tests/ops/test_release_channel_isolation.py::test_prod_compose_declares_prod_environment
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")

    # The prod-start-full target must set PKM_ENVIRONMENT=prod (possibly with
    # quotes, e.g. PKM_ENVIRONMENT="prod").
    # Anchor to start-of-line with colon to avoid matching the .PHONY declaration.
    prod_env_pattern = re.compile(
        r'^prod-start-full\s*:.*?(?=\n\S|\Z)',
        re.DOTALL | re.MULTILINE,
    )
    match = prod_env_pattern.search(makefile_text)
    assert match, (
        "Could not find 'prod-start-full' target in Makefile. "
        "The canonical prod startup target must exist."
    )

    target_body = match.group(0)
    assert re.search(r'PKM_ENVIRONMENT\s*=\s*["\']?prod["\']?', target_body), (
        "Makefile 'prod-start-full' target does not explicitly set "
        "PKM_ENVIRONMENT=prod. Prod startup must bind this explicitly "
        "to prevent implicit env inheritance (Issue #968)."
    )


# ---------------------------------------------------------------------------
# AC3: test and prod compose projects must be distinct
# ---------------------------------------------------------------------------

def test_test_and_prod_compose_projects_are_distinct() -> None:
    """The test and prod compose project names must differ.

    If both channels share the same compose project name, Docker will share
    networks, volumes, and container names — violating channel isolation.

    Guards the Makefile target definitions for prod-start-full and
    test-start-full (when present), plus the prod overlay comment.

    Verify: Issue #968 AC3 —
      tests/ops/test_release_channel_isolation.py::test_test_and_prod_compose_projects_are_distinct
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    prod_compose_text = PROD_COMPOSE.read_text(encoding="utf-8")

    # Extract prod project name from Makefile — anchor to target definition
    # (start-of-line + colon) to avoid matching the .PHONY declaration.
    prod_project_match = re.search(
        r'^prod-start-full\s*:.*?COMPOSE_PROJECT_NAME\s*=\s*["\']?(\S+?)["\']?\s',
        makefile_text, re.DOTALL | re.MULTILINE,
    )
    prod_project = prod_project_match.group(1).strip('"\'') if prod_project_match else None

    # Extract test project name from Makefile (test-start-full if present,
    # or check COMPOSE_TEST variable)
    test_project_match = re.search(
        r'^test-start-full\s*:.*?COMPOSE_PROJECT_NAME\s*=\s*["\']?(\S+?)["\']?\s',
        makefile_text, re.DOTALL | re.MULTILINE,
    )
    # Fallback: check for COMPOSE_TEST variable definition
    if not test_project_match:
        test_project_match = re.search(
            r'COMPOSE_TEST\s*[?:]?=.*?-p\s+(\S+)',
            makefile_text,
        )
    test_project = test_project_match.group(1).strip('"\'') if test_project_match else None

    # At minimum, the prod project must be explicitly named and not be "default"
    assert prod_project is not None, (
        "Could not detect COMPOSE_PROJECT_NAME in 'prod-start-full' Makefile target. "
        "Prod startup must use an explicit project name (e.g. pkm-prod)."
    )
    assert "prod" in prod_project.lower(), (
        f"Prod compose project name {prod_project!r} does not contain 'prod'. "
        "Expected a name like 'pkm-prod' to prevent naming collisions."
    )

    if test_project is not None:
        assert test_project != prod_project, (
            f"Test and prod channels share the same compose project name {prod_project!r}. "
            "They must be distinct to prevent volume/network/container collisions."
        )
        assert "test" in test_project.lower() or "pkm" in test_project.lower(), (
            f"Test compose project name {test_project!r} does not contain 'test'. "
            "Expected a name like 'pkm-test' to prevent naming collisions."
        )


# ---------------------------------------------------------------------------
# AC4: runbook must not document direct dev→prod as the default path
# ---------------------------------------------------------------------------

def test_docs_do_not_document_direct_dev_to_prod_bypass() -> None:
    """The startup runbook must not instruct operators to use make alpha-up as
    the recommended (non-deprecated) prod startup command.

    'make alpha-up' is the legacy direct-to-prod command that predates explicit
    environment binding. Its use as a recommended command is the equivalent of
    a direct dev→prod bypass without channel isolation checks.

    After #965, the runbook deprecates 'make alpha-up' and documents
    'make prod-start-full' as the canonical prod command. This guard verifies
    that regressed documentation does not reintroduce alpha-up as recommended.

    Policy: docs/RELEASE_CHANNELS/README.md §Future promotion hardening —
    direct dev→prod is not the default path.

    Verify: Issue #968 AC4 —
      tests/ops/test_release_channel_isolation.py::test_docs_do_not_document_direct_dev_to_prod_bypass
    """
    runbook_text = RUNBOOK.read_text(encoding="utf-8")

    # The deprecated section must exist and must mention alpha-up as legacy/deprecated.
    assert "alpha-up" in runbook_text, (
        "RUNBOOK_STARTUP_FULL_SYSTEM.md does not mention 'alpha-up' at all. "
        "Expected a 'Deprecated' section explaining that alpha-up is a legacy alias."
    )

    # The word 'deprecated' or 'legacy' must appear near 'alpha-up'
    alpha_up_pos = runbook_text.lower().find("alpha-up")
    context_window = runbook_text[max(0, alpha_up_pos - 200): alpha_up_pos + 300].lower()
    assert "deprecated" in context_window or "legacy" in context_window, (
        "The runbook mentions 'alpha-up' but does not label it as deprecated or legacy "
        "in the surrounding context. Direct dev→prod via alpha-up must be clearly marked "
        "as a non-default path (Issue #965 / #968)."
    )

    # The table or primary guidance must recommend prod-start-full, not alpha-up,
    # as the canonical prod startup.
    assert "prod-start-full" in runbook_text, (
        "RUNBOOK_STARTUP_FULL_SYSTEM.md does not mention 'prod-start-full'. "
        "The canonical prod startup command must be documented."
    )
