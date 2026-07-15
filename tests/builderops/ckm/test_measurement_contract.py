from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.builderops.ckm.contracts import (
    CkmContractError,
    CursorPayload,
    ErrorEnvelope,
    ResourceDto,
    ResultEnvelope,
    SnapshotManifest,
    TaggedValue,
    TruncationMetadata,
    canonical_query_digest,
    validate_contract_request,
)
from app.builderops.ckm.models import MATURITY_DIMENSIONS, CkmValidationError
from app.builderops.ckm.schema import CKM_SCHEMA_VERSION, CKM_TABLE_NAMES
from app.builderops.ckm.seed import seed_capabilities
from app.builderops.ckm.store import CkmStore


@pytest.fixture()
def store(tmp_path: Path) -> CkmStore:
    result = CkmStore(tmp_path / "builderops.sqlite3")
    result.ensure_schema()
    return result


def _capability(store: CkmStore, *, name: str = "Measurement"):
    return store.upsert_capability(
        identity_key="seed:measurement",
        name=name,
        definition="Expose descriptive CKM measurements.",
        lifecycle="confirmed",
        existence_provenance="seeded:docs/measurement.md",
    )


def _artifact(store: CkmStore, *, source_ref: str = "docs/measurement.md"):
    return store.upsert_artifact(
        source_ref=source_ref,
        artifact_kind="document",
        source="repo_artifact_ingestion",
        watermark="commit:abc",
        provenance="repo:fixture@abc",
    )


def _edge(store: CkmStore, artifact_id: str, capability_id: str, *, basis: str = "doc:1"):
    return store.upsert_evidence_edge(
        artifact_id=artifact_id,
        capability_id=capability_id,
        evidence_kind="doc",
        polarity="supports",
        maturity_dimension="documentation_quality",
        confidence=0.8,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref="docs/measurement.md",
        basis=basis,
    )


def _revision(store: CkmStore) -> int:
    return store.state_identity().state_revision


def _assert_one_mutation(store: CkmStore, action) -> object:
    before = _revision(store)
    result = action()
    assert _revision(store) == before + 1
    return result


def test_public_identity_survives_rebuild_and_rename(
    store: CkmStore, tmp_path: Path
) -> None:
    original = _capability(store)
    renamed = _capability(store, name="Measurement and Access")

    assert renamed.id == original.id
    assert renamed.public_id == original.public_id
    assert renamed.identity_key == "seed:measurement"

    first_epoch = store.state_identity().epoch
    store.rebuild()
    rebuilt = _capability(store, name="Measurement and Access")

    assert store.state_identity().epoch != first_epoch
    assert rebuilt.id != original.id
    assert rebuilt.public_id == original.public_id

    inferred = store.upsert_capability(
        identity_key="inferred:receipt:123",
        name="Inferred capability",
        definition="Candidate inferred from evidence.",
        existence_provenance="receipt:123",
    )
    inferred_renamed = store.upsert_capability(
        identity_key="inferred:receipt:123",
        name="Renamed inferred capability",
        definition="Candidate inferred from evidence.",
        existence_provenance="receipt:123",
    )
    assert inferred_renamed.public_id == inferred.public_id

    first_manifest = tmp_path / "first-capabilities.yaml"
    first_manifest.write_text(
        "capabilities:\n"
        "  - {id: mutable-slug, stable_key: permanent-001, name: Manifest capability, "
        "definition: Stable seed identity., parent: null, "
        "seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
        encoding="utf-8",
    )
    seed_capabilities(store, manifest_path=first_manifest)
    seeded = store.get_capability_by_identity_key("seed:permanent-001")
    assert seeded is not None

    renamed_manifest = tmp_path / "renamed-capabilities.yaml"
    renamed_manifest.write_text(
        "capabilities:\n"
        "  - {id: renamed-slug, stable_key: permanent-001, name: Renamed manifest capability, "
        "definition: Stable seed identity., parent: null, "
        "seed_source: 'docs/CAPABILITY_CONTRACT_MODEL.md :: Examples'}\n",
        encoding="utf-8",
    )
    seed_capabilities(store, manifest_path=renamed_manifest)
    renamed_seed = store.get_capability_by_identity_key("seed:permanent-001")
    assert renamed_seed is not None
    assert renamed_seed.public_id == seeded.public_id

    store.rebuild()
    seed_capabilities(store, manifest_path=renamed_manifest)
    rebuilt_seed = store.get_capability_by_identity_key("seed:permanent-001")
    assert rebuilt_seed is not None
    assert rebuilt_seed.public_id == seeded.public_id


