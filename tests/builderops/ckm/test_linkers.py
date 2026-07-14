from __future__ import annotations

import json
import re
from pathlib import Path

from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.ingest_repo import iter_docs, iter_schemas, iter_source, iter_tests
from app.builderops.ckm.linkers import link_deterministic
from app.builderops.ckm.seed import seed_capabilities
from app.builderops.ckm.store import CkmStore

REPO_ROOT = Path(__file__).resolve().parents[3]


def _store(tmp_path: Path) -> CkmStore:
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    seed_capabilities(store, repo_root=REPO_ROOT)
    return store


def _ingest_docs(store: CkmStore) -> None:
    for artifact in iter_docs(REPO_ROOT):
        store.upsert_artifact(
            source_ref=artifact.natural_key,
            artifact_kind=artifact.artifact_kind,
            source=artifact.source,
            watermark=artifact.source_watermark,
            provenance=artifact.provenance,
        )


def _ingest_matrix_inputs(store: CkmStore) -> None:
    _ingest_docs(store)
    for artifact in (
        *iter_tests(REPO_ROOT),
        *iter_source(REPO_ROOT),
        *iter_schemas(REPO_ROOT),
    ):
        store.upsert_artifact(
            source_ref=artifact.natural_key,
            artifact_kind=artifact.artifact_kind,
            source=artifact.source,
            watermark=artifact.source_watermark,
            provenance=artifact.provenance,
        )
    matrix_lines = (
        REPO_ROOT / "docs/architecture/traceability-matrix.md"
    ).read_text(encoding="utf-8").splitlines()
    issue_numbers = {
        number
        for line in matrix_lines
        if re.match(r"^\|\s*\d+\s*\|", line)
        for number in re.findall(r"(?<![\w/])#(\d+)\b", line)
    }
    for number in issue_numbers:
        store.upsert_artifact(
            source_ref=f"github:issue:{number}",
            artifact_kind="issue",
            source="fixture",
            watermark="one",
            provenance=json.dumps({"title": f"Issue {number}", "references": []}),
        )


