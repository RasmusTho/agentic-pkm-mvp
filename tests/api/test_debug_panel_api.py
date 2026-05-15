import textwrap
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.vault.paths import get_vault_inbox_dir_rel


def test_debug_panel_endpoint_parses_actions_and_returns_mapping_summary(tmp_path, monkeypatch) -> None:
    vault_root = tmp_path / "vault"
    system_dir = vault_root / "⚙️ System"
    system_dir.mkdir(parents=True)
    (system_dir / "vault.layout.md").write_text(
        "---\n"
        "version: '1'\n"
        "system_folder: ⚙️ System\n"
        "inbox_folder: 📥 Inbox\n"
        "desk_folder: 🛠️ Workbench\n"
        "---\n",
        encoding="utf-8",
    )
    note_rel = Path(get_vault_inbox_dir_rel(vault_root)) / "_alpha_e2e" / "test.md"
    note_path = vault_root / note_rel
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        textwrap.dedent(
            """
            ---
            uuid: 1234567890abcdef1234567890abcdef
            ---
            # Alpha E2E Runtime
            - [x] Make this note evergreen <!--ai:id=promote.evergreen-->
            """
        ).lstrip(),
        encoding="utf-8",
    )

    actions_path = tmp_path / "panel-actions.md"
    actions_path.write_text(
        textwrap.dedent(
            """
            ---
            mappings:
              - id: "promote.evergreen"
                labels:
                  - "Make this note evergreen"
                intent_type: "promotion"
                downstream_event: "review.promote.evergreen"
                params:
                  maturity: evergreen
            ---
            """
        ).lstrip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("PANEL_ACTIONS_ROOT", str(actions_path))

    client = TestClient(app)
    resp = client.get("/api/debug/panel", params={"note_rel": str(note_rel)})
    assert resp.status_code == 200
    data = resp.json()

    actions = data.get("parsed_actions") or []
    assert len(actions) == 1
    assert actions[0].get("action_id") == "promote.evergreen"
    assert actions[0].get("checked") is True
    assert actions[0].get("action_text") == "Make this note evergreen"

    diag = data.get("panel_diagnostics") or {}
    assert diag.get("panel_actions_mappings_count") == 1
    assert diag.get("has_promote_evergreen_mapping") is True


# --- security: exception must not leak internals ---

def test_debug_panel_read_error_does_not_expose_exception(tmp_path, monkeypatch) -> None:
    vault_root = tmp_path / "vault"
    system_dir = vault_root / "⚙️ System"
    system_dir.mkdir(parents=True)
    (system_dir / "vault.layout.md").write_text(
        "---\nversion: '1'\nsystem_folder: ⚙️ System\ninbox_folder: 📥 Inbox\ndesk_folder: 🛠️ Workbench\n---\n",
        encoding="utf-8",
    )
    note_path = vault_root / "test.md"
    note_path.write_text("# test", encoding="utf-8")

    monkeypatch.setenv("VAULT_ROOT", str(vault_root))

    def _raise_read(self, *args, **kwargs):
        raise PermissionError("/very/secret/path/token=abc123: permission denied")

    monkeypatch.setattr(Path, "read_text", _raise_read)

    client = TestClient(app)
    resp = client.get("/api/debug/panel", params={"note_rel": "test.md"})
    assert resp.status_code == 500
    body = resp.text
    assert "secret" not in body
    assert "token" not in body
    assert "abc123" not in body
    assert resp.json()["detail"] == "failed to read note"
