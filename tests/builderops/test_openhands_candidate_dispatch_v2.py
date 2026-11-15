"""Default candidate review dispatch with real fixture Git and fake external ports."""

import hashlib
import json
import subprocess

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_epic_workspace_openhands import FakeAgentServer
from tests.builderops.test_openhands_candidate_wiring import advance_fixture


def candidate_fixture(tmp_path, capsys, monkeypatch, *, test_source="def test_example(): pass\n"):
    data, fetch, identity = advance_fixture(tmp_path, capsys, monkeypatch, test_source=test_source)
    layout, _, _, engine, _, entry, saved, _, _ = data
    # The baseline fixture uses a diagnostic container. Model the existing pinned author
    # server in its recorded synthetic assignment, including its exact stopped lineage.
    ew._record_worker(layout, 6617, runtime="openhands", image=ew.OPENHANDS_IMAGE,
                      network=ew.DEFAULT_NETWORK, budget={"cpus": "1.0", "memory": "1g", "pids": 256})
    mapping = cycle._mapping(layout, "w-a")
    proof = {**saved["repair_execution_proof"], "source": "native-session-metadata",
             "native_session_id": "synthetic-session", "timestamp": "2026-01-01T00:00:00Z",
             "engine": "codex", "model": "gpt-6.1-terra", "effort": "ultra",
             "auth": "chatgpt", "image": ew.OPENHANDS_IMAGE}
    saved["repair_execution_proof"] = proof
    saved["repair_result"]["native_proof"] = proof
    saved["repair_stop_intent"]["assignment"] = ew.assignment_of(mapping)
    cycle._save(layout, saved, expected_worker="w-a", expected_assignment=mapping)
    server = FakeAgentServer()
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(mode=0o700)
    original_command = cycle._command

    def external_command(argv, *, timeout):
        if argv[:2] == ["docker", "inspect"]:
            ident = argv[-1]
            for name, cid in engine.ids.items():
                worker = engine.worker_for_name(name)
                if ident == cid and worker in engine.containers:
                    return subprocess.CompletedProcess(argv, 0, json.dumps([{
                        "Id": cid, "Name": "/" + name, "State": {"Running": True},
                        "Config": {"Labels": {ew.LABEL_EPIC: str(layout.epic), ew.LABEL_WORKER: worker}}}]), "")
        return original_command(argv, timeout=timeout)

    monkeypatch.setattr(cycle, "_command", external_command)
    return data, fetch, identity, server, codex_home


