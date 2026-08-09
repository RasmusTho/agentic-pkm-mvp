"""Contract checks for the separate Builder System Control specification."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "DEVUI_BUILDER_SYSTEM_CONTROL" / "README.md"


def _spec() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def _normalized_spec() -> str:
    return " ".join(_spec().split())


def test_spec_defines_information_architecture_and_hard_boundary() -> None:
    spec = _spec()
    normalized = _normalized_spec()

    assert "## Information architecture and hard boundary" in spec
    assert "contract_version: builder-system-control-view.v1" in spec
    assert "primary_identity: builder_system" in spec
    assert "not a tab, panel, or evidence group inside Focus" in spec
    assert "navigation, never a data join" in spec
    assert "No runtime, route, or visual implementation is delivered by this specification." in normalized


def test_spec_preserves_source_authority_and_lifecycle() -> None:
    spec = _spec()
    normalized = _normalized_spec()

    assert "### GoverningDocumentView.v1" in spec
    assert "### WorkflowAdapterView.v1" in spec
    assert "### CapabilityBindingView.v1" in spec
    assert "### CoverageView.v1" in spec
    assert "### RouteDeviationView.v1" in spec
    assert "source_ref: SourceRef.v1" in spec
    assert "authority_scope:" in spec
    assert "lifecycle:" in spec
    assert "owning_workflow_refs:" in spec
    assert "A skill is never the policy owner." in spec
    assert "A capability is never the policy or workflow owner." in normalized


def test_spec_requires_correlated_deviation_and_existing_route() -> None:
    spec = _spec()
    normalized = _normalized_spec()

    assert "correlation_ref: SourceRef.v1" in spec
    assert "intended_route_refs:" in spec
    assert "observed_route_refs:" in spec
    assert "existing_repair_route_ref: GovernedRouteRef.v1 | null" in spec
    assert "Textual similarity, shared provider metadata, and temporal proximity are not correlation." in normalized
    assert "does not invent a severity" in spec
    assert "A null `existing_repair_route_ref` requires `source_state.linkage: unlinked` and no offered action." in normalized


def test_spec_separates_current_target_and_authority_questions() -> None:
    spec = _spec()

    assert "## Current-to-target truth" in spec
    assert "## Open implementation dependencies" in spec
    assert "## Open authority questions" in spec
    assert "Current delivered input" in spec
    assert "Target contract; not delivered" in spec
    assert "No owner decision blocks this docs-only specification." in spec


def test_spec_has_bounded_sequenced_follow_up() -> None:
    spec = _spec()
    normalized = _normalized_spec()

    assert "## Sequenced follow-up issue breakdown" in spec
    assert "BSC-01 — compose the source inventory" in spec
    assert "BSC-02 — compose adapters and capabilities" in spec
    assert "BSC-03 — compose coverage and route deviations" in spec
    assert "BSC-04 — governed visual design handoff" in spec
    assert "BSC-05 — route previews over existing workflows" in spec
    assert "must not be filed as children of Focus parent #4693" in normalized
    assert "No follow-up creates a policy engine, workflow engine, task system, or source registry." in normalized
