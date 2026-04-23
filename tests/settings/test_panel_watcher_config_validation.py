from __future__ import annotations

from pathlib import Path

import pytest

from app.settings.validate import validate_settings
from app.settings.watcher_settings import load_watcher_settings


def _write_watchers_file(vault: Path, content: str) -> None:
    settings_dir = vault / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "watchers.md").write_text(content, encoding="utf-8")


pytestmark = pytest.mark.not_pg


def test_repo_panel_action_settings_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PANEL_ACTIONS_PATH", raising=False)
    monkeypatch.delenv("PANEL_ACTIONS_FILE", raising=False)
    monkeypatch.delenv("PANEL_ACTION_WIRING_PATH", raising=False)

    issues = validate_settings()

    assert not any(
        issue.code.startswith("panel_actions.")
        or issue.code.startswith("panel_wiring.")
        or issue.code.startswith("watcher_settings.")
        for issue in issues
    )


def test_invalid_panel_and_watcher_settings_fail_with_clear_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel_actions = tmp_path / "panel-actions.md"
    panel_actions.write_text(
        (
            "---\n"
            "mappings:\n"
            "  - id: \"Bad Id!\"\n"
            "    intent_type: promotion\n"
            "    downstream_event: promote.intent.created\n"
            "  - labels: [\"Missing required fields\"]\n"
            "---\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(panel_actions))

    wiring = tmp_path / "panel-action-wiring.yaml"
    wiring.write_text("actions:\n  - id: promote.evergreen\n", encoding="utf-8")
    monkeypatch.setenv("PANEL_ACTION_WIRING_PATH", str(wiring))

    vault = tmp_path / "vault"
    _write_watchers_file(
        vault,
        (
            "---\n"
            "auto_run:\n"
            "  auto_exec_default: \"yes\"\n"
            "  allowed_actions: promote.evergreen\n"
            "---\n"
        ),
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))

    issues = validate_settings()
    by_code = {issue.code: issue for issue in issues}

    assert "panel_actions.invalid_action_id" in by_code
    assert "action id" in by_code["panel_actions.invalid_action_id"].message
    assert "panel_actions.missing_required_fields" in by_code
    assert "required fields" in by_code["panel_actions.missing_required_fields"].message
    assert "panel_wiring.invalid" in by_code
    assert "missing target_event/event_type" in by_code["panel_wiring.invalid"].message
    assert "watcher_settings.malformed_auto_run" in by_code
    assert "auto_run.allowed_actions must be a list" in by_code["watcher_settings.malformed_auto_run"].message


def test_unreadable_panel_actions_path_reports_validation_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_panel_actions = tmp_path / "missing-panel-actions.md"
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(missing_panel_actions))

    issues = validate_settings()
    panel_issues = [issue for issue in issues if issue.code == "panel_actions.invalid"]

    assert panel_issues
    assert all(issue.message for issue in panel_issues)


def test_summary_action_allowlisted_only_in_measurement_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel_actions = tmp_path / "panel-actions.md"
    panel_actions.write_text(
        (
            "---\n"
            "mappings:\n"
            "  - id: \"promote.evergreen\"\n"
            "    intent_type: promotion\n"
            "    downstream_event: promote.intent.created\n"
            "  - id: \"ingest.summary.create\"\n"
            "    intent_type: summary\n"
            "    downstream_event: ingest.summary.create\n"
            "---\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(panel_actions))

    vault = tmp_path / "vault"
    _write_watchers_file(
        vault,
        (
            "---\n"
            "auto_run:\n"
            "  allowed_actions:\n"
            "    - promote.evergreen\n"
            "    - ingest.summary.create\n"
            "---\n"
        ),
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))

    issues = validate_settings()
    assert any(issue.code == "watcher_settings.measurement_mode_required" for issue in issues)

    _write_watchers_file(
        vault,
        (
            "---\n"
            "auto_run:\n"
            "  allowed_actions:\n"
            "    - promote.evergreen\n"
            "---\n"
        ),
    )
    monkeypatch.setenv("WATCHER_MEASUREMENT_MODE", "1")
    settings = load_watcher_settings(vault_root=vault)

    assert "promote.evergreen" in settings.allowed_actions
    assert "ingest.summary.create" in settings.allowed_actions
