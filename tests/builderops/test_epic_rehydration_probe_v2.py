from __future__ import annotations

import ast
import json
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
    external = {"issue": "3798:closed", "pr": "3803:merged", "pr_head_sha": "a" * 40, "merge_sha": "b" * 40, "repository_head": "c" * 40, "ci": {"status": "green", "scope": v2.CI_SCOPE}, "dispatcher": {"coordination_mode": "dispatcher-backed", "db_exists": True}}
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
    pack_ref = _retain(tmp_path / "pack.json", pack)
    live_target = {key: pack["target"][key] for key in ("repository", "issue_number", "pr_number")}
    live_payloads = {
        "github": {"issue": issue, "pr": pr, "review_threads": {"repository": live_target["repository"], "pr_number": 3803, "nodes": [], "complete": True}},
        "repository": {"head_sha": "c" * 40, "remote": "origin", "ref": "refs/heads/main"},
        "dispatcher": {"ok": True, "coordination_mode": "dispatcher-backed", "db_exists": True, "configured_repositories": [live_target["repository"]]},
    }
    live_reads = []
    for kind, payload in live_payloads.items():
        live_ref = _retain(tmp_path / f"live-read-{kind}.json", {"schema_name": "epic_rehydration_live_read", "schema_version": 2, "probe_id": pack["probe_id"], "kind": kind, "target": live_target, "observed_at": "2026-10-17T20:00:30Z", "availability": "observed", "payload": payload, "unavailable_reason": ""})
        live_reads.append({"kind": kind, "evidence": v2._bound_ref(live_ref)})
    values = {"slice_status": source["checkpoint"]["slice_status"], "checkpoint_decision_delta": source["checkpoint"]["decision_log_delta"], "checkpoint_gate_invariants": source["gate_invariants"], "open_review_findings": [], "external_state": external, "checkpoint_recommendations": {"recommendations": source["recommendations"], "reasons": source["recommendation_reasons"]}, "live_slice_next_action": {"action": "none", "reason": "slice is already closed and merged"}, "missing_claims": [], "fabricated_claims": "unknown"}
    obs = {"schema_name": probe.OBSERVATION_SCHEMA_NAME, "schema_version": 2, "probe_id": pack["probe_id"], "observed_at": "2026-10-17T20:01:10Z", "target": {key: pack["target"][key] for key in v2.TARGET["properties"]}, "agent": {"admitted_model": "configured-test-capability", "admitted_reasoning_effort": "high", "engine_identity": "unknown", "engine_identity_source": "not-exposed", "start_status": "succeeded", "start_observed_at": "2026-10-17T20:00:10Z"}, "fields": {name: {"value": value, "provenance": [{"kind": "checkpoint" if name.startswith("checkpoint_") else "github", "ref": "retained:independent-observation"}], "notes": []} for name, value in values.items()}, "live_reads": [{"kind": kind, "ref": f"live:{kind}"} for kind in ("github", "repository", "dispatcher")], "limitations": ["usage unavailable"]}
    obs.update(context_pack=v2._bound_ref(pack_ref), live_reads=live_reads)
    live_refs = {item["kind"]: item["evidence"]["ref"] for item in live_reads}
    for name, field in obs["fields"].items():
        if name in v2.LIVE_FIELD_KINDS:
            field["provenance"] = [{"kind": kind, "ref": live_refs[kind]} for kind in v2.LIVE_FIELD_KINDS[name]]
        elif name.startswith("checkpoint_"):
            field["provenance"] = [{"kind": "checkpoint", "ref": f"packet:{pack['probe_id']}#{v2.CHECKPOINT_POINTERS[name]}"}]
        else:
            field["provenance"] = [{"kind": "agent", "ref": f"agent:{pack['probe_id']}"}]
    refs = {"source_checkpoint": source_ref, "context_pack": pack_ref, "agent_response": _retain(tmp_path / "response.json", obs)}
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
    assert comparison["external_refresh"]["refresh_required"] is False  # actual live reads are unchanged; the response omitted known data
    assert not {"score", "threshold", "aggregate"} & comparison.keys()
    obs["fields"]["external_state"]["value"]["ci"]["status"] = "red"
    drift = probe.compare_rehydrated_observation(chain["pack"], obs)["field_results"]["external_state"]
    assert drift["status"] == "mismatch"
    assert drift["dimensions"]["repository_head"]["status"] == "unknown"
    assert drift["dimensions"]["ci"]["status"] == "mismatch"
    root = Path(chain["refs"]["context_pack"]).parent
    fact = {"schema_name": "epic_rehydration_independent_fact", "schema_version": 2, "probe_id": obs["probe_id"], "field": "slice_status", "value": "closed_merged", "provenance": deepcopy(obs["fields"]["slice_status"]["provenance"]), "observed_at": obs["observed_at"], "live_reads": [item for item in obs["live_reads"] if item["kind"] == "github"]}
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


