from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from app.builderops.ckm.assess import assess_capabilities, assessment_fingerprint
from app.builderops.ckm.contracts import (
    ACCESS_POLICY_VERSION,
    EFFECTIVE_AUDIENCE,
    REDACTION_PROFILE,
    CkmContractError,
    CompletenessManifest,
    ErrorEnvelope,
    ObjectClassCompleteness,
    ResourceDto,
    ResultEnvelope,
    SnapshotManifest,
    TaggedValue,
    canonical_digest,
    canonical_query_digest,
    stable_public_id,
    validate_contract_request,
)
from app.builderops.ckm.models import MATURITY_DIMENSIONS, CkmValidationError
from app.builderops.ckm.schema import CKM_DDL_STATEMENTS, CKM_SCHEMA_VERSION, CKM_TABLE_NAMES
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


def _edge(
    store: CkmStore,
    artifact_id: str,
    capability_id: str,
    *,
    basis: str = "doc:1",
    source_ref: str = "docs/measurement.md",
):
    return store.upsert_evidence_edge(
        artifact_id=artifact_id,
        capability_id=capability_id,
        evidence_kind="doc",
        polarity="supports",
        maturity_dimension="documentation_quality",
        confidence=0.8,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref=source_ref,
        basis=basis,
    )


def _revision(store: CkmStore) -> int:
    return store.state_identity().state_revision


def _assert_one_mutation(store: CkmStore, action) -> object:
    before = _revision(store)
    result = action()
    assert _revision(store) == before + 1
    return result


