"""Synthetic ports exercising status assembly and a disconnected coordinator continuation.

The launcher and provider/container boundaries below are fixtures. They do not prove a real native
identity, actual OpenHands service persistence, or a live client disconnect on the worker VM.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import time

import pytest

from app.builderops import epic_run_state
from tests.builderops.test_epic_workspace_engine_handoff import EPIC, ISSUE, Harness


def test_container_execution_identity_and_status_join(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    mapping = h.mapping()
    operation = "pr-completion-" + "a" * 64
    conversation = {**mapping["conversation"], "operation_id": operation}
    from app.builderops import epic_workspace as ew
    ew._record_worker(h.layout, ISSUE, conversation=conversation,
                      pr={"number": 44, "state": "open"}, last_meaningful_progress="partial work")
    synthetic = {"source": "native-session-metadata", "conversation_id": conversation["id"],
                 "operation_id": operation, "container_id": mapping["container_id"], "engine": "claude-code",
                 "model": conversation["model"], "native_session_id": "synthetic-native-session",
                 "auth": "claude-subscription", "image": mapping["image"], "effort": None,
                 "timestamp": "2026-01-01T00:00:00Z"}
    def update(state):
        state["compact_receipts"].append({"kind": "pr_cycle", "execution_proof": synthetic})
        return state
    epic_run_state.update_epic_run_state(h.layout.run_id, root=h.layout.run_state_dir,
                                         expected_epic_issue_number=EPIC, updater=update)
    assert h.main("status") == 0
    report = json.loads(capsys.readouterr().out)
    row = report["workers"][0]
    assert report["epic"] == EPIC and row["issue"] == ISSUE and row["worker"] == "w-a"
    assert row["branch"] == "b/a" and row["pr"]["number"] == 44
    assert row["lifecycle_owner"] == "owner-6618" and row["builder_session"] == "builder-session-6618"
    assert row["conversation"]["id"] == conversation["id"] and row["conversation_status"]["reachable"] is True
    assert row["observed_identity"]["native_session_id"] == "synthetic-native-session"
    assert row["native_descendants"] == "unknown" and row["last_meaningful_progress"] == "partial work"
    # An otherwise identical proof for another container is never joined to this assignment.
    ew._record_worker(h.layout, ISSUE, container_id="e" * 64)
    assert h.main("status") == 0
    assert json.loads(capsys.readouterr().out)["workers"][0]["observed_identity"] is None


@pytest.mark.skipif(not hasattr(os, "fork"), reason="synthetic detached coordinator requires POSIX fork")
def test_client_disconnect_does_not_end_epic_coordination(tmp_path, capsys, monkeypatch):
    from app.builderops import epic_workspace as ew

    h = Harness(tmp_path, capsys)
    h.failure()
    checkpoint = ew._checkpoint
    def interrupted(*args, **kwargs):
        raise ew.EpicWorkspaceError("synthetic interruption after predecessor stop")
    monkeypatch.setattr(ew, "_checkpoint", interrupted)
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "held"
    assert h.mapping()["state"] == "stopped_verified"
    saved_stop = h.mapping()["engine_handoff"]["stop_intent"]["stop_id"]
    monkeypatch.setattr(ew, "_checkpoint", checkpoint)
    h.server.streams.clear()  # replacement does not need the predecessor's event history or summary
    gate, result, pidfile = tmp_path / "client-gone", tmp_path / "coordinator-result.json", tmp_path / "pid"
    launcher = os.fork()
    if launcher == 0:
        try:
            os.setsid()
            child = os.fork()
            if child:
                pidfile.write_text(str(child))
                os._exit(0)
            deadline = time.monotonic() + 20
            while not gate.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                code = h.main("coordinate", "--tick", "after-disconnect", "--apply", "--codex-home", str(h.codex))
            result.write_text(json.dumps({"code": code, "output": output.getvalue(),
                                          "absence": h.server.absence_at_successor}))
        finally:
            os._exit(0)
    _, status = os.waitpid(launcher, 0)
    assert os.waitstatus_to_exitcode(status) == 0 and pidfile.exists()
    gate.write_text("the initiating client has exited")
    deadline = time.monotonic() + 30
    try:
        while not result.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert result.exists(), "synthetic coordinator did not finish its later pass"
        observed = json.loads(result.read_text())
        assert observed["code"] == 0 and observed["absence"] == [True]
        report = json.loads(observed["output"])
        assert report["items"][0]["handoff"]["state"] == "continued"
        assert h.mapping()["engine_handoff"]["status"] == "complete"
        assert h.mapping()["takeover"]["stop_id"] == saved_stop
        assert (h.layout.checkout("w-a") / "continued.txt").read_text() == "synthetic useful continuation\n"
    finally:
        if not result.exists():
            os.kill(int(pidfile.read_text()), signal.SIGTERM)
