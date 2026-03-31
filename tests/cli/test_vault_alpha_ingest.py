from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from app.agents.panel.filters import strip_ai_panels
from app.cli import cli
from app.ingest import vault_alpha as vault_alpha
from app.ingest.vault_alpha import _compute_ingest_fingerprint, run_vault_alpha_ingest
from app.retrieval.hybrid import get_store
from app.services.companion_note import companion_path, read_companion, write_companion, CompanionNote
from app.stores import get_object_store, reset_store_backends
from scripts.yaml_roundtrip import load_frontmatter


def _base_env(tmp_path: Path) -> dict[str, str]:
    return {
        "LLM_PROVIDER": "mock",
        "LLM_MOCK_RESPONSE": "Mock response [#1]",
        "INDEX_OUTBOX_PATH": str(tmp_path / "outbox.jsonl"),
        "STORE_BACKEND": "memory",
    }


def _write_system_settings(vault_root: Path) -> None:
    settings_dir = vault_root / "_system" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings = {
        "uuid": "TEST-SETTINGS",
        "title": "Test Settings",
        "version": "0.0.0",
        "runtime": {
            "environment": "dev",
            "database_url": "postgresql://app:app@localhost:5432/app",
            "enable_outbox": True,
            "enable_tracing": False,
        },
        "ingest": {
            "active_vault_path": str(vault_root),
            "file_glob": ["**/*.md"],
            "ignore_glob": ["_system/**"],
            "write_policy": "write_on_diff",
        },
        "index": {
            "bm25_enabled": True,
            "vector_enabled": False,
            "embedding_model": "mock",
            "min_confidence": 0.1,
            "rules": [],
        },
        "sync": {"debounce_ms": 1, "inactive_grace_s": 1},
        "observability": {
            "otlp_endpoint": "http://localhost:4318",
            "jaeger_ui": "http://localhost:16686",
            "trace_level": "info",
        },
        "events": {"catalog_path": "vault/_system/events/catalog.yaml", "sla_outbox_to_index_ms": 1000},
    }
    path = settings_dir / "system-settings.yaml"
    path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")


def _write_layout_note(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        """---
include_folders:
  - "."
---

Vault layout contract for tests.
""",
        encoding="utf-8",
    )


def _prepare_vault(tmp_path: Path) -> Path:
    source = Path("tests/fixtures/vault_alpha")
    dest = tmp_path / "vault"
    shutil.copytree(source, dest)
    _write_layout_note(dest)
    return dest


def _extract_ingested(output: str) -> int:
    match = re.search(r"ingested\s+(\d+)\s+notes", output)
    return int(match.group(1)) if match else -1