def test_public_identity_lifecycle_policy(
    store: CkmStore, tmp_path: Path
) -> None:
    original = _capability(store)
    renamed = _capability(store, name="Measurement and Access")

    assert renamed.id == original.id
    assert renamed.public_id == original.public_id
    assert renamed.identity_key == "seed:measurement"

    first_epoch = store.state_identity().epoch
    store.rebuild(retained_public_ids=[original.public_id])
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

    artifact = _artifact(store)
    edge = _edge(store, artifact.id, rebuilt.id)
    scores = {dimension: 0.5 for dimension in MATURITY_DIMENSIONS}
    citations = {dimension: [edge.to_dict()] for dimension in MATURITY_DIMENSIONS}
    fingerprint = assessment_fingerprint(
        [edge], {artifact.id: artifact}, watermark_set={"repo": "commit:abc"}
    )
    assessment = store.append_assessment(
        capability_id=rebuilt.id,
        scores=scores,
        citations=citations,
        aggregate=0.5,
        edge_fingerprint=fingerprint,
        watermark_set={"repo": "commit:abc"},
        valid_from="2026-07-15T00:00:00Z",
        asserted_at="2026-07-15T00:00:00Z",
    )

    store.rebuild(retained_public_ids=store.active_public_ids())
    rebuilt_again = _capability(store, name="Measurement and Access")
    rebuilt_artifact = _artifact(store)
    rebuilt_edge = _edge(store, rebuilt_artifact.id, rebuilt_again.id)
    rebuilt_fingerprint = assessment_fingerprint(
        [rebuilt_edge],
        {rebuilt_artifact.id: rebuilt_artifact},
        watermark_set={"repo": "commit:abc"},
    )
    rebuilt_assessment = store.append_assessment(
        capability_id=rebuilt_again.id,
        scores=scores,
        citations={
            dimension: [rebuilt_edge.to_dict()] for dimension in MATURITY_DIMENSIONS
        },
        aggregate=0.5,
        edge_fingerprint=rebuilt_fingerprint,
        watermark_set={"repo": "commit:abc"},
        valid_from="2026-07-15T00:00:00Z",
        asserted_at="2026-07-15T00:00:00Z",
    )
    assert rebuilt_edge.id != edge.id
    assert rebuilt_edge.public_id == edge.public_id
    assert rebuilt_fingerprint == fingerprint
    assert rebuilt_assessment.public_id == assessment.public_id
    deleted = store.upsert_capability(
        identity_key="inferred:deleted",
        name="Deleted capability",
        definition="Content removed after deletion.",
        existence_provenance="receipt:deleted",
    )
    store.tombstone_capability(deleted.public_id)
    assert store.identity_lifecycle(deleted.public_id) == {
        "public_id": deleted.public_id,
        "resource_type": "capability",
        "status": "tombstone",
        "successors": [],
    }
    with pytest.raises(CkmValidationError, match="tombstoned and cannot be reused"):
        store.upsert_capability(
            identity_key="inferred:deleted",
            name="Reused capability",
            definition="Must be refused.",
            existence_provenance="receipt:reuse",
        )

    deleted_artifact = _artifact(store, source_ref="docs/deleted-artifact.md")
    cascade_edge = _edge(
        store,
        deleted_artifact.id,
        rebuilt_again.id,
        basis="cascade-delete:1",
        source_ref=deleted_artifact.source_ref,
    )
    assert store.delete_artifacts_not_in(
        "repo_artifact_ingestion", {rebuilt_artifact.source_ref}
    ) == 1
    for public_id, resource_type in (
        (deleted_artifact.public_id, "artifact"),
        (cascade_edge.public_id, "evidence_edge"),
    ):
        assert store.identity_lifecycle(public_id) == {
            "public_id": public_id,
            "resource_type": resource_type,
            "status": "tombstone",
            "successors": [],
        }
    with pytest.raises(CkmValidationError, match="tombstoned and cannot be reused"):
        _artifact(store, source_ref=deleted_artifact.source_ref)

    edge_owner = _artifact(store, source_ref="docs/deleted-edges.md")
    deleted_edge = _edge(
        store,
        edge_owner.id,
        rebuilt_again.id,
        basis="direct-delete:1",
        source_ref=edge_owner.source_ref,
    )
    store.delete_evidence_edge(deleted_edge.id)
    assert store.identity_lifecycle(deleted_edge.public_id)["status"] == "tombstone"
    with pytest.raises(CkmValidationError, match="tombstoned and cannot be reused"):
        _edge(
            store,
            edge_owner.id,
            rebuilt_again.id,
            basis=deleted_edge.basis,
            source_ref=edge_owner.source_ref,
        )

    reconciled_edge = _edge(
        store,
        edge_owner.id,
        rebuilt_again.id,
        basis="deterministic:removed",
        source_ref=edge_owner.source_ref,
    )
    assert store.delete_deterministic_edges_not_in(
        set(), owned_basis_prefixes=("deterministic:",)
    ) == 1
    assert store.identity_lifecycle(reconciled_edge.public_id)["status"] == "tombstone"
    with pytest.raises(CkmValidationError, match="tombstoned and cannot be reused"):
        _edge(
            store,
            edge_owner.id,
            rebuilt_again.id,
            basis=reconciled_edge.basis,
            source_ref=edge_owner.source_ref,
        )

    deleted_finding = store.upsert_finding(
        kind="gap",
        capability_id=rebuilt_again.id,
        dimension="documentation_quality",
        statement="Temporary finding.",
        citations=[{"artifact": edge_owner.to_dict()}],
    )
    store.replace_findings([])
    assert store.identity_lifecycle(deleted_finding.public_id) == {
        "public_id": deleted_finding.public_id,
        "resource_type": "finding",
        "status": "tombstone",
        "successors": [],
    }
    with pytest.raises(CkmValidationError, match="tombstoned and cannot be reused"):
        store.upsert_finding(
            kind="gap",
            capability_id=rebuilt_again.id,
            dimension="documentation_quality",
            statement="Reused finding.",
            citations=[{"artifact": edge_owner.to_dict()}],
        )

    split_source = store.upsert_capability(
        identity_key="inferred:split-source",
        name="Split source",
        definition="Original identity.",
        existence_provenance="receipt:split",
    )
    split_successors = [
        store.upsert_capability(
            identity_key=f"inferred:split-{suffix}",
            name=f"Split successor {suffix}",
            definition="New successor identity.",
            existence_provenance="receipt:split",
        )
        for suffix in ("a", "b")
    ]
    store.tombstone_capability(
        split_source.public_id,
        successor_public_ids=[item.public_id for item in split_successors],
        relation="split_successor",
    )
    assert store.identity_lifecycle(split_source.public_id)["successors"] == [
        {"successor_public_id": item.public_id, "relation": "split_successor"}
        for item in sorted(split_successors, key=lambda item: item.public_id)
    ]

    merge_sources = [
        store.upsert_capability(
            identity_key=f"inferred:merge-{suffix}",
            name=f"Merge source {suffix}",
            definition="Input identity.",
            existence_provenance="receipt:merge",
        )
        for suffix in ("a", "b")
    ]
    merge_successor = store.upsert_capability(
        identity_key="inferred:merge-successor",
        name="Merge successor",
        definition="New merged identity.",
        existence_provenance="receipt:merge",
    )
    for source in merge_sources:
        store.tombstone_capability(
            source.public_id,
            successor_public_ids=[merge_successor.public_id],
            relation="merge_successor",
        )
        assert store.identity_lifecycle(source.public_id)["successors"] == [
            {
                "successor_public_id": merge_successor.public_id,
                "relation": "merge_successor",
            }
        ]

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
    before_seed_rename = _revision(store)
    rename_result = seed_capabilities(store, manifest_path=renamed_manifest)
    renamed_seed = store.get_capability_by_identity_key("seed:permanent-001")
    assert renamed_seed is not None
    assert rename_result["changed"] == 1
    assert renamed_seed.name == "Renamed manifest capability"
    assert renamed_seed.public_id == seeded.public_id
    assert _revision(store) == before_seed_rename + 1

    store.rebuild(retained_public_ids=store.active_public_ids())
    seed_capabilities(store, manifest_path=renamed_manifest)
    rebuilt_seed = store.get_capability_by_identity_key("seed:permanent-001")
    assert rebuilt_seed is not None
    assert rebuilt_seed.public_id == seeded.public_id