def test_all_mutations_advance_state_revision_atomically(store: CkmStore) -> None:
    capability = _assert_one_mutation(store, lambda: _capability(store))
    assert _revision(store) == 1
    _capability(store)
    assert _revision(store) == 1

    artifact = _assert_one_mutation(store, lambda: _artifact(store))
    _assert_one_mutation(store, lambda: store.set_watermark("repo", "commit:abc"))
    edge = _assert_one_mutation(
        store, lambda: _edge(store, artifact.id, capability.id, basis="deterministic:1")
    )

    before_failed_write = _revision(store)
    with pytest.raises(CkmValidationError):
        _edge(store, "missing-artifact", capability.id, basis="invalid")
    assert _revision(store) == before_failed_write

    inferred = _assert_one_mutation(
        store,
        lambda: store.upsert_evidence_edge(
            artifact_id=artifact.id,
            capability_id=capability.id,
            evidence_kind="doc",
            polarity="supports",
            maturity_dimension="functional_completeness",
            confidence=0.6,
            extraction_method="inferred",
            lifecycle="candidate",
            source_ref=artifact.source_ref,
            basis="inferred rationale",
            model="fixture-model",
            provider="fixture-provider",
        ),
    )
    _assert_one_mutation(store, lambda: store._set_inferred_edge_confirmed(inferred.id))

    scores = {dimension: 0.5 for dimension in MATURITY_DIMENSIONS}
    citations = {dimension: [edge.to_dict()] for dimension in MATURITY_DIMENSIONS}
    _assert_one_mutation(
        store,
        lambda: store.append_assessment(
            capability_id=capability.id,
            scores=scores,
            citations=citations,
            aggregate=0.5,
            watermark_set={"repo": "commit:abc"},
            valid_from="2026-07-15T00:00:00Z",
            asserted_at="2026-07-15T00:00:00Z",
        ),
    )

    finding = {
        "kind": "gap",
        "capability_id": capability.id,
        "dimension": "test_completeness",
        "statement": "No focused measurement contract test.",
        "citations": [{"artifact": artifact.to_dict(), "artifact_id": artifact.id}],
    }
    _assert_one_mutation(store, lambda: store.replace_findings([finding]))
    unchanged_revision = _revision(store)
    store.replace_findings([finding])
    assert _revision(store) == unchanged_revision

    _assert_one_mutation(store, lambda: store.delete_evidence_edge(inferred.id))
    _assert_one_mutation(
        store,
        lambda: store.delete_deterministic_edges_not_in(
            set(), owned_basis_prefixes=("deterministic:",)
        ),
    )
    extra_artifact = _assert_one_mutation(
        store, lambda: _artifact(store, source_ref="docs/stale.md")
    )
    assert extra_artifact is not None
    _assert_one_mutation(
        store,
        lambda: store.delete_artifacts_not_in(
            "repo_artifact_ingestion", {artifact.source_ref}
        ),
    )

    old_epoch = store.state_identity().epoch
    store.rebuild()
    rebuilt_state = store.state_identity()
    assert rebuilt_state.epoch != old_epoch
    assert rebuilt_state.state_revision == 1


