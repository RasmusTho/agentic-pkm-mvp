from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from app.builderops.epic_rehydration_probe import (
    EpicRehydrationProbeError,
    build_context_pack,
    build_probe_receipt,
    canonical_json_bytes,
    compare_rehydrated_observation,
    normalize_context_pack,
    normalize_probe_receipt,
    normalize_rehydrated_observation,
    parse_strict_json,
)
from app.builderops.epic_run_context_budget import (
    evaluate_slice_boundary_context_budget,
)


def _source_receipt() -> dict[str, object]:
    return evaluate_slice_boundary_context_budget(
        slice_id="issue-3798",
        slice_status="merged",
        decision_log_delta=["retain advisory-only boundary"],
        open_review_findings=[],
        external_state_marker={
            "issue": "3798:closed",
            "pr": "3803:merged",
            "head_sha": "a" * 40,
            "merge_sha": "b" * 40,
            "observed_at": "2026-10-17T20:00:00Z",
            "ci": "green",
        },
        context_measurement={"value": "unknown", "unit": "tokens", "source": "not-recorded"},
        context_pressure="unknown",
        completed_slices_since_checkpoint=0,
        repairs={"implementation": 0, "ci": 0, "review": 0},
        uncertainty={"level": "medium", "reasons": ["manual observation"]},
        next_slice={"worker_isolated": True, "setup_cost_high": False, "merge_risk_low": True},
        policy={"schema_version": 1, "rotate_on_high_context_pressure": True, "thin_worker_when_isolated": True},
        cost_inputs={},
        accepted_slice_count=None,
    )


def _source_bytes() -> bytes:
    return Path("tests/builderops/fixtures/rehydration-source-checkpoint.json").read_bytes()


def _pack() -> dict[str, object]:
    source = _source_bytes()
    return build_context_pack(
        source,
        source_ref="tests/builderops/fixtures/rehydration-source-checkpoint.json",
        source_observed_at="2026-10-17T20:00:00Z",
        slice_id="issue-3798",
        repository="RasmusTho/agentic-pkm-mvp",
        issue_number=3798,
        pr_number=3803,
        verified_pr_head_sha="a" * 40,
        merge_sha="b" * 40,
        read_instructions=[
            "Read the packet only; do not use chat history or implementation reasoning.",
            "Read live GitHub Issue, PR, CI, repository head, and dispatcher evidence.",
            "Report provenance and unknown values; do not perform mutations or start work.",
        ],
    )


def _observation(pack: dict[str, object], *, unknown_external: bool = False) -> dict[str, object]:
    source = pack["source"]["receipt"]  # type: ignore[index]
    source_external = source["checkpoint"]["external_state"]  # type: ignore[index]
    fields = {
        "slice_status": {"value": source["checkpoint"]["slice_status"], "provenance": [{"kind": "github", "ref": "issue:#3798"}], "notes": []},  # type: ignore[index]
        "decisions_and_invariants": {"value": {"decisions": source["checkpoint"]["decision_log_delta"], "gate_invariants": source["gate_invariants"]}, "provenance": [{"kind": "repository", "ref": "pr:#3803"}], "notes": []},  # type: ignore[index]
        "open_review_findings": {"value": source["checkpoint"]["open_review_findings"], "provenance": [{"kind": "github", "ref": "pr:#3803/reviews"}], "notes": []},  # type: ignore[index]
        "external_state": {"value": "unknown" if unknown_external else source_external, "provenance": [{"kind": "dispatcher", "ref": "live:dispatcher"}], "notes": []},
        "recommended_next_action": {"value": {"recommendations": source["recommendations"], "reasons": source["recommendation_reasons"]}, "provenance": [{"kind": "repository", "ref": "live:main"}], "notes": []},  # type: ignore[index]
        "missing_claims": {"value": [], "provenance": [{"kind": "agent", "ref": "fresh:response"}], "notes": []},
        "fabricated_claims": {"value": [], "provenance": [{"kind": "agent", "ref": "fresh:response"}], "notes": []},
    }
    return {
        "schema_name": "epic_rehydrated_observation",
        "schema_version": 1,
        "probe_id": pack["probe_id"],
        "observed_at": "2026-10-17T20:01:00Z",
        "target": {key: pack["target"][key] for key in ("repository", "issue_number", "pr_number", "verified_pr_head_sha", "merge_sha")},  # type: ignore[index]
        "agent": {"model": "gpt-5.6-luna", "reasoning_effort": "xhigh", "start_status": "succeeded", "start_observed_at": "2026-10-17T20:00:30Z"},
        "fields": fields,
        "live_reads": [{"kind": "github", "ref": "live:#3798,#3803"}, {"kind": "repository", "ref": "live:origin/main"}, {"kind": "dispatcher", "ref": "live:status"}],
        "limitations": ["Token, cost, elapsed time, and human minutes were not measured."],
    }


