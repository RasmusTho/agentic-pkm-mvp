from __future__ import annotations

from companion_ui.workspace.vault_settings_panel import (
    VAULT_INITIALIZE_ENDPOINT,
    VAULT_RELOAD_ENDPOINT,
    VAULT_SELECT_ENDPOINT,
    VAULT_SETTINGS_ENDPOINT,
    vault_settings_panel_markup,
)


def _projection(status: str, **context_overrides: object) -> dict:
    context = {
        "status": status,
        "active_vault_name": "Test Vault",
        "active_vault_path": "/tmp/test-vault",
        "settings_path": "/tmp/test-vault/settings",
        "machine_role": "primary",
        "validation_error": "",
        "permissions": {
            "allowWritesToVault": status == "selected",
            "allowSharedSettingsEdits": status == "selected",
            "allowLocalSettingsEdits": status == "selected",
        },
    }
    context.update(context_overrides)
    return {
        "context": context,
        "recent_vaults": [
            {
                "ref": "path:/tmp/recent-vault",
                "path": "/tmp/recent-vault",
                "vault_name": "Recent Vault",
            }
        ],
        "definitions": [],
        "settings": [],
        "validation_errors": [],
    }


def test_no_vault_state_renders() -> None:
    html = vault_settings_panel_markup(
        _projection(
            "none",
            active_vault_name=None,
            active_vault_path=None,
            settings_path=None,
            machine_role=None,
        )
    )

    assert 'data-testid="vault-settings-panel"' in html
    assert 'data-vault-status="none"' in html
    assert "No vault selected" in html
    assert f'data-api-path="{VAULT_SELECT_ENDPOINT}"' in html
    assert f'data-api-path="{VAULT_INITIALIZE_ENDPOINT}"' in html
    assert f'data-api-path="{VAULT_RELOAD_ENDPOINT}"' in html
    assert 'data-testid="vault-open-path"' in html
    assert 'data-testid="vault-init-path"' in html
    assert "Open recent vault" in html
    assert 'data-testid="vault-recent-vault"' in html
    assert 'data-vault-path="/tmp/recent-vault"' in html
    assert 'data-testid="vault-settings-folder"' in html


def test_vault_status_states_render() -> None:
    cases = {
        "selected": ("Vault selected", "Scoped settings are loaded"),
        "missing": ("Vault missing", "does not exist"),
        "invalid": ("Vault invalid", "Resolve the settings error"),
        "uninitialized": ("Vault uninitialized", "Initialize missing settings files"),
    }

    for status, expected in cases.items():
        html = vault_settings_panel_markup(
            _projection(
                status,
                validation_error="settings/vault.md has an incompatible schema"
                if status == "invalid"
                else "missing Design Handoff settings: vault.md"
                if status == "uninitialized"
                else "",
            )
        )

        assert f'data-vault-status="{status}"' in html
        assert expected[0] in html
        assert expected[1] in html
        assert "/tmp/test-vault/settings" in html
        assert 'data-testid="vault-machine-role"' in html
        assert 'data-testid="vault-permissions"' in html
        assert f'data-api-path="{VAULT_SETTINGS_ENDPOINT}"' in html

    missing_html = vault_settings_panel_markup(_projection("missing"))
    assert 'data-affordance-status="available"' in missing_html

    selected_html = vault_settings_panel_markup(_projection("selected"))
    assert 'data-testid="vault-settings-folder-open"' in selected_html
    assert 'data-settings-folder="/tmp/test-vault/settings"' in selected_html
