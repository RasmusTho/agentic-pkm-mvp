"""Exercise report-correction model binding through the real cycle with synthetic ports."""

import json
import subprocess
from functools import partial
from types import SimpleNamespace

import pytest

from app.builderops import epic_workspace as ew, openhands_pr_cycle as cycle
from tests.builderops.test_epic_workspace_engine_handoff import CONTRACT, ISSUE, Harness
from tests.builderops.test_epic_workspace_lifecycle import _git
from tests.builderops.test_openhands_model_selection import _start_fixture
from tests.builderops.test_openhands_pr_cycle import HEAD, fetch, review_material


def _wire_cycle(monkeypatch, runner, owner):
    monkeypatch.setattr(cycle, "_worker_runner", runner)
    monkeypatch.setattr(cycle, "subprocess", SimpleNamespace(run=runner, SubprocessError=subprocess.SubprocessError))
    monkeypatch.setattr(ew, "stop_worker", partial(ew.stop_worker, runner=runner))
    monkeypatch.setattr(cycle, "_review_context", lambda pr: ({}, review_material()))
    monkeypatch.setattr(cycle, "native_authority", lambda *args, **kwargs: {"claim_issue": ISSUE, "branch": "b/a"})
    monkeypatch.setattr(cycle, "_automatic_review_worker", lambda *args: owner)
    monkeypatch.setattr(cycle, "ci_once", lambda *args: pytest.fail("invalid report must not verify"))


def _reserve_correction(monkeypatch, advance, layout, number, identity, original):
    with monkeypatch.context() as interrupted:
        def before_create(*args, **kwargs):
            raise OSError("interrupted after correction reservation")

        interrupted.setattr(cycle, "start_or_reconcile_review", before_create)
        assert advance()["reason"] == "interrupted after correction reservation"
    saved = cycle._find(layout, number, identity)
    [pending] = saved["report_reconciliations"]
    assert pending["original_operation"] == original["operation_id"]
    assert saved["review_operation"] == pending["operation"] != original["operation_id"]
    assert pending["archived"]["stop_verified"] is True
    return saved, pending


def _review_outcomes(layout):
    return [(row["operation_id"], row["outcome"]) for row in ew._load_state(layout)["dispatch_decisions"]
            if row.get("kind") == "openhands_pr_completion" and row.get("request") == "independent-review"]


def test_startup_proof_without_catalog_policy_cannot_create_legacy_correction(tmp_path, capsys, monkeypatch):
    model = "claude-sonnet-5-5"
    layout, catalog_runner, server, _ = _start_fixture(tmp_path, capsys, "claude-code", [model])

    def runner(argv, **kwargs):
        if argv[:2] == ["docker", "inspect"] and len(argv) == 3 and not ew._id_present(argv[-1], catalog_runner):
            return subprocess.CompletedProcess(argv, 1, "", "No such object")
        return catalog_runner(argv, **kwargs)

    _wire_cycle(monkeypatch, runner, {"lifecycle_owner": None, "owner": None, "builder_session": None})
    head = ew.inspect_checkout(layout, "w-a", runner=runner)["head"]
    admission = [{"engine": "claude-code", "number": 10, "head_sha": head, "worker": "w-a",
                  "test_venv": "venv", "native_session_owned": True, "verify_targets": ["fixture"]}]

    def observe(path, timeout):
        status, body = fetch(path, timeout)
        return status, body.replace(HEAD.encode(), head.encode())

    def advance():
        return cycle.advance(layout, admission, fetch=observe, http=server)["results"][1]

    initial = advance()
    assert initial["action"] == "independent-review", initial
    identity = initial["identity"]
    first = cycle._mapping(layout, "w-a")["conversation"]
    assert first["model"] == model and first["selection_policy"] == "catalog" and "acp_selector" not in first
    server.native_timestamp = "2026-11-28T00:00:30Z"
    server.final_responses[first["id"]] = "Finished without a report object"
    saved, pending = _reserve_correction(monkeypatch, advance, layout, 10, identity, first)
    archived = pending["archived"]["execution_proof"]
    assert archived.pop("selection_policy") == "catalog"
    pending["original_attempt_sha256"] = cycle._digest(pending["archived"])
    cycle._save(layout, saved)
    mapping = cycle._mapping(layout, "w-a")
    old = dict(mapping["conversation"])
    assert old.pop("selection_policy") == "catalog"
    assert old["selection_proof"]["session_id"] == archived["native_session_id"]
    ew._record_worker(layout, ISSUE, conversation=old)
    server.catalog_code = 503
    writes = [call for call in server.calls if call[0] == "POST"]

    for _ in range(2):
        result = advance()
        assert [call for call in server.calls if call[0] == "POST"] == writes
        assert result["action"] == "wait" and "policy" in result["reason"]
        assert cycle._mapping(layout, "w-a")["state"] == "stopped_verified"
        assert cycle._mapping(layout, "w-a")["stop_id"] == mapping["stop_id"]
        assert cycle._find(layout, 10, identity) == saved
        assert _review_outcomes(layout) == [(first["operation_id"], "completed"), (pending["operation"], "unknown")]

    # Restore just the matching conversation policy. The older execution proof now
    # binds the catalog route, which must still qualify before any successor create.
    ew._record_worker(layout, ISSUE, conversation={**old, "selection_policy": "catalog"})
    assert advance()["action"] == "wait"
    assert len(server.conversations) == 1 and server.catalog_reads == 2
    server.catalog_code = 200
    result = advance()
    assert result["operation_id"] == pending["operation"], result
    successor = cycle._mapping(layout, "w-a")["conversation"]
    assert successor["model"] == model and successor["selection_policy"] == "catalog"
    assert len(server.conversations) == 2 and server.catalog_reads == 3


