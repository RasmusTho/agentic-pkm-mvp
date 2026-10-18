from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from app.builderops import epic_rehydration_probe as probe
from app.builderops import epic_rehydration_probe_v2 as v2
from app.builderops import manual_coordinator_rotation as rotation
from app.builderops.epic_lifecycle_plan import build_lifecycle_transition_plan
from app.builderops.epic_run_state import new_independent_issue_run_state, record_context_budget_receipt
from tests.builderops.test_epic_rehydration_probe_v2 import chain  # noqa: F401

ROOT = Path("evidence/manual_coordinator_rotation_6195_retry1_v1")
FAILED_ROOT = Path("evidence/manual_coordinator_rotation_6195_v1")
CAPTURE_SHA256 = "36a2bda8af7a092d7b660fb203dd620790d57c1865bec01d8f5efa97d252f022"
CONFORMANT_ROOT = Path("evidence/manual_coordinator_rotation_6195_conformant_v1")
CONFORMANT_CAPTURE_SHA256 = "d945db4695e2534a2b4511ea14f63fce3bbe840e3bc0e7028983cc14e93f9deb"


def _read(path):
    return probe.parse_strict_json(Path(path).read_bytes())


def _retain(path, value):
    path.write_bytes(probe.canonical_json_bytes(value) + b"\n")
    return rotation.binding(str(path))


