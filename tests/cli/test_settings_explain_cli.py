from __future__ import annotations

import json

from app.cli.settings_explain import _redact_payload, build_settings_explain_payload, emit_settings_explain


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


# --- security: _redact_payload ---


def test_redact_payload_masks_sensitive_keys() -> None:
    sensitive_keys = [
        "token", "secret", "password", "key", "dsn", "database_url",
        "api_key", "auth", "credential", "credentials",
    ]
    for k in sensitive_keys:
        result = _redact_payload({k: "supersecret"})
        assert result[k] == "***", f"expected key '{k}' to be redacted"


def test_redact_payload_preserves_non_sensitive_keys() -> None:
    obj = {"environment": "dev", "enabled": True, "count": 3}
    assert _redact_payload(obj) == obj


def test_redact_payload_recurses_into_nested_dicts() -> None:
    obj = {"outer": {"database_url": "postgresql://user:pw@host/db", "ok": True}}
    result = _redact_payload(obj)
    assert result["outer"]["database_url"] == "***"
    assert result["outer"]["ok"] is True


def test_redact_payload_recurses_into_lists() -> None:
    obj = {"items": [{"token": "t1"}, {"name": "safe"}]}
    result = _redact_payload(obj)
    assert result["items"][0]["token"] == "***"
    assert result["items"][1]["name"] == "safe"


def test_emit_settings_explain_does_not_print_raw_secret(monkeypatch, tmp_path, capsys) -> None:
    vault = tmp_path / "vault"
    settings_dir = vault / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "watchers.md").write_text("---\n---\n", encoding="utf-8")
    panel_actions = tmp_path / "panel-actions.md"
    panel_actions.write_text(
        "---\nmappings:\n  - id: promote.evergreen\n    label: Promote\n"
        "    intent_type: promotion\n    downstream_event: promote.intent.created\n"
        "    params:\n      maturity: evergreen\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(panel_actions))
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:hunter2@host/db")

    payload = build_settings_explain_payload()
    emit_settings_explain(payload, pretty=False)
    out = capsys.readouterr().out
    assert "hunter2" not in out
    parsed = json.loads(out)
    assert parsed["database_url"] == "***"