def _legacy_quota_review(monkeypatch, h, *, issue_body=lambda: CONTRACT):
    h.server.react = False
    layout, worker, number = h.layout, "w-a", 44
    head = _git(layout.checkout(worker), "rev-parse", "HEAD")
    image = h.mapping()["image"]
    native = {}

    def runner(argv, **kwargs):
        assert argv[0] == "docker"
        if argv[:3] == ["docker", "image", "inspect"] and "--format" not in argv:
            output = json.dumps([{"Id": image}])
        elif argv[:2] == ["docker", "inspect"] and len(argv) == 3:
            result = h.engine(["docker", "inspect", "--format", "{{json .}}", argv[-1]], **kwargs)
            if result.returncode:
                return subprocess.CompletedProcess(argv, 1, "", "No such object")
            row = json.loads(result.stdout)
            row.update(Image=image, Name="/" + layout.container_name(worker))
            row["State"]["Running"] = True
            env = ["CLAUDE_CODE_OAUTH_TOKEN=synthetic-fixture"] if h.mapping()["credentials"]["claude"] else []
            row["Config"].update(Image=image, Env=env)
            output = json.dumps([row])
        elif argv[:2] == ["docker", "exec"]:
            assert argv[2] == h.mapping()["container_id"]
            if argv[-1] == ew.CLAUDE_STATUS:
                output = json.dumps({"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"})
            elif argv[-2:] == ["login", "status"]:
                output = "Logged in using ChatGPT"
            elif argv[-2] in ("claude-code", "codex"):
                output = json.dumps(native[argv[-1]])
            else:
                assert "route-ok" in argv[-1]
                output = "route-ok"
        else:
            return h.engine(argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, output, "")

    owner = {key: h.mapping().get(key) for key in ("lifecycle_owner", "owner", "builder_session")}
    _wire_cycle(monkeypatch, runner, owner)

    def observe(path, timeout):
        if "/pulls?" in path:
            data = [{"number": number}]
        elif f"/pulls/{number}/reviews?" in path:
            data = []
        elif path.endswith(f"/pulls/{number}"):
            data = {"number": number, "state": "open", "body": f"Governing-Issue: #{ISSUE}", "draft": False,
                    "labels": [], "head": {"sha": head, "repo": {"full_name": cycle.completion.REPOSITORY}},
                    "base": {"sha": "b" * 40, "ref": "main"}}
        elif path.endswith(f"/issues/{ISSUE}"):
            data = {"number": ISSUE, "state": "open", "body": issue_body(), "title": "Test contract", "labels": []}
        else:
            raise AssertionError(path)
        return 200, json.dumps(data).encode()

    admission = [{"number": number, "head_sha": head, "worker": worker, "engine": "claude-code",
                  "model": "claude-sonnet-5-5", "native_session_owned": True,
                  "test_venv": "/synthetic/venv", "verify_targets": ["tests/example.py::test_step"]}]

    def advance(*, http=None):
        batch = cycle.advance(layout, admission, fetch=observe, http=http or h.server, codex_home=h.codex)
        assert batch["failures"] == [], batch
        return batch["results"][0]

    def finish(record, report):
        cid = record["id"]
        session = f"native-{cid}"
        effort = "max" if record["engine"] == "codex" else None
        h.server.conversations[cid].update(
            execution_status="finished", current_effort=effort or "default",
            available_efforts=[{"value": effort or "default"}],
            agent_state={"acp_session_id": session, "acp_session_cwd": "/workspace"})
        native[cid] = {"engine": record["engine"], "conversation_id": cid, "session_id": session,
                       "model": record["model"], "effort": effort, "timestamp": "2026-11-28T00:01:00Z"}
        h.server.final_responses[cid] = report

    return advance, finish