def test_v2_version_provenance_and_source_contract_matrix(chain, tmp_path):
    pack, obs, comp = chain["pack"], chain["observation"], chain["comparison"]
    old_pack = probe.parse_strict_json(Path("evidence/context-pack.json").read_bytes())
    old_obs = probe.parse_strict_json(Path("evidence/agent-response.json").read_bytes())
    old_comp = probe.parse_strict_json(Path("evidence/comparison.json").read_bytes())
    old_obs["target"] = deepcopy(obs["target"])
    old_obs["probe_id"] = obs["probe_id"]
    old_comp["target"] = deepcopy(pack["target"])
    old_comp["probe_id"] = pack["probe_id"]
    assert probe.normalize_rehydrated_observation(old_obs) == old_obs
    assert probe.normalize_comparison(old_comp) == old_comp
    for consumer in (
        lambda: probe.normalize_rehydrated_observation(old_obs, context_pack=pack),
        lambda: probe.normalize_rehydrated_observation(obs, context_pack=old_pack),
        lambda: probe.normalize_comparison(old_comp, context_pack=pack),
        lambda: probe.normalize_comparison(comp, context_pack=old_pack),
        lambda: probe.normalize_comparison(comp, observation=old_obs),
        lambda: probe.compare_rehydrated_observation(pack, old_obs),
        lambda: probe.compare_rehydrated_observation(old_pack, obs),
        lambda: probe.build_probe_receipt(pack, obs, old_comp, evidence_refs=chain["refs"], telemetry=chain["telemetry"]),
    ):
        with pytest.raises(probe.EpicRehydrationProbeError, match="mixed probe schema versions"):
            consumer()
    old_ref = _retain(tmp_path / "old-response.json", old_obs)
    assert probe.cli_main(["compare", "--pack-file", chain["refs"]["context_pack"], "--observation-file", old_ref, "--output", str(tmp_path / "must-not-exist.json")]) == 2
    assert not (tmp_path / "must-not-exist.json").exists()
    for field_name in v2.LIVE_FIELD_KINDS:
        bad = deepcopy(obs)
        bad["fields"][field_name]["provenance"] = [{"kind": "checkpoint", "ref": f"packet:{pack['probe_id']}#/source/receipt"}]
        with pytest.raises(probe.EpicRehydrationProbeError):
            probe.normalize_rehydrated_observation(bad, context_pack=pack)
        with pytest.raises(probe.EpicRehydrationProbeError):
            probe.compare_rehydrated_observation(pack, bad)
        # The same forgery must fail a standalone comparison, even after substitution.
        bad_comp = deepcopy(comp)
        bad_comp["observation"] = bad
        with pytest.raises(probe.EpicRehydrationProbeError):
            probe.normalize_comparison(bad_comp)
        _retain(Path(chain["refs"]["agent_response"]), bad)
        _retain(Path(chain["refs"]["comparison_receipt"]), bad_comp)
        bad_receipt = deepcopy(chain["receipt"])
        bad_receipt["observation"] = v2._bound_ref(chain["refs"]["agent_response"])
        bad_receipt["comparison"] = v2._bound_ref(chain["refs"]["comparison_receipt"])
        bad_receipt["telemetry"]["evidence"]["observation"] = bad_receipt["observation"]
        with pytest.raises(probe.EpicRehydrationProbeError):
            probe.normalize_probe_receipt(bad_receipt)
        _retain(Path(chain["refs"]["agent_response"]), obs)
        _retain(Path(chain["refs"]["comparison_receipt"]), comp)
    bad = deepcopy(obs)
    bad["live_reads"] = [{"kind": "checkpoint", "ref": "packet:source"}]
    with pytest.raises(probe.EpicRehydrationProbeError):
        probe.normalize_rehydrated_observation(bad)
    bad = deepcopy(obs)
    bad["fields"]["slice_status"]["provenance"][0]["ref"] = "undeclared:read"
    with pytest.raises(probe.EpicRehydrationProbeError):
        probe.normalize_rehydrated_observation(bad)
    source = deepcopy(pack["source"]["receipt"])
    source["checkpoint"]["decision_log_delta"] = [42]
    source_ref = _retain(tmp_path / "bad-source.json", source)
    kwargs = chain["kwargs"] | {"source_ref": source_ref}
    with pytest.raises(probe.EpicRehydrationProbeError):
        probe.build_context_pack(Path(source_ref).read_bytes(), **kwargs)
    for consumer in (probe.normalize_context_pack, probe.normalize_rehydrated_observation, probe.normalize_comparison, probe.normalize_probe_receipt):
        with pytest.raises(probe.EpicRehydrationProbeError):
            consumer([])


