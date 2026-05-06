from __future__ import annotations

from app.cli.settings_explain import build_settings_explain_payload


def test_settings_explain_surfaces_explicit_environment(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    settings_dir = vault / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "watchers.md").write_text("---\n---\n", encoding="utf-8")
    panel_actions = tmp_path / "panel-actions.md"
    panel_actions.write_text(
        "---\n"
        "mappings:\n"
        "  - id: promote.evergreen\n"
        "    label: Promote\n"
        "    intent_type: promotion\n"
        "    downstream_event: promote.intent.created\n"
        "    params:\n"
        "      maturity: evergreen\n"
        "---\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(panel_actions))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    payload = build_settings_explain_payload()

    assert payload["environment"] == "dev"
    assert payload["database_url"].endswith("/app_dev")


def test_settings_explain_includes_watcher_gate_and_allowlist(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    settings_dir = vault / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "watchers.md").write_text(
        "---\n"
        "auto_run:\n"
        "  auto_exec_default: false\n"
        "  allowed_actions:\n"
        "    - promote.evergreen\n"
        "paths:\n"
        "  watcher_tick_log: /tmp/watcher-tick.jsonl\n"
        "---\n",
        encoding="utf-8",
    )
    panel_actions = tmp_path / "panel-actions.md"
    panel_actions.write_text(
        "---\n"
        "mappings:\n"
        "  - id: promote.evergreen\n"
        "    label: Promote\n"
        "    intent_type: promotion\n"
        "    downstream_event: promote.intent.created\n"
        "    params:\n"
        "      maturity: evergreen\n"
        "---\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(panel_actions))
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")

    payload = build_settings_explain_payload()

    watcher = payload["watcher_settings"]
    assert watcher["auto_exec"]["enabled"] is True
    assert watcher["auto_exec"]["mode"] == "auto-exec"
    assert watcher["auto_exec"]["source"] == "env"
    assert watcher["allowlist"]["allowed_actions"] == ["promote.evergreen"]
    assert watcher["allowlist"]["invalid_actions"] == []
    assert "watcher_heartbeat" in watcher["paths"]
    assert "worker_heartbeat" in watcher["paths"]
    assert "write_guard" in watcher


def test_settings_explain_respects_explicit_database_override(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    settings_dir = vault / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "watchers.md").write_text("---\n---\n", encoding="utf-8")
    panel_actions = tmp_path / "panel-actions.md"
    panel_actions.write_text(
        "---\n"
        "mappings:\n"
        "  - id: promote.evergreen\n"
        "    label: Promote\n"
        "    intent_type: promotion\n"
        "    downstream_event: promote.intent.created\n"
        "    params:\n"
        "      maturity: evergreen\n"
        "---\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(panel_actions))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://custom:pw@db:5432/custom_db")

    payload = build_settings_explain_payload()
    assert payload["database_url"] == "postgresql+psycopg://custom:***@db:5432/custom_db"
    assert "pw" not in payload["database_url"]
    assert payload["database_url"].endswith("/custom_db")


def test_settings_explain_masks_password_query_params(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    settings_dir = vault / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "watchers.md").write_text("---\n---\n", encoding="utf-8")
    panel_actions = tmp_path / "panel-actions.md"
    panel_actions.write_text(
        "---\n"
        "mappings:\n"
        "  - id: promote.evergreen\n"
        "    label: Promote\n"
        "    intent_type: promotion\n"
        "    downstream_event: promote.intent.created\n"
        "    params:\n"
        "      maturity: evergreen\n"
        "---\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(panel_actions))
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://db:5432/custom_db?user=custom&password=secret",
    )

    payload = build_settings_explain_payload()
    assert payload["database_url"] == "postgresql+psycopg://db:5432/custom_db?user=custom&password=%2A%2A%2A"
    assert "secret" not in payload["database_url"]
