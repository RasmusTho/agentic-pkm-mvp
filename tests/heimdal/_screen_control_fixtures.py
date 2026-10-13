from types import SimpleNamespace
import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import companion, heimdal_screen
from app.heimdal.consent_ledger import grant_consent, reset_memory_consent_ledger
from app.heimdal.raw_store import reset_memory_raw_store
from app.heimdal.raw_liveness import reset_memory_deletion_receipts
from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE
from app.receipts.settings_receipts import query_settings_receipts
from app.vault.manager import VaultManager
from app.vault.markdown_settings import MarkdownSettingsStore
from app.vault.settings_service import SettingsService
from app.write_guard import DEFAULT_WRITE_GUARD


@pytest.fixture
def screen_env(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", secrets.token_hex(32))
    outbox = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})
    root = tmp_path / "vault"
    manager = VaultManager()
    context = manager.initialize_vault(root, machine_role="testNode", remember=False).context
    monkeypatch.setattr(heimdal_screen, "get_vault_manager", lambda: manager)
    monkeypatch.setattr(companion, "get_vault_manager", lambda: manager)
    reset_memory_consent_ledger()
    reset_memory_raw_store()
    reset_memory_deletion_receipts()
    grant_consent(grant_ref="controls-test", scope=SCREEN_CAPTURE_SCOPE, basis="screen_always_on", granted_by="operator")
    application = FastAPI()
    application.include_router(heimdal_screen.router)
    application.include_router(companion.router, prefix="/api")
    client = TestClient(application)
    yield SimpleNamespace(
        root=root, context=context, client=client, outbox=outbox,
        service=SettingsService(), path=root / "settings" / "screen_control.md",
    )
    client.close()
    reset_memory_consent_ledger()
    reset_memory_raw_store()
    reset_memory_deletion_receipts()


def edit_controls(env, **updates):
    store = MarkdownSettingsStore()
    document = store.read(env.path)
    store.write_frontmatter(env.path, {**document.frontmatter, **updates}, body=document.body)


def screen_rows(env):
    return [row for row in query_settings_receipts(outbox_path=env.outbox).rows if row.key.startswith("screen_")]


def set_control(env, key, value):
    response = env.client.put("/api/heimdal/screen/control", json={"key": key, "value": value})
    assert response.status_code == 200, response.text
    return response.json()
