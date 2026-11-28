"""Exercise dynamic selection at the normal worker and PR-cycle start boundaries."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial

import pytest

from app.builderops import epic_workspace as ew, openhands_owner_access as owner, openhands_pr_cycle as cycle
from app.builderops.openhands_model_selection import (
    ModelSelectionError, read_codex_catalog, read_fresh_codex_cache, select_from_catalog,
)
from tests.builderops.test_epic_workspace_openhands import FakeAgentServer, _main, _setup
from tests.builderops.test_openhands_pr_cycle import HEAD, fetch, review_material


_CLAUDE_SELECTORS = ("default", "sonnet", "fable", "opus", "haiku")


def _sdk_models(**overrides):
    models = {"default": "claude-sonnet-5-5", "sonnet": "claude-sonnet-5-5",
              "fable": "claude-fable-5-1", "opus": "claude-opus-5-5", "haiku": "claude-haiku-5-5"}
    return [list(row) for row in (models | overrides).items()]


class CatalogServer(FakeAgentServer):
    def __init__(self, family, models):
        super().__init__()
        self.family = family
        package = {"codex": "codex-acp", "claude-code": "claude-agent-acp"}[family]
        self.catalog = {"agent_name": f"@agentclientprotocol/{package}", "error": None,
                        "supports_runtime_model_switch": True,
                        "available_models": [{"model_id": model, "name": f"Display {model}", "description": "Picker description"}
                                             for model in models],
                        "efforts_by_model": {model: [{"value": "high"}] for model in models}}
        if family == "codex":
            self.catalog["cache_models"] = {model: ["high"] for model in models}
        self.cache_file = None
        self.catalog_code = 200
        self.catalog_exception = None
        self.catalog_reads = 0
        self.sdk_models = _sdk_models()
        self.sdk_reads = 0
        self.sdk_failure = False
        self.auth_reads = 0
        self.auth_failure = None
        self.change_session = False
        self.session = str(uuid.uuid4())
        self.initial_model = None
        self.initial_effort = None
        self.native_model = None
        self.native_effort = None
        self.native_timestamp = "2026-11-28T00:00:00Z"
        self.prompts = []
        self.lose_productive_prompt = False

    def __call__(self, method, port, key, path, body, timeout):
        if method == "POST" and path == "/acp/models":
            self.catalog_reads += 1
            self.calls.append((method, port, path, body))
            assert body["refresh"] is True
            assert body["agent_settings"]["acp_server"] == self.family
            if self.catalog_exception:
                raise self.catalog_exception
            return self.catalog_code, self.catalog
        if method == "POST" and path.endswith("/run"):
            self.calls.append((method, port, path, body))
            cid = path.split("/")[2]
            row = self.conversations[cid]
            settings = dict(row["agent_settings"])
            row.update(execution_status="finished", agent={**settings, "kind": "ACPAgent"},
                       current_model_id=self.initial_model or settings["acp_model"],
                       current_effort=self.initial_effort or settings.get("acp_effort"),
                       available_efforts=[{"value": "high"}] if self.family == "codex" else [],
                       agent_state={"acp_session_id": self.session, "acp_session_cwd": "/workspace",
                                    "acp_current_model_id": self.initial_model or settings["acp_model"]})
            return 200, {"success": True}
        if method == "POST" and path.endswith("/events"):
            self.calls.append((method, port, path, body))
            cid = path.split("/")[2]
            prompt = body["content"][0]["text"]
            self.prompts.append(prompt)
            if ew.MODEL_PROBE_REPLY in prompt:
                self.final_responses[cid] = ew.MODEL_PROBE_REPLY
                if self.change_session:
                    self.conversations[cid]["agent_state"]["acp_session_id"] = str(uuid.uuid4())
            elif self.lose_productive_prompt:
                raise OSError("test-only withheld acknowledgement")
            return 200, {"success": True}
        return super().__call__(method, port, key, path, body, timeout)

    def native_metadata(self, cid):
        row = self.conversations[cid]
        current = row["current_model_id"]
        wire = dict(self.sdk_models).get(current, current) if self.family == "claude-code" else current
        return {"engine": self.family, "conversation_id": cid, "session_id": self.session,
                "model": self.native_model or wire,
                "effort": self.native_effort or row["current_effort"], "timestamp": self.native_timestamp}


def _start_fixture(tmp_path, capsys, family, models):
    root, engine, _ = _setup(tmp_path, capsys)
    server = CatalogServer(family, models)
    layout = ew.Layout(root.resolve(), 6615)
    image = "worker@sha256:" + "a" * 64
    env = []
    if family == "codex":
        auth_home = tmp_path / "native-home"
        auth_home.mkdir(mode=0o700)
        auth = {"codex_home": auth_home}
    else:
        env = ["CLAUDE_CODE_OAUTH_TOKEN=synthetic-fixture"]
        auth_file = tmp_path / "claude.env"
        auth_file.write_text(env[0] + "\n", encoding="utf-8")
        auth_file.chmod(0o600)
        auth = {"claude_env_file": auth_file}

    def runner(argv, **kwargs):
        if argv[:3] == ["docker", "image", "inspect"] and "--format" not in argv:
            output = json.dumps([{"Id": image}])
        elif argv[:2] == ["docker", "inspect"] and len(argv) == 3:
            info = json.loads(engine(["docker", "inspect", "--format", "{{json .}}", argv[-1]], **kwargs).stdout)
            info.update(Image=image, Name="/" + layout.container_name("w-a"))
            info["State"]["Running"] = True
            info["Config"].update(Image=image, Env=env)
            output = json.dumps([info])
        elif argv[:2] == ["docker", "exec"]:
            if argv[-3:] == ["app-server", "--listen", "stdio://"]:
                assert family == "codex" and argv[2:5] == ["-w", "/home/worker", next(iter(engine.ids.values()))]
                server.catalog_reads += 1
                if server.catalog_exception:
                    raise server.catalog_exception
                if server.catalog_code != 200:
                    return subprocess.CompletedProcess(argv, 1, "", "unavailable")
                if server.cache_file is not None:
                    try:
                        server.catalog["cache_models"] = read_fresh_codex_cache(
                            server.cache_file, "0.172.0", datetime.now(timezone.utc))
                    except (OSError, ValueError):
                        return subprocess.CompletedProcess(argv, 1, "", "freshness unproved")
                output = json.dumps(server.catalog)
            elif argv[-2:] == ["login", "status"]:
                output = "Logged in using ChatGPT"
            elif argv[-1] == ew.CLAUDE_STATUS:
                server.auth_reads += 1
                output = json.dumps({"loggedIn": server.auth_reads != server.auth_failure,
                                     "authMethod": "oauth_token", "apiProvider": "firstParty"})
            elif argv[-1].endswith("/sdk.mjs"):
                assert family == "claude-code"
                assert server.catalog_reads > server.sdk_reads and server.auth_reads > server.sdk_reads
                assert argv[2:8] == ["-w", "/tmp", next(iter(engine.ids.values())), "/acp-node/bin/node",
                                     "--input-type=module", "--eval"]
                assert argv[-1] == ("/acp-node/lib/node_modules/@agentclientprotocol/claude-agent-acp/"
                                    "node_modules/@anthropic-ai/claude-agent-sdk/sdk.mjs")
                assert kwargs["timeout"] == 25
                server.sdk_reads += 1
                if server.sdk_failure:
                    return subprocess.CompletedProcess(argv, 1, "", "fixture failure")
                output = json.dumps(server.sdk_models)
            elif argv[-2] == family:
                output = json.dumps(server.native_metadata(argv[-1]))
            else:
                assert "route-ok" in argv[-1]
                output = "route-ok"
        else:
            return engine(argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, output, "")

    ew.start_openhands_worker(layout, "w-a", image=image, runner=runner, http=server, **auth)
    prompt = tmp_path / "assignment.txt"
    prompt.write_text("Perform the productive assignment", encoding="utf-8")

    def worker_start(*args):
        return _main(root, runner, server, "conversation-start", "--worker", "w-a", "--engine", family,
                     "--prompt-file", str(prompt), *args)

    return layout, runner, server, worker_start


@pytest.mark.parametrize(("family", "models", "chosen", "effort"), [
    ("codex", ["gpt-6.10-sol", "gpt-6.2-sol", "gpt-8.1-astra", "gpt-9.1-sol"], "gpt-6.10-sol", "high"),
    ("claude-code", ["claude-opus-6-2", "claude-sonnet-6-2", "claude-sonnet-5-5", "claude-sonnet-7-1"], "claude-sonnet-6-2", None),
    ("claude-code", ["claude-opus-6-2", "claude-sonnet-5-5", "claude-sonnet-7-1"], "claude-opus-6-2", None),
])
def test_worker_selects_latest_visible_exact_model_once(tmp_path, capsys, family, models, chosen, effort):
    layout, _, server, start = _start_fixture(tmp_path, capsys, family, models)
    server.catalog["available_models"][-1]["hidden"] = True
    if family == "codex":
        server.catalog["cache_models"].pop(models[-1])
    assert start() == 0
    record = ew._worker_mapping(ew._load_state(layout), "w-a")["conversation"]
    assert record["model"] == chosen and record.get("effort") == effort
    assert record["selection_proof"] == server.native_metadata(record["id"])
    assert ew.MODEL_PROBE_REPLY in server.prompts[0]
    assert server.prompts[1:] == ["Perform the productive assignment"]
    creation = next(body for method, _, path, body in server.calls if (method, path) == ("POST", "/conversations"))
    assert "initial_message" not in creation
    server.catalog_code = 503
    before = list(server.calls)
    assert start() == 2
    assert server.calls == before and ew._worker_mapping(ew._load_state(layout), "w-a")["conversation"] == record


@pytest.mark.parametrize("family", ["codex", "claude-code"])
@pytest.mark.parametrize("fault", ["missing", "error", "timeout", "unlisted", "hidden", "capability"])
def test_worker_refuses_incomplete_or_ineligible_catalog(tmp_path, capsys, family, fault):
    model = "gpt-6.3-sol" if family == "codex" else "claude-sonnet-6-2"
    _, _, server, start = _start_fixture(tmp_path, capsys, family, [model])
    explicit = []
    if fault == "missing":
        server.catalog_code = 404
    elif fault == "error":
        server.catalog["error"] = {"code": "ACPAuthRequired"}
    elif fault == "timeout":
        server.catalog_exception = TimeoutError()
    elif fault in ("unlisted", "hidden"):
        explicit = ["--model", model if fault == "hidden" else model.replace("6", "7")]
        if family == "codex":
            explicit.extend(["--effort", "high"])
        if fault == "hidden":
            server.catalog["available_models"][0]["hidden"] = True
    else:
        if family == "claude-code":
            server.catalog["supports_runtime_model_switch"] = False
        else:
            server.catalog["available_models"].append({"model_id": "gpt-6.2-sol"})
            server.catalog["efforts_by_model"]["gpt-6.2-sol"] = [{"value": "high"}]
            server.catalog["efforts_by_model"][model] = [{"value": "medium"}]
    assert start(*explicit) == 2
    assert "catalog" in capsys.readouterr().err
    assert not server.conversations and not server.prompts


@pytest.mark.parametrize(("family", "fault"), [("codex", "effort"), ("codex", "model"), ("claude-code", "model"),
                                               ("claude-code", "post-lost")])
def test_selection_mismatch_or_lost_prompt_keeps_the_writer_fence(tmp_path, capsys, family, fault):
    model = "gpt-6.3-sol" if family == "codex" else "claude-sonnet-6-2"
    layout, runner, server, start = _start_fixture(tmp_path, capsys, family, [model])
    if fault == "effort":
        server.initial_effort = "medium"
    elif fault == "model":
        server.native_model = "gpt-6.1-terra" if family == "codex" else "claude-sonnet-5-5"
    else:
        server.lose_productive_prompt = True
    assert start() == 2
    record = ew._worker_mapping(ew._load_state(layout), "w-a")["conversation"]
    assert record["model"] == model and record["status"] == "unknown"
    assert len(server.prompts) == {"effort": 0, "model": 1, "post-lost": 2}[fault]
    with pytest.raises(ew.LaunchRefused, match="unconfirmed"):
        ew.reconcile_worker_conversation(layout, "w-a", http=server, runner=runner)
    assert len(server.conversations) == 1


@pytest.mark.parametrize(("family", "model", "selector"), [
    ("codex", "gpt-7.1-sol", None), ("claude-code", "claude-sonnet-6-2", None),
    ("claude-code", "claude-sonnet-5-5", "sonnet"),
])
def test_pr_settings_and_start_bind_the_retained_operation(tmp_path, capsys, monkeypatch, family, model, selector):
    layout, runner, server, _ = _start_fixture(tmp_path, capsys, family, _CLAUDE_SELECTORS if selector else [model])
    monkeypatch.setattr(cycle, "_worker_runner", runner)
    monkeypatch.setattr(cycle, "_command", lambda argv, timeout: runner(argv, timeout=timeout))
    head = ew.inspect_checkout(layout, "w-a", runner=runner)["head"]
    settings = cycle._automatic_settings({"engine": family, "claimant": "owner", "session": "session",
                                          "lifecycle_repo": str(tmp_path), "test_venv": "venv"})
    admission = cycle._validate_admission([{**settings, "number": 7, "head_sha": head, "worker": "w-a",
                                            "native_session_owned": True, "verify_targets": ["fixture"]}])[7]
    pr = {"number": 7, "head_sha": head, "body": "PR body", "governing_issue": {"body": "Issue"}, "review_material": {}}
    op = "pr-completion-" + "c" * 64
    first = cycle.start_or_reconcile_review(layout, "w-a", op, pr, "id", admission, http=server)
    assert first["model"] == model and first["status"] == "created"
    assert cycle._retained_model(admission, first, op)["model"] == model
    assert cycle.review_result(layout, "w-a", op, pr, "id", admission, http=server) is None
    with pytest.raises(cycle.CycleError, match="productive native execution"):
        cycle.native_execution_proof(layout, "w-a", op, admission, http=server)
    server.native_timestamp = "2026-11-28T00:00:30Z"
    proof = cycle.native_execution_proof(layout, "w-a", op, admission, http=server)
    assert proof["model"] == model and proof.get("acp_selector") == selector
    assert proof["auth"] == ("chatgpt" if family == "codex" else "claude-subscription")
    server.catalog_code = 503
    assert cycle.start_or_reconcile_review(layout, "w-a", op, pr, "id", admission, http=server) == first
    assert server.catalog_reads == 1
    if selector:
        info = server.conversations[first["id"]]
        info["current_model_id"] = "default"
        with pytest.raises(cycle.CycleError, match="conversation execution"):
            cycle.native_execution_proof(layout, "w-a", op, admission, http=server)
        info["current_model_id"] = selector
        info["agent_state"]["acp_session_id"] = "changed-session"
        with pytest.raises(cycle.CycleError, match="execution metadata"):
            cycle.native_execution_proof(layout, "w-a", op, admission, http=server)
        retained = cycle._review_model(admission, {"conversation_history": [first]}, {"review_operation": op})
        assert retained["model"] == model and retained["_qualify_selection"] is True
        candidate = cycle._candidate_model(admission, {"repair_operation": op, "repair_engine": family,
                                                       "repair_model": model, "repair_execution_proof": proof})
        assert candidate == retained

        monkeypatch.setattr(cycle, "native_authority", lambda *args, **kwargs: {})
        assert _main(layout.root, runner, server, "worker-stop", "--worker", "w-a", "--reason", "fixture stop") == 0
        assert _main(layout.root, runner, server, "takeover", "--worker", "w-a", "--reason", "fixture continuation") == 0
        mapping = ew._worker_mapping(ew._load_state(layout), "w-a")
        ew.start_openhands_worker(layout, "w-a", image=mapping["image"], claude_env_file=tmp_path / "claude.env",
                                  runner=runner, http=server)
        successor = "pr-completion-" + "e" * 64
        # This exact ID is also a historical explicit pin. The retained alias
        # binding still requires discovery and must refuse when the catalog fails.
        with pytest.raises(ew.LaunchRefused, match="catalog"):
            cycle.start_or_reconcile_review(layout, "w-a", successor, pr, "id", retained, http=server)
        assert len(server.conversations) == 1

        server.catalog_code = 200
        server.sdk_models = _sdk_models(default="claude-sonnet-6-1", sonnet="claude-sonnet-6-1")
        with pytest.raises(ew.LaunchRefused, match="no eligible"):
            cycle.start_or_reconcile_review(layout, "w-a", successor, pr, "id", retained, http=server)
        assert len(server.conversations) == 1

        server.sdk_models = _sdk_models(opus="claude-opus-6-2")
        server.session = str(uuid.uuid4())
        second = cycle.start_or_reconcile_review(layout, "w-a", successor, pr, "id", retained, http=server)
        assert second["id"] != first["id"] and second["model"] == model
        assert second["acp_selector"] == selector and second["selection_policy"] == "catalog"


@pytest.mark.parametrize(("family", "model", "newer"), [
    ("codex", "gpt-6.2-sol", "gpt-6.3-sol"),
    ("claude-code", "claude-sonnet-5-5", "claude-sonnet-6-2"),
])
def test_report_correction_restarts_after_reservation_with_same_exact_pin(tmp_path, capsys, monkeypatch, family, model, newer):
    layout, runner, server, _ = _start_fixture(tmp_path, capsys, family, [model])
    monkeypatch.setattr(cycle, "_worker_runner", runner)
    monkeypatch.setattr(cycle, "_command", lambda argv, timeout: runner(argv, timeout=timeout))
    monkeypatch.setattr(cycle, "_assert_stopped", lambda *args: None)
    monkeypatch.setattr(ew, "stop_worker", partial(ew.stop_worker, runner=runner))
    monkeypatch.setattr(cycle, "_review_context", lambda pr: ({}, review_material()))
    monkeypatch.setattr(cycle, "ci_once", lambda *args: pytest.fail("invalid report must not verify"))
    monkeypatch.setattr(cycle, "native_authority", lambda *args, **kwargs: {"claim_issue": 6617, "branch": "b/a"})
    monkeypatch.setattr(cycle, "_automatic_review_worker", lambda *args: {
        "lifecycle_owner": None, "owner": None, "builder_session": None})
    head = ew.inspect_checkout(layout, "w-a", runner=runner)["head"]
    admission = [{"engine": family, "number": 10, "head_sha": head, "worker": "w-a",
                  "test_venv": "venv", "native_session_owned": True, "verify_targets": ["fixture"]}]

    def observed(path, timeout, *, contract=b"Issue contract"):
        status, body = fetch(path, timeout)
        return status, body.replace(HEAD.encode(), head.encode()).replace(b"Issue contract", contract)

    def advance(fetch_pr=observed):
        return cycle.advance(layout, admission, fetch=fetch_pr, http=server)["results"][1]

    initial = advance()
    assert initial["action"] == "independent-review", initial
    identity = initial["identity"]
    first = cycle._mapping(layout, "w-a")["conversation"]
    assert first["model"] == model and "acp_selector" not in first
    server.native_timestamp = "2026-11-28T00:00:30Z"
    server.final_responses[first["id"]] = "Finished without a report object"
    with monkeypatch.context() as interrupted:
        def before_create(*args, **kwargs):
            raise OSError("interrupted after successor reservation")
        interrupted.setattr(cycle, "start_or_reconcile_review", before_create)
        assert advance()["reason"] == "interrupted after successor reservation"
    saved = cycle._find(layout, 10, identity)
    [pending] = saved["report_reconciliations"]
    successor = saved["review_operation"]
    assert pending["original_operation"] == first["operation_id"] != successor == pending["operation"]
    assert pending["archived"]["execution_proof"]["selection_policy"] == "catalog"
    assert len(server.conversations) == 1

    server.session = str(uuid.uuid4())
    server.catalog = CatalogServer(family, [model, newer]).catalog
    if family == "claude-code":
        # A previous proof carried the native model but no policy marker. Its
        # operation-bound conversation proves that this exact legacy ID used the catalog.
        pending["archived"]["execution_proof"].pop("selection_policy")
        pending["original_attempt_sha256"] = cycle._digest(pending["archived"])
        cycle._save(layout, saved)
        original = cycle._mapping(layout, "w-a")["conversation"]
        ew._record_worker(layout, 6617, conversation=None)
        assert "selection policy is unavailable" in advance()["reason"]
        ew._record_worker(layout, 6617, conversation={**original, "model": newer})
        assert "selection conflict" in advance()["reason"]
        ew._record_worker(layout, 6617, conversation=original)
        assert len(server.conversations) == server.catalog_reads == 1
    wrong_scope = copy.deepcopy(saved)
    wrong_scope["report_reconciliations"][0]["head_sha"] = "f" * 40
    cycle._save(layout, wrong_scope)
    assert "lineage is missing or contradictory" in advance()["reason"]
    cycle._save(layout, saved)

    for _ in range(2):
        result = advance()
        assert result.get("operation_id") == successor, result
    second = cycle._mapping(layout, "w-a")["conversation"]
    assert len(server.conversations) == server.catalog_reads == 2
    assert (second["operation_id"], second["model"], second.get("effort"), second["selection_policy"]) == (
        successor, model, first.get("effort"), "catalog")
    assert second["selection_proof"]["session_id"] == server.session
    assert cycle.REPORT_CONTRACT in server.prompts[-1]

    # A changed contract at the same head gets a new review and reselects from the catalog.
    server.native_timestamp = "2026-11-28T00:01:00Z"
    server.final_responses[second["id"]] = "Still no report object"
    assert "did not produce a conforming report" in advance()["reason"]
    server.session = str(uuid.uuid4())
    changed = advance(partial(observed, contract=b"Revised issue contract"))
    assert changed["identity"] != identity and changed["action"] == "independent-review"
    third = cycle._mapping(layout, "w-a")["conversation"]
    assert third["model"] == newer and third["operation_id"] != successor
    assert len(server.conversations) == server.catalog_reads == 3


@pytest.mark.parametrize("native_effort", [None, "xhigh"])
def test_owner_terra_start_qualifies_high_and_checks_initialized_session(tmp_path, capsys, monkeypatch, native_effort):
    model = "gpt-6.1-terra"
    layout, runner, server, _ = _start_fixture(tmp_path, capsys, "codex", [model])
    server.native_effort = native_effort or "high"
    monkeypatch.setattr(owner, "WORKER", "w-a")
    calls = []

    def controller(config, *args):
        calls.append(args)
        if args[0] == "status":
            return {"workers": [{"worker": "w-a", "container": "running"}]}
        capsys.readouterr()
        status = _main(layout.root, runner, server, *args)
        output = capsys.readouterr()
        if status:
            raise owner.OwnerAccessError(output.err)
        return json.loads(output.out)

    monkeypatch.setattr(owner, "_controller", controller)
    monkeypatch.setattr(owner, "_sandbox_auth", lambda config, engine: calls.append(("auth", engine)))
    monkeypatch.setattr(owner, "_sandbox_profile", lambda config, *pin: calls.append(("profile", *pin)))
    config = {"readiness_prompt": str(tmp_path / "assignment.txt"), "sandbox_url": "https://sandbox.example"}
    command = "sandbox start codex gpt-6.1-terra"
    profile = ("profile", "codex", model, "high")
    if native_effort is not None:
        with pytest.raises(owner.OwnerAccessError, match="execution evidence does not match"):
            owner.run_command(config, command)
        assert profile not in calls and len(server.prompts) == 1
        return

    assert model + " / high" in owner.run_command(config, command)
    create = next(row for row in calls if row[0] == "conversation-start")
    assert create[create.index("--effort") + 1] == "high"
    status = ew.conversation_status(layout, "w-a", runner=runner, http=server)
    record = status["conversation"]
    assert record["selection_policy"] == "catalog" and status["selection_verified"] is True
    assert record["selection_proof"] == server.native_metadata(record["id"])
    assert profile in calls and len(server.prompts) == 2

    calls.clear()
    server.conversations[record["id"]]["agent_state"]["acp_session_id"] = "replacement-session"
    changed = ew.conversation_status(layout, "w-a", runner=runner, http=server)
    assert changed["agent_settings"] == status["agent_settings"]
    assert changed["selection_verified"] is False
    assert "native model selection is not verified" in owner.run_command(config, command)
    assert [row[0] for row in calls] == ["status", "conversation-status", "conversation-status"]
    assert len(server.prompts) == 2


@pytest.mark.parametrize(("family", "original", "older"), [
    ("codex", "gpt-6.3-sol", "gpt-6.2-sol"), ("claude-code", "claude-sonnet-6-2", "claude-sonnet-5-5"),
])
def test_catalog_regression_refuses_successor_before_new_reservation(tmp_path, capsys, family, original, older):
    layout, runner, server, start = _start_fixture(tmp_path, capsys, family, [original, older])
    assert start() == 0
    mapping = ew._worker_mapping(ew._load_state(layout), "w-a")
    server.catalog["available_models"] = [{"model_id": older}]
    if family == "codex":
        server.catalog["cache_models"].pop(original)
    with pytest.raises(ew.LaunchRefused, match="regressed"):
        ew._discover_model(family, None, "high" if family == "codex" else None, mapping,
                           mapping["port"], "test-key-is-a-private-synthetic-key", server, runner)


@pytest.mark.parametrize(("overrides", "selector", "chosen"), [
    ({}, "sonnet", "claude-sonnet-5-5"),
    ({"sonnet": "claude-sonnet-6-2", "opus": "claude-opus-6-2"}, "sonnet", "claude-sonnet-6-2"),
    ({"opus": "claude-opus-6-2", "fable": "claude-fable-7-1"}, "opus", "claude-opus-6-2"),
])
def test_claude_worker_resolves_actual_picker_aliases(tmp_path, capsys, overrides, selector, chosen):
    layout, runner, server, start = _start_fixture(tmp_path, capsys, "claude-code", _CLAUDE_SELECTORS)
    server.sdk_models = _sdk_models(**overrides) + [["claude-sonnet-9-1", None]]
    assert start() == 0
    observed = ew.conversation_status(layout, "w-a", runner=runner, http=server)
    record = observed["conversation"]
    assert observed["selection_verified"] is True
    assert observed["agent_settings"]["current_model_id"] == selector
    assert record["model"] == chosen and record["acp_selector"] == selector
    assert record["selection_proof"] == {**server.native_metadata(record["id"]), "acp_selector": selector}
    creation = next(body for method, _, path, body in server.calls if (method, path) == ("POST", "/conversations"))
    assert creation["agent_settings"]["acp_model"] == selector and "initial_message" not in creation
    assert len(server.prompts) == 2 and server.prompts[-1] == "Perform the productive assignment"
    assert server.catalog_reads == server.sdk_reads == 1 and server.auth_reads == 2
    server.conversations[record["id"]]["agent_state"]["acp_current_model_id"] = "default"
    assert ew.conversation_status(layout, "w-a", runner=runner, http=server)["selection_verified"] is False


@pytest.mark.parametrize(("fault", "expected_prompts"), [
    ("picker", 0), ("transcript", 1), ("session", 1), ("auth", 1), ("unknown-post", 2),
])
def test_claude_alias_proof_and_prompt_fence(tmp_path, capsys, fault, expected_prompts):
    layout, runner, server, start = _start_fixture(tmp_path, capsys, "claude-code", _CLAUDE_SELECTORS)
    if fault == "picker":
        server.initial_model = "default"
    elif fault == "transcript":
        server.native_model = "claude-sonnet-5-1"
    elif fault == "session":
        server.change_session = True
    elif fault == "auth":
        server.auth_failure = 2
    else:
        server.lose_productive_prompt = True
    assert start() == 2
    record = ew._worker_mapping(ew._load_state(layout), "w-a")["conversation"]
    assert (record["status"], record["model"], record["acp_selector"]) == ("unknown", "claude-sonnet-5-5", "sonnet")
    assert len(server.prompts) == expected_prompts
    assert ("selection_proof" in record) == (fault == "unknown-post")
    with pytest.raises(ew.LaunchRefused, match="unconfirmed"):
        ew.reconcile_worker_conversation(layout, "w-a", http=server, runner=runner)
    assert start() == 2 and len(server.conversations) == 1 and len(server.prompts) == expected_prompts


@pytest.mark.parametrize("fault", ["missing-metadata", "sdk-failure", "auth-failure", "quota"])
def test_claude_start_refuses_alias_catalog_failure_before_older_exact_choice(tmp_path, capsys, fault):
    layout, _, server, start = _start_fixture(tmp_path, capsys, "claude-code", ["opus", "claude-sonnet-5-5"])
    if fault == "missing-metadata":
        server.sdk_models = []
    elif fault == "sdk-failure":
        server.sdk_failure = True
    elif fault == "auth-failure":
        server.auth_failure = 1
    else:
        server.catalog["error"] = {"code": "ACPInitError", "detail": "usage limit reached"}
    assert start() == 2
    assert not server.conversations and not server.prompts
    assert ew._worker_mapping(ew._load_state(layout), "w-a").get("conversation") is None
    assert server.sdk_reads == (1 if fault in ("missing-metadata", "sdk-failure") else 0)


@pytest.mark.parametrize(("selectors", "sdk", "reason"), [
    (["sonnet", "sonnet"], _sdk_models(), "ambiguous model entries"),
    (["sonnet"], _sdk_models() + [["sonnet", "claude-sonnet-6-1"]], "duplicate selectors"),
    (["sonnet"], _sdk_models(sonnet="claude-opus-5-5"), "conflicting alias"),
    (["sonnet"], _sdk_models(sonnet=None), "unresolved"),
    (["sonnet"], _sdk_models(sonnet="sonnet"), "unresolved"),
    (["sonnet"], _sdk_models(sonnet="claude-sonnet-5-5[1m]"), "unresolved"),
    (["opus", "sonnet"], [["sonnet", "claude-sonnet-5-5"]], "missing metadata"),
    (["sonnet", "claude-opus-5-5"], _sdk_models() + [["claude-opus-5-5", "claude-opus-6-1"]], "conflicts"),
    (["sonnet", "opus[1m]"], _sdk_models(), "unsupported selectors"),
    (["fable"], _sdk_models(), "no eligible"),
    (["sonnet"], _sdk_models() * 103, "invalid"),
])
def test_claude_refuses_ambiguous_or_unsupported_catalog(selectors, sdk, reason):
    with pytest.raises(ModelSelectionError, match=reason):
        select_from_catalog("claude-code", None, None, CatalogServer("claude-code", selectors).catalog,
                            read_claude_models=lambda: sdk)


def test_claude_can_use_default_when_it_is_the_only_selectable_standard_model():
    catalog = CatalogServer("claude-code", ["default", "fable"]).catalog
    assert select_from_catalog("claude-code", None, None, catalog, read_claude_models=_sdk_models) == (
        "claude-sonnet-5-5", None, "default")


@pytest.mark.parametrize("invalid", [False, True])
def test_claude_sdk_probe_reads_only_metadata_and_closes_query(tmp_path, invalid):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required")
    fixture = tmp_path / "sdk.mjs"
    fixture.write_text("""