def _receipt_fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, Path], dict[str, object], dict[str, object], dict[str, object]]:
    pack = _pack()
    observation = _observation(pack)
    comparison = compare_rehydrated_observation(pack, observation)
    refs = {
        "source_checkpoint": tmp_path / "source.json",
        "context_pack": tmp_path / "pack.json",
        "agent_response": tmp_path / "response.json",
        "comparison_receipt": tmp_path / "comparison.json",
    }
    refs["source_checkpoint"].write_bytes(_source_bytes())
    refs["context_pack"].write_bytes(canonical_json_bytes(pack))
    refs["agent_response"].write_bytes(canonical_json_bytes(observation))
    refs["comparison_receipt"].write_bytes(canonical_json_bytes(comparison))
    receipt = build_probe_receipt(
        pack,
        observation,
        comparison,
        evidence_refs={key: str(value) for key, value in refs.items()},
        telemetry={
            "probe_count": 1,
            "agent_starts": 1,
            "repairs": {"implementation": 0, "ci": 0, "review": 0},
            "handoffs": 2,
            "context_tokens": "unknown",
            "model_cost_usd": "unknown",
            "elapsed_minutes": "unknown",
            "human_minutes": "unknown",
        },
    )
    return receipt, refs, pack, observation, comparison


def test_context_pack_is_deterministic_and_source_bound() -> None:
    first = _pack()
    second = _pack()
    assert first == second
    assert first["source"]["bytes_sha256"] == __import__("hashlib").sha256(_source_bytes()).hexdigest()  # type: ignore[index]
    assert first["source"]["origin"] == "actual_live_evaluator_checkpoint"  # type: ignore[index]
    assert first["effects"] == {category: [] for category in ("dispatch", "leases", "ci", "review", "acceptance", "merge", "closure", "agent_start")}
    assert first["live_truth_precedence"][0] == "live_github_issue_pr_ci"  # type: ignore[index]


def test_strict_boundaries_reject_invalid_input() -> None:
    with pytest.raises(EpicRehydrationProbeError):
        parse_strict_json('{"schema_version":1,"schema_version":1}')
    with pytest.raises(EpicRehydrationProbeError):
        parse_strict_json('{"value":NaN}')
    malformed = deepcopy(_pack())
    malformed["schema_version"] = True
    with pytest.raises(EpicRehydrationProbeError):
        normalize_context_pack(malformed)
    malformed = deepcopy(_pack())
    malformed["unexpected"] = "reject"
    with pytest.raises(EpicRehydrationProbeError):
        normalize_context_pack(malformed)
    malformed = deepcopy(_pack())
    malformed["source"]["bytes_sha256"] = "0" * 64  # type: ignore[index]
    with pytest.raises(EpicRehydrationProbeError):
        normalize_context_pack(malformed)
    malformed = deepcopy(_pack())
    malformed["target"]["issue_number"] = 9999  # type: ignore[index]
    with pytest.raises(EpicRehydrationProbeError):
        normalize_context_pack(malformed)
    malformed = deepcopy(_pack())
    malformed["source"]["observed_at"] = "2099-01-01T00:00:00Z"  # type: ignore[index]
    with pytest.raises(EpicRehydrationProbeError):
        normalize_context_pack(malformed)
    live_pack = json.loads(Path("evidence/context-pack.json").read_text(encoding="utf-8"))
    live_pack["target"]["repository"] = "Unrelated/foreign-repository"
    with pytest.raises(EpicRehydrationProbeError):
        normalize_context_pack(live_pack)
    for foreign_source_ref in ("evidence/context-pack.json", "evidence/telemetry.json"):
        swapped_source_pack = json.loads(Path("evidence/context-pack.json").read_text(encoding="utf-8"))
        swapped_source_pack["source"]["source_ref"] = foreign_source_ref
        with pytest.raises(EpicRehydrationProbeError):
            normalize_context_pack(swapped_source_pack)
    unsupported_ref_pack = deepcopy(_pack())
    unsupported_ref_pack["source"]["source_ref"] = "live:github:#3798"  # type: ignore[index]
    with pytest.raises(EpicRehydrationProbeError):
        normalize_context_pack(unsupported_ref_pack)
    for invalid_source_ref in (
        "tests/builderops/fixtures/missing-source.json",
        "tests/builderops/fixtures/live-issue-3798.json",
        "tests/builderops/fixtures",
    ):
        invalid_source_pack = deepcopy(_pack())
        invalid_source_pack["source"]["source_ref"] = invalid_source_ref  # type: ignore[index]
        with pytest.raises(EpicRehydrationProbeError):
            normalize_context_pack(invalid_source_pack)
    malformed_observation = _observation(_pack())
    malformed_observation["fields"]["slice_status"]["value"] = {}  # type: ignore[index]
    with pytest.raises(EpicRehydrationProbeError):
        normalize_rehydrated_observation(malformed_observation, context_pack=_pack())
    malformed_observation = _observation(_pack())
    malformed_observation["fields"]["missing_claims"]["value"] = 42  # type: ignore[index]
    with pytest.raises(EpicRehydrationProbeError):
        normalize_rehydrated_observation(malformed_observation, context_pack=_pack())
    with pytest.raises(EpicRehydrationProbeError):
        build_context_pack(
            b"{}",
            source_ref="x",
            source_observed_at="now",
            slice_id="issue-3798",
            repository="RasmusTho/agentic-pkm-mvp",
            issue_number=3798,
            pr_number=3803,
            verified_pr_head_sha="a" * 40,
            merge_sha="b" * 40,
            read_instructions=["read"],
        )


