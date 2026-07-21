from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.contracts import (
    ACCESS_POLICY_VERSION,
    ENVELOPE_SCHEMA_VERSION,
    RESOURCE_SCHEMA_VERSION,
    CkmContractError,
    ErrorEnvelope,
    canonical_digest,
)
from app.builderops.ckm.metrics import METRIC_REGISTRY, MetricRetentionStore, build_observation, metric_definition
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.ckm.schema import CKM_SCHEMA_VERSION
from app.builderops.ckm.store import CkmStore


def _result(tmp_path: Path, *, watermark: str = "commit:fixture"):
    store = CkmStore(tmp_path / "ckm.sqlite")
    store.ensure_schema()
    store.upsert_capability(identity_key="confirmed", name="Confirmed", definition="x", lifecycle="confirmed", existence_provenance="fixture")
    store.upsert_capability(identity_key="candidate", name="Candidate", definition="x", lifecycle="candidate", existence_provenance="fixture")
    store.set_watermark("repo", watermark)
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


def test_storage_usage_and_byte_cap_use_exact_utf8_bytes(tmp_path: Path) -> None:
    retained = MetricRetentionStore(tmp_path / "utf8-accounting.sqlite")
    sample = retained.retain(
        _result(tmp_path, watermark="commit:åäö🚀"),
        finding_evaluations={"finding": "åäö🚀"},
        retained_at="2026-01-01T00:00:00Z",
    )
    with sqlite3.connect(retained.path) as conn:
        source, observation, digest, watermarks, evaluations = conn.execute(
            "SELECT source_payload, observation_json, source_digest, watermarks_json, finding_evaluations_json FROM ckm_metric_sample_v1 WHERE sample_id = ?",
            (sample.sample_id,),
        ).fetchone()
    expected_bytes = len(source) + sum(
        len(value.encode("utf-8"))
        for value in (observation, digest, watermarks, evaluations)
    )
    assert retained.storage_usage() == {"count": 1, "bytes": expected_bytes}
    assert retained.preview_prune(
        now="2026-01-02T00:00:00Z", max_bytes=expected_bytes
    ) == []
    assert retained.preview_prune(
        now="2026-01-02T00:00:00Z", max_bytes=expected_bytes - 1
    ) == [{"sample_id": sample.sample_id, "reason": "storage_byte_cap"}]


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


def test_correction_preserves_non_default_metric_definition_and_refuses_mismatch(
    tmp_path: Path,
) -> None:
    retained = MetricRetentionStore(tmp_path / "metric-correction.sqlite")
    result = _result(tmp_path)
    original = retained.retain(
        result,
        metric_id="provenance_coverage",
        retained_at="2026-01-01T00:00:00Z",
    )
    corrected = retained.correct(
        original.sample_id,
        result,
        metric_id="provenance_coverage",
        semantic_version="1.0.0",
        retained_at="2026-01-02T00:00:00Z",
    )
    with sqlite3.connect(retained.path) as conn:
        rows = conn.execute(
            "SELECT sample_id, lifecycle, observation_json FROM ckm_metric_sample_v1 WHERE sample_id IN (?, ?) ORDER BY sample_id",
            (original.sample_id, corrected.sample_id),
        ).fetchall()
    observations = {sample_id: json.loads(payload) for sample_id, _, payload in rows}
    lifecycles = {sample_id: lifecycle for sample_id, lifecycle, _ in rows}
    assert lifecycles[original.sample_id] == "superseded"
    assert observations[original.sample_id]["metric_definition"] == observations[corrected.sample_id]["metric_definition"]
    for digest in ("formula_digest", "detector_digest", "configuration_digest"):
        assert observations[original.sample_id]["bindings"][digest] == observations[corrected.sample_id]["bindings"][digest]
    assert observations[corrected.sample_id]["metric_definition"]["id"] == "provenance_coverage"

    mismatch = retained.retain(
        result,
        metric_id="provenance_coverage",
        retained_at="2026-02-01T00:00:00Z",
    )
    usage_before_mismatch = retained.storage_usage()
    with pytest.raises(CkmContractError) as exc:
        retained.correct(
            mismatch.sample_id,
            result,
            metric_id="capability_population",
            retained_at="2026-02-02T00:00:00Z",
        )
    assert exc.value.code == "metric_definition_mismatch"
    assert retained.storage_usage() == usage_before_mismatch
    with sqlite3.connect(retained.path) as conn:
        assert conn.execute(
            "SELECT lifecycle FROM ckm_metric_sample_v1 WHERE sample_id = ?",
            (mismatch.sample_id,),
        ).fetchone()[0] == "retained"