def test_v2_known_usage_and_equal_tick_event_order_are_strict(chain):
    log = deepcopy(chain["log"])
    log["events"].insert(1, {"id": "retry-after-success", "kind": "admission_retry", "at": log["events"][0]["at"], "evidence": "rejected invocation retried after success at same clock tick"})
    _retain(Path(chain["execution_ref"]), log)
    with pytest.raises(probe.EpicRehydrationProbeError):
        v2.build_telemetry(chain["pack"], chain["observation"], pack_ref=chain["refs"]["context_pack"], observation_ref=chain["refs"]["agent_response"], execution_ref=chain["execution_ref"])
    log["events"][0], log["events"][1] = log["events"][1], log["events"][0]
    _retain(Path(chain["execution_ref"]), log)
    measured = v2.build_telemetry(chain["pack"], chain["observation"], pack_ref=chain["refs"]["context_pack"], observation_ref=chain["refs"]["agent_response"], execution_ref=chain["execution_ref"])
    assert measured["measurements"]["admission_retry"]["value"] == 1
    root = Path(chain["execution_ref"]).parent
    authority = {"schema_name": "epic_rehydration_usage_authority", "schema_version": 2, "probe_id": log["probe_id"], "authority": "carrier_usage_receipt", "metric": "input_tokens", "value": 123, "unit": "tokens", "scope": log["clock"]["scope"], "observed_at": log["ended_at"], "source": "retained native authoritative receipt"}
    authority_ref = _retain(root / "usage-authority.json", authority)
    log["usage"]["input_tokens"] = v2._measurement(123, "tokens", log["clock"]["scope"], v2._bound_ref(authority_ref), reason="native authoritative usage receipt")
    _retain(Path(chain["execution_ref"]), log)
    measured = v2.build_telemetry(chain["pack"], chain["observation"], pack_ref=chain["refs"]["context_pack"], observation_ref=chain["refs"]["agent_response"], execution_ref=chain["execution_ref"])
    assert v2.normalize_telemetry(measured)["measurements"]["input_tokens"]["value"] == 123
    for updates in ({"schema_version": 999}, {"unit": "bytes"}, {"scope": "foreign"}, {"unsupported": True}, {"value": True}, {"metric": "output_tokens"}, {"probe_id": "foreign"}):
        _retain(Path(authority_ref), authority | updates)
        bad_log = deepcopy(log)
        bad_log["usage"]["input_tokens"]["source"] = v2._bound_ref(authority_ref)
        _retain(Path(chain["execution_ref"]), bad_log)
        with pytest.raises(probe.EpicRehydrationProbeError):
            v2.build_telemetry(chain["pack"], chain["observation"], pack_ref=chain["refs"]["context_pack"], observation_ref=chain["refs"]["agent_response"], execution_ref=chain["execution_ref"])
        bad_measured = deepcopy(measured)
        bad_measured["evidence"]["execution"] = v2._bound_ref(chain["execution_ref"])
        bad_measured["measurements"]["input_tokens"] = bad_log["usage"]["input_tokens"]
        with pytest.raises(probe.EpicRehydrationProbeError):
            v2.normalize_telemetry(bad_measured)
        bad_receipt = deepcopy(chain["receipt"])
        bad_receipt["telemetry"] = bad_measured
        with pytest.raises(probe.EpicRehydrationProbeError):
            probe.normalize_probe_receipt(bad_receipt)


def test_v2_ci_scope_retains_historical_cancellations_without_current_gate_claim():
    value = v2._ci_summary({"statusCheckRollup": [{"name": "smoke", "conclusion": "CANCELLED"}, {"name": "smoke", "conclusion": "SUCCESS"}]})
    assert value == {"status": "red", "scope": v2.CI_SCOPE}
    assert "not_a_current_required_ci_verdict" in value["scope"]


def _rebind_chain(chain, observation, tmp_path):
    """Fault injection updates every changed raw binding, not merely the visible hash."""
    _retain(Path(chain["refs"]["agent_response"]), observation)
    comparison = deepcopy(chain["comparison"])
    comparison["observation"] = observation
    for name in comparison["field_results"]:
        comparison["field_results"][name]["provenance"] = observation["fields"][name]["provenance"]
    _retain(Path(chain["refs"]["comparison_receipt"]), comparison)
    response_binding = v2._bound_ref(chain["refs"]["agent_response"])
    telemetry = deepcopy(chain["telemetry"])
    telemetry["evidence"]["observation"] = response_binding
    telemetry["measurements"]["response_bytes"].update(value=response_binding["bytes_length"], source=response_binding)
    receipt = deepcopy(chain["receipt"])
    receipt.update(observation=response_binding, comparison=v2._bound_ref(chain["refs"]["comparison_receipt"]), telemetry=telemetry)
    telemetry_ref = _retain(tmp_path / "rebound-telemetry.json", telemetry)
    evidence_ref = _retain(tmp_path / "rebound-evidence.json", chain["refs"])
    return comparison, telemetry, receipt, telemetry_ref, evidence_ref


