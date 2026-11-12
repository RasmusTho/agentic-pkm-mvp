"""Persistent epic workspace lifecycle (#6616)."""

from __future__ import annotations

import json

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_isolation import FakeEngine, _cli, _seed_repo


def test_container_removal_preserves_checkout_and_run_state(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    assert _cli(root, 6615, engine, "worker-create", "--worker", "w-a", "--issue", "6617", "--branch", "b/a", "--next-action", "finish checkpoint tests") == 0
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--model", "claude-sonnet-5-5", "--", "sleep", "60") == 0

    layout = ew.Layout(root.resolve(), 6615)
    partial = layout.checkout("w-a") / "app" / "partial.py"
    partial.parent.mkdir()
    partial.write_text("def half_done():\n")
    (layout.checkout("w-a") / ".gitignore").write_text("*.txt\n")
    (layout.checkout("w-a") / "notes.txt").write_text("ignored but unique\n")
    (layout.home("w-a") / "session.jsonl").write_text("{}\n")

    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "controlled loss") == 0
    stop = json.loads(capsys.readouterr().out)["work_at_stop"]
    assert stop["unique_work"] is True and "app/partial.py" in stop["uncommitted_paths"]
    assert stop["ignored_paths"] == ["notes.txt"]
    assert engine.containers == {}

    # A fresh controller process (new engine object, no in-memory state) reads it back.
    fresh = FakeEngine()
    assert _cli(root, 6615, fresh, "status") == 0
    report = json.loads(capsys.readouterr().out)
    [worker] = report["workers"]
    assert worker["issue"] == 6617 and worker["branch"] == "b/a"
    assert worker["recorded_state"] == "stopped_verified" and worker["container"] == "absent"
    assert worker["model"] == "claude-sonnet-5-5"
    assert worker["next_action"] == "finish checkpoint tests"
    assert worker["work"]["uncommitted_count"] == 2  # app/partial.py and the new .gitignore
    assert worker["work"]["ignored_count"] == 1
    assert partial.read_text() == "def half_done():\n"
    assert (layout.home("w-a") / "session.jsonl").exists()

    # Re-init is idempotent and keeps the record.
    assert _cli(root, 6615, fresh, "init", "--repo-url", repo) == 0
    state = ew._load_state(layout)
    assert state["issue_mappings"]["6617"]["stop_reason"] == "controlled loss"
