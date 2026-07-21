from __future__ import annotations

import json
import hashlib
import sqlite3
import copy
from pathlib import Path
from uuid import uuid4

import pytest

import app.builderops.config as config
import app.builderops.cutover_evidence as evidence
from app.builderops.cutover_evidence import CutoverEvidenceError, build_receipt, discover_legacy_stores, write_receipt
from app.builderops.store import SqliteBuilderOpsStore


def _target(state_dir: Path) -> None:
    store = SqliteBuilderOpsStore(state_dir / "builderops.sqlite3")
    store.initialize()
    store.create_agent_worklog(
        id=f"awl_{uuid4().hex}", summary="reconciled", body="reconciled", task_context={},
        source_refs=[{"ref_type": "github_issue", "ref": "#3686"}],
        created_by={"actor_type": "agent", "id": "test"},
    )


def _receipt(state_dir: Path, root: Path) -> dict[str, object]:
    participants = [{"repository": "owner/repo", "root": str(root)}]
    report = [{"path": item["path"], "disposition": "retained"} for item in discover_legacy_stores(participants)]
    return build_receipt(state_dir=state_dir, participants=participants, reconciliation=report, actor="operator")


def _resign(receipt: dict[str, object]) -> None:
    receipt.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_declarative_marker_cannot_activate_empty_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir, root = tmp_path / "state", tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(config, "default_state_dir", lambda: state_dir)
    marker = {"schema_version": config.CUTOVER_ACK_SCHEMA, "legacy_stores_reconciled": True}
    state_dir.mkdir()
    config.host_cutover_ack_path(state_dir).write_text(json.dumps(marker), encoding="utf-8")
    config.host_cutover_ack_path(state_dir).chmod(0o600)
    with pytest.raises(ValueError, match="generated cutover receipt"):
        config.load_paths({})
    assert not (state_dir / "builderops.sqlite3").exists()


def test_generated_receipt_binds_host_user_inventory_and_reconciliation_epoch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir, root = tmp_path / "state", tmp_path / "repo"
    nested = root / "subdir"; nested.mkdir(parents=True); _target(state_dir)
    legacy = root / "runtime" / "builderops" / "builderops.sqlite3"; legacy.parent.mkdir(parents=True)
    source = SqliteBuilderOpsStore(legacy); source.initialize()
    source.create_agent_worklog(id="awl_migrated", summary="source", body="source", task_context={}, source_refs=[{"ref_type":"github_issue","ref":"#3686"}], created_by={"actor_type":"agent","id":"source"})
    with sqlite3.connect(legacy) as conn:
        payload = json.loads(conn.execute("SELECT payload FROM builderops_records WHERE id='awl_migrated'").fetchone()[0])
    SqliteBuilderOpsStore(state_dir / "builderops.sqlite3").create_record(payload)
    participants = [{"repository":"owner/repo", "root":str(root)}]
    receipt = build_receipt(state_dir=state_dir, participants=participants, reconciliation=[{"path":str(legacy), "disposition":"migrated"}], actor="operator")
    write_receipt(state_dir, receipt)
    monkeypatch.setattr(config, "default_state_dir", lambda: state_dir)
    monkeypatch.chdir(nested)
    assert config.load_paths({}).db_path == state_dir / "builderops.sqlite3"
    assert receipt["participants"] == [{"repository": "owner/repo", "root": str(root.resolve())}]
    assert receipt["host_id"] == config.current_host_id() and receipt["user_id"] == config.current_user_id()
    assert receipt["legacy_store_inventory"][0]["path"] == str(legacy.resolve())
    assert receipt["reconciliation"][0]["disposition"] == "migrated"
    assert receipt["reconciliation"][0]["source_record_count"] == 1
    assert receipt["target_store"]["identity"] and receipt["target_store"]["marker"]
    marker = json.loads(receipt["target_store"]["marker"])
    assert marker["epoch"] == receipt["reconciliation_epoch"] and marker["evidence_sha256"]
    changed = build_receipt(state_dir=state_dir, participants=participants, reconciliation=[{"path":str(legacy), "disposition":"retained"}], actor="operator")
    assert receipt["reconciliation_epoch"] != changed["reconciliation_epoch"]


