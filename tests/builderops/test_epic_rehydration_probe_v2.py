from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path

import pytest

from app.builderops import epic_rehydration_probe as probe
from app.builderops import epic_rehydration_probe_v2 as v2
from app.builderops.epic_run_context_budget import evaluate_slice_boundary_context_budget


def _retain(path: Path, value: dict) -> str:
    path.write_bytes(probe.canonical_json_bytes(value) + b"\n")
    return str(path)


@pytest.fixture
def chain(tmp_path):
    issue = {"url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/3798", "number": 3798, "state": "CLOSED"}
    pr = {"url": "https://github.com/RasmusTho/agentic-pkm-mvp/pull/3803", "number": 3803, "state": "MERGED", "headRefOid": "a" * 40, "mergeCommit": {"oid": "b" * 40}, "statusCheckRollup": [{"conclusion": "SUCCESS"}]}
    _retain(tmp_path / "live-issue-3798.json", issue)
    _retain(tmp_path / "live-pr-3803.json", pr)
    dispatcher = _retain(tmp_path / "dispatcher.json", {"coordination_mode": "dispatcher-backed", "db_exists": True, "configured_repositories": ["RasmusTho/agentic-pkm-mvp"]})
    repository = _retain(tmp_path / "repository.json", {"head_sha": "c" * 40})
    external = {"issue": "3798:closed", "pr": "3803:merged", "pr_head_sha": "a" * 40, "merge_sha": "b" * 40, "repository_head": "c" * 40, "ci": "green", "dispatcher": {"coordination_mode": "dispatcher-backed", "db_exists": True}}
    source = evaluate_slice_boundary_context_budget(
        slice_id="issue-3798", slice_status="closed_merged", decision_log_delta=["retain advisory-only boundary"],
        open_review_findings=[], external_state_marker={"issue": "3798:closed", "pr": "3803:merged", "pr_head_sha": "a" * 40, "merge_sha": "b" * 40, "observed_at": "2026-10-17T20:00:00Z", "dispatcher_status_ref": dispatcher, "repository_status_ref": repository, "probe_external_state": external},
        context_measurement={"value": "unknown", "unit": "tokens", "source": "not-exposed"}, context_pressure="unknown", completed_slices_since_checkpoint=0,
        repairs={"implementation": 0, "review": 0, "ci": 0}, uncertainty={"level": "medium", "reasons": ["manual observation"]},
        next_slice={"worker_isolated": True, "setup_cost_high": False, "merge_risk_low": True},
        policy={"schema_version": 1, "rotate_on_high_context_pressure": True, "thin_worker_when_isolated": True}, cost_inputs={}, accepted_slice_count=None,
    )
    source_ref = _retain(tmp_path / "source.json", source)
    kwargs = {"source_ref": source_ref, "source_observed_at": "2026-10-17T20:00:00Z", "slice_id": "issue-3798", "repository": "RasmusTho/agentic-pkm-mvp", "issue_number": 3798, "pr_number": 3803, "verified_pr_head_sha": "a" * 40, "merge_sha": "b" * 40, "read_instructions": ["Read packet only, then live read-only evidence. Return only the contracted observation."], "probe_id": "shadow_rehydration_3798_field_contract", "schema_version": 2}
    pack = probe.build_context_pack(Path(source_ref).read_bytes(), **kwargs)
    values = {"slice_status": source["checkpoint"]["slice_status"], "checkpoint_decision_delta": source["checkpoint"]["decision_log_delta"], "checkpoint_gate_invariants": source["gate_invariants"], "open_review_findings": [], "external_state": external, "checkpoint_recommendations": {"recommendations": source["recommendations"], "reasons": source["recommendation_reasons"]}, "live_slice_next_action": {"action": "none", "reason": "slice is already closed and merged"}, "missing_claims": [], "fabricated_claims": "unknown"}
    obs = {"schema_name": probe.OBSERVATION_SCHEMA_NAME, "schema_version": 2, "probe_id": pack["probe_id"], "observed_at": "2026-10-17T20:01:10Z", "target": {key: pack["target"][key] for key in v2.TARGET["properties"]}, "agent": {"admitted_model": "configured-test-capability", "admitted_reasoning_effort": "high", "engine_identity": "unknown", "engine_identity_source": "not-exposed", "start_status": "succeeded", "start_observed_at": "2026-10-17T20:00:10Z"}, "fields": {name: {"value": value, "provenance": [{"kind": "checkpoint" if name.startswith("checkpoint_") else "github", "ref": "retained:independent-observation"}], "notes": []} for name, value in values.items()}, "live_reads": [{"kind": kind, "ref": f"live:{kind}"} for kind in ("github", "repository", "dispatcher")], "limitations": ["usage unavailable"]}
    refs = {"source_checkpoint": source_ref, "context_pack": _retain(tmp_path / "pack.json", pack), "agent_response": _retain(tmp_path / "response.json", obs)}
    log = {"schema_name": "epic_rehydration_execution_log", "schema_version": 2, "probe_id": pack["probe_id"], "clock": {"name": "UTC system wall clock", "unit": "seconds", "scope": "native probe admission request through original response retention"}, "started_at": "2026-10-17T20:00:00Z", "ended_at": "2026-10-17T20:01:12Z", "invocation": obs["agent"], "events_complete": True, "recorder": "test coordinator", "events": [{"id": "start-1", "kind": "agent_start", "at": "2026-10-17T20:00:10Z", "evidence": "native successful admission receipt"}, {"id": "handoff-1", "kind": "handoff", "at": "2026-10-17T20:01:12Z", "evidence": "original response retained"}], "usage": {key: v2._measurement("unknown", unit, "native probe admission request through original response retention", "native carrier unavailable", availability="unknown", reason="not exposed") for key, unit in v2.USAGE_UNITS.items()}}
    execution_ref = _retain(tmp_path / "execution.json", log)
    comparison = probe.compare_rehydrated_observation(pack, obs)
    refs["comparison_receipt"] = _retain(tmp_path / "comparison.json", comparison)
    telemetry = v2.build_telemetry(pack, obs, pack_ref=refs["context_pack"], observation_ref=refs["agent_response"], execution_ref=execution_ref)
    receipt = probe.build_probe_receipt(pack, obs, comparison, evidence_refs=refs, telemetry=telemetry)
    return {"pack": pack, "observation": obs, "comparison": comparison, "telemetry": telemetry, "receipt": receipt, "refs": refs, "kwargs": kwargs, "log": log, "execution_ref": execution_ref}