def test_correction_refuses_corrupt_persisted_metric_definition(tmp_path: Path) -> None:
    retained = MetricRetentionStore(tmp_path / "corrupt-metric-correction.sqlite")
    result = _result(tmp_path)
    original = retained.retain(
        result,
        metric_id="provenance_coverage",
        retained_at="2026-01-01T00:00:00Z",
    )
    with sqlite3.connect(retained.path) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT observation_json FROM ckm_metric_sample_v1 WHERE sample_id = ?",
                (original.sample_id,),
            ).fetchone()[0]
        )
        payload["metric_definition"]["definition_digest"] = "tampered"
        conn.execute(
            "UPDATE ckm_metric_sample_v1 SET observation_json = ? WHERE sample_id = ?",
            (json.dumps(payload), original.sample_id),
        )
    with pytest.raises(CkmContractError) as exc:
        retained.correct(
            original.sample_id, result, retained_at="2026-01-02T00:00:00Z"
        )
    assert exc.value.code == "corrupt_retained_observation"
    assert retained.storage_usage()["count"] == 1


@pytest.mark.parametrize(
    ("path", "tampered_value"),
    (
        (("bindings", "watermark_digest"), "tampered"),
        (("bindings", "taxonomy_digest"), "tampered"),
        (("bindings", "provenance_digest"), "tampered"),
        (("bindings", "schema"), {"ckm": 999}),
        (("snapshot", "snapshot_digest"), "tampered"),
        (("query", "digest"), "tampered"),
        (("semantic_digest",), "tampered"),
        (("observation_id",), "ckm_observation_tampered"),
    ),
)
def test_correction_refuses_corrupt_semantic_identity_before_mutation(
    tmp_path: Path, path: tuple[str, ...], tampered_value: object
) -> None:
    retained = MetricRetentionStore(
        tmp_path / f"corrupt-semantic-{'-'.join(path)}.sqlite"
    )
    result = _result(tmp_path)
    original = retained.retain(
        result,
        metric_id="provenance_coverage",
        finding_evaluations={"finding": "bound"},
        retained_at="2026-01-01T00:00:00Z",
    )
    with sqlite3.connect(retained.path) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT observation_json FROM ckm_metric_sample_v1 WHERE sample_id = ?",
                (original.sample_id,),
            ).fetchone()[0]
        )
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = tampered_value
        conn.execute(
            "UPDATE ckm_metric_sample_v1 SET observation_json = ? WHERE sample_id = ?",
            (json.dumps(payload), original.sample_id),
        )
    usage_before = retained.storage_usage()
    with pytest.raises(CkmContractError) as exc:
        retained.correct(
            original.sample_id, result, retained_at="2026-01-02T00:00:00Z"
        )
    assert exc.value.code == "corrupt_retained_observation"
    assert retained.storage_usage() == usage_before
    with sqlite3.connect(retained.path) as conn:
        assert conn.execute(
            "SELECT lifecycle FROM ckm_metric_sample_v1 WHERE sample_id = ?",
            (original.sample_id,),
        ).fetchone()[0] == "retained"


