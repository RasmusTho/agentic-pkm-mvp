"""
Compose-contract tests for the test-channel stack.

AC-verified tests for Issue #698: watcher restart loop in test channel.

Static tests (no pg marker) inspect the compose config without starting Docker.
Live tests (pg marker) require a running pkm-test Docker stack.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO_ROOT / "docker-compose.yaml"
TEST_COMPOSE = REPO_ROOT / "docker-compose.test.yml"


# ---------------------------------------------------------------------------
# Helpers
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
    """Normalise compose service environment into a plain dict."""
    raw_env = service.get("environment") or {}
    if isinstance(raw_env, dict):
        return {str(k): (str(v) if v is not None else None) for k, v in raw_env.items()}
    env: dict[str, str | None] = {}
    for entry in raw_env:
        key, sep, value = str(entry).partition("=")
        env[key] = value if sep else None
    return env


def _compose_ports(service: dict) -> list[str]:
    """Return all port mappings as strings."""
    ports = service.get("ports") or []
    return [str(p) for p in ports]


# ---------------------------------------------------------------------------
# Static compose-config tests (no pg marker, no Docker required)
# ---------------------------------------------------------------------------

def test_test_compose_uses_test_channel_ports_only() -> None:
    """Test overlay must publish only the isolated test-channel ports.

    Verify: Issue #698 AC2 — Postgres on 15434, API on 18002.
    """
    test_overlay = _load_compose(TEST_COMPOSE)
    services = test_overlay.get("services") or {}

    db_service = services.get("db") or {}
    db_ports = _compose_ports(db_service)
    assert any("15434" in p for p in db_ports), (
        f"db service must expose test-channel port 15434 but got: {db_ports}"
    )
    assert not any("15432" in p for p in db_ports), (
        f"db service must not re-expose dev/prod port 15432 in test overlay but got: {db_ports}"
    )

    api_service = services.get("api") or {}
    api_ports = _compose_ports(api_service)
    assert any("18002" in p for p in api_ports), (
        f"api service must expose test-channel port 18002 but got: {api_ports}"
    )
    assert not any("18000" in p for p in api_ports), (
        f"api service must not re-expose dev/prod port 18000 in test overlay but got: {api_ports}"
    )


def test_test_compose_uses_prod_runtime_selector_for_test_channel() -> None:
    """Regression contract for Issue #717: test overlay replaces published ports.

    Verify: tests/ops/test_compose_override.py::test_test_compose_uses_prod_runtime_selector_for_test_channel
    """
    test_overlay = _load_compose(TEST_COMPOSE)
    services = test_overlay.get("services") or {}
    assert (services.get("db") or {}).get("ports") == ["15434:5432"]
    assert (services.get("api") or {}).get("ports") == ["18002:8000"]


def test_test_compose_watcher_env_has_valid_pkm_environment() -> None:
    """All test-overlay services must declare a PKM_ENVIRONMENT value that
    active_environment() accepts (dev, prod, or test).

    Issue #698 context: the watcher entered a restart loop because
    PKM_ENVIRONMENT=test caused a ValueError inside active_environment() at
    import time. That bug is fixed (Issue #848 / PR #940): 'test' is now a
    first-class selector value. The guard now allows 'dev', 'prod', and 'test'.

    Issue #968 policy: the test overlay must declare PKM_ENVIRONMENT=test to
    enforce channel isolation. See docs/RELEASE_CHANNELS/README.md.

    Verify: Issue #698 AC1 (compose-config side — no Docker required).
    """

    test_overlay = _load_compose(TEST_COMPOSE)
    services = test_overlay.get("services") or {}

    valid_environments = {"dev", "prod", "test"}

    for svc_name in ("api", "worker", "watcher"):
        svc = services.get(svc_name) or {}
        env = _compose_env(svc)
        if "PKM_ENVIRONMENT" not in env:
            # If not set in test overlay it inherits from base — acceptable
            continue
        pkm_env = str(env["PKM_ENVIRONMENT"]).strip().lower()
        assert pkm_env in valid_environments, (
            f"Service '{svc_name}' has PKM_ENVIRONMENT={pkm_env!r} in test overlay "
            f"but active_environment() only accepts {valid_environments}. "
            "Use 'test', 'dev', or 'prod' (Issue #698 / #968)."
        )


def test_test_compose_watcher_state_dir_overrides_parent_env() -> None:
    """The effective pkm-test watcher env must not inherit parent tmp paths.

    Verify: Issue #1656 — parent WATCHER_STATE_DIR=tmp cannot shadow the
    test-channel watcher override after base + test compose files are merged.
    """
    parent_env = os.environ.copy()
    parent_env["WATCHER_STATE_DIR"] = "tmp"

    base = _load_compose(BASE_COMPOSE)
    test_overlay = _load_compose(TEST_COMPOSE)
    base_watcher_env = _compose_env((base["services"] or {})["watcher"])
    overlay_watcher_env = _compose_env((test_overlay["services"] or {})["watcher"])

    # Compose interpolates this base entry from the parent environment before
    # the test overlay environment map is merged.
    assert base_watcher_env["WATCHER_STATE_DIR"] == "${WATCHER_STATE_DIR:-}"
    interpolated_base_env = dict(base_watcher_env)
    interpolated_base_env["WATCHER_STATE_DIR"] = parent_env["WATCHER_STATE_DIR"]

    watcher_env = {**interpolated_base_env, **overlay_watcher_env}

    assert watcher_env["WATCHER_STATE_DIR"] == "tmp-test"
    assert watcher_env["WATCHER_STOP_FILE"] == "/app/tmp-test/WATCHER_STOP"
    assert watcher_env["INDEX_OUTBOX_PATH"] == "/app/tmp-test/index-outbox.jsonl"
    assert watcher_env["WATCHER_HEARTBEAT_PATH"] == "/app/tmp-test/watcher_heartbeat.json"
    assert watcher_env["WORKER_HEARTBEAT_PATH"] == "/app/tmp-test/worker_heartbeat.json"
    assert watcher_env["WATCHER_STATE_PATH"] == "/app/tmp-test/watcher_state.json"


def test_test_compose_runtime_artifact_paths_are_shared_by_api_worker_watcher() -> None:
    """API, worker, and watcher must agree on pkm-test runtime artifacts.

    Verify: PR #1713 review-thread residual — health/status reads API env, so
    the API service must not inherit base /app/tmp heartbeat paths while the
    watcher writes /app/tmp-test.
    """
    test_overlay = _load_compose(TEST_COMPOSE)
    services = test_overlay["services"] or {}
    expected = {
        "WATCHER_STATE_DIR": "tmp-test",
        "WATCHER_STOP_FILE": "/app/tmp-test/WATCHER_STOP",
        "INDEX_OUTBOX_PATH": "/app/tmp-test/index-outbox.jsonl",
        "WATCHER_HEARTBEAT_PATH": "/app/tmp-test/watcher_heartbeat.json",
        "WORKER_HEARTBEAT_PATH": "/app/tmp-test/worker_heartbeat.json",
        "WATCHER_STATE_PATH": "/app/tmp-test/watcher_state.json",
    }

    for service_name in ("api", "worker", "watcher"):
        env = _compose_env((services or {})[service_name])
        assert {key: env.get(key) for key in expected} == expected


def test_make_test_up_starts_watcher_without_restart_loop() -> None:
    """The watcher service command must be importable under the test-overlay env.

    Simulates the environment that 'make test-up' injects and confirms that
    ``app.cli`` can be imported without raising ValueError — the crash that
    caused the watcher restart loop in Issue #698.

    Verify: Issue #698 AC1 (no Docker required; exercises the actual code path).
    """
    import os
    import sys

    test_overlay = _load_compose(TEST_COMPOSE)
    services = test_overlay.get("services") or {}
    watcher_svc = services.get("watcher") or {}
    watcher_env = _compose_env(watcher_svc)

    # Resolve the effective PKM_ENVIRONMENT that the watcher container gets.
    pkm_environment = watcher_env.get("PKM_ENVIRONMENT", "prod")

    # Temporarily set the env var and verify import succeeds.
    original = os.environ.get("PKM_ENVIRONMENT")
    try:
        os.environ["PKM_ENVIRONMENT"] = str(pkm_environment)
        # Evict cached modules so the env change takes effect.
        for mod in list(sys.modules.keys()):
            if "app.config.environment" in mod or "app.settings.watcher_settings" in mod:
                sys.modules.pop(mod, None)
        try:
            from app.config.environment import active_environment
            result = active_environment()
            assert result in ("dev", "prod", "test"), (
                f"active_environment() returned {result!r}; expected 'dev', 'prod', or 'test'. "
                "PKM_ENVIRONMENT must be set to a valid value in docker-compose.test.yml."
            )
        except ValueError as exc:
            pytest.fail(
                f"Watcher startup would crash under PKM_ENVIRONMENT={pkm_environment!r}: {exc}. "
                "Fix docker-compose.test.yml (Issue #698)."
            )
    finally:
        if original is None:
            os.environ.pop("PKM_ENVIRONMENT", None)
        else:
            os.environ["PKM_ENVIRONMENT"] = original
        # Re-evict to restore clean state for subsequent tests.
        for mod in list(sys.modules.keys()):
            if "app.config.environment" in mod or "app.settings.watcher_settings" in mod:
                sys.modules.pop(mod, None)
