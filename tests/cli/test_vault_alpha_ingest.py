from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from unittest.mock import patch
from textwrap import dedent

import pytest
from click.testing import CliRunner

from app.agents.panel.filters import strip_ai_panels
from app.cli import cli
from app.ingest.vault_alpha import _compute_ingest_fingerprint, run_vault_alpha_ingest
from app.retrieval.hybrid import get_store
from app.stores import get_object_store, reset_store_backends
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


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


def _bare_uuid(value: str | None) -> str:
    if not value:
        return ""
    s = str(value).strip()
    if s.startswith("[[") and s.endswith("]]"):
        s = s[2:-2].strip()
    return s


def _assert_wikilink_uuid(value: str | None) -> str:
    bare = _bare_uuid(value)
    assert value is not None
    assert str(value).strip().startswith("[[")
    assert str(value).strip().endswith("]]")
    assert bare
    return bare


def _seed_mirror_only_note(vault: Path) -> tuple[Path, str, dict[str, int | str]]:
    note_path = vault / "Concepts" / "MirrorOnly.md"
    body = "Mirror-only note with no frontmatter.\n"
    note_path.write_text(body, encoding="utf-8")
    fingerprint = _compute_ingest_fingerprint(strip_ai_panels(body).strip(), note_path)
    note_uuid = "55555555-5555-5555-5555-555555555555"
    mirror_path = vault / "System/Metadata/VaultMirror/Concepts" / f"{note_uuid}.md"
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    mirror_frontmatter = {
        "uuid": note_uuid,
        "source_ref": "Concepts/MirrorOnly.md",
        "ingest_fingerprint": fingerprint,
    }
    mirror_body = "Mirror for Concepts/MirrorOnly.md"
    mirror_path.write_text(dump_frontmatter(mirror_frontmatter, mirror_body), encoding="utf-8")
    return note_path, note_uuid, fingerprint


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
    _assert_wikilink_uuid(frontmatter.get("uuid"))
    docs = get_store().all()
    assert docs
    for doc in docs:
        assert "PANEL_BAD_CONTENT" not in doc.text
    assert any("Real body text" in doc.text for doc in docs)

    needs_uuid = vault / "Concepts" / "NeedsUUID.md"
    fm_needs, _ = load_frontmatter(needs_uuid.read_text(encoding="utf-8"))
    assert "ingest_fingerprint" not in fm_needs
    note_uuid = _assert_wikilink_uuid(fm_needs.get("uuid"))
    mirror_dir = vault / "System/Metadata/VaultMirror/Concepts"
    mirror_files = []
    for candidate in mirror_dir.glob("*.md"):
        fm, body = load_frontmatter(candidate.read_text(encoding="utf-8"))
        if fm.get("uuid") == note_uuid:
            mirror_files.append(candidate)
            assert "Mirror for Concepts/NeedsUUID.md" in body
    assert mirror_files, "Expected mirror file for NeedsUUID"
    mirror_fm, _ = load_frontmatter(mirror_files[0].read_text(encoding="utf-8"))
    assert mirror_fm.get("uuid") == note_uuid
    assert mirror_fm.get("origin") == "vault"
    assert mirror_fm.get("kind") == "note"
    assert mirror_fm.get("review_state") == "provisional"
    assert mirror_fm.get("maturity") == "note"

    existing = vault / "Concepts" / "ExistingUUID.md"
    fm_existing, _ = load_frontmatter(existing.read_text(encoding="utf-8"))
    assert _assert_wikilink_uuid(fm_existing.get("uuid"))
    mirror_existing_dir = vault / "System/Metadata/VaultMirror/Concepts"
    existing_mirrors = [p for p in mirror_existing_dir.glob("*.md") if _bare_uuid(fm_existing.get("uuid")) in p.name]
    assert existing_mirrors
    mirror_existing_fm, _ = load_frontmatter(existing_mirrors[0].read_text(encoding="utf-8"))
    assert mirror_existing_fm.get("uuid") == _bare_uuid(fm_existing.get("uuid"))

    skipped_paths = [vault / "System" / "Internal.md", vault / "Templates" / "NoteTemplate.md"]
    for path in skipped_paths:
        mirror_candidate = vault / "System/Metadata/VaultMirror" / path.relative_to(vault).parent
        assert not mirror_candidate.exists()


def test_vault_alpha_ingest_persists_uuid_to_note_mirror_and_store(tmp_path: Path) -> None:
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
    assert "ingest_fingerprint" not in fm_needs
    note_uuid = _assert_wikilink_uuid(fm_needs.get("uuid"))
    parsed_uuid = uuid.UUID(note_uuid)

    mirror_path = vault / "System/Metadata/VaultMirror/Concepts" / f"{note_uuid}.md"
    assert mirror_path.exists()
    mirror_fm, _ = load_frontmatter(mirror_path.read_text(encoding="utf-8"))
    assert mirror_fm.get("uuid") == note_uuid
    assert mirror_fm.get("source_ref") == "Concepts/NeedsUUID.md"

    store = get_object_store()
    stored = store.get(parsed_uuid)
    assert stored is not None
    payload = stored.get("payload") or {}
    assert payload.get("ingest_fingerprint")
    assert payload.get("text")