def _bare_uuid(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        if not value:
            return ""
        return _bare_uuid(value[0])
    s = str(value).strip()
    if s.startswith("[[") and s.endswith("]]" ):
        s = s[2:-2].strip()
    return s


def _expected_uuid(rel_path: Path, frontmatter_uuid: object | None = None, mirror_uuid: object | None = None) -> str:
    if frontmatter_uuid:
        return _bare_uuid(frontmatter_uuid)
    if mirror_uuid:
        return _bare_uuid(mirror_uuid)
    return str(uuid.uuid5(vault_alpha._VAULT_NOTE_UUID_NAMESPACE, rel_path.as_posix()))


def _seed_companion_only_note(vault: Path) -> tuple[Path, str, str]:
    """Create a note without UUID in frontmatter + a pre-existing companion for it.

    This simulates the healing scenario where a companion exists (from a previous
    ingest) but the frontmatter uuid is missing — the ingest should recover the uuid
    from the companion via content_hash lookup.

    The companion title must match what vault_alpha._derive_title() produces from the
    note body, otherwise the title guard in _find_companion_by_fingerprint() will
    reject the hash match.
    """
    note_path = vault / "Concepts" / "CompanionOnly.md"
    # Give the note a # heading so _derive_title extracts a clean, predictable title
    body = "# Companion Only\n\nNote body without frontmatter uuid.\n"
    note_path.write_text(body, encoding="utf-8")
    stripped = strip_ai_panels(body).strip()
    fingerprint = _compute_ingest_fingerprint(stripped, note_path)
    text_sha256 = str(fingerprint.get("text_sha256", ""))
    note_uuid = "55555555-5555-5555-5555-555555555555"
    from datetime import datetime, timezone
    # Title must match vault_alpha._derive_title() output: "Companion Only"
    companion = CompanionNote(
        uuid=note_uuid,
        source_ref="Concepts/CompanionOnly.md",
        title="Companion Only",
        content_hash=text_sha256,
        ingest_state="tracked",
        last_ingested=datetime.now(timezone.utc).isoformat(),
        created_by_instance="test-seed",
    )
    write_companion(vault, companion)
    return note_path, note_uuid, text_sha256


@pytest.fixture(autouse=True)
def _force_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response [#1]")


def test_vault_alpha_ingest_respects_filters_and_panels(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)
    runner = CliRunner()
    env = _base_env(tmp_path)

    with patch.dict(os.environ, env, clear=False):
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
    assert "Scanned" in result.output
    assert "Included folders" in result.output

    outbox = Path(env["INDEX_OUTBOX_PATH"])
    assert outbox.exists()
    outbox_text = outbox.read_text(encoding="utf-8")
    assert "PANEL_BAD_CONTENT" not in outbox_text

    has_panel = vault / "Concepts" / "HasPanel.md"
    frontmatter, body = load_frontmatter(has_panel.read_text(encoding="utf-8"))
    assert _bare_uuid(frontmatter.get("uuid"))
    docs = get_store().all()
    assert docs
    for doc in docs:
        assert "PANEL_BAD_CONTENT" not in doc.text
    assert any("Real body text" in doc.text for doc in docs)

    needs_uuid = vault / "Concepts" / "NeedsUUID.md"
    fm_needs, _ = load_frontmatter(needs_uuid.read_text(encoding="utf-8"))
    assert _bare_uuid(fm_needs.get("uuid"))
    expected_uuid = _expected_uuid(Path("Concepts/NeedsUUID.md"), fm_needs.get("uuid"))
    companion = read_companion(vault, expected_uuid)
    assert companion is not None, "Companion note should have been created for NeedsUUID"
    assert companion.uuid == expected_uuid
    assert companion.source_ref == "Concepts/NeedsUUID.md"
    assert companion.ingest_state == "tracked"
    assert companion.content_hash
    # Companion must NOT contain human-owned fields
    companion_file_text = (vault / companion_path(expected_uuid)).read_text(encoding="utf-8")
    assert "review_state" not in companion_file_text
    assert "maturity" not in companion_file_text

    existing = vault / "Concepts" / "ExistingUUID.md"
    fm_existing, _ = load_frontmatter(existing.read_text(encoding="utf-8"))
    expected_existing_uuid = _expected_uuid(Path("Concepts/ExistingUUID.md"), fm_existing.get("uuid"))
    companion_existing = read_companion(vault, expected_existing_uuid)
    assert companion_existing is not None
    assert companion_existing.uuid == expected_existing_uuid

    # Legacy VaultMirror directory must NOT be created
    assert not (vault / "System" / "Metadata" / "VaultMirror").exists()


def test_vault_alpha_ingest_persists_uuid_to_companion_and_store(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)
    runner = CliRunner()
    env = _base_env(tmp_path)

    with patch.dict(os.environ, env, clear=False):
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

    needs_uuid = vault / "Concepts" / "NeedsUUID.md"
    fm_needs, _ = load_frontmatter(needs_uuid.read_text(encoding="utf-8"))
    assert _bare_uuid(fm_needs.get("uuid"))
    note_uuid = _expected_uuid(Path("Concepts/NeedsUUID.md"), fm_needs.get("uuid"))
    parsed_uuid = uuid.UUID(note_uuid)

    companion = read_companion(vault, note_uuid)
    assert companion is not None, "Companion note should exist after ingest"
    assert companion.uuid == note_uuid
    assert companion.source_ref == "Concepts/NeedsUUID.md"
    assert companion.content_hash  # sha256 populated

    store = get_object_store()
    stored = store.get(parsed_uuid)
    assert stored is not None
    payload = stored.get("payload") or {}
    assert payload.get("ingest_fingerprint")
    assert payload.get("text")


def test_vault_alpha_ingest_warns_on_companion_uuid_conflict(tmp_path: Path) -> None:
    """
    Companion conflict scenario: companion file at _system/companions/<fm_uuid>.md
    contains a different uuid in its frontmatter (data corruption). Ingest should
    warn and use the frontmatter UUID (authority: healing priority step 1 > step 2).
    """
    from datetime import datetime, timezone

    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)

    # Create a note with frontmatter UUID and write a CORRUPT companion that has
    # a different uuid field inside the file.
    front_uuid = "33333333-3333-3333-3333-333333333333"
    corrupt_companion_uuid = "44444444-4444-4444-4444-444444444444"
    conflict_note = vault / "Concepts" / "CompanionConflict.md"
    conflict_note.write_text(
        f"---\nuuid: {front_uuid}\ntitle: CompanionConflict\n---\nBody with conflict.\n",
        encoding="utf-8",
    )
    # Write a companion at the frontmatter-uuid path but with a DIFFERENT uuid inside
    CompanionNote(
        uuid=corrupt_companion_uuid,  # intentionally wrong
        source_ref="Concepts/CompanionConflict.md",
        title="CompanionConflict",
        content_hash="somehash",
        ingest_state="tracked",
        last_ingested=datetime.now(timezone.utc).isoformat(),
        created_by_instance="test-corrupt",
    )
    # Write it at the FRONTMATTER uuid path (which is the lookup key)
    corrupt_path = vault / "_system" / "companions" / f"{front_uuid}.md"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    from scripts.yaml_roundtrip import dump_frontmatter as _dump_fm
    corrupt_path.write_text(
        _dump_fm(
            {
                "uuid": corrupt_companion_uuid,  # conflict: uuid in file ≠ filename
                "source_ref": "Concepts/CompanionConflict.md",
                "title": "CompanionConflict",
                "content_hash": "somehash",
                "ingest_state": "tracked",
                "last_ingested": datetime.now(timezone.utc).isoformat(),
                "created_by_instance": "test-corrupt",
            },
            "",
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    env = _base_env(tmp_path)
    result = runner.invoke(
        cli,
        ["vault-alpha-ingest", "--vault-root", str(vault), "--max-notes", "20", "--include-test-note"],
        env=env,
    )

    assert result.exit_code == 0, result.output
    try:
        stderr_output = result.stderr  # type: ignore[attr-defined]
    except Exception:
        stderr_output = ""
    warning_output = result.output + (stderr_output or "")
    assert "companion uuid" in warning_output

    # Frontmatter UUID wins; companion should be rewritten with correct uuid
    store = get_object_store()
    stored = store.get(uuid.UUID(front_uuid))
    assert stored is not None
    companion = read_companion(vault, front_uuid)
    assert companion is not None


def test_vault_alpha_ingest_rewrites_uuid_to_wikilink_and_parses_existing_formats(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)

    prelinked_uuid = "77777777-7777-7777-7777-777777777777"
    prelinked = vault / "Concepts" / "Prelinked.md"
    prelinked.write_text(
        f"---\nuuid: [[{prelinked_uuid}]]\ntitle: Prelinked Concept\n---\nPrelinked body\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    env = _base_env(tmp_path)
    with patch.dict(os.environ, env, clear=False):
        result = runner.invoke(
            cli,
            [
                "vault-alpha-ingest",
                "--vault-root",
                str(vault),
                "--max-notes",
                "20",
                "--include-test-note",
            ],
            env=env,
        )
    assert result.exit_code == 0, result.output

    existing = vault / "Concepts" / "ExistingUUID.md"
    fm_existing, _ = load_frontmatter(existing.read_text(encoding="utf-8"))
    assert fm_existing.get("uuid") == "11111111-1111-1111-1111-111111111111"

    fm_prelinked, _ = load_frontmatter(prelinked.read_text(encoding="utf-8"))
    assert _bare_uuid(fm_prelinked.get("uuid")) == prelinked_uuid

    companion_prelinked = read_companion(vault, prelinked_uuid)
    assert companion_prelinked is not None, "Companion note should exist for Prelinked"
    assert companion_prelinked.uuid == prelinked_uuid
    assert companion_prelinked.content_hash  # sha256 populated

    store = get_object_store()
    stored_prelinked = store.get(uuid.UUID(prelinked_uuid))
    assert stored_prelinked is not None
    assert (stored_prelinked.get("payload") or {}).get("ingest_fingerprint")


def test_vault_alpha_ingest_heals_missing_frontmatter_with_companion_when_store_empty(tmp_path: Path) -> None:
    """
    Healing scenario: a companion note exists for a note that has no UUID in frontmatter.
    The ingest should recover the UUID from the companion via content_hash lookup and
    write it back to the vault note's frontmatter.
    """
    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)
    note_path, seeded_uuid, seeded_hash = _seed_companion_only_note(vault)
    env = _base_env(tmp_path)

    with patch.dict(os.environ, env, clear=False):
        summary_first = run_vault_alpha_ingest(vault, max_notes=0, include_test_note=False, force=False)
        assert summary_first.ingested > 0

        frontmatter, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
        healed_uuid = _bare_uuid(frontmatter.get("uuid"))
        assert healed_uuid, "UUID should have been healed into frontmatter"
        assert healed_uuid == seeded_uuid, "Healed UUID should match the pre-seeded companion UUID"

        companion = read_companion(vault, healed_uuid)
        assert companion is not None
        assert companion.uuid == healed_uuid
        assert companion.content_hash

        store = get_object_store()
        stored = store.get(uuid.UUID(healed_uuid))
        assert stored is not None
        stored_payload = stored.get("payload") or {}
        assert stored_payload.get("ingest_fingerprint")

        summary_force = run_vault_alpha_ingest(vault, max_notes=0, include_test_note=False, force=True)
        assert summary_force.ingested > 0
        fm_after_force, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
        assert _bare_uuid(fm_after_force.get("uuid"))

        summary_skip = run_vault_alpha_ingest(vault, max_notes=0, include_test_note=False, force=False)
        assert summary_skip.errors == 0


def test_vault_alpha_ingest_detects_changes_with_fingerprint(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)
    runner = CliRunner()
    env = _base_env(tmp_path)
    store = get_object_store()

    with patch.dict(os.environ, env, clear=False):
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

    needs_uuid = vault / "Concepts" / "NeedsUUID.md"
    fm_needs, _ = load_frontmatter(needs_uuid.read_text(encoding="utf-8"))
    parsed_uuid = uuid.UUID(_expected_uuid(Path("Concepts/NeedsUUID.md"), fm_needs.get("uuid")))
    stored_first = store.get(parsed_uuid)
    assert stored_first is not None
    first_fp = (stored_first.get("payload") or {}).get("ingest_fingerprint")
    assert first_fp

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
    assert _extract_ingested(second.output) == 0
    stored_second = store.get(parsed_uuid)
    assert (stored_second.get("payload") or {}).get("ingest_fingerprint") == first_fp

    needs_uuid.write_text(needs_uuid.read_text(encoding="utf-8") + "\nUpdated content fingerprint check.\n", encoding="utf-8")

    third = runner.invoke(
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
    assert third.exit_code == 0, third.output
    assert _extract_ingested(third.output) >= 1
    stored_third = store.get(parsed_uuid)
    assert (stored_third.get("payload") or {}).get("ingest_fingerprint") != first_fp


def test_vault_alpha_ingest_force_reingests(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)
    runner = CliRunner()
    env = _base_env(tmp_path)

    with patch.dict(os.environ, env, clear=False):
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


def test_vault_alpha_ingest_handles_malformed_frontmatter(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = tmp_path
    concepts = vault / "Concepts"
    _write_layout_note(vault)
    concepts.mkdir(parents=True, exist_ok=True)
    bad = concepts / "Broken.md"
    bad.write_text(
        dedent(
            """\
            ---
            title: bad: [unclosed
            ---
            Body
            """
        ),
        encoding="utf-8",
    )

    summary = run_vault_alpha_ingest(vault, max_notes=10, include_test_note=False, force=True)

    captured = capsys.readouterr()
    assert "Malformed frontmatter" in captured.err
    assert summary.scanned == 3
    assert summary.ingested == 2
    assert summary.malformed == 1
    assert str(Path("Concepts") / "Broken.md") in summary.malformed_notes


def test_vault_alpha_ingest_records_errors_and_resumes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = tmp_path
    concepts = vault / "Concepts"
    _write_layout_note(vault)
    concepts.mkdir(parents=True, exist_ok=True)
    good_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    bad_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    good = concepts / "Good.md"
    bad = concepts / "Bad.md"
    good.write_text(
        dedent(
            f"""\
            ---
            uuid: [[{good_uuid}]]
            title: Good
            ---
            Body good
            """
        ),
        encoding="utf-8",
    )
    bad.write_text(
        dedent(
            f"""\
            ---
            uuid: [[{bad_uuid}]]
            title: Bad
            ---
            Body bad
            """
        ),
        encoding="utf-8",
    )

    import app.ingest.vault_alpha as vault_alpha_module

    original_ingest = vault_alpha_module._ingest_single
    fail_once = {"done": False}

    def fake_ingest(path: Path, *, vault_root: Path, trace_id: str) -> str:
        rel = path.relative_to(vault_root)
        if rel.name == "Bad.md" and not fail_once["done"]:
            fail_once["done"] = True
            raise RuntimeError("boom")
        return original_ingest(path, vault_root=vault_root, trace_id=trace_id)

    monkeypatch.setattr(vault_alpha_module, "_ingest_single", fake_ingest)

    summary_first = run_vault_alpha_ingest(vault, max_notes=10, include_test_note=False, force=False)
    captured_first = capsys.readouterr()
    assert "Error ingesting" in captured_first.err
    assert summary_first.errors == 1
    assert str(Path("Concepts") / "Bad.md") in summary_first.error_notes
    assert summary_first.ingested == 3

    summary_second = run_vault_alpha_ingest(
        vault,
        max_notes=10,
        include_test_note=False,
        force=False,
        resume_from=summary_first.processed_notes,
    )
    assert summary_second.errors == 0
    assert summary_second.ingested >= 1
    assert len(summary_second.processed_notes) >= 2

    store = get_object_store()
    assert store.get(uuid.UUID(good_uuid)) is not None
    assert store.get(uuid.UUID(bad_uuid)) is not None

    monkeypatch.setattr(vault_alpha_module, "_ingest_single", original_ingest)


def _write_note(vault: Path, rel_path: Path, title: str, body: str = "Body") -> Path:
    path = vault / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dedent(
            f"""\
            ---
            title: {title}
            ---
            {body}
            """
        ),
        encoding="utf-8",
    )
    return path


def _store_count() -> int:
    store = get_object_store()
    objs = getattr(store, "_objects", None)
    if isinstance(objs, dict):
        return len(objs)
    return 0


def test_ingest_vault_paths_single_note(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = tmp_path / "vault"
    note_a = _write_note(vault, Path("Concepts/NoteA.md"), title="Note A")
    _write_note(vault, Path("Concepts/NoteB.md"), title="Note B")

    runner = CliRunner()
    env = _base_env(tmp_path)

    with patch.dict(os.environ, env, clear=False):
        result = runner.invoke(
            cli,
            [
                "ingest-vault-paths",
                "--vault-root",
                str(vault),
                str(note_a),
            ],
            env=env,
        )

    assert result.exit_code == 0, result.output
    assert "Scanned 1 paths" in result.output
    assert "ingested 1 notes" in result.output

    fm_a, _ = load_frontmatter(note_a.read_text(encoding="utf-8"))
    note_a_uuid = _bare_uuid(fm_a.get("uuid"))
    assert note_a_uuid
    store = get_object_store()
    assert store.get(uuid.UUID(note_a_uuid)) is not None

    fm_b, _ = load_frontmatter((vault / "Concepts/NoteB.md").read_text(encoding="utf-8"))
    assert not _bare_uuid(fm_b.get("uuid"))
    assert _store_count() == 1


def test_ingest_vault_paths_multiple_notes(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = tmp_path / "vault"
    note_a = _write_note(vault, Path("Concepts/NoteA.md"), title="Note A")
    note_b = _write_note(vault, Path("Concepts/NoteB.md"), title="Note B")
    _write_note(vault, Path("Concepts/NoteC.md"), title="Note C (not ingested)")

    runner = CliRunner()
    env = _base_env(tmp_path)

    with patch.dict(os.environ, env, clear=False):
        result = runner.invoke(
            cli,
            [
                "ingest-vault-paths",
                "--vault-root",
                str(vault),
                str(note_a),
                str(note_b),
            ],
            env=env,
        )

    assert result.exit_code == 0, result.output
    assert "Scanned 2 paths" in result.output
    assert "ingested 2 notes" in result.output
    assert _store_count() == 2

    for note, rel_path in ((note_a, Path("Concepts/NoteA.md")), (note_b, Path("Concepts/NoteB.md"))):
        fm, _ = load_frontmatter(note.read_text(encoding="utf-8"))
        note_uuid = _bare_uuid(fm.get("uuid"))
        assert note_uuid
        assert get_object_store().get(uuid.UUID(note_uuid)) is not None

    note_c = vault / "Concepts/NoteC.md"
    fm_c, _ = load_frontmatter(note_c.read_text(encoding="utf-8"))
    assert not _bare_uuid(fm_c.get("uuid"))


def test_ingest_vault_paths_handles_missing_files(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = tmp_path / "vault"
    note_a = _write_note(vault, Path("Concepts/NoteA.md"), title="Note A")
    missing = vault / "Concepts/Missing.md"

    runner = CliRunner()
    env = _base_env(tmp_path)

    with patch.dict(os.environ, env, clear=False):
        result = runner.invoke(
            cli,
            [
                "ingest-vault-paths",
                "--vault-root",
                str(vault),
                str(note_a),
                str(missing),
            ],
            env=env,
        )

    assert result.exit_code == 0, result.output
    assert "Scanned 2 paths" in result.output
    assert "ingested 1 notes" in result.output
    assert "errors=1" in result.output
    assert "Error ingesting Concepts/Missing.md" in result.output

    fm_a, _ = load_frontmatter(note_a.read_text(encoding="utf-8"))
    note_a_uuid = _expected_uuid(Path("Concepts/NoteA.md"), fm_a.get("uuid"))
    assert get_object_store().get(uuid.UUID(note_a_uuid)) is not None
    assert _store_count() == 1


def test_vault_alpha_ingest_defaults_include_all(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "RootNote.md").write_text("Root note body", encoding="utf-8")
    _write_system_settings(vault)
    _write_layout_note(vault)

    runner = CliRunner()
    env = _base_env(tmp_path)
    with patch.dict(os.environ, env, clear=False):
        result = runner.invoke(
            cli,
            [
                "vault-alpha-ingest",
                "--vault-root",
                str(vault),
                "--max-notes",
                "5",
                "--force",
            ],
            env=env,
        )

    assert result.exit_code == 0, result.output
    assert "Included folders: ." in result.output
    assert _extract_ingested(result.output) >= 1


def test_vault_alpha_ingest_json_summary(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)
    runner = CliRunner(mix_stderr=False)
    env = _base_env(tmp_path)

    with patch.dict(os.environ, env, clear=False):
        result = runner.invoke(
            cli,
            [
                "vault-alpha-ingest",
                "--vault-root",
                str(vault),
                "--max-notes",
                "5",
                "--json",
            ],
            env=env,
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["scanned"] >= 0
    assert "skipped_locked" in payload
    assert "included_folders" in payload
