from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest
from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.contracts import CkmContractError, ErrorEnvelope
from app.builderops.ckm.metrics import METRIC_REGISTRY, MetricRetentionStore, build_observation, metric_definition
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.ckm.store import CkmStore


def _result(tmp_path: Path):
    store = CkmStore(tmp_path / "ckm.sqlite")
    store.ensure_schema()
    store.upsert_capability(identity_key="confirmed", name="Confirmed", definition="x", lifecycle="confirmed", existence_provenance="fixture")
    store.upsert_capability(identity_key="candidate", name="Candidate", definition="x", lifecycle="candidate", existence_provenance="fixture")
    payload = CkmQueryService(store.db_path).list_capabilities()
    assert not isinstance(payload, ErrorEnvelope)
    return payload


def test_metric_definitions_are_versioned_and_warn_against_gating() -> None:
    assert len(METRIC_REGISTRY) <= 6
    for definition in METRIC_REGISTRY.values():
        assert definition["id"] and definition["semantic_version"] and definition["definition_digest"]
        assert definition["purpose"] and definition["approval_owner"] and definition["formula"]
        assert definition["intended_uses"] and definition["prohibited_uses"] and definition["limitations"]
        assert definition["eligible_population"]["denominator"] and definition["output_schema"]["value_state"]
        assert definition["not_for_gating"] is True and definition["goodhart_warnings"]


def test_observation_binds_complete_semantic_bundle(tmp_path: Path) -> None:
    observation = build_observation(_result(tmp_path), generated_at="2026-07-21T00:00:00Z")
    assert observation["snapshot"]["snapshot_digest"] and observation["query"]["digest"]
    assert observation["bindings"].keys() == {"schema", "taxonomy_digest", "formula_digest", "detector_digest", "configuration_digest", "watermark_digest", "provenance_digest"}
    assert observation["metric_definition"]["definition_digest"] and observation["generated_at"]


def test_explicit_retention_runs_outside_read_path_and_binds_source_sample(tmp_path: Path, monkeypatch) -> None:
    result = _result(tmp_path)
    retained = MetricRetentionStore(tmp_path / "metrics.sqlite")
    monkeypatch.setattr(CkmQueryService, "list_capabilities", lambda *_: (_ for _ in ()).throw(AssertionError("retain must not query")))
    sample = retained.retain(result, finding_evaluations={"finding": "bound"}, retained_at="2026-07-21T00:00:00Z")
    replay = retained.replay(sample.sample_id)
    assert replay["snapshot"]["watermarks"] == result.to_dict()["snapshot"]["watermarks"]


def test_retention_identity_binds_finding_evaluations_and_is_idempotent(tmp_path: Path) -> None:
    retained = MetricRetentionStore(tmp_path / "metrics.sqlite")
    result = _result(tmp_path)
    first = retained.retain(result, finding_evaluations={"finding": "first"}, retained_at="2026-07-21T00:00:00Z")
    identical = retained.retain(result, finding_evaluations={"finding": "first"}, retained_at="2026-07-21T00:00:00Z")
    changed = retained.retain(result, finding_evaluations={"finding": "changed"}, retained_at="2026-07-21T00:00:00Z")
    assert identical.sample_id == first.sample_id
    assert changed.sample_id != first.sample_id
    assert retained.storage_usage()["count"] == 2
    with sqlite3.connect(retained.path) as conn:
        evaluations = dict(
            conn.execute(
                "SELECT sample_id, finding_evaluations_json FROM ckm_metric_sample_v1"
            ).fetchall()
        )
    assert evaluations[first.sample_id] == '{"finding":"first"}'
    assert evaluations[changed.sample_id] == '{"finding":"changed"}'


def test_replay_refuses_tampered_retained_source(tmp_path: Path) -> None:
    retained = MetricRetentionStore(tmp_path / "metrics.sqlite")
    sample = retained.retain(_result(tmp_path), retained_at="2026-07-21T00:00:00Z")
    with sqlite3.connect(retained.path) as conn:
        conn.execute(
            "UPDATE ckm_metric_sample_v1 SET source_payload = ? WHERE sample_id = ?",
            (b'{"tampered":true}', sample.sample_id),
        )
    with pytest.raises(CkmContractError) as exc:
        retained.replay(sample.sample_id)
    assert exc.value.code == "tampered_retained_source"


@pytest.mark.parametrize(
    ("tampered_payload", "storage_type"),
    (("tampered-text", "text"), (42, "integer"), (3.14, "real")),
)
def test_replay_refuses_unsupported_sqlite_payload_storage_classes(
    tmp_path: Path, tampered_payload: object, storage_type: str
) -> None:
    retained = MetricRetentionStore(tmp_path / f"metrics-{storage_type}.sqlite")
    sample = retained.retain(_result(tmp_path), retained_at="2026-07-21T00:00:00Z")
    with sqlite3.connect(retained.path) as conn:
        conn.execute(
            "UPDATE ckm_metric_sample_v1 SET source_payload = ? WHERE sample_id = ?",
            (tampered_payload, sample.sample_id),
        )
    with pytest.raises(CkmContractError) as exc:
        retained.replay(sample.sample_id)
    assert exc.value.code == "tampered_retained_source"
    assert exc.value.details["storage_type"] == storage_type