@pytest.mark.parametrize(
    ("update_sql", "value", "expected_code"),
    (
        (
            "UPDATE ckm_metric_sample_v1 SET observation_id = ? WHERE sample_id = ?",
            "ckm_observation_tampered",
            "corrupt_retained_observation",
        ),
        (
            "UPDATE ckm_metric_sample_v1 SET watermarks_json = ? WHERE sample_id = ?",
            '{"repo":"tampered"}',
            "corrupt_retained_observation",
        ),
        (
            "UPDATE ckm_metric_sample_v1 SET finding_evaluations_json = ? WHERE sample_id = ?",
            '{"finding":"tampered"}',
            "corrupt_retained_observation",
        ),
        (
            "UPDATE ckm_metric_sample_v1 SET policy_version = ? WHERE sample_id = ?",
            "tampered-policy",
            "corrupt_retained_observation",
        ),
        (
            "UPDATE ckm_metric_sample_v1 SET source_digest = ? WHERE sample_id = ?",
            "tampered-source-digest",
            "tampered_retained_source",
        ),
    ),
)
def test_correction_refuses_corrupt_identity_columns_before_mutation(
    tmp_path: Path, update_sql: str, value: str, expected_code: str
) -> None:
    retained = MetricRetentionStore(
        tmp_path / f"corrupt-column-{expected_code}-{canonical_digest(update_sql)[:8]}.sqlite"
    )
    result = _result(tmp_path)
    original = retained.retain(
        result,
        metric_id="provenance_coverage",
        finding_evaluations={"finding": "bound"},
        retained_at="2026-01-01T00:00:00Z",
    )
    with sqlite3.connect(retained.path) as conn:
        conn.execute(update_sql, (value, original.sample_id))
    with pytest.raises(CkmContractError) as exc:
        retained.correct(
            original.sample_id, result, retained_at="2026-01-02T00:00:00Z"
        )
    assert exc.value.code == expected_code
    with sqlite3.connect(retained.path) as conn:
        assert conn.execute(
            "SELECT lifecycle FROM ckm_metric_sample_v1 WHERE sample_id = ?",
            (original.sample_id,),
        ).fetchone()[0] == "retained"


def test_correction_payloads_remain_accounted_and_policy_prunable(tmp_path: Path) -> None:
    retained = MetricRetentionStore(tmp_path / "correction-accounting.sqlite")
    result = _result(tmp_path)
    original = retained.retain(
        result,
        finding_evaluations={"finding": "original-bound-content"},
        retained_at="2025-01-01T00:00:00Z",
    )
    corrected = retained.correct(
        original.sample_id,
        result,
        finding_evaluations={"finding": "corrected-bound-content"},
        retained_at="2025-01-02T00:00:00Z",
    )
    usage = retained.storage_usage()
    assert usage["count"] == 2 and usage["bytes"] > 0
    with sqlite3.connect(retained.path) as conn:
        expected_bytes = conn.execute(
            "SELECT SUM(length(source_payload) + length(CAST(observation_json AS BLOB)) + length(CAST(source_digest AS BLOB)) + length(CAST(watermarks_json AS BLOB)) + length(CAST(finding_evaluations_json AS BLOB))) FROM ckm_metric_sample_v1 WHERE source_payload IS NOT NULL"
        ).fetchone()[0]
    assert usage["bytes"] == expected_bytes

    cap_preview = retained.preview_prune(
        now="2025-01-03T00:00:00Z",
        max_count=1,
        max_bytes=usage["bytes"] - 1,
    )
    assert cap_preview == [
        {"sample_id": original.sample_id, "reason": "storage_count_and_byte_cap"}
    ]

    age_preview = retained.preview_prune(now="2026-01-02T00:00:00Z")
    assert age_preview == [
        {"sample_id": original.sample_id, "reason": "retention_expired"},
        {"sample_id": corrected.sample_id, "reason": "retention_expired"},
    ]
    retained.prune(
        [item["sample_id"] for item in age_preview],
        reason="retention_expired",
        at="2026-01-02T00:00:00Z",
    )
    assert retained.storage_usage() == {"count": 0, "bytes": 0}
    assert retained.preview_prune(now="2027-01-01T00:00:00Z") == []
    for sample_id in (original.sample_id, corrected.sample_id):
        with pytest.raises(CkmContractError) as exc:
            retained.replay(sample_id)
        assert exc.value.code == "source_unavailable"
    with sqlite3.connect(retained.path) as conn:
        lifecycle_json, observation_json, source_payload, source_digest, watermarks_json, evaluations_json = conn.execute(
            "SELECT lifecycle_marker_json, observation_json, source_payload, source_digest, watermarks_json, finding_evaluations_json FROM ckm_metric_sample_v1 WHERE sample_id = ?",
            (original.sample_id,),
        ).fetchone()
    marker = json.loads(lifecycle_json)
    assert marker["prior_marker"]["event"] == "superseded"
    assert marker["prior_marker"]["successor"] == corrected.sample_id
    assert json.loads(observation_json) == {
        "observation_id": original.observation_id,
        "payload_removed": True,
    }
    assert source_payload is None
    assert source_digest == ""
    assert json.loads(watermarks_json) == {}
    assert json.loads(evaluations_json) == {}
    with sqlite3.connect(retained.path) as conn:
        pruned_content = conn.execute(
            "SELECT sample_id, source_payload, source_digest, observation_json, watermarks_json, finding_evaluations_json FROM ckm_metric_sample_v1 ORDER BY sample_id"
        ).fetchall()
    expected_observations = {
        original.sample_id: original.observation_id,
        corrected.sample_id: corrected.observation_id,
    }
    for sample_id, payload, digest, observation, watermarks, evaluations in pruned_content:
        assert payload is None and digest == ""
        assert json.loads(observation) == {
            "observation_id": expected_observations[sample_id],
            "payload_removed": True,
        }
        assert json.loads(watermarks) == {}
        assert json.loads(evaluations) == {}


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