def test_comparison_preserves_field_mismatches_and_unknowns() -> None:
    pack = _pack()
    observation = _observation(pack, unknown_external=True)
    comparison = compare_rehydrated_observation(pack, observation)
    assert comparison["field_results"]["slice_status"]["status"] == "match"  # type: ignore[index]
    assert comparison["field_results"]["external_state"]["status"] == "unknown"  # type: ignore[index]
    assert comparison["external_refresh"]["refresh_required"] is True  # type: ignore[index]
    changed = deepcopy(observation)
    changed["fields"]["slice_status"]["value"] = "invented"  # type: ignore[index]
    changed["fields"]["fabricated_claims"]["value"] = ["slice_status"]  # type: ignore[index]
    mismatch = compare_rehydrated_observation(pack, changed)
    assert mismatch["field_results"]["slice_status"]["status"] == "mismatch"  # type: ignore[index]
    assert mismatch["field_results"]["fabricated_claims"]["status"] == "unknown"  # type: ignore[index]
    assert "status" not in mismatch and "score" not in mismatch


def test_external_projection_never_fills_sparse_live_observations() -> None:
    pack = _pack()
    source_marker = pack["source"]["external_state_marker"]  # type: ignore[index]
    for sparse in (
        {},
        {"merge_sha": source_marker["merge_sha"]},  # type: ignore[index]
        {"origin_main": "a" * 40},
    ):
        observation = _observation(pack)
        observation["fields"]["external_state"]["value"] = sparse  # type: ignore[index]
        comparison = compare_rehydrated_observation(pack, observation)
        assert comparison["field_results"]["external_state"]["status"] == "unknown"  # type: ignore[index]
        assert comparison["external_refresh"]["refresh_required"] is True  # type: ignore[index]

    complete = _observation(pack)
    complete["fields"]["external_state"]["value"] = {  # type: ignore[index]
        "issue": "3798:closed",
        "pr": "3803:merged",
        "pr_head_sha": "a" * 40,
        "merge_sha": "b" * 40,
    }
    matched = compare_rehydrated_observation(pack, complete)
    assert matched["field_results"]["external_state"]["status"] == "match"  # type: ignore[index]

    drifted = deepcopy(complete)
    drifted["fields"]["external_state"]["value"]["merge_sha"] = "c" * 40  # type: ignore[index]
    drift = compare_rehydrated_observation(pack, drifted)
    assert drift["field_results"]["external_state"]["status"] == "mismatch"  # type: ignore[index]