def _fidelity(phase, response_binding, response, contract):
    live = {item["kind"]: _read(item["evidence"]["ref"]) for item in response["live_reads"]}
    target = contract["target"]
    repo, issue, pr = target["repository"], target["issue_number"], target["pr_number"]
    github = live["github"]["payload"]
    raw_threads = {"data": {"repository": {"pullRequest": {"reviewThreads": {
        "nodes": [{"isResolved": node["isResolved"], "comments": {"nodes": [{"url": node["url"]}]}} for node in github["review_threads"]["nodes"]],
        "pageInfo": {"hasNextPage": False, "endCursor": None},
    }}}}}
    commands = [("issue", ["gh", "issue", "view", str(issue), "--repo", repo, "--json", "number,url,state,labels,closedAt"], probe.canonical_json(github["issue"]) + "\n"),
                ("pr", ["gh", "pr", "view", str(pr), "--repo", repo, "--json", "number,url,state,mergedAt,isDraft,headRefOid,mergeCommit,statusCheckRollup"], probe.canonical_json(github["pr"]) + "\n"),
                ("review_threads", ["gh", "api", "graphql", "-f", "query=" + rotation.review_query(repo, pr)], probe.canonical_json(raw_threads) + "\n"),
                ("repository", ["git", "ls-remote", "--exit-code", "origin", "refs/heads/main"], live["repository"]["payload"]["head_sha"] + "\trefs/heads/main\n"),
                ("dispatcher", [contract["planner_interpreter"], "-m", "app.dispatcher", "status", "--json"], probe.canonical_json(live["dispatcher"]["payload"]) + "\n")]
    clock_times = {kind: value["observed_at"] for kind, value in live.items()}
    clock_times["response"] = response["observed_at"] if phase == "initial" else response["completed_at"]
    if phase == "continuation":
        clock_times["continuation_start"] = response["started_at"]
        commands.append(("planner", response["planner"]["argv"], probe.canonical_json(_read(response["planner"]["output"]["ref"])) + "\n"))
    return {"schema_name": "manual_rotation_capture_fidelity", "schema_version": rotation.PROTOCOL_VERSION,
            "experiment_id": contract["experiment_id"], "actor": contract["actors"]["successor"], "phase": phase,
            "response": response_binding, "live_reads": response["live_reads"],
            "commands": [{"kind": kind, "argv": argv, "exit_code": 0, "permission_mode": "require_escalated", "raw_output": raw,
                          "output_token_budget": 16000, "original_token_count": 1} for kind, argv, raw in commands],
            "clock_reads": [{"purpose": purpose, "tool": "clock.curr_time", "result": {"current_time": datetime.fromisoformat(at.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S UTC")}} for purpose, at in clock_times.items()]}


@pytest.fixture
def rotation_chain(chain, tmp_path):  # noqa: F811 - intentionally reuse the shipped v2 fixture
    """Synthetic protocol-negative proof only; actual proof has its own retained test."""
    # v2 deliberately permits partial payloads. Only this rotation-local producer
    # adds the complete carried CLI selection; old v2 fixtures/contracts stay intact.
    github_ref = next(item for item in chain["observation"]["live_reads"] if item["kind"] == "github")
    github = _read(github_ref["evidence"]["ref"])
    github["payload"]["issue"].update(labels=[], closedAt="2026-10-17T19:00:00Z")
    github["payload"]["pr"].update(isDraft=False, mergedAt="2026-10-17T19:00:00Z")
    github["payload"]["pr"]["statusCheckRollup"][0].update(__typename="CheckRun", name="test", status="COMPLETED")
    github_ref["evidence"] = _retain(Path(github_ref["evidence"]["ref"]), github)
    _retain(Path(chain["refs"]["agent_response"]), chain["observation"])
    comparison = probe.compare_rehydrated_observation(chain["pack"], chain["observation"])
    _retain(Path(chain["refs"]["comparison_receipt"]), comparison)
    telemetry = v2.build_telemetry(chain["pack"], chain["observation"], pack_ref=chain["refs"]["context_pack"],
                                   observation_ref=chain["refs"]["agent_response"], execution_ref=chain["execution_ref"])
    chain["receipt"] = probe.build_probe_receipt(chain["pack"], chain["observation"], comparison, evidence_refs=chain["refs"], telemetry=telemetry)
    experiment = chain["pack"]["probe_id"]
    actors = {"operator": "test-operator", "incumbent": "test-incumbent", "successor": "test-fresh-successor", "writer": "test-sole-writer"}
    source = chain["pack"]["source"]["receipt"]
    accepted = record_context_budget_receipt(new_independent_issue_run_state(run_id="test-rotation", issue_numbers=[3798]), source)
    contract = {"schema_name": "manual_rotation_capture_contract", "schema_version": rotation.PROTOCOL_VERSION, "experiment_id": experiment,
                "created_at": "2026-10-17T20:00:01Z", "target": chain["observation"]["target"], "role_scope": rotation.SCOPE,
                "actors": actors, "context_pack": rotation.binding(chain["refs"]["context_pack"]),
                "source_checkpoint": rotation.binding(chain["refs"]["source_checkpoint"]),
                "accepted_run_state": _retain(tmp_path / "accepted-state.json", accepted),
                "ingestion_contract": _retain(tmp_path / "ingestion-contract.json", rotation.ingestion_contract()), "planner_interpreter": sys.executable}
    anchor = _retain(tmp_path / "capture-contract.json", contract)
    initial = _retain(tmp_path / "probe-receipt.json", chain["receipt"])
    agent = chain["observation"]["agent"]
    admission = {"schema_name": "manual_rotation_native_admission", "schema_version": rotation.PROTOCOL_VERSION, "experiment_id": experiment,
                 "actor": actors["successor"], "at": agent["start_observed_at"], "fork_turns": "none",
                 "initial_context": {"context_pack": contract["context_pack"]},
                 "requested_model": agent["admitted_model"], "requested_reasoning_effort": agent["admitted_reasoning_effort"],
                 **{key: agent[key] for key in ("admitted_model", "admitted_reasoning_effort", "engine_identity", "engine_identity_source")},
                 "status": "succeeded", "native_receipt": "synthetic test-only native admission"}
    inputs = {"schema_name": "manual_coordinator_rotation_input", "schema_version": rotation.PROTOCOL_VERSION, "experiment_id": experiment,
              "capture_contract": anchor, "probe_receipt": initial, "admission": _retain(tmp_path / "admission.json", admission)}
    inputs["initial_fidelity"] = _retain(tmp_path / "initial-fidelity.json", _fidelity("initial", chain["receipt"]["observation"], chain["observation"], contract))
    phases = {
        "manual_decision": {"schema_name": "manual_rotation_operator_decision", "actor": actors["operator"], "at": "2026-10-17T20:02:00Z",
                            "probe_receipt": initial, "initial_fidelity": inputs["initial_fidelity"], "decision": "activate_read_only_successor", "rationale": "explicit test operator choice",
                            "decision_source": "explicit_operator_action_not_comparison_rule"},
        "quiescence": {"schema_name": "manual_rotation_incumbent_quiescence", "actor": actors["incumbent"], "at": "2026-10-17T20:02:01Z",
                       "role_scope": rotation.SCOPE, "experimental_role_quiescent": True, "writer_authority_unchanged": True},
        "acknowledgment": {"schema_name": "manual_rotation_successor_acknowledgment", "actor": actors["successor"], "at": "2026-10-17T20:02:02Z",
                           "context_pack": contract["context_pack"], "role_scope": rotation.SCOPE, "writer_authority_unchanged": True},
        "activation": {"schema_name": "manual_rotation_operator_activation", "actor": actors["operator"], "at": "2026-10-17T20:02:03Z",
                       "role_scope": rotation.SCOPE, "action": "manual_activate"},
    }
    for key, phase in phases.items():
        phase.update(schema_version=rotation.PROTOCOL_VERSION, experiment_id=experiment)
        if key != "manual_decision":
            phase["manual_decision"] = inputs["manual_decision"]
        if key == "acknowledgment":
            phase["quiescence"] = inputs["quiescence"]
        if key == "activation":
            phase["acknowledgment"] = inputs["acknowledgment"]
        inputs[key] = _retain(tmp_path / f"{key}.json", phase)
    reads = []
    for item in chain["observation"]["live_reads"]:
        read = v2._read_bound(item["evidence"])
        read["observed_at"] = "2026-10-17T20:02:05Z"
        if item["kind"] == "github":
            read["payload"]["pr"]["mergedAt"] = "2026-10-17T19:00:00Z"
        reads.append({"kind": item["kind"], "evidence": _retain(tmp_path / f"continuation-{item['kind']}.json", read)})
    live = {item["kind"]: _read(item["evidence"]["ref"]) for item in reads}
    issue, pr = (live["github"]["payload"][key] for key in ("issue", "pr"))
    issue_input, pr_input = _retain(tmp_path / "continuation-issue.json", issue), _retain(tmp_path / "continuation-pr.json", pr)
    plan = build_lifecycle_transition_plan(transition="terminal", issue=issue, pull_request=pr, repo=contract["target"]["repository"])
    plan_output = _retain(tmp_path / "terminal-plan.json", plan)
    continuation = {"schema_name": "manual_rotation_successor_continuation", "schema_version": rotation.PROTOCOL_VERSION, "experiment_id": experiment,
                    "actor": actors["successor"], "started_at": "2026-10-17T20:02:04Z", "completed_at": "2026-10-17T20:02:10Z",
                    "activation": inputs["activation"], "live_reads": reads,
                    "planner": {"argv": [sys.executable, "-m", "app.builderops", "builderops", "epic-run-state", "lifecycle-plan", "--transition", "terminal",
                                         "--issue-file", issue_input["ref"], "--pr-file", pr_input["ref"], "--repo", contract["target"]["repository"], "--json"],
                                "issue_input": issue_input, "pr_input": pr_input, "output": plan_output},
                    "observation": {**v2._live_facts(live), "next_action": {"action": "preserve_terminal_state", "reason": "already closed and merged"}, "recommendation_only": True},
                    "effects": {key: [] for key in rotation.EFFECTS}}
    inputs["continuation"] = _retain(tmp_path / "continuation.json", continuation)
    inputs["continuation_fidelity"] = _retain(tmp_path / "continuation-fidelity.json", _fidelity("continuation", inputs["continuation"], continuation, contract))
    log = {"schema_name": "manual_rotation_execution_log", "schema_version": rotation.PROTOCOL_VERSION, "experiment_id": experiment, "recorder": actors["operator"],
           "started_at": "2026-10-17T20:00:02Z", "ended_at": "2026-10-17T20:02:11Z", "clock_name": "test UTC wall clock",
           "clock_scope": "synthetic test-only successor admission request through continuation readback", "events_complete": True,
           "events": [{"kind": kind, "actor": actors["successor"], "at": at, "evidence": evidence} for kind, at, evidence in (
               ("agent_start", admission["at"], inputs["admission"]), ("packet_handoff", admission["at"], contract["context_pack"]),
               ("admission_metadata_handoff", "2026-10-17T20:00:11Z", inputs["admission"]),
               ("response_handoff", "2026-10-17T20:01:11Z", chain["receipt"]["observation"]),
               ("acknowledgment_request_handoff", "2026-10-17T20:02:01.5Z", inputs["quiescence"]),
               ("acknowledgment_response_handoff", "2026-10-17T20:02:02.5Z", inputs["acknowledgment"]),
               ("activation_handoff", "2026-10-17T20:02:03Z", inputs["activation"]),
               ("continuation_handoff", "2026-10-17T20:02:11Z", inputs["continuation"]))],
           "unavailable_measurements": {key: {"value": "unknown", "reason": "no authoritative carrier/effort receipt in this scope"} for key in rotation.UNKNOWN_METRICS}}
    inputs["execution"] = _retain(tmp_path / "rotation-execution.json", log)
    return {"inputs": inputs, "anchor": anchor, "tmp_path": tmp_path}


def _coherent_mutation(case, phase, mutate):
    """Rebind every dependent phase, so a refusal cannot hide behind stale hashes."""
    inputs, replacements = deepcopy(case["inputs"]), {}

    def replace(value):
        if type(value) is dict:
            if set(value) == {"ref", "sha256", "bytes_length"} and value["ref"] in replacements:
                return deepcopy(replacements[value["ref"]])
            return {key: replace(item) for key, item in value.items()}
        if type(value) is list:
            return [replace(item) for item in value]
        return value

    for key in rotation.PHASES:
        original = inputs[key]
        value = replace(_read(original["ref"]))
        if key == phase:
            mutate(value)
        result = _retain(case["tmp_path"] / f"mutated-{key}.json", value)
        replacements[original["ref"]] = result
        inputs[key] = result
    return inputs


def test_retained_manual_rotation_replays_actual_chain():
    path, capture = ROOT / "nonconforming-result.v1.json", ROOT / "capture-contract.json"
    receipt = _read(path)
    anchor = rotation.binding(str(capture))
    assert anchor["sha256"] == CAPTURE_SHA256
    assert _read(capture)["schema_version"] == rotation.PROTOCOL_VERSION
    assert rotation.normalize_nonconforming_result(receipt, expected_capture_contract=anchor) == receipt
    assert receipt["frozen_protocol_conformance"] == "NONCONFORMING"
    assert receipt["metadata_concordance"]["status"] == "mismatch"
    assert receipt["metadata_concordance"]["expected"] == "unknown(native carrier exposes no independent engine identity)"
    assert receipt["metadata_concordance"]["observed"] == "native carrier exposes no independent engine identity"
    with pytest.raises(rotation.Error):
        rotation.normalize_receipt(receipt, expected_capture_contract=anchor)
    assert receipt["target"]["issue_number"] == 6195 and receipt["target"]["pr_number"] == 6200
    assert receipt["actors"]["operator"] == receipt["actors"]["incumbent"] == "/root"
    assert receipt["actors"]["successor"] != receipt["actors"]["writer"]
    replay = subprocess.run([sys.executable, "-m", "app.builderops.manual_coordinator_rotation", "verify-result", "--input-file", str(path),
                             "--capture-contract-file", str(capture), "--expected-capture-sha256", CAPTURE_SHA256], capture_output=True, text=True, check=False)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    assert json.loads(replay.stdout)["frozen_protocol_conformance"] == "NONCONFORMING"
    strict_args = ["build", "--input-file", str(ROOT / "rotation-input.json"), "--capture-contract-file", str(capture),
                   "--expected-capture-sha256", CAPTURE_SHA256]
    strict = subprocess.run([sys.executable, "-m", "app.builderops.manual_coordinator_rotation", *strict_args],
                            capture_output=True, text=True, check=False)
    assert strict.returncode == 2 and strict.stdout == rotation.SOURCE_MISMATCH_REFUSAL
    archive = receipt["historical_verifier"]
    assert rotation.historical_source_binding(archive["ref"]) == archive
    historical = subprocess.run([sys.executable, "-c", "import runpy,sys; p=sys.argv[1]; sys.argv=sys.argv[1:]; runpy.run_path(p,run_name='__main__')",
                                 archive["ref"], *strict_args], capture_output=True, text=True, check=False)
    assert historical.returncode == 2 and historical.stdout == strict.stdout
    assert not (ROOT / "receipt.json").exists()
    assert receipt["measurements"]["elapsed_wall_seconds"] == 938.0
    assert receipt["measurements"]["corrections"]["implementation_repair"] == 3
    assert receipt["continuation_live_facts"]["external_state"]["repository_head"] == "2bc3034da1f84a981e33e9a9be1ad450aec95d23"


@pytest.mark.parametrize("phase,mutate", [
    ("admission", lambda value: value.update(actor="test-sole-writer")),
    ("admission", lambda value: value.update(fork_turns="all")),
    ("admission", lambda value: value.update(extra="not a declared fact")),
    ("manual_decision", lambda value: value.update(decision_source="all_fields_match")),
    ("quiescence", lambda value: value.update(at="2026-10-17T20:02:04Z")),
    ("acknowledgment", lambda value: value.update(actor="test-incumbent")),
    ("activation", lambda value: value.update(actor="test-fresh-successor")),
    ("continuation", lambda value: value.update(actor="different-successor")),
    ("continuation", lambda value: value.update(started_at="2026-10-17T20:02:02Z")),
    ("continuation", lambda value: value["observation"]["external_state"].update(issue="9999:closed")),
    ("continuation", lambda value: value["planner"]["argv"].append("--apply")),
    ("continuation", lambda value: value.update(schema_version=True)),
    ("continuation", lambda value: value.update(extra="not a declared fact")),
    ("execution", lambda value: value.update(events_complete=False)),
])
def test_rotation_admission_rejects_invalid_phase_and_binding_matrix(rotation_chain, phase, mutate):
    case = rotation_chain
    rotation.build_receipt(case["inputs"], expected_capture_contract=case["anchor"])
    bad = _coherent_mutation(case, phase, mutate)
    with pytest.raises(rotation.Error):
        rotation.build_receipt(bad, expected_capture_contract=case["anchor"])


def test_rotation_capture_pin_rejects_coherent_rebinding_and_missing_manual_decision(rotation_chain):
    case = rotation_chain
    foreign = _read(case["anchor"]["ref"])
    foreign["actors"]["successor"] = "coherently-rebound-successor"
    inputs = deepcopy(case["inputs"])
    inputs["capture_contract"] = _retain(case["tmp_path"] / "foreign-contract.json", foreign)
    with pytest.raises(rotation.Error, match="caller-pinned"):
        rotation.build_receipt(inputs, expected_capture_contract=case["anchor"])
    del inputs["manual_decision"]
    with pytest.raises(rotation.Error):
        rotation.build_receipt(inputs, expected_capture_contract=case["anchor"])


def test_rotation_continuation_live_drift_outranks_initial_checkpoint(rotation_chain):
    case = rotation_chain
    inputs = deepcopy(case["inputs"])
    contract = _read(case["anchor"]["ref"])
    continuation = _read(inputs["continuation"]["ref"])
    repository = next(item for item in continuation["live_reads"] if item["kind"] == "repository")
    refreshed = _read(repository["evidence"]["ref"])
    refreshed["payload"]["head_sha"] = "f" * 40
    repository["evidence"] = _retain(case["tmp_path"] / "drifted-live-repository.json", refreshed)
    live = {item["kind"]: _read(item["evidence"]["ref"]) for item in continuation["live_reads"]}
    continuation["observation"].update(v2._live_facts(live))

    def bind_updated_continuation(value, suffix):
        inputs["continuation"] = _retain(case["tmp_path"] / f"{suffix}-continuation.json", value)
        inputs["continuation_fidelity"] = _retain(
            case["tmp_path"] / f"{suffix}-fidelity.json",
            _fidelity("continuation", inputs["continuation"], value, contract),
        )
        log = _read(case["inputs"]["execution"]["ref"])
        next(event for event in log["events"] if event["kind"] == "continuation_handoff")["evidence"] = inputs["continuation"]
        inputs["execution"] = _retain(case["tmp_path"] / f"{suffix}-execution.json", log)

    bind_updated_continuation(continuation, "refreshed")
    receipt = rotation.build_receipt(inputs, expected_capture_contract=case["anchor"])
    assert receipt["continuation_live_facts"]["external_state"]["repository_head"] == "f" * 40
    initial_head = receipt["initial_field_results"]["external_state"]["observed"]["repository_head"]
    assert initial_head != "f" * 40
    continuation["observation"]["external_state"]["repository_head"] = initial_head
    bind_updated_continuation(continuation, "stale-checkpoint")
    with pytest.raises(rotation.Error, match="continuation external_state"):
        rotation.build_receipt(inputs, expected_capture_contract=case["anchor"])


def test_rotation_serialized_ingestion_is_strict_and_create_only(rotation_chain, tmp_path):
    case = rotation_chain
    good = probe.canonical_json_bytes(case["inputs"])
    invalid = [b"{", good[:-1], b'{"schema_name":"one","schema_name":"two"}', b'{"x":NaN}', b'{"x":Infinity}', b"[]", b"\xff"]
    for change in ({"schema_version": True}, {"schema_version": 1.0}, {"extra": 1}):
        invalid.append(probe.canonical_json_bytes({**case["inputs"], **change}))
    before = {item["ref"]: Path(item["ref"]).read_bytes() for item in case["inputs"].values() if type(item) is dict}
    source = tmp_path / "serialized-input.json"
    output = tmp_path / "must-remain-absent.json"
    args = ["build", "--input-file", str(source), "--capture-contract-file", case["anchor"]["ref"], "--expected-capture-sha256", case["anchor"]["sha256"], "--output", str(output)]
    for raw in invalid:
        source.write_bytes(raw)
        assert rotation.cli_main(args) == 2
        assert not output.exists()
    source.write_bytes(good)
    existing = tmp_path / "existing.json"
    existing.write_bytes(b"retained output")
    hardlink, symlink = tmp_path / "hardlink.json", tmp_path / "symlink.json"
    hardlink.hardlink_to(Path(case["anchor"]["ref"]))
    symlink.symlink_to(Path(case["anchor"]["ref"]))
    for target in (source, existing, hardlink, symlink, Path(case["anchor"]["ref"]), Path(case["inputs"]["continuation"]["ref"])):
        assert rotation.cli_main([*args[:-1], str(target)]) == 2
    assert existing.read_bytes() == b"retained output"
    assert all(Path(ref).read_bytes() == raw for ref, raw in before.items())
    assert rotation.cli_main(args) == 0
    assert rotation.normalize_receipt(_read(output), expected_capture_contract=case["anchor"])


def test_rotation_verifier_has_no_authority_effects(rotation_chain, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("verifier launched a process"))
    receipt = rotation.build_receipt(rotation_chain["inputs"], expected_capture_contract=rotation_chain["anchor"])
    assert receipt["effects"] == {key: [] for key in rotation.EFFECTS}
    reported = _report_case(rotation_chain)
    result = rotation.build_nonconforming_result(reported["report"], expected_capture_contract=rotation_chain["anchor"])
    assert result["effects"] == {key: [] for key in rotation.EFFECTS}
    tree = ast.parse(Path(rotation.__file__).read_text())
    forbidden = {"subprocess", "socket", "requests", "httpx", "app.dispatcher", "app.verified_merge"}
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    assert not any(name and any(name == item or name.startswith(item + ".") for item in forbidden) for name in imports)


def test_rotation_measurements_are_provenance_bound(rotation_chain):
    case = rotation_chain
    receipt = rotation.build_receipt(case["inputs"], expected_capture_contract=case["anchor"])
    measurements = receipt["measurements"]
    assert measurements["successful_native_starts"] == 1 and measurements["native_followup_handoffs"] == 2
    assert measurements["artifact_handoffs"] == 7
    assert measurements["elapsed_wall_seconds"] == 129.0
    assert measurements["packet_bytes"] == Path(_read(case["anchor"]["ref"])["context_pack"]["ref"]).stat().st_size
    assert all(item["value"] == "unknown" for item in measurements["unavailable"].values())
    changed = deepcopy(receipt)
    changed["measurements"]["packet_bytes"] += 1
    with pytest.raises(rotation.Error):
        rotation.normalize_receipt(changed, expected_capture_contract=case["anchor"])
    bad = _coherent_mutation(case, "execution", lambda value: value["unavailable_measurements"]["input_tokens"].update(value=0))
    with pytest.raises(rotation.Error):
        rotation.build_receipt(bad, expected_capture_contract=case["anchor"])


def _raw_status_omission(value):
    command = next(item for item in value["commands"] if item["kind"] == "pr")
    actual = probe.parse_strict_json(command["raw_output"])
    del actual["statusCheckRollup"][0]["status"]
    command["raw_output"] = probe.canonical_json(actual) + "\n"


def _estimated_response_clock(value):
    clock = next(item for item in value["clock_reads"] if item["purpose"] == "response")
    clock["result"]["current_time"] = "2026-10-17 20:01:11 UTC"


@pytest.mark.parametrize("mutate,refusal", [
    (_raw_status_omission, "complete rollup family"),
    (_estimated_response_clock, "actual response clock"),
    (lambda value: value["commands"][0].update(original_token_count=16001), "truncated"),
    (lambda value: value["commands"].append(deepcopy(value["commands"][0])), "one actual upstream"),
    (lambda value: value["commands"][0].update(raw_output='{"number":3798,"number":3799}'), "duplicate JSON key"),
])
def test_rotation_source_fidelity_refuses_dropped_payloads_and_estimated_clocks(rotation_chain, mutate, refusal):
    case = rotation_chain
    inputs = _coherent_mutation(case, "initial_fidelity", mutate)
    with pytest.raises(rotation.Error, match=refusal):
        rotation.build_receipt(inputs, expected_capture_contract=case["anchor"])


def test_rotation_review_read_allows_only_equivalent_anonymous_spelling(rotation_chain):
    def anonymous(value):
        command = next(item for item in value["commands"] if item["kind"] == "review_threads")
        command["argv"][-1] = "query=query " + command["argv"][-1][6:].replace("{", "{ ").replace("}", " }")
    case = rotation_chain
    inputs = _coherent_mutation(case, "initial_fidelity", anonymous)
    assert rotation.build_receipt(inputs, expected_capture_contract=case["anchor"])


@pytest.mark.parametrize("change", [
    lambda value: "mutation " + value,
    lambda value: value.replace("repository(", "renamed:repository("),
    lambda value: value.replace("isResolved", "isResolved id"),
    lambda value: value.replace('"RasmusTho"', '"foreign-owner"'),
    lambda value: value.replace("number:3803", "number:3804"),
    lambda value: value.replace("after:null", 'after:"foreign-cursor"'),
    lambda value: value.replace("first:100", "first:101"),
    lambda value: "query NamedOperation " + value,
    lambda value: value.replace("repository", "reposit ory"),
])
def test_rotation_review_read_rejects_mutation_alias_extra_target_and_cursor(rotation_chain, change):
    def altered(value):
        command = next(item for item in value["commands"] if item["kind"] == "review_threads")
        command["argv"][-1] = "query=" + change(command["argv"][-1][6:])
    case = rotation_chain
    inputs = _coherent_mutation(case, "initial_fidelity", altered)
    with pytest.raises(rotation.Error):
        rotation.build_receipt(inputs, expected_capture_contract=case["anchor"])


def test_retained_invalid_first_capture_is_immutable_and_never_activated():
    originals = {
        "live-read-github.json": ("9e28a99e18c56387a1556a0a7254e340d51c48e24813615fb3d69e4e9e413715", 7019),
        "live-read-repository.json": ("2e49e630264e39c468ad297231f53d3a95d7db37a08167da7fc9b9147d53cc18", 419),
        "live-read-dispatcher.json": ("91674a721bede36ac3ff4b87efb3d78c956c6370132c19288abd0351dfba3801", 2563),
        "agent-response.original.json": ("91ca44c676af305264c70af4f92cfab20e02b5a05b8a73bbe66b77863da5233d", 6178),
    }
    for name, (digest, length) in originals.items():
        record = rotation.binding(str(FAILED_ROOT / "successor/initial" / name))
        assert (record["sha256"], record["bytes_length"]) == (digest, length)
    assert rotation.binding(str(FAILED_ROOT / "capture-contract.json"))["sha256"] == "838c7168547a01872969adda61885792d97a1f03f90d3f02b7260354da19f931"
    assert _read(FAILED_ROOT / "ingestion-contract.json")["schema_version"] == 1
    for path in ("operator/manual-decision.json", "operator/quiescence.json", "operator/activation.json", "successor/acknowledgment.original.json", "receipt.json"):
        assert not (FAILED_ROOT / path).exists()


def _report_case(case, inputs=None):
    """Synthetic negative-proof plumbing; actual native proof is retained above."""
    if inputs is None:
        inputs = _coherent_mutation(case, "admission", lambda value: value.update(engine_identity_source="unknown(test operator explanation)"))
    root = case["tmp_path"]
    input_binding = _retain(root / "report-chain-input.json", inputs)
    contract = _read(case["anchor"]["ref"])
    raw = Path(rotation.__file__).read_bytes()
    source = root / "historical-source.py.txt"
    source.write_bytes(raw)
    archive = rotation.historical_source_binding(str(source))
    module = {**archive, "ref": "app/builderops/manual_coordinator_rotation.py"}
    refusal = {
        "purpose": "Synthetic refusal plumbing, not actual native evidence", "actor": contract["actors"]["writer"],
        "argv": [contract["planner_interpreter"], "-m", "app.builderops.manual_coordinator_rotation", "build",
                 "--input-file", input_binding["ref"], "--capture-contract-file", case["anchor"]["ref"],
                 "--expected-capture-sha256", case["anchor"]["sha256"], "--output", str(root / "strict-output.json")],
        "result": {"chunk_id": "synthetic", "wall_time_seconds": 0.0, "exit_code": 2, "original_token_count": 1,
                   "output": rotation.SOURCE_MISMATCH_REFUSAL},
        "retention_clock": {"tool": "clock.curr_time", "result": {"current_time": "2026-10-17 20:02:12 UTC"}, "scope": "test only"},
        "module": module, "input": input_binding, "output_created": False,
        "qualifying_interval_repair_count_unchanged": sum(event["kind"] == "implementation_repair" for event in _read(inputs["execution"]["ref"])["events"]),
    }
    refusal_binding = _retain(root / "strict-refusal.json", refusal)
    custody = {"purpose": "Synthetic historical custody", "captured_module": module, "preserved_source": archive,
               "strict_refusal_ref": refusal_binding["ref"], "verification": "Synthetic exact source byte binding",
               "observed_clock": {"tool": "clock.curr_time", "result": {"current_time": "2026-10-17 20:02:13 UTC"}},
               "historical_replay_note": "Current-path identity is not historical byte identity"}
    report = {"schema_name": "manual_rotation_nonconforming_result_input", "schema_version": 1,
              "rotation_input": input_binding, "strict_refusal": refusal_binding, "historical_source": archive,
              "source_custody": _retain(root / "source-custody.json", custody)}
    return {**case, "chain_inputs": inputs, "report": report}


def _result_cli(case, mode="build-result", value=None, output=None):
    source = case["tmp_path"] / "serialized-result-input.json"
    if value is None:
        value = case["report"]
    source.write_bytes(value if type(value) is bytes else probe.canonical_json_bytes(value) + b"\n")
    args = [sys.executable, "-m", "app.builderops.manual_coordinator_rotation", mode, "--input-file", str(source),
            "--capture-contract-file", case["anchor"]["ref"], "--expected-capture-sha256", case["anchor"]["sha256"]]
    if output is not None:
        args += ["--output", str(output)]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _coherent_capture_case(tmp_path, phase, *, mutate=lambda value: None, pages=None, conforming=False, agent_metadata=None):
    """Private synthetic clones of retained bytes; never edit operator originals.

    Keep the external capture pin. Rebind the entire downstream DAG, including v2
    comparison/telemetry, planner inputs/output and every phase. Invalid required
    v2 identity cases retain intentionally invalid semantics, not stale hashes.
    """
    memo = {}
    github_ref = str(ROOT / f"successor/{phase}/live-read-github.json")
    changed = _read(github_ref)
    mutate(changed["payload"])
    core_present = all({"number", "url", "state"} <= set(changed["payload"][kind]) for kind in ("issue", "pr"))
    original_probe = _read(ROOT / "successor/initial/probe-receipt.json")
    pack = _read(ROOT / "context-pack.json")

    def destination(ref):
        if ref.startswith(str(ROOT) + "/") and not ref.startswith(str(ROOT / "accepted") + "/") and ref not in {
            str(ROOT / name) for name in ("capture-contract.json", "context-pack.json", "ingestion-contract.json")
        }:
            return str(tmp_path / "coherent" / ref[len(str(ROOT)) + 1:])
        return ref

    def rewrite(value):
        if type(value) is dict:
            if set(value) == {"ref", "sha256", "bytes_length"} and type(value["ref"]) is str:
                return clone(value)
            return {key: rewrite(item) for key, item in value.items()}
        if type(value) is list:
            return [rewrite(item) for item in value]
        return destination(value) if type(value) is str else value

    def clone(record):
        ref = record["ref"]
        if destination(ref) == ref or not ref.endswith(".json"):
            return deepcopy(record)
        if ref in memo:
            return deepcopy(memo[ref])
        value = changed if ref == github_ref else _read(ref)
        if ref == str(ROOT / f"successor/{phase}/live-read-github.json") and pages is not None:
            value["payload"]["review_threads"]["nodes"] = [
                {"isResolved": node["isResolved"], "url": node["comments"]["nodes"][0]["url"]}
                for page in pages for node in page["nodes"]
            ]
        if phase == "continuation" and ref in {str(ROOT / f"successor/continuation/live-{kind}-{number}.json") for kind, number in (("issue", 6195), ("pr", 6200))}:
            value = deepcopy(changed["payload"]["issue" if "live-issue-" in ref else "pr"])
        value = rewrite(value)
        if ref == str(ROOT / "operator/admission.corrected.original.json") and conforming:
            value["engine_identity_source"] = "native carrier exposes no independent engine identity"
        if agent_metadata is not None and ref == str(ROOT / "successor/initial/agent-response.original.json"):
            value["agent"] = deepcopy(agent_metadata)
        if agent_metadata is not None and ref == str(ROOT / "successor/initial/execution.json"):
            value["invocation"] = deepcopy(agent_metadata)
        if ref == str(ROOT / "successor/initial/agent-response.original.json") and phase == "initial" and core_present:
            live = {item["kind"]: _read(item["evidence"]["ref"]) for item in value["live_reads"]}
            for name, fact in v2._live_facts(live).items():
                value["fields"][name]["value"] = fact
            value["fields"]["missing_claims"]["value"] = [name for name in v2.COMPARED if v2._unknown(value["fields"][name]["value"])]
        if ref == str(ROOT / "successor/initial/comparison.json") and (phase != "initial" or core_present):
            obs = clone(original_probe["observation"])
            value = v2.compare_rehydrated_observation(pack, _read(obs["ref"]), context_pack_ref=str(ROOT / "context-pack.json"), observation_ref=obs["ref"])
        if ref == str(ROOT / "successor/initial/probe-receipt.json") and (phase != "initial" or core_present):
            obs, comparison = clone(original_probe["observation"]), clone(original_probe["comparison"])
            execution = clone(original_probe["telemetry"]["evidence"]["execution"])
            telemetry = v2.build_telemetry(pack, _read(obs["ref"]), pack_ref=str(ROOT / "context-pack.json"), observation_ref=obs["ref"], execution_ref=execution["ref"])
            value = v2.build_probe_receipt(pack, _read(obs["ref"]), _read(comparison["ref"]), evidence_refs={
                "source_checkpoint": str(ROOT / "accepted/source-checkpoint.json"), "context_pack": str(ROOT / "context-pack.json"),
                "agent_response": obs["ref"], "comparison_receipt": comparison["ref"],
            }, telemetry=telemetry)
        if phase == "continuation" and core_present and ref == str(ROOT / "successor/continuation/terminal-plan.original.json"):
            value = build_lifecycle_transition_plan(transition="terminal", issue=changed["payload"]["issue"], pull_request=changed["payload"]["pr"], repo=pack["target"]["repository"])
        if phase == "continuation" and core_present and ref == str(ROOT / "successor/continuation/continuation.original.json"):
            live = {item["kind"]: _read(item["evidence"]["ref"]) for item in value["live_reads"]}
            value["observation"].update(v2._live_facts(live))
        if ref == str(ROOT / f"successor/{phase}/capture-fidelity.original.json"):
            for item in value["commands"]:
                if item["kind"] in {"issue", "pr"}:
                    item["raw_output"] = probe.canonical_json(changed["payload"][item["kind"]]) + "\n"
                elif item["kind"] == "planner":
                    continuation = _read(value["response"]["ref"])
                    item["raw_output"] = probe.canonical_json(_read(continuation["planner"]["output"]["ref"])) + "\n"
            if pages is not None:
                prototype = next(item for item in value["commands"] if item["kind"] == "review_threads")
                value["commands"] = [item for item in value["commands"] if item["kind"] != "review_threads"]
                cursor = None
                for page in pages:
                    item = deepcopy(prototype)
                    item["argv"][-1] = "query=" + rotation.review_query(pack["target"]["repository"], 6200, cursor)
                    item["raw_output"] = probe.canonical_json({"data": {"repository": {"pullRequest": {"reviewThreads": page}}}}) + "\n"
                    value["commands"].append(item)
                    cursor = page["pageInfo"]["endCursor"]
        path = Path(destination(ref))
        path.parent.mkdir(parents=True, exist_ok=True)
        memo[ref] = _retain(path, value)
        return deepcopy(memo[ref])

    report = rewrite(_read(ROOT / "nonconforming-result-input.json"))
    return {"report": report, "anchor": rotation.binding(str(ROOT / "capture-contract.json")), "tmp_path": tmp_path}


SELECTED_FIELDS = [("issue", name) for name in "number,url,state,labels,closedAt".split(",")] + [
    ("pr", name) for name in "number,url,state,mergedAt,isDraft,headRefOid,mergeCommit,statusCheckRollup".split(",")
]


def test_coherent_complete_synthetic_copy_has_a_strict_cli_baseline(tmp_path):
    # This new private fixture is deliberately conforming; actual admission and
    # response originals remain unequal and are never repaired by the cloner.
    case = _coherent_capture_case(tmp_path, "initial", conforming=True)
    inputs = _read(case["report"]["rotation_input"]["ref"])
    output = tmp_path / "synthetic-strict-receipt.json"
    result = _result_cli(case, mode="build", value=inputs, output=output)
    assert result.returncode == 0 and output.exists(), result.stdout + result.stderr
    assert json.loads(result.stdout)["frozen_protocol_conformance"] == "CONFORMING"
    rejected = _result_cli(case)
    assert rejected.returncode == 2 and "requires an actual source-explanation mismatch" in rejected.stdout


@pytest.mark.parametrize("phase", ["initial", "continuation"])
@pytest.mark.parametrize("kind,field", SELECTED_FIELDS)
def test_coherent_selected_field_omission_refuses_actual_cli(tmp_path, phase, kind, field):
    def omit(payload):
        del payload[kind][field]
    for conforming in (False, True):
        root = tmp_path / str(conforming)
        root.mkdir()
        case = _coherent_capture_case(root, phase, mutate=omit, conforming=conforming)
        output = root / "must-not-exist.json"
        mode = "build" if conforming else "build-result"
        value = _read(case["report"]["rotation_input"]["ref"]) if conforming else case["report"]
        result = _result_cli(case, mode=mode, value=value, output=output)
        assert result.returncode == 2 and not output.exists(), result.stdout + result.stderr
        assert "bound bytes" not in result.stdout and "does not match retained bytes" not in result.stdout
        if field in {"labels", "closedAt", "isDraft", "mergedAt"}:
            assert f"complete {kind} --json capture" in result.stdout


@pytest.mark.parametrize("phase", ["initial", "continuation"])
@pytest.mark.parametrize("field", ["__typename", "name", "status", "conclusion"])
def test_coherent_checkrun_field_omission_refuses_actual_cli(tmp_path, phase, field):
    def omit(payload):
        del payload["pr"]["statusCheckRollup"][0][field]
    case = _coherent_capture_case(tmp_path, phase, mutate=omit)
    output = tmp_path / "missing-family-result.json"
    result = _result_cli(case, output=output)
    assert result.returncode == 2 and "complete rollup family" in result.stdout
    assert not output.exists()


def _review_pages(cursors):
    return [{"nodes": [{"isResolved": True, "comments": {"nodes": [{"url": f"https://github.com/RasmusTho/agentic-pkm-mvp/pull/6200#discussion_synthetic_{index}"}]}}],
             "pageInfo": {"hasNextPage": index < len(cursors) - 1, "endCursor": cursor}}
            for index, cursor in enumerate(cursors)]


@pytest.mark.parametrize("phase", ["initial", "continuation"])
@pytest.mark.parametrize("cursors", [("A", "A", "Z"), ("A", "B", "A", "Z"), (None, "Z")])
def test_coherent_nonprogressing_review_pages_refuse_actual_cli(tmp_path, phase, cursors):
    case = _coherent_capture_case(tmp_path, phase, pages=_review_pages(cursors))
    output = tmp_path / "nonprogressing-result.json"
    result = _result_cli(case, output=output)
    assert result.returncode == 2 and "non-progressing nonterminal cursor" in result.stdout
    assert not output.exists()


@pytest.mark.parametrize("phase", ["initial", "continuation"])
def test_coherent_two_page_capture_and_extra_metadata_are_preserved(tmp_path, phase):
    def extra(payload):
        payload["pr"]["future_upstream_metadata"] = {"retained": True}
        payload["pr"]["statusCheckRollup"][0]["future_check_metadata"] = [1, None]
    case = _coherent_capture_case(tmp_path, phase, mutate=extra, pages=_review_pages(("A", "B")))
    result = _result_cli(case)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["frozen_protocol_conformance"] == "NONCONFORMING"
    github = _read(tmp_path / f"coherent/successor/{phase}/live-read-github.json")
    assert github["payload"]["pr"]["future_upstream_metadata"] == {"retained": True}
    assert len(github["payload"]["review_threads"]["nodes"]) == 2


@pytest.mark.parametrize("rollup,ci", [
    ([], "unknown"), (None, "unknown"),
    ([{"__typename": "CheckRun", "name": "pending", "status": "IN_PROGRESS", "conclusion": None}], "pending"),
    ([{"__typename": "CheckRun", "name": "queued", "status": "QUEUED", "conclusion": ""}], "pending"),
    ([{"__typename": "StatusContext", "context": "legacy", "state": "SUCCESS"}], "green"),
    ([{"__typename": "StatusContext", "context": "legacy", "state": "PENDING"},
      {"__typename": "CheckRun", "name": "done", "status": "COMPLETED", "conclusion": "SUCCESS"}], "pending"),
])
@pytest.mark.parametrize("phase", ["initial", "continuation"])
def test_complete_rollup_families_allow_legitimate_states_actual_cli(tmp_path, phase, rollup, ci):
    case = _coherent_capture_case(tmp_path, phase, mutate=lambda payload: payload["pr"].update(statusCheckRollup=rollup))
    output = tmp_path / "complete-rollup-result.json"
    result = _result_cli(case, output=output)
    assert result.returncode == 0, result.stdout + result.stderr
    facts = _read(output)
    actual = facts["continuation_live_facts"]["external_state"]["ci"]["status"] if phase == "continuation" else facts["initial_field_results"]["external_state"]["observed"]["ci"]["status"]
    assert actual == ci


@pytest.mark.parametrize("phase", ["initial", "continuation"])
@pytest.mark.parametrize("field", ["__typename", "context", "state"])
def test_coherent_status_context_omission_refuses_actual_cli(tmp_path, phase, field):
    def omit(payload):
        row = {"__typename": "StatusContext", "context": "legacy", "state": "SUCCESS"}
        del row[field]
        payload["pr"]["statusCheckRollup"] = [row]
    case = _coherent_capture_case(tmp_path, phase, mutate=omit)
    result = _result_cli(case, output=tmp_path / "missing-context-result.json")
    assert result.returncode == 2 and "complete rollup family" in result.stdout
    assert not (tmp_path / "missing-context-result.json").exists()


@pytest.mark.parametrize("phase", ["initial", "continuation"])
@pytest.mark.parametrize("bad", [None, 0, "false"])
def test_coherent_draft_type_never_coerces_actual_cli(tmp_path, phase, bad):
    case = _coherent_capture_case(tmp_path, phase, mutate=lambda payload: payload["pr"].update(isDraft=bad))
    output = tmp_path / "coerced-draft-result.json"
    result = _result_cli(case, output=output)
    assert result.returncode == 2 and "complete pr --json capture" in result.stdout
    assert not output.exists()


@pytest.mark.parametrize("kind,key,bad", [
    ("issue", "number", True), ("issue", "url", None), ("issue", "state", 0),
    ("issue", "labels", {}), ("issue", "labels", [{"name": 1}]), ("issue", "labels", [{}]),
    ("issue", "closedAt", False), ("issue", "closedAt", "not-a-time"),
    ("pr", "mergedAt", []), ("pr", "isDraft", 0), ("pr", "headRefOid", None),
    ("pr", "mergeCommit", {}), ("pr", "mergeCommit", {"oid": "bad"}),
    ("pr", "statusCheckRollup", {}), ("pr", "statusCheckRollup", [True]),
    ("pr", "statusCheckRollup", [{"__typename": "UnknownFamily"}]),
    ("pr", "statusCheckRollup", [{"__typename": "CheckRun", "name": "x", "status": True, "conclusion": "SUCCESS"}]),
    ("pr", "statusCheckRollup", [{"__typename": "StatusContext", "context": 1, "state": "SUCCESS"}]),
])
def test_selected_types_and_consumed_nested_fields_are_strict(kind, key, bad):
    payload = deepcopy(_read(ROOT / "successor/initial/live-read-github.json")["payload"][kind])
    payload[key] = bad
    fields = "number,url,state,labels,closedAt" if kind == "issue" else "number,url,state,mergedAt,isDraft,headRefOid,mergeCommit,statusCheckRollup"
    with pytest.raises(rotation.Error):
        rotation._github_capture(payload, kind=kind, fields=fields)


def test_nullable_selected_values_are_present_not_filled():
    payload = _read(ROOT / "successor/initial/live-read-github.json")["payload"]
    payload["issue"].update(labels=[], closedAt=None, future_metadata={"retained": True})
    payload["pr"].update(mergedAt=None, mergeCommit=None, statusCheckRollup=None)
    for kind, fields in (("issue", "number,url,state,labels,closedAt"),
                         ("pr", "number,url,state,mergedAt,isDraft,headRefOid,mergeCommit,statusCheckRollup")):
        rotation._github_capture(payload[kind], kind=kind, fields=fields)
    assert payload["issue"]["closedAt"] is None and payload["pr"]["mergeCommit"] is None


@pytest.mark.parametrize("bad", [
    {"nodes": {}, "pageInfo": {"hasNextPage": False, "endCursor": None}},
    {"nodes": [], "pageInfo": {"hasNextPage": 0, "endCursor": None}},
    {"nodes": [], "pageInfo": {"hasNextPage": False}},
    {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": 1}},
    {"nodes": [{"isResolved": 1, "comments": {"nodes": [{"url": "x"}]}}], "pageInfo": {"hasNextPage": False, "endCursor": None}},
    {"nodes": [{"isResolved": True, "comments": {"nodes": []}}], "pageInfo": {"hasNextPage": False, "endCursor": None}},
    {"nodes": [{"isResolved": True, "comments": {"nodes": [{"url": None}]}}], "pageInfo": {"hasNextPage": False, "endCursor": None}},
])
def test_raw_review_selected_types_refuse_at_actual_cli(rotation_chain, bad):
    def corrupt(value):
        command = next(item for item in value["commands"] if item["kind"] == "review_threads")
        command["raw_output"] = probe.canonical_json({"data": {"repository": {"pullRequest": {"reviewThreads": bad}}}})
    inputs = _coherent_mutation(rotation_chain, "initial_fidelity", corrupt)
    case = _report_case(rotation_chain, _coherent_mutation({**rotation_chain, "inputs": inputs}, "admission",
                                                        lambda value: value.update(engine_identity_source="unknown(test mismatch)")))
    output = case["tmp_path"] / "malformed-review-result.json"
    result = _result_cli(case, output=output)
    assert result.returncode == 2 and "complete raw review selection" in result.stdout
    assert not output.exists()


def test_nonconforming_result_is_explicit_not_a_strict_fallback(rotation_chain):
    case = _report_case(rotation_chain)
    result = rotation.build_nonconforming_result(case["report"], expected_capture_contract=case["anchor"])
    assert result["frozen_protocol_conformance"] == "NONCONFORMING"
    assert result["metadata_concordance"]["expected"] != result["metadata_concordance"]["observed"]
    assert rotation.normalize_nonconforming_result(result, expected_capture_contract=case["anchor"]) == result
    for value in (case["report"], result):
        assert _result_cli(case, mode="build", value=value).returncode == 2
    output = case["tmp_path"] / "explicit-result.json"
    built = _result_cli(case, output=output)
    assert built.returncode == 0, built.stdout + built.stderr
    assert json.loads(built.stdout)["frozen_protocol_conformance"] == "NONCONFORMING"
    assert _result_cli(case, mode="verify-result", value=_read(output)).returncode == 0
    changed = _read(output)
    changed["frozen_protocol_conformance"] = "CONFORMING"
    assert _result_cli(case, mode="verify-result", value=changed).returncode == 2
    conforming = _report_case(rotation_chain, deepcopy(rotation_chain["inputs"]))
    assert _result_cli(conforming).returncode == 2


@pytest.mark.parametrize("phase,mutate", [
    ("admission", lambda value: value.update(actor="foreign-actor")),
    ("admission", lambda value: value.update(admitted_model="foreign-model")),
    ("admission", lambda value: value.update(requested_model="foreign-request")),
    ("admission", lambda value: value.update(admitted_reasoning_effort="low")),
    ("admission", lambda value: value.update(at="2026-10-17T20:00:11Z")),
    ("admission", lambda value: value.update(engine_identity="inferred-engine")),
    ("admission", lambda value: value.update(fork_turns="all")),
    ("manual_decision", lambda value: value.update(decision_source="automatic_match_rule")),
    ("quiescence", lambda value: value.update(at="2026-10-17T20:02:04Z")),
    ("acknowledgment", lambda value: value.update(actor="wrong-successor")),
    ("activation", lambda value: value.update(actor="successor")),
    ("continuation", lambda value: value.update(started_at="2026-10-17T20:02:02Z")),
    ("continuation", lambda value: value["observation"]["external_state"].update(issue="9999:closed")),
    ("continuation", lambda value: value["effects"]["closure"].append("not allowed")),
    ("continuation", lambda value: value["planner"]["argv"].append("--apply")),
    ("initial_fidelity", _raw_status_omission),
    ("initial_fidelity", _estimated_response_clock),
    ("execution", lambda value: value["unavailable_measurements"]["input_tokens"].update(value=0)),
])
def test_nonconforming_actual_cli_still_refuses_hard_boundaries(rotation_chain, phase, mutate):
    case = _report_case(rotation_chain)
    assert rotation.build_nonconforming_result(case["report"], expected_capture_contract=case["anchor"])
    base = {**case, "inputs": case["chain_inputs"]}
    altered = _coherent_mutation(base, phase, mutate)
    case = _report_case(rotation_chain, altered)
    output = case["tmp_path"] / "refused-result.json"
    result = _result_cli(case, output=output)
    assert result.returncode == 2, result.stdout + result.stderr
    assert not output.exists()


def test_nonconforming_actual_cli_refuses_missing_manual_decision(rotation_chain):
    case = _report_case(rotation_chain)
    inputs = deepcopy(case["chain_inputs"])
    del inputs["manual_decision"]
    case = _report_case(rotation_chain, inputs)
    output = case["tmp_path"] / "no-decision-result.json"
    result = _result_cli(case, output=output)
    assert result.returncode == 2 and "manual_decision" in result.stdout
    assert not output.exists()


@pytest.mark.parametrize("kind", ["source-bytes", "refusal-input", "refusal-output", "custody-hash", "foreign-capture"])
def test_nonconforming_actual_cli_refuses_forged_historical_custody(rotation_chain, kind):
    case = _report_case(rotation_chain)
    if kind == "source-bytes":
        Path(case["report"]["historical_source"]["ref"]).write_bytes(b"changed historical source")
    elif kind.startswith("refusal-"):
        value = _read(case["report"]["strict_refusal"]["ref"])
        if kind == "refusal-input":
            value["input"]["sha256"] = "0" * 64
        else:
            value["result"]["output"] = "unrelated error\n"
        case["report"]["strict_refusal"] = _retain(case["tmp_path"] / "forged-refusal.json", value)
    elif kind == "custody-hash":
        value = _read(case["report"]["source_custody"]["ref"])
        value["captured_module"]["sha256"] = "0" * 64
        case["report"]["source_custody"] = _retain(case["tmp_path"] / "forged-custody.json", value)
    else:
        inputs = _read(case["report"]["rotation_input"]["ref"])
        inputs["capture_contract"]["sha256"] = "0" * 64
        case["report"]["rotation_input"] = _retain(case["tmp_path"] / "foreign-input.json", inputs)
    output = case["tmp_path"] / "refused-custody-result.json"
    assert _result_cli(case, output=output).returncode == 2
    assert not output.exists()


def test_nonconforming_actual_cli_strict_serialization_and_create_only(rotation_chain):
    case = _report_case(rotation_chain)
    good = probe.canonical_json_bytes(case["report"])
    invalid = [b"{", good[:-1], b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b"[]", b"\xff"]
    invalid += [probe.canonical_json_bytes({**case["report"], **change}) for change in ({"schema_version": True}, {"schema_version": 1.0}, {"extra": 1})]
    incomplete = deepcopy(case["report"])
    del incomplete["source_custody"]
    invalid.append(probe.canonical_json_bytes(incomplete))
    output = case["tmp_path"] / "new-result.json"
    before = {item["ref"]: Path(item["ref"]).read_bytes() for item in case["report"].values() if type(item) is dict}
    for raw in invalid:
        assert _result_cli(case, value=raw, output=output).returncode == 2
        assert not output.exists()
    existing = case["tmp_path"] / "existing-result.json"
    existing.write_bytes(b"preserve existing")
    hardlink, symlink = case["tmp_path"] / "result-hardlink.json", case["tmp_path"] / "result-symlink.json"
    hardlink.hardlink_to(Path(case["anchor"]["ref"]))
    symlink.symlink_to(Path(case["anchor"]["ref"]))
    targets = [existing, hardlink, symlink, case["tmp_path"] / "serialized-result-input.json", Path(case["anchor"]["ref"])]
    targets += [Path(ref) for ref in before]
    for target in targets:
        assert _result_cli(case, output=target).returncode == 2
    assert existing.read_bytes() == b"preserve existing"
    assert all(Path(ref).read_bytes() == raw for ref, raw in before.items())
    assert _result_cli(case, output=output).returncode == 0


def _metadata_cli(tmp_path, *, admission=None, capture=None, output=None, observation=None, digest=None):
    """Exercise the serialized producer; historical inputs are read-only test authority."""
    source = tmp_path / "serialized-admission.json"
    if admission is None:
        admission = _read(ROOT / "operator/admission.corrected.original.json")
    source.write_bytes(admission if type(admission) is bytes else probe.canonical_json_bytes(admission) + b"\n")
    capture = ROOT / "capture-contract.json" if capture is None else capture
    pin = rotation.binding(str(capture))["sha256"] if digest is None else digest
    argv = [sys.executable, "-m", "app.builderops.manual_coordinator_rotation", "metadata", "--input-file", str(source),
            "--capture-contract-file", str(capture), "--expected-capture-sha256", pin]
    if observation is not None:
        argv += ["--observation-file", str(observation)]
    if output is not None:
        argv += ["--output", str(output)]
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def test_rotation_metadata_producer_preserves_exact_admission(tmp_path):
    admission = _read(ROOT / "operator/admission.corrected.original.json")
    output = tmp_path / "exact-admitted-agent.json"
    produced = _metadata_cli(tmp_path, output=output)
    assert produced.returncode == 0, produced.stdout + produced.stderr
    agent = _read(output)
    assert json.loads(produced.stdout) == agent
    assert agent == {**{key: admission[key] for key in (
        "admitted_model", "admitted_reasoning_effort", "engine_identity", "engine_identity_source",
    )}, "start_status": admission["status"], "start_observed_at": admission["at"]}
    assert agent["engine_identity_source"] == "unknown(native carrier exposes no independent engine identity)"
    former_response = ROOT / "successor/initial/agent-response.original.json"
    former = _metadata_cli(tmp_path, observation=former_response)
    assert former.returncode == 2 and "pre-activation admission metadata" in former.stdout

    # Private synthetic clone only: original admission is the producer authority,
    # not a rewritten admission made equal to the former response after capture.
    case = _coherent_capture_case(tmp_path, "initial", agent_metadata=agent)
    inputs = _read(case["report"]["rotation_input"]["ref"])
    exact_response = _read(inputs["probe_receipt"]["ref"])["observation"]["ref"]
    preflight = _metadata_cli(tmp_path, observation=exact_response)
    assert preflight.returncode == 0 and json.loads(preflight.stdout) == agent
    receipt_path = tmp_path / "strict-produced-receipt.json"
    built = _result_cli(case, mode="build", value=inputs, output=receipt_path)
    assert built.returncode == 0, built.stdout + built.stderr
    verified = _result_cli(case, mode="verify", value=_read(receipt_path))
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert json.loads(verified.stdout)["frozen_protocol_conformance"] == "CONFORMING"


def test_rotation_metadata_serialized_ingestion_is_strict(tmp_path):
    admission = _read(ROOT / "operator/admission.corrected.original.json")
    good = probe.canonical_json_bytes(admission)
    invalid = [b"{", good[:-1], b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b"[]", b"\xff"]
    mutations = [
        lambda item: item.pop("engine_identity_source"),
        lambda item: item.update(extra="not admitted"),
        lambda item: item.update(schema_version=True),
        lambda item: item.update(schema_version=2.0),
        lambda item: item.update(engine_identity_source=1),
        lambda item: item.update(engine_identity="inferred-engine"),
        lambda item: item.update(schema_name="manual_rotation_operator_activation"),
        lambda item: item.update(experiment_id="foreign-experiment"),
        lambda item: item.update(actor="foreign-successor"),
        lambda item: item.update(fork_turns="all"),
        lambda item: item.update(status="requested"),
        lambda item: item.update(requested_model="not-the-admitted-model"),
        lambda item: item.update(requested_reasoning_effort="not-the-admitted-effort"),
        lambda item: item.update(at="2026-01-01T00:00:00Z"),
        lambda item: item["initial_context"]["context_pack"].update(sha256="0" * 64),
    ]
    for mutate in mutations:
        changed = deepcopy(admission)
        mutate(changed)
        invalid.append(probe.canonical_json_bytes(changed))
    output = tmp_path / "must-not-exist.json"
    originals = {str(path): path.read_bytes() for path in ROOT.rglob("*") if path.is_file()}
    for raw in invalid:
        result = _metadata_cli(tmp_path, admission=raw, output=output)
        assert result.returncode == 2, result.stdout + result.stderr
        assert not output.exists()
    assert _metadata_cli(tmp_path, digest="0" * 64, output=output).returncode == 2
    for key, changed in (("target", {"issue_number": 9999}), ("source_checkpoint", {"sha256": "0" * 64})):
        capture = _read(ROOT / "capture-contract.json")
        capture[key].update(changed)
        capture_path = tmp_path / f"foreign-{key}.json"
        _retain(capture_path, capture)
        assert _metadata_cli(tmp_path, capture=capture_path, output=output).returncode == 2
        assert not output.exists()
    existing = tmp_path / "partial-output.json"
    existing.write_bytes(b'{"partial":')
    hardlink, symlink = tmp_path / "metadata-hardlink.json", tmp_path / "metadata-symlink.json"
    hardlink.hardlink_to(tmp_path / "serialized-admission.json")
    symlink.symlink_to((ROOT / "context-pack.json").resolve())
    for target in (existing, hardlink, symlink, tmp_path / "serialized-admission.json", ROOT / "capture-contract.json",
                   ROOT / "operator/admission.corrected.original.json", ROOT / "accepted/source-checkpoint.json"):
        assert _metadata_cli(tmp_path, output=target).returncode == 2
    assert existing.read_bytes() == b'{"partial":'
    assert all(Path(ref).read_bytes() == raw for ref, raw in originals.items())
    assert _metadata_cli(tmp_path, output=output).returncode == 0
    assert _metadata_cli(tmp_path, output=output).returncode == 2


def test_rotation_metadata_producer_has_no_authority_effects(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("metadata producer launched a process"))
    monkeypatch.setattr(probe, "_write_json_file", lambda *args, **kwargs: pytest.fail("pure producer wrote an artifact"))
    result = rotation.response_invocation_metadata(
        _read(ROOT / "operator/admission.corrected.original.json"),
        expected_capture_contract=rotation.binding(str(ROOT / "capture-contract.json")),
    )
    assert set(result) == set(v2.AGENT["properties"])
    tree = ast.parse(Path(rotation.__file__).read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    forbidden = {"subprocess", "socket", "requests", "httpx", "app.dispatcher", "app.verified_merge"}
    assert not any(name and any(name == item or name.startswith(item + ".") for item in forbidden) for name in imports)


def test_historical_nonconforming_rotation_remains_immutable():
    digest = hashlib.sha256()
    for root in (FAILED_ROOT, ROOT):
        for path in sorted(root.rglob("*")):
            if path.is_file():
                digest.update(str(path).encode() + b"\0" + path.read_bytes() + b"\0")
    assert digest.hexdigest() == "fbd488ce080fdd5c407f455aa504a184057149a5ed08cbb9f417d446be911d4e"
    test_retained_manual_rotation_replays_actual_chain()


def test_retained_conformant_rotation_replays_actual_chain(tmp_path):
    """Actual new native chain, not the private synthetic producer regression."""
    root = CONFORMANT_ROOT
    capture, receipt_path = root / "capture-contract.json", root / "writer/receipt.v1.json"
    anchor = rotation.binding(str(capture))
    assert anchor["sha256"] == CONFORMANT_CAPTURE_SHA256
    receipt = _read(receipt_path)
    assert receipt["experiment_id"] + ".v1" == "manual_coordinator_rotation_6195_conformant.v1"
    assert rotation.normalize_receipt(receipt, expected_capture_contract=anchor) == receipt
    assert receipt["actors"] == {
        "operator": "/root", "incumbent": "/root", "successor": "/root/manual_rotation_successor_6244",
        "writer": "/root/implement_metadata_conformance_6244",
    }
    response = _read(root / "successor/initial/agent-response.original.json")
    metadata = _read(root / "successor/initial/admitted-agent-metadata.original.json")
    admission = _read(root / "operator/admission.original.json")
    assert response["agent"] == metadata == rotation.response_invocation_metadata(
        admission, expected_capture_contract=anchor, observation=response,
    )
    assert metadata["engine_identity_source"] == admission["engine_identity_source"]
    assert receipt["effects"] == {key: [] for key in rotation.EFFECTS}
    assert receipt["continuation_live_facts"]["slice_status"] == "closed_merged"
    assert receipt["continuation_live_facts"]["open_review_findings"] == []
    assert receipt["continuation_live_facts"]["external_state"]["repository_head"] == "6aa98b572a6dd497a3d035f0860bed40d613a306"
    for mode, source in (("build", root / "writer/rotation-input.json"), ("verify", receipt_path)):
        replay = subprocess.run([
            sys.executable, "-m", "app.builderops.manual_coordinator_rotation", mode,
            "--input-file", str(source), "--capture-contract-file", str(capture),
            "--expected-capture-sha256", CONFORMANT_CAPTURE_SHA256,
            "--output", str(tmp_path / f"conformant-{mode}.json"),
        ], capture_output=True, text=True, check=False)
        assert replay.returncode == 0, replay.stdout + replay.stderr
        assert json.loads(replay.stdout)["frozen_protocol_conformance"] == "CONFORMING"
        assert _read(tmp_path / f"conformant-{mode}.json") == receipt


def test_conformant_rotation_measurements_are_provenance_bound():
    receipt = _read(CONFORMANT_ROOT / "writer/receipt.v1.json")
    anchor = rotation.binding(str(CONFORMANT_ROOT / "capture-contract.json"))
    assert anchor["sha256"] == CONFORMANT_CAPTURE_SHA256
    measurements = rotation.normalize_receipt(receipt, expected_capture_contract=anchor)["measurements"]
    assert (measurements["started_at"], measurements["ended_at"], measurements["elapsed_wall_seconds"]) == (
        "2026-10-18T16:45:04Z", "2026-10-18T16:56:29Z", 685.0,
    )
    assert (measurements["packet_bytes"], measurements["initial_response_bytes"], measurements["continuation_response_bytes"]) == (58717, 7049, 3611)
    assert (measurements["successful_native_starts"], measurements["native_followup_handoffs"], measurements["artifact_handoffs"]) == (1, 2, 7)
    assert measurements["corrections"] == {key: 0 for key in rotation.CORRECTIONS}
    assert all(value["value"] == "unknown" for value in measurements["unavailable"].values())
    initial = _read(CONFORMANT_ROOT / "writer/initial-telemetry.json")
    assert initial["measurements"]["elapsed_wall_time"]["value"] == 276.0
    assert initial["evidence"]["execution"]["ref"] != receipt["inputs"]["execution"]["ref"]
    changed = deepcopy(receipt)
    changed["measurements"]["packet_bytes"] += 1
    with pytest.raises(rotation.Error):
        rotation.normalize_receipt(changed, expected_capture_contract=anchor)