def test_retained_samples_apply_storage_accounting_and_pruning_policy(tmp_path: Path) -> None:
    retained = MetricRetentionStore(tmp_path / "metrics.sqlite")
    sample = retained.retain(_result(tmp_path), retained_at="2026-01-01T00:00:00Z")
    assert retained.retain(_result(tmp_path), retained_at="2026-01-01T00:00:00Z").sample_id == sample.sample_id
    assert retained.storage_usage()["count"] == 1 and retained.storage_usage()["bytes"] > 0
    assert retained.preview_prune(now="2026-12-31T23:59:59Z") == []
    assert retained.preview_prune(now="2027-01-01T00:00:00Z") == [{"sample_id": sample.sample_id, "reason": "retention_expired"}]
    assert retained.preview_prune(now="2026-01-02T00:00:00Z", earlier_than_365_days=True) == [{"sample_id": sample.sample_id, "reason": "explicit_operator_prune_preview"}]


def test_retained_sample_correction_and_deletion_preserve_lifecycle_truth(tmp_path: Path) -> None:
    retained = MetricRetentionStore(tmp_path / "metrics.sqlite")
    first = retained.retain(_result(tmp_path), retained_at="2026-07-21T00:00:00Z")
    corrected = retained.correct(first.sample_id, _result(tmp_path), retained_at="2026-07-22T00:00:00Z")
    assert corrected.observation_id == first.observation_id
    with pytest.raises(CkmContractError, match="preview"):
        retained.prune([corrected.sample_id], reason="operator_deleted", at="2026-07-23T00:00:00Z")
    retained.prune([corrected.sample_id], reason="operator_deleted", at="2026-07-23T00:00:00Z", previewed_sample_ids=[corrected.sample_id])
    with pytest.raises(CkmContractError, match="unavailable") as exc:
        retained.replay(corrected.sample_id)
    assert exc.value.code == "source_unavailable"


def test_observation_is_deterministic_for_same_snapshot_and_definition(tmp_path: Path) -> None:
    result = _result(tmp_path)
    first = build_observation(result, generated_at="2026-07-21T00:00:00Z")
    second = build_observation(result, generated_at="2026-07-22T00:00:00Z")
    assert first["semantic_digest"] == second["semantic_digest"]
    assert first["observation_id"] == second["observation_id"]


def test_metric_value_states_and_candidate_separation(tmp_path: Path) -> None:
    observation = build_observation(_result(tmp_path))
    assert observation["vector"]["confirmed_population"] == {"state": "measured", "value": 1}
    assert observation["vector"]["candidate_population"] == {"state": "measured", "value": 1}
    assert set(observation["distributions"]["confirmed"]) == {"measured", "missing", "unassessed", "unsupported"}
    assert observation["composition"]["confirmed_public_ids"] != observation["composition"]["candidate_public_ids"]


def test_metric_registry_bounds_advisory_aggregate_without_scalar_authority(tmp_path: Path) -> None:
    observation = build_observation(_result(tmp_path))
    assert observation["aggregate"] == {"label": "human_advisory_only", "value": None, "sole_input_prohibited": True, "machine_authority_prohibited": True}
    for field in ("vector", "distributions", "composition", "citations", "freshness", "confidence", "limitations", "goodhart_warnings"):
        assert observation[field]
    assert "ranking" in observation["metric_definition"]["prohibited_uses"]


def test_metric_version_and_semantics_mismatch_refuse(tmp_path: Path) -> None:
    with pytest.raises(CkmContractError) as unknown:
        metric_definition("unknown")
    assert unknown.value.code == "unknown_metric_definition"
    with pytest.raises(CkmContractError) as version:
        metric_definition("capability_population", "2.0.0")
    assert version.value.code == "unsupported_metric_version"
    store = CkmStore(tmp_path / "empty.sqlite")
    store.ensure_schema()
    result = CkmQueryService(store.db_path).get_capability("missing")
    assert isinstance(result, ErrorEnvelope)
    with pytest.raises(CkmContractError) as semantics:
        build_observation(result)  # type: ignore[arg-type]
    assert semantics.value.code == "unsupported_metric_semantics"


def test_cli_measure_retains_only_after_public_query_result(tmp_path: Path) -> None:
    _result(tmp_path)
    runner = CliRunner()
    invocation = runner.invoke(builderops, ["--db-path", str(tmp_path / "ckm.sqlite"), "ckm", "measure", "--retain"])
    assert invocation.exit_code == 0, invocation.output
    assert "human_advisory_only" in invocation.output
    assert (tmp_path / "ckm-metric-samples.sqlite").exists()