def test_probe_receipt_preserves_telemetry_and_agent_provenance(tmp_path: Path) -> None:
    pack = _pack()
    observation = _observation(pack)
    comparison = compare_rehydrated_observation(pack, observation)
    refs = {
        "source_checkpoint": tmp_path / "source.json",
        "context_pack": tmp_path / "pack.json",
        "agent_response": tmp_path / "response.json",
        "comparison_receipt": tmp_path / "comparison.json",
    }
    refs["source_checkpoint"].write_bytes(_source_bytes())
    refs["context_pack"].write_bytes(canonical_json_bytes(pack))
    refs["agent_response"].write_bytes(canonical_json_bytes(observation))
    refs["comparison_receipt"].write_bytes(canonical_json_bytes(comparison))
    receipt = build_probe_receipt(
        pack,
        observation,
        comparison,
        evidence_refs={
            "source_checkpoint": str(refs["source_checkpoint"]),
            "context_pack": str(refs["context_pack"]),
            "agent_response": str(refs["agent_response"]),
            "comparison_receipt": str(refs["comparison_receipt"]),
        },
        telemetry={
            "probe_count": 1,
            "agent_starts": 1,
            "repairs": {"implementation": 0, "ci": 0, "review": 0},
            "handoffs": 0,
            "context_tokens": "unknown",
            "model_cost_usd": "unknown",
            "elapsed_minutes": "unknown",
            "human_minutes": "unknown",
        },
    )
    assert receipt["mode"] == "one_initial_read_only"
    assert receipt["agent"]["model"] == "gpt-5.6-luna"  # type: ignore[index]
    assert receipt["telemetry"]["human_minutes"] == "unknown"  # type: ignore[index]
    assert receipt["telemetry"]["agent_starts"] == 1  # type: ignore[index]
    assert all(value == [] for value in receipt["effects"].values())  # type: ignore[union-attr]
    with pytest.raises(EpicRehydrationProbeError):
        build_probe_receipt(
            pack,
            observation,
            comparison,
            evidence_refs={
                "source_checkpoint": str(refs["source_checkpoint"]),
                "context_pack": str(refs["context_pack"]),
                "agent_response": str(refs["agent_response"]),
                "comparison_receipt": str(refs["comparison_receipt"]),
            },
            telemetry={
                "probe_count": 1,
                "agent_starts": 1,
                "repairs": {"implementation": 0, "ci": 0, "review": 0},
                "handoffs": 0,
                "context_tokens": "unknown",
                "model_cost_usd": "unknown",
                "elapsed_minutes": "unknown",
                "human_minutes": "unknown",
            },
            source_observed_at="2026-10-18T20:00:00Z",
        )


def test_probe_receipt_binds_retained_evidence_bytes(tmp_path: Path) -> None:
    pack = _pack()
    observation = _observation(pack)
    comparison = compare_rehydrated_observation(pack, observation)
    refs = {
        "source_checkpoint": tmp_path / "source.json",
        "context_pack": tmp_path / "pack.json",
        "agent_response": tmp_path / "response.json",
        "comparison_receipt": tmp_path / "comparison.json",
    }
    refs["source_checkpoint"].write_bytes(_source_bytes())
    refs["context_pack"].write_bytes(canonical_json_bytes(pack) + b"\n")
    refs["agent_response"].write_bytes(canonical_json_bytes(observation) + b"\n")
    refs["comparison_receipt"].write_bytes(canonical_json_bytes(comparison) + b"\n")
    receipt = build_probe_receipt(
        pack,
        observation,
        comparison,
        evidence_refs={key: str(value) for key, value in refs.items()},
        telemetry={
            "probe_count": 1,
            "agent_starts": 1,
            "repairs": {"implementation": 0, "ci": 0, "review": 0},
            "handoffs": 0,
            "context_tokens": "unknown",
            "model_cost_usd": "unknown",
            "elapsed_minutes": "unknown",
            "human_minutes": "unknown",
        },
    )
    import hashlib

    assert receipt["context_pack"]["sha256"] == hashlib.sha256(refs["context_pack"].read_bytes()).hexdigest()  # type: ignore[index]
    refs["context_pack"].write_bytes(b"tampered")
    with pytest.raises(EpicRehydrationProbeError):
        normalize_probe_receipt(receipt)