@pytest.mark.parametrize(
    ("snapshot_field", "detail_key", "requested", "supported"),
    (
        (
            "envelope_schema_version",
            "snapshot.envelope_schema_version",
            999,
            ENVELOPE_SCHEMA_VERSION,
        ),
        (
            "resource_schema_version",
            "snapshot.resource_schema_version",
            999,
            RESOURCE_SCHEMA_VERSION,
        ),
        (
            "ckm_schema_version",
            "snapshot.ckm_schema_version",
            999,
            CKM_SCHEMA_VERSION,
        ),
        (
            "access_policy_version",
            "snapshot.access_policy_version",
            "unknown-policy",
            ACCESS_POLICY_VERSION,
        ),
    ),
)
def test_metric_snapshot_schema_bundle_refuses_unknown_versions(
    tmp_path: Path,
    snapshot_field: str,
    detail_key: str,
    requested: object,
    supported: object,
) -> None:
    result = _result(tmp_path)
    unsupported = replace(
        result,
        snapshot=replace(result.snapshot, **{snapshot_field: requested}),
    )

    with pytest.raises(CkmContractError) as refusal:
        build_observation(unsupported)

    assert refusal.value.code == "unsupported_metric_schema"
    assert refusal.value.details["mismatches"][detail_key] == {
        "requested": requested,
        "supported": supported,
    }


def test_metric_schema_bundle_refuses_resource_dto_version_atomically(
    tmp_path: Path,
) -> None:
    result = _result(tmp_path)
    unsupported_resource = replace(result.resources[0], schema_version=999)
    unsupported = replace(
        result,
        resources=(unsupported_resource, *result.resources[1:]),
    )
    retained = MetricRetentionStore(tmp_path / "unsupported-schema.sqlite")

    with pytest.raises(CkmContractError) as refusal:
        retained.retain(unsupported, retained_at="2026-07-21T00:00:00Z")

    assert refusal.value.code == "unsupported_metric_schema"
    assert refusal.value.details["mismatches"]["resources[0].schema_version"] == {
        "requested": 999,
        "supported": RESOURCE_SCHEMA_VERSION,
    }
    assert not retained.path.exists()


def test_metric_schema_bundle_refuses_result_snapshot_envelope_inconsistency(
    tmp_path: Path,
) -> None:
    result = _result(tmp_path)
    inconsistent = replace(
        result,
        schema_version=998,
        snapshot=replace(result.snapshot, envelope_schema_version=999),
    )

    with pytest.raises(CkmContractError) as refusal:
        build_observation(inconsistent)

    assert refusal.value.code == "unsupported_metric_schema"
    assert refusal.value.details["inconsistencies"] == {
        "result.snapshot.envelope_schema_version": {
            "result": 998,
            "snapshot": 999,
        }
    }


def test_cli_measure_retains_only_after_public_query_result(tmp_path: Path) -> None:
    _result(tmp_path)
    runner = CliRunner()
    invocation = runner.invoke(builderops, ["--db-path", str(tmp_path / "ckm.sqlite"), "ckm", "measure", "--retain"])
    assert invocation.exit_code == 0, invocation.output
    assert "human_advisory_only" in invocation.output
    assert (tmp_path / "ckm-metric-samples.sqlite").exists()
