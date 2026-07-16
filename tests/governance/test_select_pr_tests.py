from __future__ import annotations

from scripts.select_pr_tests import select_tests


def test_openapi_yaml_change_selects_static_contract_validation() -> None:
    selection = select_tests(["api/openapi.yaml"])

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert "companion_ui" in selection.subsystems
    assert "tests/architecture/test_openapi_static_contract.py" in selection.targets


def test_static_openapi_contract_test_path_is_owned() -> None:
    selection = select_tests(["tests/architecture/test_openapi_static_contract.py"])

    assert selection.unowned_paths == ()
    assert "companion_ui" in selection.subsystems


def test_companion_api_paths_select_api_targets() -> None:
    selection = select_tests(["companion-ui/companion-app/src/workspace.ts", "tests/api/test_status_api.py"])

    assert "companion_ui" in selection.subsystems
    assert "tests/companion_ui" in selection.targets
    assert "tests/api" in selection.targets


def test_fastapi_deps_module_is_owned_by_companion_ui() -> None:
    # app/deps.py holds the FastAPI dependency providers consumed by the API
    # routers (app/api/routers/agent.py); its behavior is exercised by the API
    # suites, so it must resolve there instead of fail-closing as unowned.
    selection = select_tests(["app/deps.py"])

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert "companion_ui" in selection.subsystems
    assert "tests/api" in selection.targets


def test_health_contract_module_is_owned_by_runtime_health() -> None:
    selection = select_tests(["app/health_contract.py"])

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert "runtime_health" in selection.subsystems
    assert "tests/health" in selection.targets
    assert "tests/api" in selection.targets
    assert "tests/cli/test_health_contract_cli.py" in selection.targets
    assert "tests/observability/test_health_contract_settings.py" in selection.targets


def test_observability_tracing_module_is_owned_by_promotion_panel() -> None:
    # app/observability/tracing.py is only consumed by the promotion agent
    # (app/promotion/queue.py, app/agents/promotion/agent.py), so its
    # regressions surface through the promotion suites.
    selection = select_tests(["app/observability/tracing.py"])

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert "promotion_panel" in selection.subsystems
    assert "tests/promotion" in selection.targets