def test_default_candidate_dispatch_reconciles_lost_create_without_duplicate(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, codex_home = candidate_fixture(tmp_path, capsys, monkeypatch)
    layout, author, publisher, engine, _, entry, _, _, _ = data
    def audited_http(method, port, key, path, body, timeout):
        if method == "POST" and path == "/conversations":
            dispatch = cycle._find(layout, 10, identity)["candidate_review_dispatch"]
            record = cycle._mapping(layout, dispatch["worker"])["conversation"]
            assert record["status"] == "creating" and record["id"] == body["conversation_id"]
            assert record["operation_id"] == dispatch["operation_id"] and dispatch["materialized"] is True
        return server(method, port, key, path, body, timeout)

    first = cycle.advance(layout, [entry], fetch=fetch, http=audited_http, codex_home=codex_home)
    assert first["results"][0]["action"] == "awaiting-candidate-review", first
    before_author = cycle._mapping(layout, "w-a")
    server.lose_next_create = True
    server.create_not_applied = True
    result = cycle.advance(layout, [entry], fetch=fetch, http=audited_http, codex_home=codex_home)
    assert result["results"][0]["action"] == "candidate-review-dispatched", result
    row = result["results"][0]
    assert row["conversation_status"] == "unknown"
    posts = [call for call in server.calls if call[0] == "POST"]
    assert len(posts) == 1
    payload = posts[0][3]
    assert payload["conversation_id"] == row["conversation_id"]
    assert payload["tags"] == {"epic": "6615", "issue": "6617", "worker": row["worker"]}
    assert payload["agent_settings"] == {"agent_kind": "acp", "acp_server": "codex", "acp_model": "gpt-6.1-terra"}
    state = cycle._find(layout, 10, identity)
    candidate = state["repair_candidate"]
    scope = state["candidate_review_dispatch"]["binding"]["scope_hashes"]
    assert scope["6617"]["body_sha256"] == hashlib.sha256(data[4]["governing_issue"]["body"].encode()).hexdigest()
    checkout = layout.checkout(row["worker"])
    assert cycle._candidate_git(checkout, "rev-parse", "HEAD").strip() == candidate["candidate_head"]
    assert cycle._candidate_git(checkout, "rev-parse", "HEAD^{tree}").strip() == candidate["tree"]
    assert (checkout / "README.md").read_bytes() == (author / "README.md").read_bytes()
    assert not (checkout / ".git/objects/info/alternates").exists()
    assert all(p.stat().st_nlink == 1 for p in (checkout / ".git/objects").rglob("*") if p.is_file())
    mounts = [engine.runs()[-1][i + 1] for i, value in enumerate(engine.runs()[-1]) if value == "--mount"]
    assert all(str(author) not in mount and str(publisher) not in mount for mount in mounts)
    assert all(str(ew._checkpoint_repo(layout, "w-a")) not in mount for mount in mounts)
    author_now = cycle._mapping(layout, "w-a")
    author_now.pop("review_workers")
    assert author_now == before_author
    assert (author / "private.cache").read_text() == "ignored unique work\n"
    prompt = payload["initial_message"]["content"][0]["text"]
    assert candidate["candidate_head"] in prompt and candidate["tree"] in prompt
    assert "new.py" in prompt and "remove.py" in prompt and "scope_hashes" in prompt
    again = cycle.advance(layout, [entry], fetch=fetch, http=audited_http, codex_home=codex_home)
    assert again["results"][0]["conversation_id"] == row["conversation_id"], again
    assert again["results"][0]["conversation_status"] == "unknown"
    assert len([call for call in server.calls if call[0] == "POST"]) == 1
    server.conversations[row["conversation_id"]] = {"id": row["conversation_id"], "execution_status": "running",
        "agent_settings": payload["agent_settings"], "tags": payload["tags"], "workspace": payload["workspace"]}
    resolved = cycle.advance(layout, [entry], fetch=fetch, http=audited_http, codex_home=codex_home)
    assert resolved["results"][0]["conversation_id"] == row["conversation_id"], resolved
    assert resolved["results"][0]["conversation_status"] == "created"
    assert len([call for call in server.calls if call[0] == "POST"]) == 1


@pytest.mark.parametrize("stage", ["init", "partial-init", "fetch"])
def test_interrupted_git_materialization_replays_same_intent_and_checkout(tmp_path, capsys, monkeypatch, stage):
    data, fetch, identity, server, codex_home = candidate_fixture(tmp_path, capsys, monkeypatch)
    layout, _, _, _, _, entry, _, _, _ = data
    assert cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)["results"][0]["action"] == "awaiting-candidate-review"
    transport = subprocess.run
    interrupted = []

    def lose_fetch_reply(argv, **kwargs):
        matches = ("init" in argv and "--quiet" in argv) if stage in ("init", "partial-init") else (
            "fetch" in argv and "--no-write-fetch-head" in argv)
        if argv[0] == "git" and matches and not interrupted and stage == "partial-init":
            gitdir = cycle.Path(kwargs["cwd"]) / ".git"
            (gitdir / "objects" / "info").mkdir(parents=True)
            (gitdir / "config").write_text("[core]\n\trepositoryformatversion = 0\n")
            interrupted.append(True)
            raise subprocess.TimeoutExpired(argv, 120)
        result = transport(argv, **kwargs)
        if argv[0] == "git" and matches and not interrupted:
            interrupted.append(True)
            raise subprocess.TimeoutExpired(argv, 120)
        return result

    monkeypatch.setattr(subprocess, "run", lose_fetch_reply)
    held = cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)
    assert held["results"][0]["action"] == "wait", held
    intent = cycle._find(layout, 10, identity)["candidate_review_dispatch"]
    assert interrupted and intent["materialized"] is False
    assert layout.checkout(intent["worker"]).is_dir()
    assert not [call for call in server.calls if call[0] == "POST"]
    foreign = layout.checkout(intent["worker"]) / "foreign.txt"
    foreign.write_text("preserve foreign work\n")
    refused = cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)
    assert refused["results"][0]["action"] == "wait", refused
    assert foreign.read_text() == "preserve foreign work\n"
    foreign.unlink()  # The synthetic fixture owner clears only its own test file.
    resumed = cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)
    assert resumed["results"][0]["action"] == "candidate-review-dispatched", resumed
    assert resumed["results"][0]["worker"] == intent["worker"]
    assert resumed["results"][0]["operation_id"] == intent["operation_id"]
    assert len([call for call in server.calls if call[0] == "POST"]) == 1


