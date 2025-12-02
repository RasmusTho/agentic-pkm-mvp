from __future__ import annotations

import re
import shutil
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli
from app.retrieval.hybrid import get_store
from app.stores import reset_store_backends
from scripts.yaml_roundtrip import load_frontmatter


def _base_env(tmp_path: Path) -> dict[str, str]:
    return {
        "LLM_PROVIDER": "mock",
        "LLM_MOCK_RESPONSE": "Mock response [#1]",
        "INDEX_OUTBOX_PATH": str(tmp_path / "outbox.jsonl"),
        "STORE_BACKEND": "memory",
    }


def _prepare_vault(tmp_path: Path) -> Path:
    source = Path("tests/fixtures/vault_alpha")
    dest = tmp_path / "vault"
    shutil.copytree(source, dest)
    return dest


def _extract_ingested(output: str) -> int:
    match = re.search(r"ingested\s+(\d+)\s+notes", output)
    return int(match.group(1)) if match else -1


def test_vault_alpha_ingest_respects_filters_and_panels(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)
    runner = CliRunner()
    env = _base_env(tmp_path)

    result = runner.invoke(
        cli,
        [
            "vault-alpha-ingest",
            "--vault-root",
            str(vault),
            "--max-notes",
            "10",
            "--include-test-note",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert "Scanned 4 files" in result.output
    assert "Included folders" in result.output

    outbox = Path(env["INDEX_OUTBOX_PATH"])
    assert outbox.exists()
    outbox_text = outbox.read_text(encoding="utf-8")
    assert "PANEL_BAD_CONTENT" not in outbox_text

    has_panel = vault / "Concepts" / "HasPanel.md"
    frontmatter, body = load_frontmatter(has_panel.read_text(encoding="utf-8"))
    assert "uuid" not in frontmatter
    docs = get_store().all()
    assert docs
    for doc in docs:
        assert "PANEL_BAD_CONTENT" not in doc.text
    assert any("Real body text" in doc.text for doc in docs)

    needs_uuid = vault / "Concepts" / "NeedsUUID.md"
    fm_needs, _ = load_frontmatter(needs_uuid.read_text(encoding="utf-8"))
    assert not fm_needs.get("uuid")
    mirror_dir = vault / "System/Metadata/VaultMirror/Concepts"
    mirror_files = []
    for candidate in mirror_dir.glob("*.md"):
        fm, body = load_frontmatter(candidate.read_text(encoding="utf-8"))
        if fm.get("title") == "Needs UUID Concept":
            mirror_files.append(candidate)
            assert "Mirror for Concepts/NeedsUUID.md" in body
    assert mirror_files, "Expected mirror file for NeedsUUID"
    mirror_fm, _ = load_frontmatter(mirror_files[0].read_text(encoding="utf-8"))
    assert mirror_fm.get("uuid")
    assert mirror_fm.get("origin") == "vault"
    assert mirror_fm.get("kind") == "note"
    assert mirror_fm.get("review_state") == "provisional"
    assert mirror_fm.get("maturity") == "note"

    existing = vault / "Concepts" / "ExistingUUID.md"
    fm_existing, _ = load_frontmatter(existing.read_text(encoding="utf-8"))
    mirror_existing_dir = vault / "System/Metadata/VaultMirror/Concepts"
    existing_mirrors = [p for p in mirror_existing_dir.glob("*.md") if fm_existing.get("uuid") in p.name]
    assert existing_mirrors
    mirror_existing_fm, _ = load_frontmatter(existing_mirrors[0].read_text(encoding="utf-8"))
    assert mirror_existing_fm.get("uuid") == fm_existing.get("uuid")

    skipped_paths = [vault / "System" / "Internal.md", vault / "Templates" / "NoteTemplate.md"]
    for path in skipped_paths:
        mirror_candidate = vault / "System/Metadata/VaultMirror" / path.relative_to(vault).parent
        assert not mirror_candidate.exists()


def test_vault_alpha_ingest_force_reingests(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)
    runner = CliRunner()
    env = _base_env(tmp_path)

    first = runner.invoke(
        cli,
        [
            "vault-alpha-ingest",
            "--vault-root",
            str(vault),
            "--max-notes",
            "10",
            "--include-test-note",
        ],
        env=env,
    )
    assert first.exit_code == 0, first.output
    ingested_first = _extract_ingested(first.output)
    assert ingested_first > 0

    second = runner.invoke(
        cli,
        [
            "vault-alpha-ingest",
            "--vault-root",
            str(vault),
            "--max-notes",
            "10",
            "--include-test-note",
        ],
        env=env,
    )
    assert second.exit_code == 0, second.output
    ingested_second = _extract_ingested(second.output)
    assert ingested_second == 0

    third = runner.invoke(
        cli,
        [
            "vault-alpha-ingest",
            "--vault-root",
            str(vault),
            "--max-notes",
            "10",
            "--include-test-note",
            "--force",
        ],
        env=env,
    )
    assert third.exit_code == 0, third.output
    ingested_third = _extract_ingested(third.output)
    assert ingested_third > 0