def test_v2_field_contract_aligns_equivalent_observations(chain):
    pack, obs = chain["pack"], chain["observation"]
    assert pack["schema_version"] == 2
    assert pack["response_contract"] == v2.RESPONSE_CONTRACT
    assert probe.normalize_rehydrated_observation(obs, context_pack=pack) == obs
    results = chain["comparison"]["field_results"]
    assert all(results[name]["status"] == "match" for name in v2.COMPARED)
    assert results["live_slice_next_action"]["status"] == "not_comparable"
    assert results["checkpoint_recommendations"]["observed"] != results["live_slice_next_action"]["observed"]
    assert probe.normalize_comparison(chain["comparison"]) == chain["comparison"]


def test_v2_comparison_preserves_drift_missing_and_unknowns(chain):
    obs = deepcopy(chain["observation"])
    obs["fields"]["slice_status"]["value"] = "in_progress"
    obs["fields"]["external_state"]["value"]["repository_head"] = "unknown"
    obs["fields"]["checkpoint_decision_delta"]["value"] = "unknown"
    obs["fields"]["missing_claims"]["value"] = ["checkpoint_decision_delta", "external_state"]
    obs["fields"]["fabricated_claims"]["value"] = ["slice_status"]
    comparison = probe.compare_rehydrated_observation(chain["pack"], obs)
    fields = comparison["field_results"]
    assert fields["slice_status"]["status"] == "mismatch"
    assert fields["external_state"]["status"] == "unknown"
    assert fields["external_state"]["observed"]["repository_head"] == "unknown"
    assert fields["missing_claims"]["status"] == "match"
    assert fields["fabricated_claims"]["status"] == "unknown"  # self-report/drift is not independent proof
    assert comparison["external_refresh"]["refresh_required"] is True
    assert not {"score", "threshold", "aggregate"} & comparison.keys()
    obs["fields"]["external_state"]["value"]["ci"] = "red"
    drift = probe.compare_rehydrated_observation(chain["pack"], obs)["field_results"]["external_state"]
    assert drift["status"] == "mismatch"
    assert drift["dimensions"]["repository_head"]["status"] == "unknown"
    assert drift["dimensions"]["ci"]["status"] == "mismatch"
    root = Path(chain["refs"]["context_pack"]).parent
    fact = {"schema_name": "epic_rehydration_independent_fact", "schema_version": 2, "probe_id": obs["probe_id"], "field": "slice_status", "value": "closed_merged", "provenance": [{"kind": "github", "ref": "independently retained live lifecycle reads"}], "observed_at": obs["observed_at"]}
    fact_ref = _retain(root / "independent-fact.json", fact)
    _retain(Path(chain["refs"]["agent_response"]), obs)
    audit = {"schema_name": "epic_rehydration_fabrication_audit", "schema_version": 2, "probe_id": obs["probe_id"], "context_pack": v2._bound_ref(chain["refs"]["context_pack"]), "observation": v2._bound_ref(chain["refs"]["agent_response"]), "auditor": "separate-test-auditor", "independence": "separate_agent_or_human", "findings": [{"field": "slice_status", "claimed_value": "in_progress", "established_value": "closed_merged", "evidence": v2._bound_ref(fact_ref), "verdict": "fabricated"}]}
    audit_ref = _retain(root / "audit.json", audit)
    audited = probe.compare_rehydrated_observation(chain["pack"], obs, fabrication_audit_ref=audit_ref)
    assert audited["field_results"]["fabricated_claims"]["status"] == "match"
    assert probe.normalize_comparison(audited) == audited
    audit["findings"][0]["claimed_value"] = "different claim"
    _retain(Path(audit_ref), audit)
    with pytest.raises(probe.EpicRehydrationProbeError):
        probe.normalize_comparison(audited)