def test_rebuild_tombstones_active_identities_absent_from_declared_keep_set(
    store: CkmStore,
) -> None:
    capability = _capability(store)
    artifact = _artifact(store)

    store.rebuild(retained_public_ids=[capability.public_id])
    rebuilt_capability = _capability(store)

    assert rebuilt_capability.public_id == capability.public_id
    assert store.identity_lifecycle(capability.public_id)["status"] == "active"
    artifact_lifecycle = store.identity_lifecycle(artifact.public_id)
    assert artifact_lifecycle is not None
    assert artifact_lifecycle["status"] == "tombstone"
    assert store.list_artifacts() == []


@pytest.mark.parametrize("relation", ["split_successor", "merge_successor"])
def test_tombstone_rejects_self_successor(store: CkmStore, relation: str) -> None:
    capability = _capability(store)

    with pytest.raises(CkmValidationError, match="cannot be its own successor"):
        store.tombstone_capability(
            capability.public_id,
            successor_public_ids=[capability.public_id],
            relation=relation,
        )

    assert store.get_capability(capability.id) is not None
    assert store.identity_lifecycle(capability.public_id)["status"] == "active"


@pytest.mark.parametrize("relation", ["split_successor", "merge_successor"])
def test_assessed_capability_tombstone_atomically_retires_public_dependents(
    store: CkmStore, relation: str
) -> None:
    source = store.upsert_capability(
        identity_key=f"inferred:assessed-{relation}",
        name=f"Assessed {relation}",
        definition="Capability with every public dependent class.",
        existence_provenance="receipt:assessed-lifecycle",
    )
    successor = store.upsert_capability(
        identity_key=f"inferred:assessed-{relation}-successor",
        name=f"Assessed {relation} successor",
        definition="Lifecycle successor.",
        existence_provenance="receipt:assessed-lifecycle",
    )
    artifact = _artifact(store, source_ref=f"docs/{relation}.md")
    edge = _edge(
        store,
        artifact.id,
        source.id,
        basis=f"{relation}:evidence",
        source_ref=artifact.source_ref,
    )
    scores = {dimension: 0.5 for dimension in MATURITY_DIMENSIONS}
    assessment = store.append_assessment(
        capability_id=source.id,
        scores=scores,
        citations={dimension: [edge.to_dict()] for dimension in MATURITY_DIMENSIONS},
        aggregate=0.5,
        edge_fingerprint=assessment_fingerprint(
            [edge],
            {artifact.id: artifact},
            watermark_set={"repo": "commit:assessed"},
        ),
        watermark_set={"repo": "commit:assessed"},
    )
    finding = store.upsert_finding(
        kind="gap",
        capability_id=source.id,
        dimension="documentation_quality",
        statement="Temporary dependent finding.",
        citations=[{"artifact": artifact.to_dict()}],
    )

    store.tombstone_capability(
        source.public_id,
        successor_public_ids=[successor.public_id],
        relation=relation,
    )

    assert store.get_capability(source.id) is None
    assert store.get_active_evidence_edge_by_id(edge.id) is None
    assert store.list_assessments_for_capability(source.id) == []
    assert store.get_finding(
        kind="gap", capability_id=source.id, dimension="documentation_quality"
    ) is None
    for public_id in (
        source.public_id,
        edge.public_id,
        assessment.public_id,
        finding.public_id,
    ):
        assert store.identity_lifecycle(public_id)["status"] == "tombstone"
    assert store.identity_lifecycle(source.public_id)["successors"] == [
        {"successor_public_id": successor.public_id, "relation": relation}
    ]


