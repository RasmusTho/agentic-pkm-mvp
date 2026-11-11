"""Registered read-only YouTube auth status contract."""

import json
import importlib

from click.testing import CliRunner

from app.cli import cli
auth_cli = importlib.import_module("app.cli.youtube_auth")
from app.knowledge_acquisition import youtube_account_binding as binding_module
from app.knowledge_acquisition import youtube_token_store as token_module
from app.knowledge_acquisition.youtube_account_binding import AccountBindingStore
from app.knowledge_acquisition.youtube_oauth import SCOPE
from app.knowledge_acquisition.youtube_token_store import StoredToken, YouTubeTokenStore


def _invoke():
    return CliRunner().invoke(cli, ["youtube-auth", "status", "--json"])


def test_registered_auth_status_uses_existing_service(monkeypatch, tmp_path):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("YOUTUBE_TOKEN_STORE_KEY", "00" * 32)
    binding_module.reset_memory_account_bindings()
    bindings = AccountBindingStore.for_runtime()
    row = bindings.create(provider_channel_id="UC-example", display_label="Example", scopes=[SCOPE])
    path = tmp_path / "private" / "tokens.enc"
    store = YouTubeTokenStore(path)
    store.put(row.account_binding_id, StoredToken(access_token="secret", refresh_token="secret", provider_channel_id="UC-example", expires_at=None, scopes=(SCOPE,), obtained_at="2026-01-01T00:00:00Z"))
    monkeypatch.setattr(auth_cli, "YouTubeTokenStore", lambda **kw: YouTubeTokenStore(path, **kw))
    result = _invoke()
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"status": "connected", "reason_code": None, "scopes": [SCOPE], "token_store": "encrypted"}
    assert "secret" not in result.output
    assert "Status: connected" in CliRunner().invoke(cli, ["youtube-auth", "status"]).output


def test_auth_status_handles_missing_ambiguous_and_secrets(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    binding_module.reset_memory_account_bindings()
    assert json.loads(_invoke().output)["status"] == "absent"
    bindings = AccountBindingStore.for_runtime()
    bindings.create(provider_channel_id="UC-one", display_label="one", scopes=[SCOPE])
    bindings.create(provider_channel_id="UC-two", display_label="two", scopes=[SCOPE])
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.output)["reason_code"] == "ambiguous_bindings"
    monkeypatch.setattr(AccountBindingStore, "for_runtime", lambda **kw: (_ for _ in ()).throw(RuntimeError("secret-sentinel")))
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "unavailable"
    assert "secret-sentinel" not in result.output


def test_auth_status_has_no_write_or_network_effects(monkeypatch, tmp_path):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    binding_module.reset_memory_account_bindings()
    bindings = AccountBindingStore.for_runtime()
    bindings.create(provider_channel_id="UC-one", display_label="one", scopes=[SCOPE])
    path = tmp_path / "missing" / "tokens.enc"
    monkeypatch.setattr(auth_cli, "YouTubeTokenStore", lambda **kw: YouTubeTokenStore(path, **kw))
    monkeypatch.setattr(token_module.os, "mkdir", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("write")))
    import httpx
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network")))
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "degraded"
    assert not path.parent.exists()


def test_read_only_postgres_constructor_never_bootstraps(monkeypatch):
    calls = []

    class Cursor:
        def execute(self, statement, *args):
            calls.append(statement)

        def fetchone(self):
            return ("youtube_account_binding",)

        def fetchall(self):
            return []

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    monkeypatch.setattr(binding_module, "_pg_connect", Connection)
    assert AccountBindingStore.for_runtime(read_only=True).list_all() == ()
    assert calls and all(query.startswith("SELECT") for query in calls)


def test_read_only_default_refuses_legacy_without_migration(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy.enc"
    legacy.write_bytes(b"legacy ciphertext")
    monkeypatch.setattr(token_module, "canonical_oauth_state_root", lambda: tmp_path / "state")
    monkeypatch.setattr(token_module, "active_environment", lambda: token_module.ENV_DEV)
    monkeypatch.setattr(token_module, "_legacy_default_token_store_paths", lambda: (legacy,))
    monkeypatch.delenv(token_module.PATH_ENV_VAR, raising=False)
    monkeypatch.setattr(token_module.YouTubeTokenStore, "_migrate_legacy_default", lambda self: (_ for _ in ()).throw(AssertionError("migration")))
    import pytest
    with pytest.raises(token_module.OAuthStateMigrationError):
        YouTubeTokenStore(read_only=True)
    assert legacy.read_bytes() == b"legacy ciphertext"
    assert not (tmp_path / "state").exists()
