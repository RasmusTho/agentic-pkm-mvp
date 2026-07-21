from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pytest

from app.builderops.ckm.comparison import _component_delta, compare_retained_observations
from app.builderops.ckm.contracts import CkmContractError
from app.builderops.ckm.metrics import MetricRetentionStore
from tests.builderops.ckm.test_metrics import _result


def _samples(path: Path):
    store = MetricRetentionStore(path / "retained.sqlite")
    return store, [store.retain(_result(path / str(n), watermark=f"commit:{n}"), retained_at=f"2026-07-2{n}T00:00:00Z") for n in (1, 2)]

def test_compatibility_binds_every_semantics_bearing_field(tmp_path: Path) -> None:
    store, samples = _samples(tmp_path)
    result = compare_retained_observations(store, [item.sample_id for item in samples])
    assert {"metric.id", "formula_digest", "detector_digest", "configuration_digest", "schema.envelope", "schema.resource", "taxonomy_digest", "canonical_query_digest", "value_state_schema", "candidate_confirmed_policy", "identity_policy_version", "access_policy_version", "redaction_policy_version"} <= set(result["compatibility"]["bindings"])

def test_compatible_observations_produce_deterministic_bound_delta(tmp_path: Path) -> None:
    store, samples = _samples(tmp_path)
    first = compare_retained_observations(store, [item.sample_id for item in samples])
    assert first == compare_retained_observations(store, [item.sample_id for item in samples])
    assert first["inputs"] and first["components"] and first["provenance"] and first["freshness"] and first["limitations"]

def test_semantic_mismatch_refuses_without_partial_comparison(tmp_path: Path) -> None:
    store = MetricRetentionStore(tmp_path / "retained.sqlite")
    samples = [
        store.retain(_result(tmp_path / "one"), retained_at="2026-07-21T00:00:00Z"),
        store.retain(_result(tmp_path / "two"), metric_id="provenance_coverage", retained_at="2026-07-22T00:00:00Z"),
    ]
    with pytest.raises(CkmContractError, match="incompatible") as exc:
        compare_retained_observations(store, [item.sample_id for item in samples])
    assert "metric.id" in exc.value.details["mismatched_fields"]

@pytest.mark.parametrize("mutation", ["DELETE FROM ckm_metric_sample_v1 WHERE sample_id = ?", "UPDATE ckm_metric_sample_v1 SET source_payload = NULL WHERE sample_id = ?", "UPDATE ckm_metric_sample_v1 SET source_payload = x'7B7D' WHERE sample_id = ?", "UPDATE ckm_metric_sample_v1 SET policy_version = 'missing' WHERE sample_id = ?", "UPDATE ckm_metric_sample_v1 SET expires_at = '2000-01-01T00:00:00Z' WHERE sample_id = ?"])
def test_unavailable_or_tampered_retained_source_refuses_comparison(tmp_path: Path, mutation: str) -> None:
    store, samples = _samples(tmp_path)
    with sqlite3.connect(store.path) as conn: conn.execute(mutation, (samples[1].sample_id,))
    with pytest.raises(CkmContractError): compare_retained_observations(store, [item.sample_id for item in samples])

def test_value_state_transitions_are_not_coerced_to_numbers(tmp_path: Path) -> None:
    assert _component_delta([{"state": "measured", "value": 0}, {"state": "missing", "reason": "absent"}]) is None
    assert _component_delta([{"state": "unassessed", "reason": "unknown"}, {"state": "unsupported", "reason": "not supported"}]) is None

def test_comparison_bounds_advisory_aggregate_without_authority(tmp_path: Path) -> None:
    store, samples = _samples(tmp_path); aggregate = compare_retained_observations(store, [item.sample_id for item in samples])["aggregate"]
    assert aggregate["label"] == "human_advisory_only" and aggregate["sole_input_prohibited"] and aggregate["co_present_components"]

def test_comparison_disclaims_trend_and_cadence_claims(tmp_path: Path) -> None:
    store, samples = _samples(tmp_path); limitations = " ".join(compare_retained_observations(store, [item.sample_id for item in samples])["limitations"])
    assert "trend" in limitations and "cadence" in limitations

def test_comparison_read_path_never_creates_or_mutates_retention_storage(tmp_path: Path) -> None:
    missing = MetricRetentionStore(tmp_path / "missing" / "retained.sqlite")
    with pytest.raises(CkmContractError) as exc:
        compare_retained_observations(missing, ["one", "two"])
    assert exc.value.code == "source_unavailable"
    assert not missing.path.parent.exists()
    incomplete = tmp_path / "incomplete.sqlite"
    with sqlite3.connect(incomplete) as conn:
        conn.execute("CREATE TABLE unrelated (id TEXT)")
    before = incomplete.read_bytes()
    with pytest.raises(CkmContractError) as exc:
        compare_retained_observations(MetricRetentionStore(incomplete), ["one", "two"])
    assert exc.value.code == "source_unavailable"
    assert incomplete.read_bytes() == before
    store, samples = _samples(tmp_path / "valid")
    before_bytes = store.path.read_bytes()
    before_stat = store.path.stat()
    before_entries = {item.name for item in store.path.parent.iterdir()}
    compare_retained_observations(store, [item.sample_id for item in samples])
    after_stat = store.path.stat()
    assert store.path.read_bytes() == before_bytes
    assert after_stat.st_mtime_ns == before_stat.st_mtime_ns
    assert after_stat.st_size == before_stat.st_size
    assert {item.name for item in store.path.parent.iterdir()} == before_entries

def test_forged_observation_source_binding_refuses_before_comparison(tmp_path: Path) -> None:
    store, samples = _samples(tmp_path)
    with sqlite3.connect(store.path) as conn:
        raw = conn.execute("SELECT observation_json FROM ckm_metric_sample_v1 WHERE sample_id = ?", (samples[1].sample_id,)).fetchone()[0]
        forged = json.loads(raw)
        forged["snapshot"]["snapshot_digest"] = "forged"
        conn.execute("UPDATE ckm_metric_sample_v1 SET observation_json = ? WHERE sample_id = ?", (json.dumps(forged, sort_keys=True, separators=(",", ":")), samples[1].sample_id))
    with pytest.raises(CkmContractError) as exc:
        compare_retained_observations(store, [item.sample_id for item in samples])
    assert exc.value.code == "observation_source_mismatch"