def test_identity_revision_migration_updates_every_producer(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    legacy = CkmStore(db_path)
    legacy.ensure_schema()
    capability = _capability(legacy)
    artifact = _artifact(legacy)
    edge = _edge(legacy, artifact.id, capability.id)
    legacy.upsert_evidence_edge(
        artifact_id=artifact.id,
        capability_id=capability.id,
        evidence_kind="doc",
        polarity="supports",
        maturity_dimension="documentation_quality",
        confidence=0.9,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref=artifact.source_ref,
        basis=edge.basis,
    )
    scores = {dimension: 0.5 for dimension in MATURITY_DIMENSIONS}
    citations = {dimension: [edge.to_dict()] for dimension in MATURITY_DIMENSIONS}
    legacy.append_assessment(
        capability_id=capability.id,
        scores=scores,
        citations=citations,
        aggregate=0.5,
        watermark_set={"repo": "commit:abc"},
        valid_from="2026-07-15T00:00:00Z",
        asserted_at="2026-07-15T00:00:00Z",
    )
    legacy.upsert_finding(
        kind="gap",
        capability_id=capability.id,
        dimension="test_completeness",
        statement="Missing migration coverage.",
        citations=[{"artifact": artifact.to_dict(), "artifact_id": artifact.id}],
    )

    with sqlite3.connect(db_path) as conn:
        for index_name in (
            "idx_ckm_capability_public_id",
            "idx_ckm_capability_identity_key",
            "idx_ckm_artifact_public_id",
            "idx_ckm_evidence_edge_public_id",
            "idx_ckm_assessment_public_id",
            "idx_ckm_finding_public_id",
        ):
            conn.execute(f"DROP INDEX {index_name}")
        conn.execute("DROP TABLE ckm_state")
        conn.execute("UPDATE ckm_capability SET public_id = '', identity_key = ''")
        conn.execute("UPDATE ckm_artifact SET public_id = ''")
        conn.execute("UPDATE ckm_evidence_edge SET public_id = ''")
        conn.execute("UPDATE ckm_evidence_edge_history SET public_id = ''")
        conn.execute("UPDATE ckm_assessment SET public_id = ''")
        conn.execute("UPDATE ckm_finding SET public_id = ''")
        conn.commit()

    legacy.ensure_schema()
    migrated_state = legacy.state_identity()
    assert migrated_state.schema_version == CKM_SCHEMA_VERSION
    assert migrated_state.state_revision == 1
    assert all(item.public_id for item in legacy.list_capabilities())
    assert all(item.identity_key for item in legacy.list_capabilities())
    assert all(item.public_id for item in legacy.list_artifacts())
    assert all(item.public_id for item in legacy.list_evidence_edges())
    assert all(item.public_id for item in legacy.list_assessments_for_capability(capability.id))
    assert all(item.public_id for item in legacy.list_findings())
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM ckm_evidence_edge_history WHERE public_id = ''"
        ).fetchone()[0] == 0

    legacy.ensure_schema()
    assert legacy.state_identity() == migrated_state

    damaged = CkmStore(tmp_path / "damaged.sqlite3")
    damaged.ensure_schema()
    with sqlite3.connect(damaged.db_path) as conn:
        conn.execute("UPDATE ckm_state SET schema_version = 4")
        conn.commit()
    with pytest.raises(CkmValidationError, match="unsupported CKM state schema version"):
        damaged.ensure_schema()

    partial = CkmStore(tmp_path / "partial.sqlite3")
    with sqlite3.connect(partial.db_path) as conn:
        conn.execute("CREATE TABLE ckm_capability (id TEXT PRIMARY KEY)")
    with pytest.raises(CkmValidationError, match="unsupported partial CKM schema"):
        partial.ensure_schema()

    assert set(legacy.table_names()) == set(CKM_TABLE_NAMES)


