import importlib
from pathlib import Path

import pytest

from app.cli.uat import DEFAULT_TARGET_SUBDIR, seed_vault_test_notes
import app.observability.status_service as status_service
from app.runtime.runtime_loop import RuntimeLoopConfig, run_once
from app.store import object_store as object_store_module
from app.store.object_store import ObjectStore
import app.outbox.events as outbox_events

PROMOTE_UUID = "11111111-1111-4111-8111-111111111111"


@pytest.mark.e2e
def test_runtime_loop_run_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    object_store_module._MEMORY_STORE.clear()

    outbox_path = tmp_path / "outbox.jsonl"
    original_outbox = outbox_events.INDEX_OUTBOX_PATH

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")

    # Ensure status service picks up the temp outbox path
    outbox_events.INDEX_OUTBOX_PATH = str(outbox_path)
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
    assert summary.watcher.get("panel_skipped_policy", 0) >= 1
    assert summary.promotion.get("applied", 0) >= 1

    store = ObjectStore()
    promoted = store.get_object(PROMOTE_UUID)
    assert promoted is not None
    assert (promoted.payload or {}).get("review_state")

    status = status_service.get_system_status()
    assert status.events.promote_created_total >= 1
    assert status.events.promotion_executed_total >= 1

    outbox_events.INDEX_OUTBOX_PATH = original_outbox
    importlib.reload(status_service)
    object_store_module._MEMORY_STORE.clear()
