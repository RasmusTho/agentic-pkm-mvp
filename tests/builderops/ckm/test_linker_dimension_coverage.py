"""Every declared maturity dimension must have a producing linker, or be
declared unmeasurable explicitly (models.py :: UNMEASURABLE_MATURITY_DIMENSIONS).

A dimension with zero producing linkers and no declaration degrades silently:
it is ``missing`` for every capability forever, scores ``0.0`` forever, and
nothing fails loudly to say so. This module is the deterministic guard
against that (issue #4258); it names the offending dimension when it fires.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.builderops.ckm.assess import assess_capabilities
from app.builderops.ckm.linkers import link_deterministic
from app.builderops.ckm.models import (
    MATURITY_DIMENSIONS,
    UNMEASURABLE_MATURITY_DIMENSIONS,
    CkmCapability,
)
from app.builderops.ckm.store import CkmStore


def _register(store: CkmStore, source_ref: str, artifact_kind: str, **provenance: object) -> None:
    store.upsert_artifact(
        source_ref=source_ref,
        artifact_kind=artifact_kind,
        source="fixture",
        watermark="one",
        provenance=json.dumps({"source_ref": source_ref, **provenance}),
    )


def _build_full_coverage_fixture(root: Path, store: CkmStore) -> CkmCapability:
    """Register one capability plus a minimal artifact set that exercises
    every deterministic-linker rule family capable of emitting a distinct
    ``maturity_dimension`` value:

    - matrix linker (single-candidate boundary, so no name/source selector is
      needed): a document, an ADR, a source file, and a test cited by one row
      -> documentation_quality, architectural_stability, functional_completeness,
      test_completeness.
    - spec-directory linker: a spec file naming the capability as its
      ``parent_capability`` -> requirement_coverage.
    - github-spec-ref linker: an open issue referencing that spec file
      (neither a closed ``type:task`` nor a merged PR) -> integration_completeness.
    """

    capability = store.upsert_capability(
        identity_key="fixture:coverage:ops-capability",
        name="Ops Capability",
        definition="Fixture capability spanning every linker-producible dimension.",
        existence_provenance="seeded:docs/PLAN.md :: ops",
        lifecycle="confirmed",
        boundary_ref="RCA",
    )

    # NOTE: the doc's filename deliberately avoids the operational-readiness
    # scorer's keyword fallback ("operat", "runbook", "health", "observab",
    # "deploy" -- app/builderops/ckm/assess.py :: _operational) so this fixture
    # stays a clean trace of what the *linkers* produce, not what that
    # unrelated (out-of-scope) scorer heuristic happens to pick up.
    matrix_path = root / "docs/architecture/traceability-matrix.md"
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_path.write_text(
        "| # | Principle | Control boundaries | Contract | Tests |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 1 | Ops readiness needs coverage. | RCA | "
        "[Ops doc](../../docs/PLAN.md) [ADR](../../docs/adr/ADR-9000.md) "
        "[Ops source](../../app/ops.py) | [Ops test](../../tests/test_ops.py) |\n",
        encoding="utf-8",
    )

    spec_path = root / "docs/CAP/TASK.md"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        '---\nparent_capability: "Ops Capability"\n---\n\nOps task body.\n',
        encoding="utf-8",
    )

    _register(store, "docs/PLAN.md", "document")
    _register(store, "docs/adr/ADR-9000.md", "adr")
    _register(store, "app/ops.py", "source_file")
    _register(store, "tests/test_ops.py", "test")
    _register(store, "docs/CAP/TASK.md", "spec")
    _register(
        store,
        "github:issue:1",
        "issue",
        references=["docs/CAP/TASK.md"],
        state="open",
        labels=[],
    )

    return capability


def test_every_dimension_has_a_producing_linker(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    _build_full_coverage_fixture(root, store)

    link_deterministic(store, root)

    produced_dimensions = {edge.maturity_dimension for edge in store.list_evidence_edges()}
    expected_producible = set(MATURITY_DIMENSIONS) - UNMEASURABLE_MATURITY_DIMENSIONS
    missing = sorted(expected_producible - produced_dimensions)
    assert not missing, (
        "declared maturity dimension(s) with no producing deterministic linker: "
        f"{missing}. Either add a producing linker rule in "
        "app/builderops/ckm/linkers.py or declare the dimension unmeasurable in "
        "app/builderops/ckm/models.py :: UNMEASURABLE_MATURITY_DIMENSIONS."
    )


def test_unmeasurable_dimensions_are_declared(tmp_path: Path) -> None:
    # The one currently-known case (issue #4258): operational_readiness has
    # zero producing linkers and must be resolved explicitly rather than left
    # to silently degrade to "missing" / score 0.0 forever.
    assert "operational_readiness" in UNMEASURABLE_MATURITY_DIMENSIONS
    # Declared-unmeasurable dimensions stay declared maturity dimensions; a
    # removal from MATURITY_DIMENSIONS would be a separate, explicit decision.
    assert UNMEASURABLE_MATURITY_DIMENSIONS <= set(MATURITY_DIMENSIONS)

    root = tmp_path / "repo"
    root.mkdir()
    store = CkmStore(tmp_path / "builderops.sqlite3")
    store.ensure_schema()
    capability = _build_full_coverage_fixture(root, store)
    link_deterministic(store, root)

    produced_dimensions = {edge.maturity_dimension for edge in store.list_evidence_edges()}
    stale = sorted(UNMEASURABLE_MATURITY_DIMENSIONS & produced_dimensions)
    assert not stale, (
        f"dimension(s) declared unmeasurable actually have a live deterministic "
        f"producer, so the declaration is stale: {stale}"
    )

    run = assess_capabilities(store)
    assert run.assessed >= 1
    assessment = store.latest_assessment_for_capability(capability.id)
    assert assessment is not None
    for dimension in UNMEASURABLE_MATURITY_DIMENSIONS:
        # The resolution must be readable straight off the model -- a
        # dedicated status, not inferred from an empty evidence/citation table.
        assert assessment.dimension_status[dimension] == "unsupported", (
            f"{dimension} is declared unmeasurable but its assessment "
            f"dimension_status is {assessment.dimension_status[dimension]!r}, "
            "not the model-visible 'unsupported' state"
        )
        assert assessment.scores[dimension] == 0.0
        assert assessment.citations[dimension] == []
