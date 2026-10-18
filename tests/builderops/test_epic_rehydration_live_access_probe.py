from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from app.builderops import epic_rehydration_probe as probe
from app.builderops import epic_rehydration_probe_v2 as v2
from app.builderops.epic_run_context_budget import evaluate_slice_boundary_context_budget

ROOT = Path("evidence/shadow_rehydration_3798_live_access_v2")
PROBE = ROOT / "probe-retry1"
RECEIPT = Path("evidence/shadow_rehydration_3798_live_access.v2.json")
PACKET = PROBE / "context-pack.json"
RESPONSE = PROBE / "agent-response.original.json"
TARGET = {"repository": "RasmusTho/agentic-pkm-mvp", "issue_number": 3798, "pr_number": 3803}
ORIGINALS = {
    "context-pack.json": ("83451b93a0c2b98de6fe70e6850c14fc984894fc8ecfb34a4d82c01671269cce", 30772),
    "agent-response.original.json": ("c9d709efbbf6bec564c89b57b9053f08906a303f229c244b7888cd0986289b54", 7230),
    "live-read-github.json": ("357a6024dd521224129f75dcbf69fe15b08cc00ce1db81e9c11cf67f459dbe82", 10365),
    "live-read-repository.json": ("0617f94800a512b18748a7c22cca633ec9909e94ebc266aed5fb8aeda471feb6", 424),
    "live-read-dispatcher.json": ("8a5a2bbcdd3d8b879f224c442c9b71a69442cbfb059fc5b8595d1a746799127b", 2660),
}


def _read(path: Path) -> dict:
    return probe.parse_strict_json(path.read_bytes())


def _require_observed_access(packet: dict, response: dict) -> dict:
    """Positive access proof is narrower than a replayable unavailable result."""
    probe.normalize_rehydrated_observation(response, context_pack=packet, context_pack_ref=str(PACKET))
    reads = {item["kind"]: v2._read_bound(item["evidence"]) for item in response["live_reads"]}
    assert set(reads) == {"github", "repository", "dispatcher"}
    for kind in ("github", "repository"):
        assert reads[kind]["availability"] == "observed", f"{kind} access was not observed"
        assert reads[kind]["target"] == TARGET
        assert reads[kind]["unavailable_reason"] == ""
    github = reads["github"]["payload"]
    assert github["issue"]["number"] == 3798
    assert github["issue"]["url"] == "https://github.com/RasmusTho/agentic-pkm-mvp/issues/3798"
    assert github["pr"]["number"] == 3803
    assert github["pr"]["url"] == "https://github.com/RasmusTho/agentic-pkm-mvp/pull/3803"
    assert github["review_threads"]["repository"] == TARGET["repository"]
    assert github["review_threads"]["pr_number"] == 3803
    assert github["review_threads"]["complete"] is True
    assert "statusCheckRollup" in github["pr"]  # Empty is legitimate, not a CI verdict.
    assert reads["repository"]["payload"]["remote"] == "origin"
    assert reads["repository"]["payload"]["ref"] == "refs/heads/main"
    return reads