def _assert_all_consumers_refuse(chain, bad, tmp_path, *, match=None):
    comp, telemetry, receipt, telemetry_ref, evidence_ref = _rebind_chain(chain, bad, tmp_path)
    for consumer in (
        lambda: probe.normalize_rehydrated_observation(bad, context_pack=chain["pack"]),
        lambda: probe.compare_rehydrated_observation(chain["pack"], bad),
        lambda: probe.normalize_comparison(comp),
        lambda: v2.build_telemetry(chain["pack"], bad, pack_ref=chain["refs"]["context_pack"], observation_ref=chain["refs"]["agent_response"], execution_ref=chain["execution_ref"]),
        lambda: v2.normalize_telemetry(telemetry),
        lambda: probe.build_probe_receipt(chain["pack"], bad, comp, evidence_refs=chain["refs"], telemetry=telemetry),
        lambda: probe.normalize_probe_receipt(receipt),
    ):
        with pytest.raises(probe.EpicRehydrationProbeError, match=match) as error:
            consumer()
        assert "retained evidence digest/length mismatch" not in str(error.value)
    commands = [
        ["compare", "--pack-file", chain["refs"]["context_pack"], "--observation-file", chain["refs"]["agent_response"]],
        ["telemetry", "--pack-file", chain["refs"]["context_pack"], "--observation-file", chain["refs"]["agent_response"], "--execution-file", chain["execution_ref"]],
        ["receipt", "--pack-file", chain["refs"]["context_pack"], "--observation-file", chain["refs"]["agent_response"], "--comparison-file", chain["refs"]["comparison_receipt"], "--telemetry-file", telemetry_ref, "--evidence-file", evidence_ref],
    ]
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    for index, command in enumerate(commands):
        output = tmp_path / f"refusal-output-{index}.json"
        assert not output.exists()
        assert probe.cli_main([*command, "--output", str(output)]) == 2
        assert not output.exists()
    assert {path: path.read_bytes() for path in before} == before


def _replace_github_read(chain, binding):
    bad = deepcopy(chain["observation"])
    for read in bad["live_reads"]:
        if read["kind"] == "github":
            read["evidence"] = binding
    for name in v2.LIVE_FIELD_KINDS:
        for provenance in bad["fields"][name]["provenance"]:
            if provenance["kind"] == "github":
                provenance["ref"] = binding["ref"]
    return bad


def test_v2_provenance_alias_matrix_reaches_every_consumer(chain, tmp_path):
    forbidden = [chain["refs"]["source_checkpoint"], chain["refs"]["context_pack"], *[item["ref"] for item in chain["pack"]["source_custody"].values()]]
    for index, source_ref in enumerate(forbidden):
        source = Path(source_ref)
        symlink = tmp_path / f"source-symlink-{index}.json"
        symlink.symlink_to(source)
        hardlink = tmp_path / f"source-hardlink-{index}.json"
        hardlink.hardlink_to(source)
        copied = tmp_path / f"source-copy-{index}.json"
        copied.write_bytes(source.read_bytes())
        # A '..' spelling and a relative spelling still resolve against repo CWD.
        import os

        relative = os.path.relpath(source)
        refs = [str(source), str(source.parent / ".." / source.parent.name / source.name), relative, str(source) + "#/checkpoint", source.as_uri(), str(symlink), str(hardlink), str(copied)]
        for ref in refs:
            raw = source.read_bytes()
            binding = {"ref": ref, "sha256": probe.sha256_bytes(raw), "bytes_length": len(raw)}
            _assert_all_consumers_refuse(chain, _replace_github_read(chain, binding), tmp_path)
    for ref in (f"packet:{chain['pack']['probe_id']}#/source/receipt", "source:checkpoint", "live:github", str(tmp_path / "missing.json")):
        _assert_all_consumers_refuse(chain, _replace_github_read(chain, {"ref": ref, "sha256": "0" * 64, "bytes_length": 1}), tmp_path)