import assert from "node:assert/strict";
export function query({prompt, options}) {
    const {abortController, ...settings} = options;
    assert.deepEqual(settings, {cwd: "/tmp", persistSession: false, settingSources: [], tools: []});
    assert.ok(abortController instanceof AbortController);
    const next = prompt[Symbol.asyncIterator]().next();
    let closed = false;
    const guard = setTimeout(() => process.exit(2), 2000);
    next.then(row => {
        assert.equal(closed, true);
        assert.equal(row.done, true);
        clearTimeout(guard);
        process.stderr.write("closed without prompt");
    });
    return {
        async supportedModels() {
            return [{value: "sonnet", resolvedModel: """ + ('"x".repeat(101)' if invalid else '"claude-sonnet-5-5"') + """,
                displayName: "omitted", description: "omitted"}];
        },
        close() { closed = true; },
    };
}
""", encoding="utf-8")
    run = subprocess.run([node, "--input-type=module", "--eval", ew._CLAUDE_CATALOG_PROBE, str(fixture)],
                         capture_output=True, text=True, check=False, timeout=5)
    assert run.stderr == "closed without prompt"
    if invalid:
        assert run.returncode == 1 and not run.stdout
    else:
        assert run.returncode == 0 and json.loads(run.stdout) == [["sonnet", "claude-sonnet-5-5"]]


def test_codex_read_only_app_server_catalog_protocol(tmp_path):
    rpc = tmp_path / "codex-catalog-fixture.py"
    rpc.write_text('''import json, sys
def read(method):
    request = json.loads(sys.stdin.readline())
    assert request["method"] == method
    return request
def send(request, result):
    print(json.dumps({"id": request["id"], "result": result}), flush=True)
send(read("initialize"), {"userAgent": "synthetic app-server"})
read("initialized")
for cursor, next_cursor, model, hidden in ((None, "page-2", "gpt-6.3-sol", False), ("page-2", None, "gpt-9.3-sol", True)):
    request = read("model/list")
    assert request["params"] == {"cursor": cursor, "includeHidden": False, "limit": 100}
    send(request, {"data": [{"id": model, "hidden": hidden, "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}],
                   "nextCursor": next_cursor})
assert sys.stdin.readline() == ""
''', encoding="utf-8")
    assert read_codex_catalog([sys.executable, str(rpc)]) == {
        "available_models": [{"model_id": "gpt-6.3-sol", "hidden": False}, {"model_id": "gpt-9.3-sol", "hidden": True}],
        "efforts_by_model": {"gpt-6.3-sol": [{"value": "high"}], "gpt-9.3-sol": [{"value": "high"}]}, "error": None,
    }


@pytest.mark.parametrize("fault", ["native-error", "old-cache", "missing-cache", "different-client", "older-native-list"])
def test_codex_start_requires_successful_app_server_and_fresh_matching_cache(tmp_path, capsys, fault):
    old, new = "gpt-6.2-sol", "gpt-6.3-sol"
    _, _, server, start = _start_fixture(tmp_path, capsys, "codex", [old])
    now = datetime.now(timezone.utc)
    available = [old, new] if fault == "older-native-list" else [old]
    cache = tmp_path / "native-model-cache.json"
    if fault != "missing-cache":
        cache.write_text(json.dumps({
            "fetched_at": (now - timedelta(minutes=10) if fault == "old-cache" else now).isoformat(),
            "client_version": "0.160.1" if fault == "different-client" else "0.172.0",
            "models": [{"slug": name, "visibility": "list", "supported_reasoning_levels": [{"effort": "high"}]}
                       for name in available],
        }), encoding="utf-8")
    server.cache_file = cache
    if fault == "native-error":
        server.catalog_code = 503
    assert start() == 2
    assert "catalog" in capsys.readouterr().err
    assert not server.conversations and not server.prompts


def test_codex_model_list_jsonrpc_error_refuses(tmp_path):
    rpc = tmp_path / "codex-error-fixture.py"
    rpc.write_text('''import json, sys
init = json.loads(sys.stdin.readline())
print(json.dumps({"id": init["id"], "result": {}}), flush=True)
assert json.loads(sys.stdin.readline())["method"] == "initialized"
req = json.loads(sys.stdin.readline())
assert req["method"] == "model/list"
print(json.dumps({"id": req["id"], "error": {"code": -32603, "message": "fixture failure"}}), flush=True)
''', encoding="utf-8")
    with pytest.raises(ModelSelectionError, match="catalog request failed"):
        read_codex_catalog([sys.executable, str(rpc)])
