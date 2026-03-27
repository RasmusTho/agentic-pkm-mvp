from __future__ import annotations

from app.cli.settings_explain import build_settings_explain_payload


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
