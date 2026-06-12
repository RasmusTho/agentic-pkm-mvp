"""Tests for GET /api/companion/vault/notes — vault note browser endpoint.

Covers:
- Returns list of markdown notes from active vault
- Notes include path, title, size_bytes
- Response includes vault_identity
- Filter by q param (title and path substring match)
- Skips hidden directories (.obsidian, .git)
- Returns empty list when vault is empty
- Handles vault with spaces in path
- 500-note cap
- _parse_browse_max_notes: invalid env falls back to 500
- _parse_browse_max_notes: zero/negative env falls back to 500
- _safe_vault_browse_max_notes: invalid env falls back to 250
- _safe_vault_browse_max_notes: clamps values to [1, 1000]
- Cap is applied: list endpoint returns at most _BROWSE_MAX_NOTES results
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.panel.confirmation as confirm_module
from app.api.app import app


@pytest.fixture(autouse=True)
def _clear_runtime_state() -> None:
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    yield
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    return tmp_path


def _note(vault: Path, rel: str, content: str = "") -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content or f"# {p.stem}\n\nBody.\n", encoding="utf-8")
    return p


def _get_notes(client: TestClient, q: str = "") -> dict:
    params = {"q": q} if q else {}
    return client.get("/api/companion/vault/notes", params=params)


def test_returns_200(client: TestClient, vault: Path) -> None:
    _note(vault, "notes/note.md")
    resp = _get_notes(client)
    assert resp.status_code == 200


def test_empty_vault_returns_empty_list(client: TestClient, vault: Path) -> None:
    resp = _get_notes(client)
    data = resp.json()
    assert data["notes"] == []
    assert data["total_count"] == 0


def test_lists_markdown_notes(client: TestClient, vault: Path) -> None:
    _note(vault, "notes/alpha.md", "# Alpha\n\nBody.\n")
    _note(vault, "notes/beta.md", "# Beta\n\nBody.\n")
    resp = _get_notes(client)
    assert resp.status_code == 200
    data = resp.json()
    paths = [n["path"] for n in data["notes"]]
    assert "notes/alpha.md" in paths
    assert "notes/beta.md" in paths


def test_note_entry_has_required_fields(client: TestClient, vault: Path) -> None:
    _note(vault, "notes/note.md", "# My Note\n\nBody.\n")
    resp = _get_notes(client)
    entry = next(n for n in resp.json()["notes"] if n["path"] == "notes/note.md")
    assert entry["title"] == "My Note"
    assert isinstance(entry["size_bytes"], int)
    assert entry["size_bytes"] > 0


def test_title_from_heading(client: TestClient, vault: Path) -> None:
    _note(vault, "Inbox/todo.md", "# My Todo List\n\nItems.\n")
    resp = _get_notes(client)
    entry = next(n for n in resp.json()["notes"] if "todo" in n["path"])
    assert entry["title"] == "My Todo List"


def test_title_from_heading_strips_inline_markdown(client: TestClient, vault: Path) -> None:
    _note(vault, "Inbox/summary.md", "# 0. **Executive summary**\n\nItems.\n")
    resp = _get_notes(client)
    entry = next(n for n in resp.json()["notes"] if "summary" in n["path"])
    assert entry["title"] == "0. Executive summary"


def test_title_from_heading_strips_markdown_image_sigil(client: TestClient, vault: Path) -> None:
    _note(vault, "Inbox/diagram.md", "# ![Diagram](https://example.com/x.png)\n\nItems.\n")
    resp = _get_notes(client)
    entry = next(n for n in resp.json()["notes"] if "diagram" in n["path"])
    assert entry["title"] == "Diagram"


def test_title_fallback_to_stem(client: TestClient, vault: Path) -> None:
    _note(vault, "notes/unnamed.md", "No heading here.\n")
    resp = _get_notes(client)
    entry = next(n for n in resp.json()["notes"] if "unnamed" in n["path"])
    assert entry["title"] == "unnamed"


def test_skips_hidden_directories(client: TestClient, vault: Path) -> None:
    _note(vault, ".obsidian/config.md")
    _note(vault, ".git/COMMIT_EDITMSG.md")
    _note(vault, "notes/visible.md")
    resp = _get_notes(client)
    paths = [n["path"] for n in resp.json()["notes"]]
    assert all(not p.startswith(".") for p in paths)
    assert "notes/visible.md" in paths


def test_response_includes_vault_identity(client: TestClient, vault: Path) -> None:
    resp = _get_notes(client)
    data = resp.json()
    assert "vault_identity" in data
    identity = data["vault_identity"]
    assert "vault_name" in identity
    assert identity["channel"] == "dev"
    assert identity["provenance"] == "env"


def test_selected_vault_overrides_env_vault_root_for_notes(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.routes.companion as companion_module
    from app.vault.app_local import AppLocalSettingsStore
    from app.vault.manager import VaultManager

    env_vault = tmp_path / "env-vault"
    selected_vault = tmp_path / "selected-vault"
    _note(env_vault, "notes/env-only.md", "# Env Only\n\nWrong vault.\n")
    _note(selected_vault, "notes/selected-only.md", "# Selected Only\n\nRight vault.\n")
    monkeypatch.setenv("VAULT_ROOT", str(env_vault))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    result = manager.initialize_vault(
        selected_vault,
        vault_name="Selected Vault",
        remember=False,
    )
    assert result.context.status == "selected"
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)

    selected_resp = _get_notes(client, q="selected-only")
    assert selected_resp.status_code == 200
    selected_paths = [n["path"] for n in selected_resp.json()["notes"]]
    assert selected_paths == ["notes/selected-only.md"]

    env_resp = _get_notes(client, q="env-only")
    assert env_resp.status_code == 200
    assert env_resp.json()["notes"] == []


def test_filter_by_q_matches_path(client: TestClient, vault: Path) -> None:
    _note(vault, "Inbox/meeting-notes.md", "# Meeting\n\nBody.\n")
    _note(vault, "notes/other.md", "# Other\n\nBody.\n")
    resp = _get_notes(client, q="meeting")
    paths = [n["path"] for n in resp.json()["notes"]]
    assert any("meeting" in p for p in paths)
    assert all(
        "meeting" in n["path"].lower() or "meeting" in n["title"].lower()
        for n in resp.json()["notes"]
    )


def test_filter_by_q_matches_title(client: TestClient, vault: Path) -> None:
    _note(vault, "notes/sprint-review.md", "# Quarterly Review\n\nNotes.\n")
    _note(vault, "notes/other.md", "# Unrelated\n\nBody.\n")
    resp = _get_notes(client, q="quarterly")
    data = resp.json()
    titles = [n["title"].lower() for n in data["notes"]]
    assert any("quarterly" in t for t in titles)
    assert not any("unrelated" in t for t in titles)


def test_filter_empty_q_returns_all(client: TestClient, vault: Path) -> None:
    _note(vault, "notes/a.md")
    _note(vault, "notes/b.md")
    resp_unfiltered = _get_notes(client)
    resp_q_empty = _get_notes(client, q="")
    assert resp_unfiltered.json()["total_count"] == resp_q_empty.json()["total_count"]


def test_vault_path_with_spaces(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_dir = tmp_path / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Niflheim"
    vault_dir.mkdir(parents=True)
    _note(vault_dir, "notes/spacenote.md", "# Space Note\n\nBody.\n")
    monkeypatch.setenv("VAULT_ROOT", str(vault_dir))
    resp = _get_notes(client)
    assert resp.status_code == 200
    paths = [n["path"] for n in resp.json()["notes"]]
    assert "notes/spacenote.md" in paths


def test_non_markdown_files_excluded(client: TestClient, vault: Path) -> None:
    (vault / "notes").mkdir(parents=True, exist_ok=True)
    (vault / "notes" / "image.png").write_bytes(b"\x89PNG")
    (vault / "notes" / "data.json").write_text("{}", encoding="utf-8")
    _note(vault, "notes/note.md")
    resp = _get_notes(client)
    paths = [n["path"] for n in resp.json()["notes"]]
    assert all(p.endswith(".md") for p in paths)


def test_invalid_browse_max_notes_env_falls_back(
    client: TestClient, vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "not-a-number")
    _note(vault, "notes/a.md")
    _note(vault, "notes/b.md")
    import importlib
    import app.api.routes.companion as companion_module

    importlib.reload(companion_module)
    resp = _get_notes(client)
    assert resp.status_code == 200
    assert resp.json()["total_count"] == 2


def test_non_positive_browse_max_notes_env_falls_back(
    client: TestClient, vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "-1")
    _note(vault, "notes/a.md")
    import importlib
    import app.api.routes.companion as companion_module

    importlib.reload(companion_module)
    resp = _get_notes(client)
    assert resp.status_code == 200
    assert resp.json()["total_count"] == 1


# ---------------------------------------------------------------------------
# Unit tests: _parse_browse_max_notes — env validation (P1 / P2 review gate)
# ---------------------------------------------------------------------------


def test_parse_browse_max_notes_invalid_env_returns_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-numeric VAULT_BROWSE_MAX_NOTES must not raise; returns 500."""
    import app.api.routes.companion as companion_module

    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "abc")
    result = companion_module._parse_browse_max_notes()
    assert result == 500