def test_quota_exhausted_legacy_claude_correction_keeps_its_archived_selection(tmp_path, capsys, monkeypatch):
    auth = tmp_path / "fixture.env"
    auth.write_text("CLAUDE_CODE_OAUTH_TOKEN=synthetic-fixture\n", encoding="utf-8")
    auth.chmod(0o600)
    run = Harness.main

    def start_with_claude(self, *args):
        if args[0] == "openhands-start":
            args = (*args, "--claude-env-file", str(auth))
        return run(self, *args)

    with monkeypatch.context() as startup:
        startup.setattr(Harness, "main", start_with_claude)
        h = Harness(tmp_path, capsys, start_conversation=False, codex_on_predecessor=True)

    advance, finish = _legacy_quota_review(monkeypatch, h)
    initial = advance()
    assert initial["action"] == "independent-review"
    identity, operation = initial["identity"], initial["operation_id"]
    original = h.mapping()["conversation"]
    assert original["engine"] == "claude-code" and "selection_policy" not in original
    finish(original, "Original Claude finished without a report object")
    saved, pending = _reserve_correction(monkeypatch, advance, h.layout, 44, identity, original)
    correction = pending["operation"]
    assert advance()["operation_id"] == correction
    mapping = h.mapping()
    conversation = mapping["conversation"]
    assert (conversation["operation_id"], conversation["engine"], conversation["model"]) == (
        correction, "claude-code", original["model"])
    assert "selection_proof" not in conversation and mapping.get("engine_handoff") is None
    assert len(h.posts()) == 2

    h.old_conversation = conversation["id"]
    h.failure()
    posts = h.posts()
    outcomes = [(operation, "completed"), (correction, "unknown")]
    ticks = [(advance(), h.posts(), h.mapping(), cycle._find(h.layout, 44, identity), _review_outcomes(h.layout))
             for _ in range(2)]
    assert h.posts() == posts, [result for result, *_ in ticks]
    for result, creates, worker, receipt, dispatch in ticks:
        assert result["operation_id"] == correction
        assert result["engine_handoff"] == {
            "state": "held", "error": "report correction quota handoff would change the archived review selection",
        }
        assert creates == posts and worker == mapping and receipt == saved and dispatch == outcomes


