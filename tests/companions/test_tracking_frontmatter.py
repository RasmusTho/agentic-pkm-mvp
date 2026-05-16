"""
Tests for companion tracking frontmatter provenance population.

Issue #975: companion tracking notes had created_by_instance: "" despite
runtime knowing instance provenance.

Covers:
- created_by_instance is populated from runtime instance identity
- if identity is unavailable, field uses an explicit diagnostic value (not empty string)
"""
from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.stores import reset_store_backends


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_layout(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        '---\ninclude_folders:\n  - "."\n---\n\nVault layout.\n',
        encoding="utf-8",
    )


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    # Disable companion cooldown so companion is written immediately in tests
    monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("COMPANION_RENAME_COOLDOWN_SECONDS", "0")
    reset_store_backends()


# ---------------------------------------------------------------------------
# AC1: created_by_instance uses resolved runtime instance identity
# ---------------------------------------------------------------------------


def test_created_by_instance_uses_runtime_instance_identity(
    tmp_path: Path, _mock_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Companion tracking writer must populate created_by_instance from the same
    runtime instance provenance resolver used by outbox event metadata.
    """
    bundle = SimpleNamespace(
        instance=SimpleNamespace(id="home", role="master", environment="prod")
    )
    monkeypatch.setattr(
        "app.ingest.vault_alpha.get_settings_bundle", lambda: bundle, raising=False
    )

    _write_layout(tmp_path)
    note = tmp_path / "note.md"
    note.write_text("---\ntitle: Test Note\n---\n\nBody text.", encoding="utf-8")

    run_vault_alpha_ingest_paths(
        vault_root=tmp_path,
        paths=[note],
    )

    # Find the companion that was written
    companions_dir = tmp_path / "⚙️ System" / "companions"
    written = list(companions_dir.glob("*.md")) if companions_dir.exists() else []
    assert written, "No companion note was written during ingest"

    from scripts.yaml_roundtrip import load_frontmatter
    fm, _ = load_frontmatter(written[0].read_text(encoding="utf-8"))
    assert isinstance(fm, dict), "Companion frontmatter is not a dict"
    created_by = fm.get("created_by_instance", "")
    assert created_by == "home", (
        f"created_by_instance should be 'home' (from runtime identity), got {created_by!r}"
    )


# ---------------------------------------------------------------------------
# AC2: missing identity uses explicit diagnostic, not empty string
# ---------------------------------------------------------------------------


def test_missing_instance_identity_is_explicit(
    tmp_path: Path, _mock_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    When runtime instance identity is unavailable (settings bundle raises or returns None),
    the companion writer must write an explicit diagnostic value rather than an empty string.
    """
    def _no_bundle():
        raise RuntimeError("settings unavailable in test")

    monkeypatch.setattr(
        "app.ingest.vault_alpha.get_settings_bundle", _no_bundle, raising=False
    )

    _write_layout(tmp_path)
    note = tmp_path / "note2.md"
    note.write_text("---\ntitle: Note Without Identity\n---\n\nBody.", encoding="utf-8")

    run_vault_alpha_ingest_paths(
        vault_root=tmp_path,
        paths=[note],
    )

    companions_dir = tmp_path / "⚙️ System" / "companions"
    written = list(companions_dir.glob("*.md")) if companions_dir.exists() else []
    assert written, "No companion note was written during ingest"

    from scripts.yaml_roundtrip import load_frontmatter
    fm, _ = load_frontmatter(written[0].read_text(encoding="utf-8"))
    assert isinstance(fm, dict)
    created_by = fm.get("created_by_instance", "")
    # Must not be empty string — must carry an explicit diagnostic value
    assert created_by != "", (
        "created_by_instance must not be empty string when identity is unavailable; "
        "use an explicit diagnostic value like 'unknown'"
    )
    assert "unknown" in str(created_by).lower(), (
        f"created_by_instance should contain 'unknown' when identity is unavailable, got {created_by!r}"
    )