def test_standalone_receipt_reconstructs_and_cross_binds_retained_chain(tmp_path: Path) -> None:
    receipt, refs, pack, observation, comparison = _receipt_fixture(tmp_path)
    assert normalize_probe_receipt(receipt) == receipt

    mutations = {
        "target": lambda item: item["target"].__setitem__("repository", "foreign/repo"),
        "source": lambda item: item["source_checkpoint"].__setitem__("source_ref", "missing.json"),
        "agent": lambda item: item["agent"].__setitem__("model", "foreign-model"),
        "probe": lambda item: item.__setitem__("probe_id", "foreign-probe"),
        "limitations": lambda item: item["limitations"].append("unrecorded limitation"),
    }
    for name, mutate in mutations.items():
        mutated = deepcopy(receipt)
        mutate(mutated)
        with pytest.raises(EpicRehydrationProbeError, match="bound|context-pack|observation"):
            normalize_probe_receipt(mutated)

    wrong_pack = deepcopy(pack)
    wrong_pack["source"]["source_ref"] = str(tmp_path / "missing-source.json")  # type: ignore[index]
    wrong_pack_path = tmp_path / "wrong-pack.json"
    wrong_pack_bytes = canonical_json_bytes(wrong_pack)
    wrong_pack_path.write_bytes(wrong_pack_bytes)
    wrong_pack_receipt = deepcopy(receipt)
    wrong_pack_receipt["context_pack"] = {  # type: ignore[index]
        "ref": str(wrong_pack_path),
        "sha256": hashlib.sha256(wrong_pack_bytes).hexdigest(),
    }
    wrong_pack_receipt["evidence"]["context_pack"] = str(wrong_pack_path)  # type: ignore[index]
    with pytest.raises(EpicRehydrationProbeError):
        normalize_probe_receipt(wrong_pack_receipt)

    changed_observation = deepcopy(observation)
    changed_observation["fields"]["slice_status"]["value"] = "changed"  # type: ignore[index]
    changed_observation_path = tmp_path / "changed-observation.json"
    changed_observation_bytes = canonical_json_bytes(changed_observation)
    changed_observation_path.write_bytes(changed_observation_bytes)
    stale_comparison_receipt = deepcopy(receipt)
    stale_comparison_receipt["observation"] = {  # type: ignore[index]
        "ref": str(changed_observation_path),
        "sha256": hashlib.sha256(changed_observation_bytes).hexdigest(),
    }
    stale_comparison_receipt["evidence"]["agent_response"] = str(changed_observation_path)  # type: ignore[index]
    with pytest.raises(EpicRehydrationProbeError):
        normalize_probe_receipt(stale_comparison_receipt)

    changed_comparison = deepcopy(comparison)
    changed_comparison["external_refresh"]["refresh_required"] = True  # type: ignore[index]
    changed_comparison_path = tmp_path / "changed-comparison.json"
    changed_comparison_bytes = canonical_json_bytes(changed_comparison)
    changed_comparison_path.write_bytes(changed_comparison_bytes)
    stale_comparison = deepcopy(receipt)
    stale_comparison["comparison"] = {  # type: ignore[index]
        "ref": str(changed_comparison_path),
        "sha256": hashlib.sha256(changed_comparison_bytes).hexdigest(),
    }
    stale_comparison["evidence"]["comparison_receipt"] = str(changed_comparison_path)  # type: ignore[index]
    with pytest.raises(EpicRehydrationProbeError):
        normalize_probe_receipt(stale_comparison)

    malformed_observation_path = tmp_path / "malformed-observation.json"
    malformed_observation_bytes = canonical_json_bytes({"unexpected": "object"})
    malformed_observation_path.write_bytes(malformed_observation_bytes)
    malformed_receipt = deepcopy(receipt)
    malformed_receipt["observation"] = {  # type: ignore[index]
        "ref": str(malformed_observation_path),
        "sha256": hashlib.sha256(malformed_observation_bytes).hexdigest(),
    }
    malformed_receipt["evidence"]["agent_response"] = str(malformed_observation_path)  # type: ignore[index]
    with pytest.raises(EpicRehydrationProbeError):
        normalize_probe_receipt(malformed_receipt)

    source_copy = tmp_path / "source-copy.json"
    source_copy.write_bytes(refs["source_checkpoint"].read_bytes())
    copied_source_receipt = deepcopy(receipt)
    copied_source_receipt["evidence"]["source_checkpoint"] = str(source_copy)  # type: ignore[index]
    assert normalize_probe_receipt(copied_source_receipt) == copied_source_receipt


