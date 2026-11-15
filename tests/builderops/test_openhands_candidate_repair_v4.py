"""Candidate repair dispatch through the default cycle and owned real Git fixture."""

import json

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_openhands_candidate_result_v3 import advance, prepared


def finding_ready(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, home, reviewer, cid, report, _ = prepared(tmp_path, capsys, monkeypatch)
    finding = {"severity": "P1", "category": "correctness", "protected_class": "none", "summary": "repair",
               "file": "new.py", "line": 1, "failure_scenario": "failure"}
    report.update(verdict="findings", findings=[finding])
    server.final_responses[cid] = json.dumps(report)
    result = advance(data, fetch, server, home)
    assert result["action"] == "awaiting-candidate-repair", result
    return data, fetch, identity, server, home, reviewer, report


def test_default_candidate_repair_dispatch_reconciles_lost_create(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, home, reviewer, report = finding_ready(tmp_path, capsys, monkeypatch)
    layout, author, publisher, engine, _, entry, _, _, _ = data
    original_author = cycle._mapping(layout, "w-a")
    original_review = cycle._mapping(layout, reviewer)
    saved = cycle._find(layout, 10, identity)
    candidate = saved["repair_candidate"]
    assert "candidate_repair_stop_intent" not in saved
    assert "candidate_repair_execution_proof" not in saved
    server.lose_next_create = True
    server.create_not_applied = True
    observed = []

    def http(method, port, key, path, body, timeout):
        if method == "POST" and path == "/conversations":
            current = cycle._find(layout, 10, identity)
            intent = current["candidate_repair"]
            worker = intent["worker"]
            record = cycle._mapping(layout, worker)["conversation"]
            assert record["status"] == "creating" and record["id"] == body["conversation_id"]
            assert body["agent_settings"] == {"agent_kind": "acp", "acp_server": "codex", "acp_model": "gpt-6.1-terra"}
            assert body["tags"] == {"epic": "6615", "issue": "6617", "worker": worker}
            assert intent["source_base_head"] == candidate["candidate_head"]
            assert cycle._candidate_git(layout.checkout(worker), "rev-parse", "HEAD").strip() == candidate["candidate_head"]
            assert cycle._candidate_git(layout.checkout(worker), "rev-parse", "HEAD^{tree}").strip() == candidate["tree"]
            assert not (layout.checkout(worker) / ".git/objects/info/alternates").exists()
            assert all(p.stat().st_nlink == 1 for p in (layout.checkout(worker) / ".git/objects").rglob("*") if p.is_file())
            mounts = [engine.runs()[-1][i + 1] for i, value in enumerate(engine.runs()[-1]) if value == "--mount"]
            assert all(str(author) not in m and str(publisher) not in m and str(layout.checkout(reviewer)) not in m for m in mounts)
            assert all(str(ew._checkpoint_repo(layout, name)) not in m for m in mounts for name in ("w-a", reviewer))
            prompt = body["initial_message"]["content"][0]["text"]
            assert candidate["candidate_head"] in prompt and entry["head_sha"] in prompt and "failure" in prompt
            observed.append(body["conversation_id"])
        return server(method, port, key, path, body, timeout)

    answer = cycle.advance(layout, [entry], fetch=fetch, http=http, codex_home=home)["results"][0]
    assert answer["action"] == "candidate-repair-author", answer
    assert answer["conversation_status"] == "unknown"
    assert observed == [answer["conversation_id"]]
    again = cycle.advance(layout, [entry], fetch=fetch, http=http, codex_home=home)["results"][0]
    assert again["action"] == "candidate-repair-author", again
    assert again["conversation_id"] == answer["conversation_id"]
    assert len(observed) == 1
    current_author = cycle._mapping(layout, "w-a")
    current_author.pop("review_workers")
    original_author.pop("review_workers")
    assert current_author == original_author
    assert cycle._mapping(layout, reviewer) == original_review
    assert (author / "private.cache").read_text() == "ignored unique work\n"
    assert ew._worker_mapping(ew._load_state(layout), answer["worker"])["state"] == "running"


@pytest.mark.parametrize("drift", ["source", "authority", "finding"])
def test_candidate_repair_source_drift_stops_author_without_clobber(tmp_path, capsys, monkeypatch, drift):
    data, fetch, identity, server, home, _, _ = finding_ready(tmp_path, capsys, monkeypatch)
    started = advance(data, fetch, server, home)
    assert started["action"] == "candidate-repair-author", started
    if drift == "source":
        (data[1] / "private.cache").write_text("retained changed source\n")
    elif drift == "authority":
        data[8]["holder"] = "foreign"
    else:
        saved = cycle._find(data[0], 10, identity)
        saved["candidate_review_receipt"]["report"]["findings"][0]["summary"] = "stale finding"
        cycle._save(data[0], saved)
    held = advance(data, fetch, server, home)
    assert held["action"] == "wait", held
    assert cycle._mapping(data[0], started["worker"])["state"] == "stopped_verified"
    assert cycle._find(data[0], 10, identity)["candidate_repair"]["held"] is True
    assert (data[1] / "private.cache").read_text() == (
        "retained changed source\n" if drift == "source" else "ignored unique work\n")


@pytest.mark.parametrize("lost_commit", [False, True])
def test_finished_candidate_repair_prepares_second_additive_commit(tmp_path, capsys, monkeypatch, lost_commit):
    import subprocess

    data, fetch, identity, server, home, reviewer, _ = finding_ready(tmp_path, capsys, monkeypatch)
    layout, author, publisher, engine, _, entry, _, _, _ = data
    before = cycle._find(layout, 10, identity)["repair_candidate"]
    started = advance(data, fetch, server, home)
    assert started["action"] == "candidate-repair-author", started
    worker, cid = started["worker"], started["conversation_id"]
    mapping = cycle._mapping(layout, worker)
    container_id = mapping["container_id"]
    original_command = cycle._command

    def command(argv, *, timeout):
        if argv[:2] == ["docker", "inspect"] and worker in engine.containers and argv[-1] == container_id:
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"Id": container_id, "Image": "sha256:image",
                "Name": "/" + layout.container_name(worker), "State": {"Running": True}, "Config": {
                    "Image": ew.OPENHANDS_IMAGE, "Env": [], "Labels": {
                        ew.LABEL_EPIC: str(layout.epic), ew.LABEL_WORKER: worker}}}]), "")
        if argv[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, '[{"Id":"sha256:image"}]', "")
        if argv[1:3] == ["exec", container_id]:
            if argv[-2:] == ["login", "status"]:
                output = "Logged in using ChatGPT"
            elif argv[-2:] == ["codex", cid]:
                output = json.dumps({"engine": "codex", "conversation_id": cid, "session_id": "repair-native",
                    "model": "gpt-6.1-terra", "effort": "ultra", "timestamp": "2026-11-15T00:00:00Z"})
            else:
                output = "route-ok\n"
            return subprocess.CompletedProcess(argv, 0, output, "")
        return original_command(argv, timeout=timeout)

    monkeypatch.setattr(cycle, "_command", command)
    (layout.checkout(worker) / "new.py").write_text("candidate repair\n")
    (layout.checkout(worker) / "repair-unique.cache").write_text("retain repair artifact\n")
    server.conversations[cid].update(execution_status="finished",
        agent={"kind": "ACPAgent", "acp_server": "codex", "acp_model": "gpt-6.1-terra"},
        current_model_id="gpt-6.1-terra", current_effort="ultra", available_efforts=[{"value": "ultra"}],
        agent_state={"acp_session_id": "repair-native", "acp_session_cwd": "/workspace"})
    server.events = [{"kind": "MessageEvent", "source": "agent"}]
    if lost_commit:
        executor = cycle.publication.SubprocessExecutor
        lost = []

        class LoseCommitReply(executor):
            def run(self, argv, *, cwd, input_text=None):
                output = super().run(argv, cwd=cwd, input_text=input_text)
                if argv[0] == "git" and "commit" in argv and not lost:
                    lost.append(True)
                    raise RuntimeError("synthetic lost commit readback")
                return output

        monkeypatch.setattr(cycle.publication, "SubprocessExecutor", LoseCommitReply)
    answer = advance(data, fetch, server, home)
    if lost_commit:
        assert answer["action"] == "wait" and lost, answer
        answer = advance(data, fetch, server, home)
    assert answer["action"] == "awaiting-candidate-review", answer
    saved = cycle._find(layout, 10, identity)
    candidate = saved["repair_candidate"]
    assert "candidate_repair_stop_intent" not in saved
    assert "candidate_repair_execution_proof" not in saved
    assert candidate["candidate_head"] != before["candidate_head"]
    assert candidate["old_head"] == entry["head_sha"]
    assert candidate["source_base_head"] == before["candidate_head"]
    assert cycle._candidate_git(publisher, "rev-parse", "HEAD^").strip() == before["candidate_head"]
    assert cycle._candidate_git(publisher, "rev-parse", "HEAD^{tree}").strip() == candidate["tree"]
    assert cycle._candidate_git(publisher, "rev-list", "--count", f"{entry['head_sha']}..HEAD").strip() == "2"
    assert cycle._mapping(layout, worker)["state"] == "stopped_verified"
    assert (layout.checkout(worker) / "repair-unique.cache").read_text() == "retain repair artifact\n"
    assert (author / "private.cache").read_text() == "ignored unique work\n"
    assert cycle._mapping(layout, reviewer)["state"] == "stopped_verified"
    assert len([call for call in server.calls if call[0] == "POST"]) == 2
    next_review = advance(data, fetch, server, home)
    assert next_review["action"] == "candidate-review-dispatched", next_review
    assert next_review["worker"] != reviewer
    assert len([call for call in server.calls if call[0] == "POST"]) == 3