def test_v2_live_read_domain_target_and_context_matrix(chain, tmp_path):
    github = next(item for item in chain["observation"]["live_reads"] if item["kind"] == "github")
    original = probe.parse_strict_json(Path(github["evidence"]["ref"]).read_bytes())
    mutations = [
        lambda value: value.update(kind="repository"),
        lambda value: value["target"].update(repository="foreign/repo"),
        lambda value: value["target"].update(issue_number=999),
        lambda value: value["target"].update(pr_number=999),
        lambda value: value["payload"]["issue"].update(number=999),
        lambda value: value["payload"]["pr"].update(number=999),
        lambda value: value["payload"]["review_threads"].update(pr_number=999),
        lambda value: value.update(observed_at="2026-10-17T19:59:00Z"),
        lambda value: value.update(schema_name="epic_rehydration_context_pack"),
        lambda value: value.update(extra=True),
    ]
    for index, mutate in enumerate(mutations):
        bad_read = deepcopy(original)
        mutate(bad_read)
        ref = _retain(tmp_path / f"bad-live-{index}.json", bad_read)
        _assert_all_consumers_refuse(chain, _replace_github_read(chain, v2._bound_ref(ref)), tmp_path)
    with pytest.raises(probe.EpicRehydrationProbeError, match="requires context_pack"):
        probe.normalize_rehydrated_observation(chain["observation"])


def test_v2_real_live_drift_unknown_and_identical_reread_are_preserved(chain, tmp_path):
    obs = deepcopy(chain["observation"])
    repository = next(item for item in obs["live_reads"] if item["kind"] == "repository")
    original = probe.parse_strict_json(Path(repository["evidence"]["ref"]).read_bytes())
    copy_ref = _retain(tmp_path / "genuine-identical-reread.json", original)
    assert v2._bound_ref(copy_ref)["sha256"] == repository["evidence"]["sha256"]
    repository["evidence"] = v2._bound_ref(copy_ref)
    for item in obs["fields"]["external_state"]["provenance"]:
        if item["kind"] == "repository":
            item["ref"] = copy_ref
    assert probe.compare_rehydrated_observation(chain["pack"], obs)["field_results"]["external_state"]["status"] == "match"
    original["payload"]["head_sha"] = "d" * 40
    _retain(Path(copy_ref), original)
    repository["evidence"] = v2._bound_ref(copy_ref)
    obs["fields"]["external_state"]["value"]["repository_head"] = "d" * 40
    drift = probe.compare_rehydrated_observation(chain["pack"], obs)
    assert drift["field_results"]["external_state"]["status"] == "mismatch"
    assert drift["external_refresh"]["refresh_required"] is True
    original.update(availability="unavailable", payload="unknown", unavailable_reason="read failed")
    _retain(Path(copy_ref), original)
    repository["evidence"] = v2._bound_ref(copy_ref)
    obs["fields"]["external_state"]["value"]["repository_head"] = "unknown"
    unknown = probe.compare_rehydrated_observation(chain["pack"], obs)
    assert unknown["field_results"]["external_state"]["observed"]["repository_head"] == "unknown"
    assert unknown["external_refresh"]["status"] == "unknown"


def test_v2_exact_observer_packet_bytes_bind_every_file_consumer(chain, tmp_path):
    alternate = tmp_path / "same-packet-different-bytes.json"
    alternate.write_text(json.dumps(chain["pack"], indent=2) + "\n")
    binding = v2._bound_ref(str(alternate), chain["pack"])
    assert binding["sha256"] != chain["observation"]["context_pack"]["sha256"]
    assert binding["bytes_length"] != chain["observation"]["context_pack"]["bytes_length"]
    telemetry = deepcopy(chain["telemetry"])
    telemetry["evidence"]["context_pack"] = binding
    telemetry["measurements"]["packet_bytes"].update(value=binding["bytes_length"], source=binding)
    refs = chain["refs"] | {"context_pack": str(alternate)}
    receipt = deepcopy(chain["receipt"])
    receipt.update(context_pack=binding, evidence=refs, telemetry=telemetry)
    for consumer in (
        lambda: probe.normalize_rehydrated_observation(chain["observation"], context_pack=chain["pack"], context_pack_ref=str(alternate)),
        lambda: probe.compare_rehydrated_observation(chain["pack"], chain["observation"], context_pack_ref=str(alternate)),
        lambda: v2.build_telemetry(chain["pack"], chain["observation"], pack_ref=str(alternate), observation_ref=refs["agent_response"], execution_ref=chain["execution_ref"]),
        lambda: v2.normalize_telemetry(telemetry),
        lambda: probe.build_probe_receipt(chain["pack"], chain["observation"], chain["comparison"], evidence_refs=refs, telemetry=chain["telemetry"]),
        lambda: probe.normalize_probe_receipt(receipt),
    ):
        with pytest.raises(probe.EpicRehydrationProbeError, match="observer's exact raw packet"):
            consumer()
    telemetry_ref = _retain(tmp_path / "alternate-telemetry.json", telemetry)
    refs_ref = _retain(tmp_path / "alternate-refs.json", refs)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    for index, command in enumerate((
        ["compare", "--pack-file", str(alternate), "--observation-file", refs["agent_response"]],
        ["telemetry", "--pack-file", str(alternate), "--observation-file", refs["agent_response"], "--execution-file", chain["execution_ref"]],
        ["receipt", "--pack-file", str(alternate), "--observation-file", refs["agent_response"], "--comparison-file", refs["comparison_receipt"], "--telemetry-file", telemetry_ref, "--evidence-file", refs_ref],
    )):
        output = tmp_path / f"alternate-refused-{index}.json"
        assert probe.cli_main([*command, "--output", str(output)]) == 2
        assert not output.exists()
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("kind", ["github", "repository", "dispatcher"])
@pytest.mark.parametrize("at", ["2026-10-17T20:00:05Z", "2026-10-17T20:01:11Z"])
def test_v2_probe_reads_are_after_admission_and_before_response(chain, tmp_path, kind, at):
    bad = deepcopy(chain["observation"])
    item = next(item for item in bad["live_reads"] if item["kind"] == kind)
    read = probe.parse_strict_json(Path(item["evidence"]["ref"]).read_bytes())
    read["observed_at"] = at
    _retain(Path(item["evidence"]["ref"]), read)
    item["evidence"] = v2._bound_ref(item["evidence"]["ref"])
    _assert_all_consumers_refuse(chain, bad, tmp_path, match="admitted observation interval")