def test_envelope_missing_states_and_projection_marker(store: CkmStore) -> None:
    capability = _capability(store)
    snapshot = SnapshotManifest.build(
        state=store.state_identity(),
        taxonomy_digest="taxonomy-v1",
        watermarks={"repo": "commit:abc"},
        provenance=[{"ref_type": "repo", "ref": "fixture@abc"}],
        read_set=[capability.public_id],
    )
    resource = ResourceDto(
        public_id=capability.public_id,
        resource_type="capability",
        display_name=capability.name,
        lifecycle="candidate",
        candidate=True,
        provenance=[{"ref_type": "seed", "ref": capability.existence_provenance}],
        values={
            "measured_zero": TaggedValue.measured(0),
            "missing": TaggedValue.missing("no assessment"),
            "not_applicable": TaggedValue.not_applicable("dimension does not apply"),
            "unsupported": TaggedValue.unsupported("not implemented in schema v1"),
        },
    )
    envelope = ResultEnvelope(
        resource_type="capability",
        query_digest=canonical_query_digest({"resource": "capability"}),
        snapshot=snapshot,
        resources=[resource],
        truncation=TruncationMetadata(
            truncated=True,
            returned_count=1,
            limit=1,
            next_cursor="opaque-cursor",
        ),
    ).to_dict()

    assert envelope["projection"] == {
        "status": "derived_projection",
        "authoritative": False,
    }
    assert envelope["resources"][0]["candidate"] is True
    assert envelope["resources"][0]["provenance"]
    assert envelope["resources"][0]["values"]["measured_zero"] == {
        "state": "measured",
        "value": 0,
    }
    assert {value["state"] for value in envelope["resources"][0]["values"].values()} == {
        "measured",
        "missing",
        "not_applicable",
        "unsupported",
    }
    assert envelope["snapshot"]["snapshot_digest"]
    assert envelope["truncation"]["truncated"] is True

    typed_error = CkmContractError(code="unsupported_filter", message="not supported")
    assert ErrorEnvelope(typed_error).to_dict()["error"]["code"] == "unsupported_filter"


def test_cursor_contract_binds_query_snapshot_versions() -> None:
    secret = b"test-only-secret"
    query_digest = canonical_query_digest(
        {"resource_type": "capability", "filters": {"lifecycle": "candidate"}}
    )
    cursor = CursorPayload(
        resource_type="capability",
        query_digest=query_digest,
        snapshot_digest="snapshot-123",
        limit=25,
        last_key=("capability", "ckm_capability_abc"),
    )
    token = cursor.encode(secret)
    decoded = CursorPayload.decode(token, secret)

    assert decoded == cursor
    decoded.assert_bound_to(
        resource_type="capability",
        query_digest=query_digest,
        snapshot_digest="snapshot-123",
        limit=25,
    )
    with pytest.raises(CkmContractError) as mismatch:
        decoded.assert_bound_to(
            resource_type="capability",
            query_digest=query_digest,
            snapshot_digest="new-snapshot",
            limit=25,
        )
    assert mismatch.value.code == "cursor_binding_mismatch"

    body, signature = token.split(".", 1)
    tampered = f"{body[:-1]}{'A' if body[-1] != 'A' else 'B'}.{signature}"
    with pytest.raises(CkmContractError) as invalid:
        CursorPayload.decode(tampered, secret)
    assert invalid.value.code == "invalid_cursor"


def test_unsupported_versions_and_semantics_are_typed() -> None:
    cases = (
        ({"resource_type": "capability", "ckm_schema_version": 99}, "unsupported_version"),
        ({"resource_type": "capability", "envelope_schema_version": 99}, "unsupported_version"),
        ({"resource_type": "unknown"}, "unsupported_resource"),
        (
            {
                "resource_type": "capability",
                "filters": {"rank": "top"},
                "supported_filters": frozenset({"lifecycle"}),
            },
            "unsupported_filter",
        ),
        (
            {"resource_type": "capability", "history_mode": "as_of"},
            "unsupported_historical_semantics",
        ),
    )
    for arguments, expected_code in cases:
        with pytest.raises(CkmContractError) as refusal:
            validate_contract_request(**arguments)
        assert refusal.value.code == expected_code
        assert refusal.value.to_dict()["code"] == expected_code