def test_same_lease_renewal_allows_candidate_author(tmp_path, capsys, monkeypatch):
    data, fetch, _, server, home, _, _ = finding_ready(tmp_path, capsys, monkeypatch)
    inspect = cycle.closure._dispatcher_inspect

    def renewed(*args):
        task, events, lease = inspect(*args)
        expiry = "2099-02-01T00:00:00Z"
        return {**task, "lease_expires_at": expiry}, events, {**lease, "expires_at": expiry}

    monkeypatch.setattr(cycle.closure, "_dispatcher_inspect", renewed)
    answer = advance(data, fetch, server, home)
    assert answer["action"] == "candidate-repair-author", answer


def test_foreign_publisher_commit_holds_before_author_creation(tmp_path, capsys, monkeypatch):
    from tests.builderops.test_epic_workspace_lifecycle import _git

    data, fetch, identity, server, home, _, _ = finding_ready(tmp_path, capsys, monkeypatch)
    publisher = data[2]
    (publisher / "foreign.txt").write_text("preserve foreign commit\n")
    _git(publisher, "add", "foreign.txt")
    _git(publisher, "commit", "-m", "foreign synthetic work")
    foreign = _git(publisher, "rev-parse", "HEAD")
    held = advance(data, fetch, server, home)
    assert held["action"] == "wait", held
    assert "candidate_repair" not in cycle._find(data[0], 10, identity)
    assert _git(publisher, "rev-parse", "HEAD") == foreign
    assert (publisher / "foreign.txt").read_text() == "preserve foreign commit\n"
    assert len([call for call in server.calls if call[0] == "POST"]) == 1