@pytest.mark.parametrize("kind,number", [("issue", 3798.0), ("pr", 3803.0)])
def test_v2_source_custody_identities_are_exact_integers(chain, tmp_path, kind, number):
    bad_chain = deepcopy(chain)
    pack = bad_chain["pack"]
    custody_ref = pack["source_custody"][kind]["ref"]
    custody = probe.parse_strict_json(Path(custody_ref).read_bytes())
    custody["number"] = number
    _retain(Path(custody_ref), custody)
    pack["source_custody"][kind] = v2._bound_ref(custody_ref)
    marker = pack["source"]["receipt"]["checkpoint"]["external_state"]["marker"]
    marker["probe_external_state"][kind] = f"{number}:{custody['state'].lower()}"
    pack["source"]["external_state_marker"] = deepcopy(marker)
    _retain(Path(bad_chain["refs"]["source_checkpoint"]), pack["source"]["receipt"])
    source_binding = v2._bound_ref(bad_chain["refs"]["source_checkpoint"])
    pack["source"].update(bytes_sha256=source_binding["sha256"], bytes_length=source_binding["bytes_length"])
    _retain(Path(bad_chain["refs"]["context_pack"]), pack)
    packet_binding = v2._bound_ref(bad_chain["refs"]["context_pack"])
    obs = deepcopy(bad_chain["observation"])
    obs["context_pack"] = packet_binding
    bad_chain["comparison"]["context_pack"] = pack
    bad_chain["comparison"]["field_results"]["external_state"]["expected"] = marker["probe_external_state"]
    bad_chain["telemetry"]["evidence"]["context_pack"] = packet_binding
    bad_chain["telemetry"]["measurements"]["packet_bytes"].update(value=packet_binding["bytes_length"], source=packet_binding)
    bad_chain["receipt"].update(context_pack=packet_binding, source_checkpoint=pack["source"])
    with pytest.raises(probe.EpicRehydrationProbeError, match="exact integer"):
        probe.normalize_context_pack(pack)
    with pytest.raises(probe.EpicRehydrationProbeError, match="exact integer"):
        probe.build_context_pack(Path(bad_chain["refs"]["source_checkpoint"]).read_bytes(), **chain["kwargs"])
    _assert_all_consumers_refuse(bad_chain, obs, tmp_path, match="exact integer")
    kwargs = chain["kwargs"]
    output = tmp_path / "source-number-refused.json"
    assert probe.cli_main(["build-pack", "--source-file", kwargs["source_ref"], "--source-ref", kwargs["source_ref"], "--source-observed-at", kwargs["source_observed_at"], "--slice-id", kwargs["slice_id"], "--repository", kwargs["repository"], "--issue-number", "3798", "--pr-number", "3803", "--verified-pr-head-sha", "a" * 40, "--merge-sha", "b" * 40, "--read-instruction", "packet-only", "--probe-id", kwargs["probe_id"], "--schema-version", "2", "--output", str(output)]) == 2
    assert not output.exists()


@pytest.mark.parametrize("kind,key", [("repository", "head_sha"), ("github", "headRefOid"), ("github", "mergeCommit")])
def test_v2_live_sha_newlines_fail_all_consumers(chain, tmp_path, kind, key):
    bad = deepcopy(chain["observation"])
    item = next(item for item in bad["live_reads"] if item["kind"] == kind)
    read = probe.parse_strict_json(Path(item["evidence"]["ref"]).read_bytes())
    payload = read["payload"] if kind == "repository" else read["payload"]["pr"]
    if key == "mergeCommit":
        payload[key]["oid"] += "\n"
    else:
        payload[key] += "\n"
    _retain(Path(item["evidence"]["ref"]), read)
    item["evidence"] = v2._bound_ref(item["evidence"]["ref"])
    _assert_all_consumers_refuse(chain, bad, tmp_path, match="violates v2 contract")
    for shape, length in ((v2.SHA, 40), (v2.BINDING["properties"]["sha256"], 64)):
        for suffix in ("\n", "\r\n", " ", "g"):
            with pytest.raises(probe.EpicRehydrationProbeError):
                v2._validate("c" * length + suffix, shape, "carried digest")