def test_source_drift_stops_actual_reviewer_and_preserves_original_work(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, codex_home = candidate_fixture(tmp_path, capsys, monkeypatch)
    layout, author, _, engine, _, entry, _, _, _ = data
    assert cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)["results"][0]["action"] == "awaiting-candidate-review"
    dispatched = cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)
    assert dispatched["results"][0]["action"] == "candidate-review-dispatched", dispatched
    worker = dispatched["results"][0]["worker"]
    assert engine.containers[worker] == "running"
    old = entry["head_sha"]
    ew.create_worker(layout, "peer", issue=6619, branch="b/peer", next_action="review", runner=engine)
    ew.start_openhands_worker(layout, "peer", runner=engine, http=server)
    original_pr, original_issue = cycle.closure._pr, cycle.closure._issue
    original_refs = cycle.closure._closing_issue_references
    peer_issue = {"number": 6619, "state": "open", "title": "Peer",
                  "body": data[4]["governing_issue"]["body"], "labels": [{"name": "agent:in-progress"}]}
    peer_pr = {"number": 9, "state": "open", "draft": False, "title": "Peer", "labels": [],
               "body": "Governing-Issue: #6619\nFixes #6619\n",
               "head": {"sha": old, "ref": "b/peer", "repo": {"full_name": cycle.completion.REPOSITORY}},
               "base": {"sha": old, "ref": "main"}}
    monkeypatch.setattr(cycle.closure, "_pr", lambda executor, cwd, repo, number:
                        peer_pr if number == 9 else original_pr(executor, cwd, repo, number))
    monkeypatch.setattr(cycle.closure, "_issue", lambda executor, cwd, repo, number:
                        peer_issue if number == 6619 else original_issue(executor, cwd, repo, number))
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda executor, cwd, repo, number:
                        [6619] if number == 9 else original_refs(executor, cwd, repo, number))

    def peer_fetch(path, timeout):
        if "/pulls?" in path:
            value = [{"number": 9}, {"number": 10}]
        elif "/pulls/9/reviews" in path:
            value = []
        elif path.endswith("/pulls/9"):
            value = peer_pr
        elif path.endswith("/issues/6619"):
            value = peer_issue
        else:
            return fetch(path, timeout)
        return 200, json.dumps(value).encode()

    (author / "private.cache").write_text("new retained work\n")
    held = cycle.advance(layout, [{**entry, "number": 9, "worker": "peer"}, entry],
                         fetch=peer_fetch, http=server, codex_home=codex_home)
    assert held["results"][0]["action"] == "independent-review", held
    assert held["results"][1]["action"] == "wait", held
    assert worker not in engine.containers
    mapping = cycle._mapping(layout, worker)
    assert mapping["state"] == "stopped_verified"
    assert mapping["conversation"]["status"] == ew.CONVERSATION_ENDED
    assert cycle._find(layout, 10, identity)["candidate_review_dispatch"]["held"] is True
    assert (author / "private.cache").read_text() == "new retained work\n"
    assert len([call for call in server.calls if call[0] == "POST"]) == 2


def test_changed_claim_authority_holds_before_review_effect(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, codex_home = candidate_fixture(tmp_path, capsys, monkeypatch)
    layout, _, _, engine, _, entry, _, _, lease = data
    assert cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)["results"][0]["action"] == "awaiting-candidate-review"
    lease["holder"] = "foreign"
    held = cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)
    assert held["results"][0]["action"] == "wait", held
    assert "candidate_review_dispatch" not in cycle._find(layout, 10, identity)
    assert not [call for call in server.calls if call[0] == "POST"]
    assert not engine.containers


def test_missing_pr_observation_stops_same_active_reviewer(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, codex_home = candidate_fixture(tmp_path, capsys, monkeypatch)
    layout, _, _, engine, _, entry, _, _, _ = data
    assert cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)["results"][0]["action"] == "awaiting-candidate-review"
    started = cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)
    row = started["results"][0]
    assert row["action"] == "candidate-review-dispatched", started

    def missing(path, timeout):
        if "/pulls?" in path:
            return 200, b"[]"
        return fetch(path, timeout)

    held = cycle.advance(layout, [entry], fetch=missing, http=server, codex_home=codex_home)
    assert held["results"][0]["action"] == "wait", held
    assert row["worker"] not in engine.containers
    assert cycle._find(layout, 10, identity)["candidate_review_dispatch"]["held"] is True
    assert len([call for call in server.calls if call[0] == "POST"]) == 1


def test_sol_high_candidate_review_dispatch_uses_selected_upstream_settings(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, codex_home = candidate_fixture(tmp_path, capsys, monkeypatch)
    layout, _, _, _, _, entry, _, _, _ = data
    entry.update(model="gpt-6.1-sol", effort="high")
    first = cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)
    assert first["results"][0]["action"] == "awaiting-candidate-review", first
    second = cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=codex_home)
    assert second["results"][0]["action"] == "candidate-review-dispatched", second
    posts = [c for c in server.calls if c[0] == "POST" and c[2] == "/conversations"]
    assert len(posts) == 1
    assert posts[0][3]["agent_settings"] == {"agent_kind": "acp", "acp_server": "codex",
                                             "acp_model": "gpt-6.1-sol", "acp_effort": "high"}