def test_vault_alpha_ingest_warns_on_mirror_conflict(tmp_path: Path) -> None:
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
    try:
        stderr_output = result.stderr  # type: ignore[attr-defined]
    except Exception:
        stderr_output = ""
    warning_output = result.output + (stderr_output or "")
    assert "mirror uuid" in warning_output

    conflict = vault / "Concepts" / "MirrorConflict.md"
    fm_conflict, _ = load_frontmatter(conflict.read_text(encoding="utf-8"))
    front_uuid = _assert_wikilink_uuid(fm_conflict.get("uuid"))

    store = get_object_store()
    stored = store.get(uuid.UUID(front_uuid))
    assert stored is not None
    mirror_path = vault / "System/Metadata/VaultMirror/Concepts" / f"{front_uuid}.md"
    assert mirror_path.exists()


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
    assert _assert_wikilink_uuid(fm_existing.get("uuid")) == "11111111-1111-1111-1111-111111111111"
    assert "ingest_fingerprint" not in fm_existing

    fm_prelinked, _ = load_frontmatter(prelinked.read_text(encoding="utf-8"))
    assert _assert_wikilink_uuid(fm_prelinked.get("uuid")) == prelinked_uuid
    assert "ingest_fingerprint" not in fm_prelinked

    mirror_prelinked = vault / "System/Metadata/VaultMirror/Concepts" / f"{prelinked_uuid}.md"
    assert mirror_prelinked.exists()
    mirror_prelinked_fm, _ = load_frontmatter(mirror_prelinked.read_text(encoding="utf-8"))
    assert mirror_prelinked_fm.get("uuid") == prelinked_uuid
    assert mirror_prelinked_fm.get("ingest_fingerprint")

    store = get_object_store()
    stored_prelinked = store.get(uuid.UUID(prelinked_uuid))
    assert stored_prelinked is not None
    assert (stored_prelinked.get("payload") or {}).get("ingest_fingerprint")


def test_vault_alpha_ingest_heals_missing_frontmatter_with_mirror_when_store_empty(tmp_path: Path) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = _prepare_vault(tmp_path)
    note_path, note_uuid, _ = _seed_mirror_only_note(vault)
    env = _base_env(tmp_path)

    with patch.dict(os.environ, env, clear=False):
        summary_first = run_vault_alpha_ingest(vault, max_notes=0, include_test_note=False, force=False)
        assert summary_first.ingested > 0

        frontmatter, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
        assert _assert_wikilink_uuid(frontmatter.get("uuid")) == note_uuid
        assert "ingest_fingerprint" not in frontmatter

        mirror_path = vault / "System/Metadata/VaultMirror/Concepts" / f"{note_uuid}.md"
        mirror_fm, _ = load_frontmatter(mirror_path.read_text(encoding="utf-8"))
        assert mirror_fm.get("uuid") == note_uuid
        front_fp = mirror_fm.get("ingest_fingerprint")
        assert front_fp

        store = get_object_store()
        stored = store.get(uuid.UUID(note_uuid))
        assert stored is not None
        stored_payload = stored.get("payload") or {}
        assert stored_payload.get("ingest_fingerprint") == front_fp

        summary_force = run_vault_alpha_ingest(vault, max_notes=0, include_test_note=False, force=True)
        assert summary_force.ingested > 0
        fm_after_force, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
        assert _assert_wikilink_uuid(fm_after_force.get("uuid")) == note_uuid
        assert "ingest_fingerprint" not in fm_after_force
        mirror_after_force, _ = load_frontmatter(mirror_path.read_text(encoding="utf-8"))
        assert mirror_after_force.get("ingest_fingerprint") == front_fp

        summary_skip = run_vault_alpha_ingest(vault, max_notes=0, include_test_note=False, force=False)
        assert summary_skip.ingested == 0


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
    parsed_uuid = uuid.UUID(_assert_wikilink_uuid(str(fm_needs["uuid"])))
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
    assert summary.scanned == 1
    assert summary.ingested == 0
    assert summary.malformed == 1
    assert str(Path("Concepts") / "Broken.md") in summary.malformed_notes


def test_vault_alpha_ingest_records_errors_and_resumes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_store_backends()
    get_store().set_documents([])
    vault = tmp_path
    concepts = vault / "Concepts"
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

    import app.ingest.vault_alpha as vault_alpha

    original_ingest = vault_alpha._ingest_single
    fail_once = {"done": False}

    def fake_ingest(path: Path, *, vault_root: Path, trace_id: str) -> str:
        rel = path.relative_to(vault_root)
        if rel.name == "Bad.md" and not fail_once["done"]:
            fail_once["done"] = True
            raise RuntimeError("boom")
        return original_ingest(path, vault_root=vault_root, trace_id=trace_id)

    monkeypatch.setattr(vault_alpha, "_ingest_single", fake_ingest)

    summary_first = run_vault_alpha_ingest(vault, max_notes=10, include_test_note=False, force=False)
    captured_first = capsys.readouterr()
    assert "Error ingesting" in captured_first.err
    assert summary_first.errors == 1
    assert str(Path("Concepts") / "Bad.md") in summary_first.error_notes
    assert summary_first.ingested == 1

    # Resume using processed list to avoid rework on already ingested files
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

    # restore original ingest
    monkeypatch.setattr(vault_alpha, "_ingest_single", original_ingest)


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
    note_a_uuid = _assert_wikilink_uuid(fm_a.get("uuid"))
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

    for note in (note_a, note_b):
        fm, _ = load_frontmatter(note.read_text(encoding="utf-8"))
        note_uuid = _assert_wikilink_uuid(fm.get("uuid"))
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
    note_a_uuid = _assert_wikilink_uuid(fm_a.get("uuid"))
    assert get_object_store().get(uuid.UUID(note_a_uuid)) is not None
    assert _store_count() == 1