def test_matrix_rows_become_edges_on_live_matrix(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ingest_matrix_inputs(store)
    result = link_deterministic(store, REPO_ROOT)
    matrix_edges = [
        edge for edge in store.list_evidence_edges()
        if edge.basis.startswith("matrix:")
    ]
    assert result["matrix"] > 0
    assert matrix_edges
    capability_by_id = {item.id: item for item in store.list_capabilities()}
    assert {
        capability_by_id[edge.capability_id].boundary_ref for edge in matrix_edges
    } >= {"RCA", "GOV", "SIP"}
    artifact_by_id = {item.id: item for item in store.list_artifacts()}
    assert any(artifact_by_id[edge.artifact_id].artifact_kind == "adr" for edge in matrix_edges)
    assert any(edge.basis.startswith("matrix:row:43|") for edge in matrix_edges)


def test_live_retrieval_has_capability_specific_functional_evidence(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _ingest_matrix_inputs(store)

    link_deterministic(store, REPO_ROOT)

    capabilities = {item.id: item for item in store.list_capabilities()}
    functional_edges = [
        edge for edge in store.list_evidence_edges()
        if edge.maturity_dimension == "functional_completeness"
        and edge.basis.startswith("matrix:")
    ]
    retrieval = next(item for item in capabilities.values() if item.name == "Retrieval")
    context = next(item for item in capabilities.values() if item.name == "Context building")

    retrieval_edges = [
        edge for edge in functional_edges if edge.capability_id == retrieval.id
    ]
    context_edges = [
        edge for edge in functional_edges if edge.capability_id == context.id
    ]
    assert retrieval_edges
    assert len(retrieval_edges) > len(context_edges)
    artifacts = {item.id: item for item in store.list_artifacts()}
    retrieval_sources = {
        artifacts[edge.artifact_id].source_ref
        for edge in retrieval_edges
        if artifacts[edge.artifact_id].artifact_kind == "source_file"
    }
    assert "app/retrieval/capability.py" in retrieval_sources
    assert all("|citation:app/" in edge.basis for edge in retrieval_edges if edge.evidence_kind == "source")
    assert {edge.artifact_id for edge in retrieval_edges} != {
        edge.artifact_id for edge in context_edges
    }


def test_shared_boundary_evidence_is_capability_specific(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ingest_matrix_inputs(store)

    link_deterministic(store, REPO_ROOT)

    capabilities = {item.id: item for item in store.list_capabilities()}
    artifacts = {item.id: item for item in store.list_artifacts()}
    artifacts_by_ref = {item.source_ref: item for item in artifacts.values()}
    matrix_lines = (
        REPO_ROOT / "docs/architecture/traceability-matrix.md"
    ).read_text(encoding="utf-8").splitlines()
    boundary_counts: dict[str, int] = {}
    for capability in capabilities.values():
        if capability.boundary_ref:
            boundary_counts[capability.boundary_ref] = (
                boundary_counts.get(capability.boundary_ref, 0) + 1
            )
    matrix_edges = [
        edge for edge in store.list_evidence_edges()
        if edge.basis.startswith("matrix:")
        and (
            boundary := capabilities[edge.capability_id].boundary_ref
        ) is not None
        and boundary_counts[boundary] > 1
    ]
    assert matrix_edges

    for edge in matrix_edges:
        basis = edge.basis
        assert "|selector:" in basis
        row_number = int(re.search(r"(?:^|:)row:(\d+)", basis).group(1))
        citation_ref = basis.split("|citation:", 1)[1].split("|", 1)[0]
        selector_kind, selector_value = basis.split("|selector:", 1)[1].split(":", 1)
        row = matrix_lines[row_number - 1]
        citation = artifacts_by_ref[citation_ref]
        artifact_path = REPO_ROOT / citation.source_ref
        provenance = json.loads(citation.provenance)
        source_text = (
            artifact_path.read_text(encoding="utf-8")
            if artifact_path.is_file()
            else "\n".join(
                str(provenance.get(key, "")) for key in ("title", "payload_summary")
            )
        )
        assert selector_kind in {"row-name", "source-name", "seed-source"}
        if selector_kind == "row-name":
            assert re.search(re.escape(selector_value), row, re.IGNORECASE)
        elif selector_kind == "source-name":
            assert re.search(re.escape(selector_value), source_text, re.IGNORECASE)
        else:
            assert citation.source_ref == selector_value


def test_matrix_test_imports_do_not_manufacture_unrelated_source_edges(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    matrix = root / "docs/architecture/traceability-matrix.md"
    retrieval_source = root / "app/retrieval/capability.py"
    unrelated_source = root / "app/episodes/segmenter.py"
    test_path = root / "tests/test_retrieval.py"
    for path in (matrix, retrieval_source, unrelated_source, test_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    matrix.write_text(
        "| # | Principle | Control boundaries | Contract | Tests |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 1 | Retrieval produces candidates. | RCA | "
        "[Retrieval implementation](../../app/retrieval/capability.py) | "
        "[retrieval test](../../tests/test_retrieval.py) |\n",
        encoding="utf-8",
    )
    retrieval_source.write_text("def retrieve() -> None:\n    pass\n", encoding="utf-8")
    unrelated_source.write_text("def segment() -> None:\n    pass\n", encoding="utf-8")
    test_path.write_text(
        "from app.retrieval.capability import retrieve\n"
        "from app.episodes.segmenter import segment\n",
        encoding="utf-8",
    )

    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    retrieval = store.upsert_capability(
        name="Retrieval",
        definition="Fixture",
        existence_provenance="seeded:docs/retrieval.md :: retrieval",
        lifecycle="confirmed",
        boundary_ref="RCA",
    )
    store.upsert_capability(
        name="Context building",
        definition="Fixture",
        existence_provenance="seeded:docs/context.md :: context",
        lifecycle="confirmed",
        boundary_ref="RCA",
    )
    for source_ref, kind in (
        ("app/retrieval/capability.py", "source_file"),
        ("app/episodes/segmenter.py", "source_file"),
        ("tests/test_retrieval.py", "test"),
    ):
        store.upsert_artifact(
            source_ref=source_ref,
            artifact_kind=kind,
            source="fixture",
            watermark="one",
            provenance=json.dumps({"source_ref": source_ref}),
        )

    link_deterministic(store, root)

    artifacts = {item.id: item for item in store.list_artifacts()}
    retrieval_edges = [
        edge for edge in store.list_evidence_edges()
        if edge.capability_id == retrieval.id
    ]
    source_refs = {
        artifacts[edge.artifact_id].source_ref
        for edge in retrieval_edges
        if artifacts[edge.artifact_id].artifact_kind == "source_file"
    }
    assert source_refs == {"app/retrieval/capability.py"}
    direct = next(edge for edge in retrieval_edges if edge.evidence_kind == "source")
    assert direct.basis == (
        "matrix:row:3|citation:app/retrieval/capability.py|selector:row-name:Retrieval"
    )
    assert any(
        edge.evidence_kind == "test"
        and edge.basis == "test-code:app/retrieval/capability.py"
        for edge in retrieval_edges
    )


def test_edges_carry_method_lifecycle_basis(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ingest_docs(store)
    link_deterministic(store, REPO_ROOT)
    edges = store.list_evidence_edges()
    assert edges
    assert all(edge.extraction_method == "deterministic" for edge in edges)
    assert all(edge.lifecycle == "confirmed" for edge in edges)
    assert all(edge.basis for edge in edges)


def test_adr_shared_seed_path_requires_capability_specific_selector(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    adr_path = root / "docs/adr/ADR-9000-shared-seed.md"
    adr_path.parent.mkdir(parents=True)
    adr_path.write_text(
        "# ADR-9000\n\nSee docs/shared-owner.md for the taxonomy.\n",
        encoding="utf-8",
    )
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    capabilities = {
        name: store.upsert_capability(
            name=name,
            definition="Fixture capability",
            existence_provenance="seeded:docs/shared-owner.md :: Shared taxonomy",
            boundary_ref=boundary,
        )
        for name, boundary in (
            ("Human Authority Kernel", None),
            ("Retrieval & Context Assembly", "RCA"),
            ("Machine Memory & Learning", "MEM"),
        )
    }
    adr = store.upsert_artifact(
        source_ref="docs/adr/ADR-9000-shared-seed.md",
        artifact_kind="adr",
        source="repo_docs",
        watermark="one",
        provenance='{"source_ref":"docs/adr/ADR-9000-shared-seed.md"}',
    )

    path_only = link_deterministic(store, root)

    assert path_only["adr"] == 0
    assert not [edge for edge in store.list_evidence_edges() if edge.artifact_id == adr.id]

    adr_path.write_text(
        "# ADR-9000\n\nSee docs/shared-owner.md. This decision covers RCA and "
        "the Human Authority Kernel.\n",
        encoding="utf-8",
    )
    selected = link_deterministic(store, root)
    adr_edges = [
        edge for edge in store.list_evidence_edges() if edge.artifact_id == adr.id
    ]

    assert selected["adr"] == 2
    assert {edge.capability_id for edge in adr_edges} == {
        capabilities["Human Authority Kernel"].id,
        capabilities["Retrieval & Context Assembly"].id,
    }
    assert {edge.basis for edge in adr_edges} == {
        "adr-reference:docs/shared-owner.md|selector:name:Human Authority Kernel",
        "adr-reference:docs/shared-owner.md|selector:boundary:RCA",
    }


def test_live_adr_shared_seed_associations_name_their_selector(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ingest_docs(store)

    link_deterministic(store, REPO_ROOT)

    artifacts = {artifact.id: artifact for artifact in store.list_artifacts()}
    capabilities = {capability.id: capability for capability in store.list_capabilities()}
    shared_edges = [
        edge
        for edge in store.list_evidence_edges()
        if edge.basis.startswith(
            "adr-reference:docs/SYSTEM_BREAKDOWN_STRUCTURE.md|selector:"
        )
    ]
    assert shared_edges
    assert not any(
        artifacts[edge.artifact_id].source_ref
        in {
            "docs/adr/ADR-0015-authority-first-target-sbs.md",
            "docs/adr/ADR-0016-contract-first-module-lazy-sbs.md",
        }
        for edge in shared_edges
    )
    for edge in shared_edges:
        artifact = artifacts[edge.artifact_id]
        capability = capabilities[edge.capability_id]
        text = (REPO_ROOT / artifact.source_ref).read_text(encoding="utf-8")
        selector = edge.basis.split("|selector:", 1)[1]
        selector_kind, selector_value = selector.split(":", 1)
        if selector_kind == "boundary":
            assert capability.boundary_ref == selector_value
            assert re.search(
                rf"(?<![A-Z0-9]){re.escape(selector_value)}(?![A-Z0-9])", text
            )
        else:
            assert selector_kind in {"name", "anchor"}
            assert re.search(re.escape(selector_value), text, re.IGNORECASE)
    assert any(
        artifacts[edge.artifact_id].source_ref
        == "docs/adr/ADR-0020-sfc-single-node-upgrade-path.md"
        and capabilities[edge.capability_id].boundary_ref == "SFC"
        for edge in shared_edges
    )


def test_link_idempotent_incremental(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ingest_docs(store)
    first = link_deterministic(store, REPO_ROOT)
    first_edges = {
        (edge.artifact_id, edge.capability_id, edge.basis): edge.id
        for edge in store.list_evidence_edges()
    }
    sample = next(iter(store.list_evidence_edges()))
    store.upsert_evidence_edge(
        artifact_id=sample.artifact_id,
        capability_id=sample.capability_id,
        evidence_kind=sample.evidence_kind,
        polarity="supports",
        maturity_dimension=sample.maturity_dimension,
        confidence=1.0,
        extraction_method="deterministic",
        lifecycle="confirmed",
        source_ref=sample.source_ref,
        basis="matrix:removed-source-reference",
    )
    second = link_deterministic(store, REPO_ROOT)
    assert first["matrix"] > 0
    assert sum(second[name] for name in ("matrix", "spec", "adr", "test_code", "github_ref")) == 0
    assert second["removed"] == 1
    assert {
        (edge.artifact_id, edge.capability_id, edge.basis): edge.id
        for edge in store.list_evidence_edges()
    } == first_edges
    capability = next(
        item for item in store.list_capabilities() if item.existence_provenance.startswith("seeded:")
    )
    seed_path = capability.existence_provenance.removeprefix("seeded:").split("::", 1)[0].strip()
    store.upsert_artifact(
        source_ref="github:issue:incremental",
        artifact_kind="issue",
        source="fixture",
        watermark="new",
        provenance=json.dumps({"references": [seed_path]}),
    )
    incremental = link_deterministic(store, REPO_ROOT)
    assert incremental["github_ref"] == 1
    assert sum(
        incremental[name] for name in ("matrix", "spec", "adr", "test_code")
    ) == 0


def test_spec_test_code_and_github_linker_families(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "docs/CAP").mkdir(parents=True)
    (root / "app/foo.py").write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
    (root / "tests/test_foo.py").write_text(
        "from app.foo import value\n\ndef test_value():\n    assert value() == 1\n",
        encoding="utf-8",
    )
    (root / "docs/CAP/TASK.md").write_text(
        '---\nparent_capability: "Example Capability"\n---\n\nImplementation: app/foo.py\n',
        encoding="utf-8",
    )
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    store.upsert_capability(
        name="Example Capability",
        definition="Fixture capability",
        existence_provenance="seeded:docs/owner.md :: example",
        lifecycle="confirmed",
    )

    def artifact(
        source_ref: str,
        kind: str,
        references: list[str] | None = None,
        **provenance: object,
    ):
        return store.upsert_artifact(
            source_ref=source_ref,
            artifact_kind=kind,
            source="fixture",
            watermark="one",
            provenance=json.dumps({
                "source_ref": source_ref,
                "references": references or [],
                **provenance,
            }),
        )

    source = artifact("app/foo.py", "source_file")
    test = artifact("tests/test_foo.py", "test")
    spec = artifact("docs/CAP/TASK.md", "spec")
    issue = artifact(
        "github:issue:1", "issue", ["docs/CAP/TASK.md"], state="open", labels=[]
    )
    pull_request = artifact(
        "github:pull:2", "pull_request", ["docs/owner.md"], state="open", merged_at=None
    )
    closed_task = artifact(
        "github:issue:3",
        "issue",
        ["docs/owner.md"],
        state="closed",
        labels=["type:task"],
    )
    merged_pr = artifact(
        "github:pull:4",
        "pull_request",
        ["docs/owner.md"],
        state="closed",
        merged_at="2026-07-01T00:00:00Z",
    )

    result = link_deterministic(store, root)
    edges = store.list_evidence_edges()
    by_artifact = {
        item.id: item for item in (source, test, spec, issue, pull_request, closed_task, merged_pr)
    }
    linked = {
        (by_artifact[edge.artifact_id].source_ref, edge.basis)
        for edge in edges
        if edge.artifact_id in by_artifact
    }
    assert result["spec"] == 2
    assert result["test_code"] == 1
    assert result["github_ref"] == 4
    assert ("app/foo.py", "spec-source:docs/CAP/TASK.md") in linked
    assert ("tests/test_foo.py", "test-code:app/foo.py") in linked
    assert ("docs/CAP/TASK.md", "spec-directory:docs/CAP/TASK.md") in linked
    assert ("github:issue:1", "github-spec-ref:docs/CAP/TASK.md") in linked
    assert ("github:pull:2", "github-ref:docs/owner.md") in linked
    dimensions = {by_artifact[edge.artifact_id].source_ref: edge.maturity_dimension for edge in edges if edge.artifact_id in by_artifact and edge.basis.startswith("github")}
    assert dimensions["github:issue:1"] == "integration_completeness"
    assert dimensions["github:pull:2"] == "integration_completeness"
    assert dimensions["github:issue:3"] == "requirement_coverage"
    assert dimensions["github:pull:4"] == "functional_completeness"

    artifact(
        "github:issue:1",
        "issue",
        ["docs/CAP/TASK.md"],
        state="closed",
        labels=["type:task"],
    )
    artifact(
        "github:pull:2",
        "pull_request",
        ["docs/owner.md"],
        state="closed",
        merged_at="2026-07-02T00:00:00Z",
    )
    transition = link_deterministic(store, root)
    transitioned = {
        by_artifact[edge.artifact_id].source_ref: edge.maturity_dimension
        for edge in store.list_evidence_edges()
        if edge.artifact_id in {issue.id, pull_request.id}
        and edge.basis.startswith("github")
    }
    assert transition["github_ref"] == 0
    assert transitioned["github:issue:1"] == "requirement_coverage"
    assert transitioned["github:pull:2"] == "functional_completeness"


def test_candidate_inference_never_promotes_to_confirmed_test_edge(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app/foo.py").write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
    (root / "tests/test_foo.py").write_text("from app.foo import value\n", encoding="utf-8")
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    capability = store.upsert_capability(
        name="Inferred Capability",
        definition="Fixture",
        existence_provenance="seeded:docs/owner.md :: inferred",
    )
    source = store.upsert_artifact(
        source_ref="app/foo.py",
        artifact_kind="source_file",
        source="fixture",
        watermark="one",
        provenance='{"source_ref":"app/foo.py"}',
    )
    store.upsert_artifact(
        source_ref="tests/test_foo.py",
        artifact_kind="test",
        source="fixture",
        watermark="one",
        provenance='{"source_ref":"tests/test_foo.py"}',
    )
    store.upsert_evidence_edge(
        artifact_id=source.id,
        capability_id=capability.id,
        evidence_kind="source",
        polarity="supports",
        maturity_dimension="functional_completeness",
        confidence=0.5,
        extraction_method="inferred",
        lifecycle="candidate",
        source_ref=source.source_ref,
        basis="inferred:fixture",
        model="fixture-model",
        provider="fixture-provider",
    )

    result = link_deterministic(store, root)

    assert result["test_code"] == 0
    assert not any(edge.basis.startswith("test-code:") for edge in store.list_evidence_edges())


def test_unlinked_backlog_reported(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_artifact(
        source_ref="docs/unlinked.md",
        artifact_kind="document",
        source="repo_docs",
        watermark="one",
        provenance='{"source_ref":"docs/unlinked.md"}',
    )
    result = link_deterministic(store, REPO_ROOT)
    assert result["unlinked_artifacts"] == 1

    runner = CliRunner()
    invocation = runner.invoke(
        builderops,
        ["--db-path", str(store.db_path), "ckm", "link", "--repo-root", str(REPO_ROOT)],
    )
    assert invocation.exit_code == 0
    assert "unlinked artifacts: 1" in invocation.output