def test_all_mutations_advance_state_revision_atomically(
    store: CkmStore, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    before_confirmation = _revision(store)
    barrier = Barrier(2)

    def confirm() -> object:
        barrier.wait()
        return store._set_inferred_edge_confirmed(inferred.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        confirmed = list(executor.map(lambda _: confirm(), range(2)))
    assert all(result.lifecycle == "confirmed" for result in confirmed)
    assert _revision(store) == before_confirmation + 1
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM ckm_evidence_edge_history WHERE edge_id = ?",
            (inferred.id,),
        ).fetchone()[0] == 1

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

    finding_citations = [{"artifact": artifact.to_dict(), "artifact_id": artifact.id}]
    _assert_one_mutation(
        store,
        lambda: store.upsert_finding(
            kind="gap",
            capability_id=capability.id,
            dimension="requirement_coverage",
            statement="No direct requirement evidence.",
            citations=finding_citations,
        ),
    )

    finding = {
        "kind": "gap",
        "capability_id": capability.id,
        "dimension": "test_completeness",
        "statement": "No focused measurement contract test.",
        "citations": finding_citations,
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

    before_failed_rebuild = store.state_identity()
    with monkeypatch.context() as patch:
        patch.setattr(
            "app.builderops.ckm.store.CKM_DDL_STATEMENTS",
            [*CKM_DDL_STATEMENTS, "INVALID REBUILD DDL"],
        )
        with pytest.raises(sqlite3.OperationalError):
            store.rebuild(retained_public_ids=store.active_public_ids())
    assert store.state_identity() == before_failed_rebuild
    assert store.get_capability(capability.id) is not None

    old_epoch = before_failed_rebuild.epoch
    store.rebuild(retained_public_ids=[])
    rebuilt_state = store.state_identity()
    assert rebuilt_state.epoch != old_epoch
    assert rebuilt_state.state_revision == 1


def test_identity_revision_migration_updates_every_producer(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    legacy = CkmStore(db_path)
    legacy.ensure_schema()
    legacy.set_watermark("repo", "commit:abc")
    capability = legacy.upsert_capability(
        identity_key="pre-v5-placeholder",
        name="Legacy inferred capability",
        definition="Pre-Q1 inferred fixture.",
        existence_provenance="receipt:legacy-inference",
    )
    inferred_capability = capability
    artifact = _artifact(legacy)
    edge = _edge(legacy, artifact.id, capability.id)
    unselected_artifact = _artifact(
        legacy, source_ref="docs/measurement-diagram.md"
    )
    unselected_edge = _edge(
        legacy,
        unselected_artifact.id,
        capability.id,
        basis="diagram:1",
        source_ref=unselected_artifact.source_ref,
    )
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
    current_assessment = legacy.append_assessment(
        capability_id=capability.id,
        scores=scores,
        citations=citations,
        aggregate=0.5,
        edge_fingerprint=hashlib.sha256(
            f"{edge.id}:{artifact.id}:{unselected_edge.id}:{unselected_artifact.id}".encode(
                "utf-8"
            )
        ).hexdigest(),
        watermark_set={"repo": "commit:abc"},
        valid_from="2026-07-15T00:00:00Z",
        asserted_at="2026-07-15T00:00:00Z",
    )
    with sqlite3.connect(db_path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(ckm_assessment)")]
        current_row = conn.execute(
            "SELECT * FROM ckm_assessment WHERE id = ?", (current_assessment.id,)
        ).fetchone()
        assert current_row is not None
        historical = dict(zip(columns, current_row, strict=True))
        historical.update(
            {
                # Inserted second but lexically before the first row's
                # generated id: migration must use runtime's rowid tie-break.
                "id": "000_pre_v5_runtime_latest",
                "public_id": "legacy-history-placeholder",
                "functional_completeness": 0.4,
                "aggregate": 0.4,
                "edge_fingerprint": hashlib.sha256(
                    b"historical-pre-v5-evidence-domain"
                ).hexdigest(),
                "valid_from": "2026-07-15T00:00:00Z",
                "asserted_at": "2026-07-15T00:00:00Z",
            }
        )
        conn.execute(
            f"INSERT INTO ckm_assessment ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [historical[column] for column in columns],
        )
        conn.commit()

    zero_capability = legacy.upsert_capability(
        identity_key="pre-v5-zero-evidence",
        name="Zero evidence capability",
        definition="A valid empty assessment domain.",
        existence_provenance="receipt:legacy-zero",
    )
    legacy.append_assessment(
        capability_id=zero_capability.id,
        scores=scores,
        citations={dimension: [] for dimension in MATURITY_DIMENSIONS},
        aggregate=0.5,
        edge_fingerprint=hashlib.sha256(b"pre-v5-empty-domain").hexdigest(),
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
    stale_artifact = _artifact(legacy, source_ref="docs/stale-history.md")
    stale_edge = _edge(
        legacy,
        stale_artifact.id,
        capability.id,
        basis="stale-history:1",
        source_ref=stale_artifact.source_ref,
    )
    legacy.upsert_finding(
        kind="gap",
        capability_id=capability.id,
        dimension="operational_readiness",
        statement="Historical artifact was retired.",
        citations=[
            {"artifact": stale_artifact.to_dict(), "artifact_id": stale_artifact.id}
        ],
    )
    assert legacy.delete_artifacts_not_in(
        "repo_artifact_ingestion",
        {artifact.source_ref, unselected_artifact.source_ref},
    ) == 1

    def strip_public_ids(value: object) -> object:
        if isinstance(value, list):
            return [strip_public_ids(item) for item in value]
        if isinstance(value, dict):
            return {
                key: strip_public_ids(item)
                for key, item in value.items()
                if key != "public_id"
            }
        return value

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT * FROM ckm_assessment").fetchall():
            for dimension in MATURITY_DIMENSIONS:
                column = f"{dimension}_citations"
                stripped = strip_public_ids(json.loads(row[column]))
                conn.execute(
                    f"UPDATE ckm_assessment SET {column} = ? WHERE id = ?",
                    (json.dumps(stripped), row["id"]),
                )
        for row in conn.execute("SELECT id, citations FROM ckm_finding").fetchall():
            stripped = strip_public_ids(json.loads(row["citations"]))
            conn.execute(
                "UPDATE ckm_finding SET citations = ? WHERE id = ?",
                (json.dumps(stripped), row["id"]),
            )
        for index_name in (
            "idx_ckm_capability_public_id",
            "idx_ckm_capability_identity_key",
            "idx_ckm_artifact_public_id",
            "idx_ckm_evidence_edge_public_id",
            "idx_ckm_assessment_public_id",
            "idx_ckm_finding_public_id",
        ):
            conn.execute(f"DROP INDEX {index_name}")
        conn.execute("DROP TABLE ckm_identity_successor")
        conn.execute("DROP TABLE ckm_public_identity")
        conn.execute("DROP TABLE ckm_state")
        conn.execute("ALTER TABLE ckm_capability DROP COLUMN public_id")
        conn.execute("ALTER TABLE ckm_capability DROP COLUMN identity_key")
        conn.execute("ALTER TABLE ckm_artifact DROP COLUMN public_id")
        conn.execute("ALTER TABLE ckm_evidence_edge DROP COLUMN public_id")
        conn.execute("ALTER TABLE ckm_evidence_edge_history DROP COLUMN public_id")
        conn.execute("ALTER TABLE ckm_assessment DROP COLUMN public_id")
        conn.execute("ALTER TABLE ckm_finding DROP COLUMN public_id")
        conn.commit()

    legacy.ensure_schema()
    migrated_state = legacy.state_identity()
    migrated_inferred = legacy.get_capability(inferred_capability.id)
    assert migrated_inferred is not None
    assert migrated_state.schema_version == CKM_SCHEMA_VERSION
    assert migrated_state.state_revision == 1
    assert all(item.public_id for item in legacy.list_capabilities())
    assert all(item.identity_key for item in legacy.list_capabilities())
    assert all(item.public_id for item in legacy.list_artifacts())
    assert all(item.public_id for item in legacy.list_evidence_edges())
    assessments = legacy.list_assessments_for_capability(capability.id)
    assert all(item.public_id for item in assessments)
    assert len(assessments) == 2
    historical_assessment, migrated_current_assessment = assessments
    assert historical_assessment.edge_fingerprint == "legacy"
    assert historical_assessment.public_id != migrated_current_assessment.public_id
    migrated_assessment_public_id = migrated_current_assessment.public_id
    assert migrated_current_assessment.edge_fingerprint.startswith("v2:")
    zero_assessment = legacy.latest_assessment_for_capability(zero_capability.id)
    assert zero_assessment is not None
    assert zero_assessment.edge_fingerprint.startswith("v2:")
    immediate_run = assess_capabilities(legacy)
    assert immediate_run.assessed == 0
    assert immediate_run.skipped == 2
    assert all(
        citation.get("public_id")
        for assessment in assessments
        for dimension in MATURITY_DIMENSIONS
        for citation in assessment.citations[dimension]
    )
    findings = legacy.list_findings()
    assert all(item.public_id for item in findings)
    assert all(item.validate() for item in findings)
    assert all(
        citation.get("artifact", {}).get("public_id")
        for finding in findings
        for citation in finding.citations
        if "artifact" in citation
    )
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM ckm_evidence_edge_history WHERE public_id = ''"
        ).fetchone()[0] == 0
        migrated_history_public_id = conn.execute(
            "SELECT public_id FROM ckm_evidence_edge_history WHERE edge_id = ?",
            (stale_edge.id,),
        ).fetchone()[0]
    expected_history_public_id = stable_public_id(
        "evidence_edge",
        canonical_digest(
            {
                "artifact": stable_public_id("artifact", stale_artifact.source_ref),
                "capability": migrated_inferred.public_id,
                "basis": stale_edge.basis,
            }
        ),
    )
    assert migrated_history_public_id == expected_history_public_id

    legacy.ensure_schema()
    assert legacy.state_identity() == migrated_state

    repair_store = CkmStore(tmp_path / "citation-repair.sqlite3")
    repair_store.ensure_schema()
    repair_capability = _capability(repair_store)
    repair_artifact = _artifact(repair_store)
    repair_edge = _edge(repair_store, repair_artifact.id, repair_capability.id)
    incomplete_edge_snapshot = repair_edge.to_dict()
    incomplete_edge_snapshot.pop("public_id")
    repair_store.append_assessment(
        capability_id=repair_capability.id,
        scores={dimension: 0.5 for dimension in MATURITY_DIMENSIONS},
        citations={
            dimension: [dict(incomplete_edge_snapshot)] for dimension in MATURITY_DIMENSIONS
        },
        aggregate=0.5,
        watermark_set={"repo": "commit:abc"},
        valid_from="2026-07-15T00:00:00Z",
        asserted_at="2026-07-15T00:00:00Z",
    )
    before_citation_repair = repair_store.state_identity()
    repair_store.ensure_schema()
    after_citation_repair = repair_store.state_identity()
    assert after_citation_repair.state_revision == before_citation_repair.state_revision + 1
    repaired_assessment = repair_store.latest_assessment_for_capability(repair_capability.id)
    assert repaired_assessment is not None
    assert all(
        citation.get("public_id")
        for dimension in MATURITY_DIMENSIONS
        for citation in repaired_assessment.citations[dimension]
    )
    repair_store.ensure_schema()
    assert repair_store.state_identity() == after_citation_repair

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

    missing_column = CkmStore(tmp_path / "missing-column.sqlite3")
    missing_column.ensure_schema()
    with sqlite3.connect(missing_column.db_path) as conn:
        conn.execute("ALTER TABLE ckm_artifact DROP COLUMN watermark")
        conn.commit()
    with pytest.raises(CkmValidationError, match="ckm_artifact.*watermark"):
        missing_column.ensure_schema()

    blank_identity = CkmStore(tmp_path / "blank-identity.sqlite3")
    blank_identity.ensure_schema()
    blank_capability = _capability(blank_identity)
    before_blank_identity = blank_identity.state_identity()
    with sqlite3.connect(blank_identity.db_path) as conn:
        conn.execute(
            "UPDATE ckm_capability SET public_id = '' WHERE id = ?",
            (blank_capability.id,),
        )
        conn.commit()
    with pytest.raises(CkmValidationError, match="ckm_capability.public_id.*blank"):
        blank_identity.ensure_schema()
    assert blank_identity.state_identity() == before_blank_identity
    with sqlite3.connect(blank_identity.db_path) as conn:
        assert conn.execute(
            "SELECT public_id FROM ckm_capability WHERE id = ?",
            (blank_capability.id,),
        ).fetchone()[0] == ""

    assert set(legacy.table_names()) == set(CKM_TABLE_NAMES)

    migrated_inferred_public_id = migrated_inferred.public_id
    legacy.rebuild(retained_public_ids=legacy.active_public_ids())
    rebuilt_inferred = legacy.upsert_capability(
        identity_key=migrated_inferred.identity_key,
        name="Legacy inferred capability",
        definition="Pre-Q1 inferred fixture.",
        existence_provenance="receipt:legacy-inference",
    )
    assert rebuilt_inferred.public_id == migrated_inferred_public_id
    rebuilt_artifact = _artifact(legacy)
    rebuilt_edge = _edge(legacy, rebuilt_artifact.id, rebuilt_inferred.id)
    rebuilt_edge = legacy.upsert_evidence_edge(
        artifact_id=rebuilt_artifact.id,
        capability_id=rebuilt_inferred.id,
        evidence_kind="doc",
        polarity="supports",
        maturity_dimension="documentation_quality",
        confidence=0.9,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref=rebuilt_artifact.source_ref,
        basis=rebuilt_edge.basis,
    )
    rebuilt_unselected_artifact = _artifact(
        legacy, source_ref="docs/measurement-diagram.md"
    )
    rebuilt_unselected_edge = _edge(
        legacy,
        rebuilt_unselected_artifact.id,
        rebuilt_inferred.id,
        basis="diagram:1",
        source_ref=rebuilt_unselected_artifact.source_ref,
    )
    rebuilt_assessment = legacy.append_assessment(
        capability_id=rebuilt_inferred.id,
        scores=scores,
        citations={
            dimension: [rebuilt_edge.to_dict()] for dimension in MATURITY_DIMENSIONS
        },
        aggregate=0.5,
        edge_fingerprint=assessment_fingerprint(
            [rebuilt_edge, rebuilt_unselected_edge],
            {
                rebuilt_artifact.id: rebuilt_artifact,
                rebuilt_unselected_artifact.id: rebuilt_unselected_artifact,
            },
            watermark_set={"repo": "commit:abc"},
        ),
        watermark_set={"repo": "commit:abc"},
        valid_from="2026-07-15T00:00:00Z",
        asserted_at="2026-07-15T00:00:00Z",
    )
    assert rebuilt_assessment.public_id == migrated_assessment_public_id


def test_envelope_missing_states_and_projection_marker(store: CkmStore) -> None:
    capability = _capability(store)
    snapshot = SnapshotManifest.build(
        state=store.state_identity(),
        taxonomy_digest="taxonomy-v1",
        watermarks={"repo": "commit:abc"},
        provenance=[{"ref_type": "repo", "ref": "fixture@abc"}],
        completeness=CompletenessManifest(
            object_classes=[ObjectClassCompleteness("capability", included=1)],
            complete=True,
        ),
        read_set={"capability": [capability.public_id]},
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
            "unassessed": TaggedValue.unassessed("no assessment has run"),
            "unsupported": TaggedValue.unsupported("not implemented in schema v1"),
        },
    )
    envelope = ResultEnvelope(
        resource_type="capability",
        query_digest=canonical_query_digest({"resource": "capability"}),
        snapshot=snapshot,
        resources=[resource],
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
        "unassessed",
        "unsupported",
    }
    assert envelope["snapshot"]["snapshot_digest"]
    assert envelope["snapshot"]["effective_audience"] == EFFECTIVE_AUDIENCE
    assert envelope["snapshot"]["access_policy_version"] == ACCESS_POLICY_VERSION
    assert envelope["snapshot"]["redaction_profile"] == REDACTION_PROFILE
    assert envelope["snapshot"]["completeness"]["complete"] is True

    with pytest.raises(ValueError, match="exactly match the snapshot read set"):
        ResultEnvelope(
            resource_type="capability",
            query_digest=canonical_query_digest({"resource": "capability"}),
            snapshot=snapshot,
            resources=[],
        )

    typed_error = CkmContractError(code="unsupported_filter", message="not supported")
    assert ErrorEnvelope(typed_error).to_dict()["error"]["code"] == "unsupported_filter"


def test_snapshot_manifest_accounts_for_complete_scope(store: CkmStore) -> None:
    accounting = [
        ObjectClassCompleteness("capability", included=3, filtered=1),
        ObjectClassCompleteness("artifact", included=5, omitted=1),
        ObjectClassCompleteness("evidence_edge", included=7, truncated=2),
    ]
    incomplete = CompletenessManifest(object_classes=accounting, complete=False)
    snapshot = SnapshotManifest.build(
        state=store.state_identity(),
        taxonomy_digest="taxonomy-v1",
        watermarks={"repo": "commit:abc"},
        provenance=[{"ref_type": "repo", "ref": "fixture@abc"}],
        completeness=incomplete,
        read_set={
            "capability": [f"cap-{index}" for index in range(3)],
            "artifact": [f"artifact-{index}" for index in range(5)],
            "evidence_edge": [f"edge-{index}" for index in range(7)],
        },
    )
    assert snapshot.to_dict()["completeness"] == {
        "complete": False,
        "object_classes": [
            {
                "object_class": item.object_class,
                "included": item.included,
                "filtered": item.filtered,
                "omitted": item.omitted,
                "truncated": item.truncated,
            }
            for item in accounting
        ],
    }
    with pytest.raises(ValueError, match="incomplete snapshot"):
        ResultEnvelope(
            resource_type="capability",
            query_digest=canonical_query_digest({"resource": "capability"}),
            snapshot=snapshot,
            resources=[],
        )
    with pytest.raises(ValueError, match="complete must agree"):
        CompletenessManifest(object_classes=accounting, complete=True)

    complete = CompletenessManifest(
        object_classes=[ObjectClassCompleteness("capability", included=1)],
        complete=True,
    )
    with pytest.raises(ValueError, match="exactly match the declared read-set scope"):
        SnapshotManifest.build(
            state=store.state_identity(),
            taxonomy_digest="taxonomy-v1",
            watermarks={"repo": "commit:abc"},
            provenance=[{"ref_type": "repo", "ref": "fixture@abc"}],
            completeness=complete,
            read_set={"capability": ["capability-one"], "artifact": []},
        )
    with pytest.raises(ValueError, match="included count must match"):
        SnapshotManifest.build(
            state=store.state_identity(),
            taxonomy_digest="taxonomy-v1",
            watermarks={"repo": "commit:abc"},
            provenance=[{"ref_type": "repo", "ref": "fixture@abc"}],
            completeness=complete,
            read_set={"capability": []},
        )

    immutable = SnapshotManifest.build(
        state=store.state_identity(),
        taxonomy_digest="taxonomy-v1",
        watermarks={"repo": "commit:abc"},
        provenance=[{"ref_type": "repo", "ref": "fixture@abc"}],
        completeness=complete,
        read_set={"capability": ["capability-one"]},
    )
    original_digest = immutable.read_set_digest
    original_snapshot = immutable.to_dict()
    with pytest.raises(TypeError):
        immutable.read_set["capability"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        immutable.watermarks["repo"] = "commit:mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        immutable.provenance[0]["ref"] = "fixture@mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        immutable.completeness.object_classes[0] = ObjectClassCompleteness(  # type: ignore[index]
            "artifact", included=0
        )
    assert immutable.read_set == {"capability": ("capability-one",)}
    assert immutable.read_set_digest == original_digest
    assert immutable.to_dict() == original_snapshot

    artifact_only = SnapshotManifest.build(
        state=store.state_identity(),
        taxonomy_digest="taxonomy-v1",
        watermarks={"repo": "commit:abc"},
        provenance=[{"ref_type": "repo", "ref": "fixture@abc"}],
        completeness=CompletenessManifest(
            object_classes=[ObjectClassCompleteness("artifact", included=0)],
            complete=True,
        ),
        read_set={"artifact": []},
    )
    with pytest.raises(ValueError, match="resource type must be declared"):
        ResultEnvelope(
            resource_type="capability",
            query_digest=canonical_query_digest({"resource": "capability"}),
            snapshot=artifact_only,
            resources=[],
        )


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
        (
            {"resource_type": "capability", "effective_audience": "remote_team"},
            "unsupported_access_policy",
        ),
    )
    for arguments, expected_code in cases:
        with pytest.raises(CkmContractError) as refusal:
            validate_contract_request(**arguments)
        assert refusal.value.code == expected_code
        assert refusal.value.to_dict()["code"] == expected_code