def _audit_fixture(chain, tmp_path, name="slice_status"):
    obs = deepcopy(chain["observation"])
    obs["fields"][name]["value"] = "in_progress" if name == "slice_status" else ["invented checkpoint statement"]
    obs["fields"]["fabricated_claims"]["value"] = [name]
    _retain(Path(chain["refs"]["agent_response"]), obs)
    live_reads = deepcopy([item for item in obs["live_reads"] if item["kind"] in v2.LIVE_FIELD_KINDS.get(name, ())])
    fact = {"schema_name": "epic_rehydration_independent_fact", "schema_version": 2, "probe_id": obs["probe_id"], "field": name, "value": deepcopy(chain["observation"]["fields"][name]["value"]), "provenance": deepcopy(obs["fields"][name]["provenance"]), "observed_at": obs["observed_at"], "live_reads": live_reads}
    fact_ref = _retain(tmp_path / "audit-fact.json", fact)
    audit = {"schema_name": "epic_rehydration_fabrication_audit", "schema_version": 2, "probe_id": obs["probe_id"], "context_pack": obs["context_pack"], "observation": v2._bound_ref(chain["refs"]["agent_response"]), "auditor": "separate-test-auditor", "independence": "separate_agent_or_human", "findings": [{"field": name, "claimed_value": obs["fields"][name]["value"], "established_value": fact["value"], "evidence": v2._bound_ref(fact_ref), "verdict": "fabricated"}]}
    audit_ref = _retain(tmp_path / "audit.json", audit)
    comparison = probe.compare_rehydrated_observation(chain["pack"], obs, fabrication_audit_ref=audit_ref)
    _retain(Path(chain["refs"]["comparison_receipt"]), comparison)
    telemetry = v2.build_telemetry(chain["pack"], obs, pack_ref=chain["refs"]["context_pack"], observation_ref=chain["refs"]["agent_response"], execution_ref=chain["execution_ref"])
    receipt = probe.build_probe_receipt(chain["pack"], obs, comparison, evidence_refs=chain["refs"], telemetry=telemetry)
    return obs, fact, fact_ref, audit, audit_ref, comparison, telemetry, receipt


@pytest.mark.parametrize("case", ["checkpoint_live_fact", "source_hardlink", "source_fragment", "contrary_payload", "unknown_claim", "alternate_packet"])
def test_v2_audit_provenance_and_semantic_replay_matrix(chain, tmp_path, case):
    obs, fact, fact_ref, audit, audit_ref, comp, telemetry, receipt = _audit_fixture(chain, tmp_path)
    assert comp["field_results"]["fabricated_claims"]["status"] == "match"
    assert probe.normalize_probe_receipt(receipt) == receipt
    if case == "checkpoint_live_fact":
        fact["provenance"] = [{"kind": "checkpoint", "ref": f"packet:{obs['probe_id']}#/source/receipt/checkpoint/slice_status"}]
        fact["live_reads"] = []
    elif case in {"source_hardlink", "source_fragment"}:
        alias = tmp_path / "audit-source-hardlink.json"
        alias.hardlink_to(chain["refs"]["source_checkpoint"])
        ref = str(alias) if case == "source_hardlink" else chain["refs"]["source_checkpoint"] + "#/checkpoint/slice_status"
        raw = Path(chain["refs"]["source_checkpoint"]).read_bytes()
        binding = {"ref": ref, "sha256": probe.sha256_bytes(raw), "bytes_length": len(raw)}
        fact["provenance"] = [{"kind": "github", "ref": ref}]
        fact["live_reads"] = [{"kind": "github", "evidence": binding}]
    elif case == "contrary_payload":
        fact["value"] = "blocked"
        audit["findings"][0]["established_value"] = "blocked"
    elif case == "alternate_packet":
        alternate = tmp_path / "audit-alternate-packet.json"
        alternate.write_text(json.dumps(chain["pack"], indent=2) + "\n")
        audit["context_pack"] = v2._bound_ref(str(alternate))
    else:
        obs["fields"]["slice_status"]["value"] = "unknown"
        _retain(Path(chain["refs"]["agent_response"]), obs)
        audit["observation"] = v2._bound_ref(chain["refs"]["agent_response"])
        audit["findings"][0]["claimed_value"] = "unknown"
        comp["observation"] = obs
        comp["field_results"]["slice_status"].update(observed="unknown", status="unknown", evidence_support="unknown")
        telemetry["evidence"]["observation"] = audit["observation"]
        telemetry["measurements"]["response_bytes"].update(value=audit["observation"]["bytes_length"], source=audit["observation"])
        receipt["observation"] = audit["observation"]
    _retain(Path(fact_ref), fact)
    audit["findings"][0]["evidence"] = v2._bound_ref(fact_ref)
    _retain(Path(audit_ref), audit)
    comp["fabrication_audit"] = v2._bound_ref(audit_ref)
    _retain(Path(chain["refs"]["comparison_receipt"]), comp)
    receipt.update(comparison=v2._bound_ref(chain["refs"]["comparison_receipt"]), telemetry=telemetry)
    for consumer in (
        lambda: probe.compare_rehydrated_observation(chain["pack"], obs, fabrication_audit_ref=audit_ref),
        lambda: probe.normalize_comparison(comp),
        lambda: probe.build_probe_receipt(chain["pack"], obs, comp, evidence_refs=chain["refs"], telemetry=telemetry),
        lambda: probe.normalize_probe_receipt(receipt),
    ):
        with pytest.raises(probe.EpicRehydrationProbeError) as error:
            consumer()
        assert "retained evidence digest/length mismatch" not in str(error.value)
    telemetry_ref = _retain(tmp_path / "audit-telemetry.json", telemetry)
    refs_ref = _retain(tmp_path / "audit-refs.json", chain["refs"])
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    for index, command in enumerate((
        ["compare", "--pack-file", chain["refs"]["context_pack"], "--observation-file", chain["refs"]["agent_response"], "--fabrication-audit-file", audit_ref],
        ["receipt", "--pack-file", chain["refs"]["context_pack"], "--observation-file", chain["refs"]["agent_response"], "--comparison-file", chain["refs"]["comparison_receipt"], "--telemetry-file", telemetry_ref, "--evidence-file", refs_ref],
    )):
        output = tmp_path / f"audit-must-not-exist-{index}.json"
        assert probe.cli_main([*command, "--output", str(output)]) == 2
        assert not output.exists()
    assert {path: path.read_bytes() for path in before} == before