def test_retained_live_access_probe_replays_complete_chain():
    receipt = _read(RECEIPT)
    assert probe.normalize_probe_receipt(receipt) == receipt
    standalone = subprocess.run(
        [sys.executable, "-c", "from pathlib import Path; from app.builderops.epic_rehydration_probe import parse_strict_json, normalize_probe_receipt; p=Path('evidence/shadow_rehydration_3798_live_access.v2.json'); value=parse_strict_json(p.read_bytes()); assert normalize_probe_receipt(value)==value; print('complete-chain accepted')"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, check=False,
    )
    assert standalone.returncode == 0, standalone.stderr
    assert standalone.stdout.strip() == "complete-chain accepted"
    packet, response = _read(PACKET), _read(RESPONSE)
    reads = _require_observed_access(packet, response)
    assert v2._bound_ref(str(PACKET)) == {"ref": str(PACKET), "sha256": "83451b93a0c2b98de6fe70e6850c14fc984894fc8ecfb34a4d82c01671269cce", "bytes_length": 30772}
    capture = _read(PROBE / "native-capture.json")
    expected_originals = {str(PACKET), str(RESPONSE), *(str(PROBE / f"live-read-{kind}.json") for kind in ("github", "repository", "dispatcher"))}
    assert {item["ref"] for item in capture["original_artifacts"]} == expected_originals
    for binding in capture["original_artifacts"]:
        assert v2._bound_ref(binding["ref"]) == binding
        assert (binding["sha256"], binding["bytes_length"]) == ORIGINALS[Path(binding["ref"]).name]
    assert reads["dispatcher"]["availability"] == "observed"
    source = _read(ROOT / "accepted/source-checkpoint.json")
    checkpoint, signals = source["checkpoint"], source["signals"]
    replayed = evaluate_slice_boundary_context_budget(
        slice_id=source["slice_id"], slice_status=checkpoint["slice_status"],
        decision_log_delta=checkpoint["decision_log_delta"], open_review_findings=checkpoint["open_review_findings"],
        external_state_marker=checkpoint["external_state"]["marker"],
        previous_external_state_marker=checkpoint["external_state"]["previous_marker"],
        context_measurement=source["measurements"]["context"], context_pressure=signals["context_pressure"],
        completed_slices_since_checkpoint=signals["completed_slices_since_checkpoint"], repairs=signals["repairs"],
        uncertainty=signals["uncertainty"], next_slice=source["next_slice"], policy=source["policy"],
        cost_inputs={}, accepted_slice_count=None,
    )
    assert replayed == source == packet["source"]["receipt"]
    assert _read(ROOT / "accepted/run-state-plan.json")["dry_run"] is True
    assert _read(ROOT / "accepted/run-state-accepted.json")["state"]["context_budget_receipts"] == [source]
    assert _read(ROOT / "accepted/run-state-readback.json")["context_budget_receipts"] == [source]
    assert _read(ROOT / "accepted/source-capture.json")["run_state_readback_equal"] is True
    assert all(not Path(ref).is_absolute() for ref in receipt["evidence"].values())
    comparison = _read(PROBE / "comparison.json")
    assert comparison["field_results"]["fabricated_claims"]["status"] == "unknown"
    assert comparison["field_results"]["live_slice_next_action"]["status"] == "not_comparable"
    assert set(comparison["field_results"]["external_state"]["dimensions"]) == set(v2.EXTERNAL["properties"])
    assert comparison["field_results"]["external_state"]["independent_live_value"]["repository_head"] == reads["repository"]["payload"]["head_sha"]
    assert not {"score", "threshold", "aggregate"} & comparison.keys()
    measurements = receipt["telemetry"]["measurements"]
    assert measurements["packet_bytes"]["value"] == len(PACKET.read_bytes())
    assert measurements["response_bytes"]["value"] == len(RESPONSE.read_bytes())
    assert measurements["agent_start"]["value"] == 1
    assert measurements["handoff"]["value"] == 2
    assert measurements["elapsed_wall_time"]["value"] == 177.0
    assert all(measurements[name]["value"] == 0 for name in ("admission_retry", "implementation_repair", "review_repair", "ci_repair"))
    assert response["agent"]["engine_identity"] == "unknown"
    assert all(measurements[name]["availability"] == "unknown" for name in v2.USAGE_UNITS)
    for value in (packet, comparison, _read(PROBE / "telemetry.json"), receipt):
        assert all(value["effects"][kind] == [] for kind in probe._EFFECT_CATEGORIES)


def test_failed_first_response_is_retained_and_still_refused(tmp_path):
    first = ROOT / "probe"
    packet = _read(first / "context-pack.json")
    response = _read(first / "agent-response.original.json")
    capture = _read(first / "native-capture.json")
    assert capture["response_semantic_admission"] == "refused"
    assert capture["comparison_exit_code"] == 2
    assert capture["elapsed_seconds"] == 193
    for binding in capture["original_artifacts"]:
        assert v2._bound_ref(binding["ref"]) == binding
    assert v2._bound_ref(str(first / "agent-response.original.json"))["sha256"] == "91dca02bb48594866e0b6488414ecfdb340d54fb1d00fc3f1b1f52a496f59cb4"
    with pytest.raises(probe.EpicRehydrationProbeError, match="agent reporting provenance must identify this probe"):
        probe.normalize_rehydrated_observation(response, context_pack=packet, context_pack_ref=str(first / "context-pack.json"))
    output = tmp_path / "must-not-be-created.json"
    assert probe.cli_main(["compare", "--pack-file", str(first / "context-pack.json"), "--observation-file", str(first / "agent-response.original.json"), "--output", str(output)]) == 2
    assert not output.exists()
    assert not (first / "comparison.json").exists()


@pytest.mark.parametrize("kind", ["github", "repository"])
@pytest.mark.parametrize("failure", ["missing", "unavailable", "foreign-target"])
def test_positive_live_access_proof_rejects_incomplete_or_foreign_reads(tmp_path, kind, failure):
    packet, response = _read(PACKET), deepcopy(_read(RESPONSE))
    item = next(item for item in response["live_reads"] if item["kind"] == kind)
    if failure == "missing":
        response["live_reads"].remove(item)
    else:
        envelope = v2._read_bound(item["evidence"])
        if failure == "unavailable":
            envelope.update(availability="unavailable", payload="unknown", unavailable_reason="retained negative access-proof test")
        else:
            envelope["target"]["issue_number"] = 3799
        path = tmp_path / f"{kind}-{failure}.json"
        path.write_bytes(probe.canonical_json_bytes(envelope) + b"\n")
        previous = item["evidence"]["ref"]
        item["evidence"] = v2._bound_ref(str(path))
        for field in response["fields"].values():
            for provenance in field["provenance"]:
                if provenance["ref"] == previous:
                    provenance["ref"] = str(path)
    with pytest.raises((AssertionError, probe.EpicRehydrationProbeError)):
        _require_observed_access(packet, response)
