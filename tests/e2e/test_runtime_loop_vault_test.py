import importlib
import json
from pathlib import Path

import pytest

from app.cli.uat import DEFAULT_TARGET_SUBDIR, seed_vault_test_notes
import app.observability.status_service as status_service
from app.promotion.consumer import consume_promotion_intents
from app.runtime.runtime_loop import RuntimeLoopConfig, run_once
from app.store import object_store as object_store_module
from app.store.object_store import ObjectStore
from scripts.yaml_roundtrip import load_frontmatter

PROMOTE_UUID = "11111111-1111-4111-8111-111111111111"


@pytest.mark.e2e
def test_runtime_loop_run_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    object_store_module._MEMORY_STORE.clear()

    outbox_path = tmp_path / "outbox.jsonl"

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(Path(__file__).resolve().parents[2] / "docs/settings/panel-actions.md"))
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")

    importlib.reload(status_service)

    vault_root = tmp_path / "vault"
    seed_vault_test_notes(vault_root=vault_root)

    snapshot_path = tmp_path / "snapshot.json"
    cfg = RuntimeLoopConfig(
        snapshot_path=snapshot_path,
        max_notes=50,
        force=True,
        dry_run=False,
        run_panels=True,
        run_promotion_consumer=True,
        outbox_path=outbox_path,
    )

    summary = run_once(vault_root / DEFAULT_TARGET_SUBDIR, cfg)

    assert summary.watcher.get("ingested", 0) >= 1
    assert summary.watcher.get("panel_promotions", 0) >= 1
    assert summary.watcher.get("panel_skipped_policy", 0) == 0
    assert summary.promotion.get("applied", 0) >= 1

    note_path = vault_root / DEFAULT_TARGET_SUBDIR / "AgenticPKM-UAT" / "evergreen-strategy.md"
    frontmatter, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter.get("review_state") == "reviewed"
    assert frontmatter.get("maturity") == "evergreen"

    records = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    promote_events = [rec for rec in records if rec.get("event") == "promote.intent.created"]
    assert promote_events, "expected promote.intent.created in outbox"
    assert promote_events[0].get("payload", {}).get("note", {}).get("path") == str(note_path)

    cursor_path = Path(str(snapshot_path) + ".outbox_cursor.json")
    second_summary = consume_promotion_intents(
        outbox_path=outbox_path, cursor_path=cursor_path, snapshot_path=snapshot_path
    )
    assert second_summary["applied"] == 0
    assert second_summary["errors"] == 0

    store = ObjectStore()
    promoted = store.get_object(PROMOTE_UUID)
    assert promoted is not None
    assert (promoted.payload or {}).get("review_state")
    assert (promoted.payload or {}).get("maturity") == "evergreen"

    status = status_service.get_system_status()
    assert status.events.promote_created_total >= 1
    assert status.events.promotion_executed_total >= 1

    object_store_module._MEMORY_STORE.clear()
