from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

from click.testing import CliRunner

from app.builderops.cli import builderops
from app.builderops.ckm.ingest_repo import iter_docs, iter_schemas, iter_tests
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


def test_matrix_rows_become_edges_on_live_matrix(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ingest_docs(store)
    for artifact in (*iter_tests(REPO_ROOT), *iter_schemas(REPO_ROOT)):
        store.upsert_artifact(
            source_ref=artifact.natural_key,
            artifact_kind=artifact.artifact_kind,
            source=artifact.source,
            watermark=artifact.source_watermark,
            provenance=artifact.provenance,
        )
    matrix_path = REPO_ROOT / "docs/architecture/traceability-matrix.md"
    matrix_lines = matrix_path.read_text(encoding="utf-8").splitlines()
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
            provenance=json.dumps({"references": []}),
        )
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
    rca_ids = {
        capability.id
        for capability in capability_by_id.values()
        if capability.boundary_ref == "RCA"
    }
    assert rca_ids <= {edge.capability_id for edge in matrix_edges}
    artifact_by_id = {item.id: item for item in store.list_artifacts()}
    assert any(artifact_by_id[edge.artifact_id].artifact_kind == "adr" for edge in matrix_edges)
    edge_keys = {
        (artifact_by_id[edge.artifact_id].source_ref, edge.capability_id, edge.basis)
        for edge in matrix_edges
    }
    artifacts = {item.source_ref for item in artifact_by_id.values()}
    capabilities_by_boundary: dict[str, set[str]] = {}
    for capability in capability_by_id.values():
        if capability.boundary_ref:
            capabilities_by_boundary.setdefault(capability.boundary_ref, set()).add(capability.id)
    for line_number, line in enumerate(matrix_lines, 1):
        if not re.match(r"^\|\s*\d+\s*\|", line):
            continue
        boundaries = set(re.findall(r"\b(?:HIX|WSP|HKA|SIP|GOV|EBF|PDM|DRI|RCA|MEM|CAO|EXE|SFC|OEF|CES)\b", line))
        references = {
            match.replace("../", "")
            for match in re.findall(
                r"(?:\.\./)*(?:app|docs|tests|schemas)/[A-Za-z0-9_./-]+(?:\.md|\.py|\.json)?",
                line,
            )
        }
        references.update(
            posixpath.normpath(posixpath.join("docs/architecture", target))
            for target in re.findall(r"\]\(([^)#]+(?:\.md|\.py|\.json))\)", line)
        )
        references.update(f"github:issue:{number}" for number in re.findall(r"(?<![\w/])#(\d+)\b", line))
        for number in re.findall(r"\bADR-(\d{4})\b", line):
            references.update(ref for ref in artifacts if ref.startswith(f"docs/adr/ADR-{number}"))
        for reference in references & artifacts:
            for boundary in boundaries:
                for capability_id in capabilities_by_boundary.get(boundary, set()):
                    assert (reference, capability_id, f"matrix:row:{line_number}") in edge_keys


def test_edges_carry_method_lifecycle_basis(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ingest_docs(store)
    link_deterministic(store, REPO_ROOT)
    edges = store.list_evidence_edges()
    assert edges
    assert all(edge.extraction_method == "deterministic" for edge in edges)
    assert all(edge.lifecycle == "confirmed" for edge in edges)
    assert all(edge.basis for edge in edges)


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