def test_v2_separate_audit_read_chronology_is_source_to_fact_not_probe_admission(chain, tmp_path):
    obs, fact, fact_ref, audit, audit_ref, comp, _, _ = _audit_fixture(chain, tmp_path)
    item = fact["live_reads"][0]
    read = probe.parse_strict_json(Path(item["evidence"]["ref"]).read_bytes())
    read_ref = str(tmp_path / "separate-auditor-live-read.json")
    fact["provenance"][0]["ref"] = read_ref
    for at, valid in (("2026-10-17T20:00:05Z", True), ("2026-10-17T19:59:59Z", False), ("2026-10-17T20:01:11Z", False)):
        read["observed_at"] = at
        _retain(Path(read_ref), read)
        item["evidence"] = v2._bound_ref(read_ref)
        _retain(Path(fact_ref), fact)
        audit["findings"][0]["evidence"] = v2._bound_ref(fact_ref)
        _retain(Path(audit_ref), audit)
        comp["fabrication_audit"] = v2._bound_ref(audit_ref)
        if valid:
            assert probe.compare_rehydrated_observation(chain["pack"], obs, fabrication_audit_ref=audit_ref)["field_results"]["fabricated_claims"]["status"] == "match"
            assert probe.normalize_comparison(comp) == comp
        else:
            with pytest.raises(probe.EpicRehydrationProbeError, match="admitted observation interval"):
                probe.normalize_comparison(comp)


def test_v2_checkpoint_audit_requires_exact_semantic_pointer(chain, tmp_path):
    obs, fact, fact_ref, audit, audit_ref, comp, telemetry, receipt = _audit_fixture(chain, tmp_path, "checkpoint_decision_delta")
    assert probe.normalize_probe_receipt(receipt) == receipt
    fact["provenance"][0]["ref"] = f"packet:{obs['probe_id']}#/source/receipt/gate_invariants"
    _retain(Path(fact_ref), fact)
    audit["findings"][0]["evidence"] = v2._bound_ref(fact_ref)
    _retain(Path(audit_ref), audit)
    comp["fabrication_audit"] = v2._bound_ref(audit_ref)
    _retain(Path(chain["refs"]["comparison_receipt"]), comp)
    receipt["comparison"] = v2._bound_ref(chain["refs"]["comparison_receipt"])
    for consumer in (lambda: probe.compare_rehydrated_observation(chain["pack"], obs, fabrication_audit_ref=audit_ref), lambda: probe.normalize_comparison(comp), lambda: probe.normalize_probe_receipt(receipt)):
        with pytest.raises(probe.EpicRehydrationProbeError, match="exact field-specific"):
            consumer()


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