def test_v2_telemetry_is_measured_and_provenance_bound(chain):
    telemetry = chain["telemetry"]
    values = telemetry["measurements"]
    assert values["packet_bytes"]["value"] == len(Path(chain["refs"]["context_pack"]).read_bytes())
    assert values["response_bytes"]["value"] == len(Path(chain["refs"]["agent_response"]).read_bytes())
    assert values["elapsed_wall_time"]["value"] == 72.0
    assert values["agent_start"]["value"] == values["handoff"]["value"] == 1
    assert values["admission_retry"]["value"] == values["implementation_repair"]["value"] == 0
    assert all(values[name]["value"] == "unknown" for name in v2.USAGE_UNITS)
    assert v2.normalize_telemetry(telemetry) == telemetry
    for key in ("packet_bytes", "response_bytes", "elapsed_wall_time", *v2.EVENT_KINDS):
        bad = deepcopy(telemetry)
        bad["measurements"][key]["value"] += 1
        with pytest.raises(probe.EpicRehydrationProbeError):
            v2.normalize_telemetry(bad)
    for mutate in (
        lambda log: log.update(ended_at="2026-10-17T19:59:59Z"),
        lambda log: log["events"].append(deepcopy(log["events"][0])),
        lambda log: log["usage"]["input_tokens"].update(availability="measured", value=123),
        lambda log: log["events"][0].update(kind="admission_retry"),
    ):
        bad_log = deepcopy(chain["log"])
        mutate(bad_log)
        _retain(Path(chain["execution_ref"]), bad_log)
        with pytest.raises(probe.EpicRehydrationProbeError):
            v2.build_telemetry(chain["pack"], chain["observation"], pack_ref=chain["refs"]["context_pack"], observation_ref=chain["refs"]["agent_response"], execution_ref=chain["execution_ref"])


