from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli.uat import SEED_SOURCE, run_vault_test_flow, seed_vault_test_notes
from app.promotion.consumer import reset_promotion_dedup_store
from app.store import object_store as object_store_module
from scripts.yaml_roundtrip import load_frontmatter

pytestmark = pytest.mark.not_pg

GOLDEN_DIR = Path(__file__).parent / "golden_snapshots"
MANIFEST_PATH = GOLDEN_DIR / "manifest.json"
VOLATILE_KEYS = frozenset({"modified_at", "last_processed", "indexed_at"})


@pytest.fixture(autouse=True)
def _reset() -> None:
    object_store_module._MEMORY_STORE.clear()
    reset_promotion_dedup_store()


def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "direct")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", '{"type":"note","confidence":0.95}')
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "config")
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "capture")
    monkeypatch.setenv("VAULT_DESK_DIR_REL", "workbench")
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    return outbox_path


def _load_manifest() -> dict[str, dict[str, object]]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _parse_note(path: Path) -> tuple[dict[str, object], str]:
    frontmatter, body = load_frontmatter(path.read_text(encoding="utf-8"))
    return (frontmatter if isinstance(frontmatter, dict) else {}), body


def _strip_volatile(frontmatter: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in frontmatter.items() if key not in VOLATILE_KEYS}


def _read_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _events_of_type(records: list[dict], event_type: str) -> list[dict]:
    return [record for record in records if record.get("event") == event_type]


def _assert_envelope(record: dict, expected_event: str) -> None:
    assert record.get("event") == expected_event
    assert isinstance(record.get("event_id"), str) and record["event_id"]
    assert isinstance(record.get("trace_id"), str) and record["trace_id"]
    source = record.get("source")
    if isinstance(source, dict):
        assert source.get("component")
    else:
        assert isinstance(source, str) and source
    assert isinstance(record.get("payload"), dict)
    timestamp = record.get("timestamp", "")
    assert isinstance(timestamp, str) and timestamp


def _seed_names() -> list[str]:
    return sorted(path.name for path in SEED_SOURCE.glob("*.md"))


def _run_seeded_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, object, Path, list[dict], dict[str, object]]:
    outbox_path = _setup_env(monkeypatch, tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    seed = seed_vault_test_notes(vault_root=vault, target_subdir="Test")
    summary = run_vault_test_flow(vault_root=vault, target_subdir="Test", assert_expectations=False)
    return seed.destination, summary, outbox_path, _read_outbox(outbox_path), dict(object_store_module._MEMORY_STORE)


class TestColdStartPrecondition:
    def test_store_starts_empty(self) -> None:
        object_store_module._MEMORY_STORE.clear()
        assert len(object_store_module._MEMORY_STORE) == 0


class TestColdRebuildMatchesGolden:
    def test_cold_start_produces_objects(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _, _, objects = _run_seeded_flow(tmp_path, monkeypatch)

        assert objects
        assert len(objects) == len(_seed_names())
        for object_id, domain_object in objects.items():
            assert object_id
            assert domain_object.uuid == object_id
            assert domain_object.kind == "note"
            assert domain_object.source_ref

    def test_cold_start_matches_golden_frontmatter(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seeded_folder, _, _, _, _ = _run_seeded_flow(tmp_path, monkeypatch)

        for note_name in _seed_names():
            actual_fm, _ = _parse_note(seeded_folder / note_name)
            golden_fm, _ = _parse_note(GOLDEN_DIR / note_name.replace(".md", ".golden.md"))
            assert _strip_volatile(actual_fm) == _strip_volatile(golden_fm), note_name

    def test_cold_start_matches_golden_body(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seeded_folder, _, _, _, _ = _run_seeded_flow(tmp_path, monkeypatch)

        for note_name in _seed_names():
            _, actual_body = _parse_note(seeded_folder / note_name)
            _, golden_body = _parse_note(GOLDEN_DIR / note_name.replace(".md", ".golden.md"))
            assert actual_body == golden_body, note_name


class TestColdRebuildEventChain:
    def test_cold_start_emits_promote_events(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _, records, _ = _run_seeded_flow(tmp_path, monkeypatch)

        assert _events_of_type(records, "promote.intent.created")
        assert _events_of_type(records, "promote.done")

    def test_cold_start_event_envelopes_valid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _, records, _ = _run_seeded_flow(tmp_path, monkeypatch)

        event_records = [record for record in records if record.get("event")]
        assert event_records
        for record in event_records:
            _assert_envelope(record, str(record["event"]))


class TestColdRebuildIdempotency:
    def test_rerun_from_cold_is_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, summary, _, _, _ = _run_seeded_flow(tmp_path, monkeypatch)

        checks = summary.checks or {}
        assert checks.get("rerun_no_changes") is True
        assert checks.get("rerun_no_panel_side_effects") is True

    def test_full_clear_and_rebuild_matches_first_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        first_folder, _, _, _, _ = _run_seeded_flow(tmp_path / "first", monkeypatch)
        first_frontmatter = {
            note_name: _strip_volatile(_parse_note(first_folder / note_name)[0])
            for note_name in _seed_names()
        }

        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

        second_folder, _, _, _, _ = _run_seeded_flow(tmp_path / "second", monkeypatch)
        second_frontmatter = {
            note_name: _strip_volatile(_parse_note(second_folder / note_name)[0])
            for note_name in _seed_names()
        }

        assert second_frontmatter == first_frontmatter


class TestColdStartCoreFields:
    def test_objects_have_valid_core6_fields(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _, _, objects = _run_seeded_flow(tmp_path, monkeypatch)
        manifest = _load_manifest()

        assert len(objects) == len(manifest)
        for domain_object in objects.values():
            assert domain_object.uuid
            assert domain_object.kind == "note"
            assert domain_object.source_ref
            core6 = domain_object.payload.get("core6") or {}
            assert core6.get("id") == domain_object.uuid
            assert core6.get("origin") == "vault"

        evergreen_uuid = "11111111-1111-4111-8111-111111111111"
        evergreen = objects[evergreen_uuid]
        assert evergreen.payload.get("review_state") == "reviewed"
        assert evergreen.payload.get("maturity") == "evergreen"