def test_parse_browse_max_notes_zero_returns_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero value for VAULT_BROWSE_MAX_NOTES falls back to 500."""
    import app.api.routes.companion as companion_module

    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "0")
    assert companion_module._parse_browse_max_notes() == 500


def test_parse_browse_max_notes_negative_returns_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative value for VAULT_BROWSE_MAX_NOTES falls back to 500."""
    import app.api.routes.companion as companion_module

    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "-10")
    assert companion_module._parse_browse_max_notes() == 500


def test_parse_browse_max_notes_valid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid positive value is returned as-is."""
    import app.api.routes.companion as companion_module

    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "200")
    assert companion_module._parse_browse_max_notes() == 200


# ---------------------------------------------------------------------------
# Unit tests: _safe_vault_browse_max_notes — env validation (vault browser)
# ---------------------------------------------------------------------------


def test_safe_vault_browse_max_notes_invalid_env_returns_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-numeric VAULT_BROWSE_MAX_NOTES must not raise; returns 250."""
    import app.api.routes.companion as companion_module

    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "notanumber")
    assert companion_module._safe_vault_browse_max_notes() == 250


def test_safe_vault_browse_max_notes_clamps_above_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Values above 1000 are clamped to 1000."""
    import app.api.routes.companion as companion_module

    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "99999")
    assert companion_module._safe_vault_browse_max_notes() == 1000


def test_safe_vault_browse_max_notes_clamps_below_min(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero and negative values are clamped to 1."""
    import app.api.routes.companion as companion_module

    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "0")
    assert companion_module._safe_vault_browse_max_notes() == 1


def test_safe_vault_browse_max_notes_missing_env_returns_250(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing env var returns default of 250."""
    import app.api.routes.companion as companion_module

    monkeypatch.delenv("VAULT_BROWSE_MAX_NOTES", raising=False)
    assert companion_module._safe_vault_browse_max_notes() == 250


# ---------------------------------------------------------------------------
# Integration test: cap is applied (avoids full-vault materialization before cap)
# ---------------------------------------------------------------------------


def test_cap_limits_notes_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint respects the _BROWSE_MAX_NOTES cap (avoids full scan before limit)."""
    import app.api.routes.companion as companion_module

    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")

    # Create more notes than the cap
    cap = 3
    original_cap = companion_module._BROWSE_MAX_NOTES
    companion_module._BROWSE_MAX_NOTES = cap
    try:
        for i in range(cap + 2):
            _note(tmp_path, f"notes/note{i:04d}.md", f"# Note {i}\n\nBody.\n")
        client = TestClient(app)
        resp = client.get("/api/companion/vault/notes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["notes"]) <= cap
    finally:
        companion_module._BROWSE_MAX_NOTES = original_cap