def test_v2_serialized_consumers_bind_complete_evidence_chain(chain):
    assert probe.normalize_probe_receipt(chain["receipt"]) == chain["receipt"]
    for mutate in (
        lambda value: value["fields"]["checkpoint_recommendations"]["value"].update(reasons=42),
        lambda value: value["fields"]["external_state"]["value"].update(unexpected=True),
        lambda value: value["target"].update(issue_number=True),
        lambda value: value.update(schema_version=2.0),
        lambda value: value["fields"].pop("missing_claims"),
    ):
        bad = deepcopy(chain["observation"])
        mutate(bad)
        with pytest.raises(probe.EpicRehydrationProbeError):
            probe.normalize_rehydrated_observation(bad, context_pack=chain["pack"])
    for raw in (b'{"schema_version":2,"schema_version":2}', b'{"x":NaN}', b'[]', b'{broken'):
        with pytest.raises(probe.EpicRehydrationProbeError):
            probe.parse_strict_json(raw)
    bad_comparison = deepcopy(chain["comparison"])
    bad_comparison["field_results"]["slice_status"]["status"] = "mismatch"
    for consumer in (lambda: probe.normalize_comparison(bad_comparison), lambda: probe.build_probe_receipt(chain["pack"], chain["observation"], bad_comparison, evidence_refs=chain["refs"], telemetry=chain["telemetry"])):
        with pytest.raises(probe.EpicRehydrationProbeError):
            consumer()
    # Coherent hash updates cannot turn a falsified comparison into valid semantics.
    _retain(Path(chain["refs"]["comparison_receipt"]), bad_comparison)
    bad_receipt = deepcopy(chain["receipt"])
    bad_receipt["comparison"] = v2._bound_ref(chain["refs"]["comparison_receipt"])
    with pytest.raises(probe.EpicRehydrationProbeError):
        probe.normalize_probe_receipt(bad_receipt)
    # Source custody corruption fails even if all digest bindings are recomputed.
    bad_pack = deepcopy(chain["pack"])
    repository_ref = bad_pack["source_custody"]["repository"]["ref"]
    _retain(Path(repository_ref), {"head_sha": "d" * 40})
    bad_pack["source_custody"]["repository"] = v2._bound_ref(repository_ref)
    with pytest.raises(probe.EpicRehydrationProbeError):
        probe.normalize_context_pack(bad_pack)


def test_v1_evidence_remains_compatible():
    root = Path("evidence")
    for name, consumer in (("context-pack.json", probe.normalize_context_pack), ("agent-response.json", probe.normalize_rehydrated_observation), ("comparison.json", probe.normalize_comparison), ("shadow_rehydration_3798.v1.json", probe.normalize_probe_receipt)):
        value = probe.parse_strict_json((root / name).read_bytes())
        assert consumer(value) == value
    assert probe.SCHEMA_VERSION == 1


def test_v2_manual_entrypoints_have_no_authority_effects(chain, tmp_path):
    for value in (chain["pack"], chain["comparison"], chain["telemetry"], chain["receipt"]):
        assert all(value["effects"][name] == [] for name in probe._EFFECT_CATEGORIES)
    _retain(tmp_path / "telemetry.json", chain["telemetry"])
    _retain(tmp_path / "refs.json", chain["refs"])
    commands = [
        ["compare", "--pack-file", chain["refs"]["context_pack"], "--observation-file", chain["refs"]["agent_response"]],
        ["telemetry", "--pack-file", chain["refs"]["context_pack"], "--observation-file", chain["refs"]["agent_response"], "--execution-file", chain["execution_ref"]],
        ["receipt", "--pack-file", chain["refs"]["context_pack"], "--observation-file", chain["refs"]["agent_response"], "--comparison-file", chain["refs"]["comparison_receipt"], "--telemetry-file", str(tmp_path / "telemetry.json"), "--evidence-file", str(tmp_path / "refs.json")],
    ]
    kwargs = chain["kwargs"]
    build = ["build-pack", "--source-file", kwargs["source_ref"], "--source-ref", kwargs["source_ref"], "--source-observed-at", kwargs["source_observed_at"], "--slice-id", kwargs["slice_id"], "--repository", kwargs["repository"], "--issue-number", "3798", "--pr-number", "3803", "--verified-pr-head-sha", "a" * 40, "--merge-sha", "b" * 40, "--read-instruction", kwargs["read_instructions"][0], "--probe-id", kwargs["probe_id"], "--schema-version", "2"]
    commands.append(build)
    input_paths = list(tmp_path.glob("*.json"))
    before = {path: path.read_bytes() for path in input_paths}
    for index, command in enumerate(commands):
        output = tmp_path / f"new-{index}.json"
        assert probe.cli_main([*command, "--output", str(output)]) == 0
        assert probe.cli_main([*command, "--output", str(output)]) == 2
        for path in input_paths:
            assert probe.cli_main([*command, "--output", str(path)]) == 2
        for alias_kind in ("symlink", "hardlink"):
            alias = tmp_path / f"alias-{index}-{alias_kind}.json"
            if alias_kind == "symlink":
                alias.symlink_to(input_paths[0])
            else:
                alias.hardlink_to(input_paths[0])
            assert probe.cli_main([*command, "--output", str(alias)]) == 2
    assert {path: path.read_bytes() for path in input_paths} == before
    for module in (probe, v2):
        tree = ast.parse(Path(module.__file__).read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(name.startswith(("app.dispatcher", "app.github", "app.model_access", "subprocess")) for name in imports)