def test_manual_probe_has_no_authority_effects(tmp_path: Path) -> None:
    module = Path(__file__).parents[2] / "app" / "builderops" / "epic_rehydration_probe.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imported_modules = {node.module for node in imports}
    assert not any(module_name and ("dispatcher" in module_name or "github" in module_name) for module_name in imported_modules)
    output = tmp_path / "help.txt"
    result = subprocess.run(
        [sys.executable, "-m", "app.builderops.epic_rehydration_probe", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "observer-only" in result.stdout
    assert not output.exists()

    pack_path = tmp_path / "pack.json"
    observation_path = tmp_path / "observation.json"
    pack_path.write_bytes(canonical_json_bytes(_pack()))
    observation_path.write_bytes(canonical_json_bytes(_observation(_pack())))
    before = pack_path.read_bytes()
    aliased = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.builderops.epic_rehydration_probe",
            "compare",
            "--pack-file",
            str(pack_path),
            "--observation-file",
            str(observation_path),
            "--output",
            str(pack_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert aliased.returncode == 2
    assert pack_path.read_bytes() == before

    existing_output = tmp_path / "existing-output.json"
    existing_output.write_bytes(b"sentinel")
    refused_existing = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.builderops.epic_rehydration_probe",
            "compare",
            "--pack-file",
            str(pack_path),
            "--observation-file",
            str(observation_path),
            "--output",
            str(existing_output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused_existing.returncode == 2
    assert existing_output.read_bytes() == b"sentinel"

    build_existing = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.builderops.epic_rehydration_probe",
            "build-pack",
            "--source-file",
            "tests/builderops/fixtures/rehydration-source-checkpoint.json",
            "--output",
            str(existing_output),
            "--source-ref",
            "tests/builderops/fixtures/rehydration-source-checkpoint.json",
            "--source-observed-at",
            "2026-10-17T20:00:00Z",
            "--slice-id",
            "issue-3798",
            "--repository",
            "RasmusTho/agentic-pkm-mvp",
            "--issue-number",
            "3798",
            "--pr-number",
            "3803",
            "--verified-pr-head-sha",
            "a" * 40,
            "--merge-sha",
            "b" * 40,
            "--read-instruction",
            "Read only.",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert build_existing.returncode == 2
    assert existing_output.read_bytes() == b"sentinel"

    distinct_output = tmp_path / "new-comparison.json"
    created = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.builderops.epic_rehydration_probe",
            "compare",
            "--pack-file",
            str(pack_path),
            "--observation-file",
            str(observation_path),
            "--output",
            str(distinct_output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0
    assert distinct_output.is_file()

    compare_source_before = Path(_pack()["source"]["source_ref"]).read_bytes()  # type: ignore[index]
    compare_transitive_alias = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.builderops.epic_rehydration_probe",
            "compare",
            "--pack-file",
            str(pack_path),
            "--observation-file",
            str(observation_path),
            "--output",
            str(Path(_pack()["source"]["source_ref"])),  # type: ignore[index]
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compare_transitive_alias.returncode == 2
    assert Path(_pack()["source"]["source_ref"]).read_bytes() == compare_source_before  # type: ignore[index]

    comparison_path = tmp_path / "comparison.json"
    comparison_path.write_bytes(
        canonical_json_bytes(compare_rehydrated_observation(_pack(), _observation(_pack())))
    )
    telemetry_path = tmp_path / "telemetry.json"
    telemetry_path.write_bytes(
        canonical_json_bytes(
            {
                "probe_count": 1,
                "agent_starts": 1,
                "repairs": {"implementation": 0, "ci": 0, "review": 0},
                "handoffs": 0,
                "context_tokens": "unknown",
                "model_cost_usd": "unknown",
                "elapsed_minutes": "unknown",
                "human_minutes": "unknown",
            }
        )
    )
    source_path = tmp_path / "source.json"
    source_path.write_bytes(_source_bytes())
    refs_path = tmp_path / "refs.json"
    refs_path.write_bytes(
        canonical_json_bytes(
            {
                "source_checkpoint": str(source_path),
                "context_pack": str(pack_path),
                "agent_response": str(observation_path),
                "comparison_receipt": str(comparison_path),
            }
        )
    )
    source_before = source_path.read_bytes()
    transitive_alias = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.builderops.epic_rehydration_probe",
            "receipt",
            "--pack-file",
            str(pack_path),
            "--observation-file",
            str(observation_path),
            "--comparison-file",
            str(comparison_path),
            "--telemetry-file",
            str(telemetry_path),
            "--evidence-file",
            str(refs_path),
            "--output",
            str(source_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert transitive_alias.returncode == 2
    assert source_path.read_bytes() == source_before
