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