def test_stale_copied_or_incomplete_receipts_fail_before_store_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir, root = tmp_path / "state", tmp_path / "repo"
    root.mkdir(); _target(state_dir)
    legacy = root / "nested" / "runtime" / "builderops" / "builderops.sqlite3"
    legacy.parent.mkdir(parents=True); SqliteBuilderOpsStore(legacy).initialize()
    monkeypatch.setattr(config, "default_state_dir", lambda: state_dir)
    monkeypatch.chdir(root)
    original = _receipt(state_dir, root)
    pristine = copy.deepcopy(original)
    clean_root, clean_state = tmp_path / "clean-root", tmp_path / "clean-state"
    clean_root.mkdir(); _target(clean_state)
    clean_receipt = _receipt(clean_state, clean_root)
    initialize_calls: list[object] = []
    monkeypatch.setattr(SqliteBuilderOpsStore, "initialize", lambda self: initialize_calls.append(self))
    def reject(mutator) -> None:
        receipt = copy.deepcopy(original); mutator(receipt); _resign(receipt); write_receipt(state_dir, receipt)
        with pytest.raises(ValueError, match="generated cutover receipt"): config.load_paths({})
        assert original == pristine
    reject(lambda r: r.__setitem__("host_id", "copied-host"))
    reject(lambda r: r.__setitem__("user_id", "999999"))
    reject(lambda r: r.__setitem__("reconciliation_epoch", str(uuid4())))
    reject(lambda r: r["reconciliation"][0].__setitem__("source_record_count", 99))
    reject(lambda r: r.__setitem__("legacy_store_inventory", []))
    reject(lambda r: r.__setitem__("target_store", {"path":"/copied/target", "identity":"copied", "marker":"copied", "record_count":1}))
    write_receipt(state_dir, original)
    SqliteBuilderOpsStore(legacy).create_agent_worklog(id="awl_post_epoch", summary="post", body="post", task_context={}, source_refs=[{"ref_type":"github_issue","ref":"#3686"}], created_by={"actor_type":"agent","id":"post"})
    with pytest.raises(ValueError): config.load_paths({})
    with pytest.raises(CutoverEvidenceError, match="not accounted"):
        build_receipt(state_dir=state_dir, participants=[{"repository":"owner/repo", "root":str(root)}], reconciliation=[{"path":str(legacy),"disposition":"migrated"}], actor="operator")
    # Traversal errors must be surfaced through the supplied os.walk onerror
    # callback; they must not silently produce an incomplete inventory.
    write_receipt(state_dir, original)
    def denied_walk(_root, *, followlinks, onerror):
        assert followlinks is False
        onerror(PermissionError("denied"))
        return iter(())
    with monkeypatch.context() as walk_patch:
        walk_patch.setattr(evidence.os, "walk", denied_walk)
        with pytest.raises(ValueError, match="generated cutover receipt"): config.load_paths({})
    # A malformed legacy DB fails validation before an implicit consumer can initialize.
    legacy.write_bytes(b"not sqlite")
    with pytest.raises(ValueError, match="generated cutover receipt"): config.load_paths({})
    # Empty and uninitialized targets cannot be activated by a declarative marker.
    for name, make_target in (("empty", lambda path: path.write_bytes(b"")), ("uninitialized", lambda path: sqlite3.connect(path).close())):
        isolated = tmp_path / name; isolated.mkdir()
        marker = isolated / config.CUTOVER_ACK_NAME
        copied = copy.deepcopy(clean_receipt)
        marker.write_text(json.dumps(copied), encoding="utf-8"); marker.chmod(0o600)
        make_target(isolated / "builderops.sqlite3")
        monkeypatch.setattr(config, "default_state_dir", lambda value=isolated: value)
        monkeypatch.chdir(clean_root)
        with pytest.raises(ValueError, match="generated cutover receipt"): config.load_paths({})
        assert not initialize_calls
    assert not initialize_calls


def test_cutover_producer_rejects_post_cutoff_inventory_without_stamping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir, root = tmp_path / "state", tmp_path / "repo"
    root.mkdir(); _target(state_dir)
    participants = [{"repository": "owner/repo", "root": str(root)}]
    real_discover = evidence.discover_legacy_stores
    monkeypatch.setattr(evidence, "discover_legacy_stores", lambda _participants: [{"repository":"owner/repo", "path":str(root / "runtime/builderops/builderops.sqlite3"), "sha256":"x", "size":1, "mtime_ns": 9_999_999_999_999_999_999}])
    with pytest.raises(CutoverEvidenceError, match="changed during reconciliation"):
        build_receipt(state_dir=state_dir, participants=participants, reconciliation=[{"path":str(root / "runtime/builderops/builderops.sqlite3"), "disposition":"retained"}], actor="operator")
    assert not config.host_cutover_ack_path(state_dir).exists()
    with sqlite3.connect(f"file:{state_dir / 'builderops.sqlite3'}?mode=ro", uri=True) as conn:
        assert conn.execute("SELECT value FROM builderops_meta WHERE key = 'host_store_cutover_v2'").fetchone() is None
    monkeypatch.setattr(evidence, "discover_legacy_stores", real_discover)
    legacy = root / "runtime" / "builderops" / "builderops.sqlite3"; legacy.parent.mkdir(parents=True)
    SqliteBuilderOpsStore(legacy).initialize()
    inventory = real_discover(participants)
    calls = 0
    def drifting(_participants):
        nonlocal calls
        calls += 1
        result = copy.deepcopy(inventory)
        if calls > 1:
            result[0]["mtime_ns"] += 1
        return result
    monkeypatch.setattr(evidence, "discover_legacy_stores", drifting)
    with pytest.raises(CutoverEvidenceError, match="inventory drifted"):
        build_receipt(state_dir=state_dir, participants=participants, reconciliation=[{"path":str(legacy), "disposition":"retained"}], actor="operator")
    assert not config.host_cutover_ack_path(state_dir).exists()
    with sqlite3.connect(f"file:{state_dir / 'builderops.sqlite3'}?mode=ro", uri=True) as conn:
        assert conn.execute("SELECT value FROM builderops_meta WHERE key = 'host_store_cutover_v2'").fetchone() is None