@pytest.mark.parametrize("lose_create", [False, True])
def test_quota_handoff_terra_correction_recovers_proves_and_releases(tmp_path, capsys, monkeypatch, lose_create):
    h = Harness(tmp_path, capsys, start_conversation=False)
    layout, worker, number = h.layout, "w-a", 44
    unavailable = None
    withhold_readback = False
    contract = CONTRACT
    advance_cycle, finish = _legacy_quota_review(monkeypatch, h, issue_body=lambda: contract)

    def http(method, port, key, path, body, timeout):
        nonlocal unavailable
        if method == "GET" and withhold_readback and path == f"/conversations/{unavailable}":
            return 503, None
        response = h.server(method, port, key, path, body, timeout)
        if method == "POST" and path == "/conversations" and withhold_readback:
            assert unavailable is None, "the same correction must never send another create"
            unavailable = body["conversation_id"]
            raise OSError("synthetic lost correction create response")
        return response

    def advance():
        return advance_cycle(http=http)

    initial = advance()
    assert initial["action"] == "independent-review", initial
    identity, operation = initial["identity"], initial["operation_id"]
    h.old_conversation = h.mapping()["conversation"]["id"]
    h.failure()
    handed_off = advance()
    assert handed_off["engine_handoff"]["state"] == "awaiting_pr_cycle", handed_off
    assert advance()["operation_id"] == operation
    first = h.mapping()["conversation"]
    handoff = h.mapping()["engine_handoff"]
    assert handoff["status"] == "complete" and handoff["successor_conversation"] == first["id"]
    assert len(h.posts()) == 2 and first["engine"] == "codex" and first["model"] == "gpt-6.1-terra"

    finish(first, "Original Terra finished without a report object")
    saved, pending = _reserve_correction(monkeypatch, advance, layout, number, identity, first)
    correction = saved["review_operation"]
    assert pending["archived"]["execution_proof"]["engine"] == "codex"
    assert h.mapping()["state"] == "stopped_verified" and len(h.posts()) == 2

    withhold_readback = lose_create
    assert advance()["operation_id"] == correction
    second = h.mapping()["conversation"]
    correction_container = h.mapping()["container_id"]
    assert correction_container != pending["archived"]["stop_intent"]["container_id"]
    assert (second["operation_id"], second["engine"], second["model"], second.get("effort")) == (
        correction, "codex", "gpt-6.1-terra", None)
    assert "selection_policy" not in second
    assert h.posts()[-1][3]["conversation_id"] == second["id"]
    assert "initial_message" in h.posts()[-1][3]
    assert len(h.posts()) == 3
    if lose_create:
        assert second["status"] == "unknown"
        for _ in range(2):
            assert advance()["operation_id"] == correction
            assert h.mapping()["conversation"] == second
            assert _review_outcomes(layout) == [(operation, "completed"), (correction, "unknown")]
            assert len(h.posts()) == 3
        contract = CONTRACT + "\nA revised review contract."
        changed = advance()
        assert changed["identity"] != identity and changed["operation_id"] == correction
        assert "review_operation" not in cycle._find(layout, number, changed["identity"])
        assert h.mapping()["conversation"] == second and len(h.posts()) == 3
        contract = CONTRACT
        withhold_readback = False
        assert advance()["operation_id"] == correction
        assert h.mapping()["conversation"]["status"] == "created"

    finish(second, "Correction Terra finished without a report object")
    # The native producer can be proved independently under the recovered admission.
    proof = cycle.native_execution_proof(layout, worker, correction, {"engine": "codex", "model": "gpt-6.1-terra"}, http=http)
    if lose_create:
        current = h.mapping()["conversation"]
        ew._record_worker(layout, ISSUE, conversation={**current, "engine": "claude-code",
                                                       "model": "claude-sonnet-5-5"})
        held = advance()
        assert held["action"] == "wait" and "correction conflicts" in held["reason"]
        assert cycle._find(layout, number, identity) == saved
        ew._record_worker(layout, ISSUE, conversation=current)

        ew._record_worker(layout, ISSUE, engine_handoff={
            **handoff, "confirmation": {**handoff["confirmation"], "model": "claude-opus-5-5"}})
        held = advance()
        assert held["action"] == "wait" and "handoff does not bind" in held["reason"]
        assert cycle._find(layout, number, identity) == saved
        assert h.mapping()["state"] == "running" and len(h.posts()) == 3
        ew._record_worker(layout, ISSUE, engine_handoff=handoff)
    terminal = advance()
    assert "did not produce a conforming report" in terminal["reason"], terminal
    final = cycle._find(layout, number, identity)
    assert final["execution_proof"] == proof and final["public_report_conversation"] == second["id"]
    assert final["stop_verified"] is True
    stop = final["stop_intent"]
    assert stop["previous_stop_id"] == pending["archived"]["stop_intent"]["stop_id"]
    assert h.mapping()["state"] == "stopped_verified" and h.mapping()["stop_id"] == stop["stop_id"]
    assert h.mapping()["conversation"]["status"] == ew.CONVERSATION_ENDED
    assert h.mapping()["engine_handoff"] == handoff
    assert not ew._id_present(correction_container, h.engine)
    assert _review_outcomes(layout) == [(operation, "completed"), (correction, "completed")]
    assert advance()["action"] == "wait" and len(h.posts()) == 3
