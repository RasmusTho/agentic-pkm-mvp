"""BCP-04 AC6: delivery-manifest routing is explicit and non-transitive.

The client loads the addressed repo's delivery manifest and routes by
``(RepoRef, stack, task-class)``. A manifest resolved for one repository is
never reused or inferred for another, even when the stack and task class match;
missing or ambiguous manifests and implicit (CWD-derived) repository authority
fail closed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.builderops.control_plane.routing import (
    DeliveryManifestRegistry,
    ManifestError,
    ManifestNotFoundError,
    RepoRef,
    RepoRefError,
    RouteResolutionError,
)

REPO_A = "RasmusTho/agentic-pkm-mvp"
REPO_B = "RasmusTho/example-second-repo"


def _doc(repository: str, policy_tag: str) -> dict[str, object]:
    return {
        "repository": repository,
        "routes": [
            {
                "stack": "builderops-control-plane",
                "task_class": "implementation",
                "policy": {"tcd_route": policy_tag, "model_family": "sonnet"},
            }
        ],
    }


def test_repo_stack_task_routing_is_explicit_and_non_transitive() -> None:
    registry = DeliveryManifestRegistry.from_documents(
        [_doc(REPO_A, "route-a"), _doc(REPO_B, "route-b")]
    )
    repo_a = RepoRef.parse(REPO_A)
    repo_b = RepoRef.parse(REPO_B)

    route_a = registry.resolve_route(repo_a, "builderops-control-plane", "implementation")
    route_b = registry.resolve_route(repo_b, "builderops-control-plane", "implementation")

    # Each repo resolves from its OWN manifest even though the stack and
    # task-class are identical: routing is keyed by the full RepoRef triple.
    assert route_a.repository == repo_a.canonical
    assert route_b.repository == repo_b.canonical
    assert route_a.policy["tcd_route"] == "route-a"
    assert route_b.policy["tcd_route"] == "route-b"
    assert route_a.repository != route_b.repository

    # Non-transitive: a repo with no loaded manifest never borrows another
    # repo's defaults, even when the requested stack/task-class exists elsewhere.
    repo_c = RepoRef.parse("RasmusTho/heimdal")
    with pytest.raises(ManifestNotFoundError):
        registry.resolve_route(repo_c, "builderops-control-plane", "implementation")


def test_only_repo_a_manifest_never_serves_repo_b() -> None:
    registry = DeliveryManifestRegistry.from_documents([_doc(REPO_A, "route-a")])
    # Repo A resolves; repo B (identical stack/task-class, no manifest) fails closed.
    assert registry.resolve_route(
        RepoRef.parse(REPO_A), "builderops-control-plane", "implementation"
    )
    with pytest.raises(ManifestNotFoundError):
        registry.resolve_route(
            RepoRef.parse(REPO_B), "builderops-control-plane", "implementation"
        )


def test_missing_route_within_a_manifest_fails_closed() -> None:
    registry = DeliveryManifestRegistry.from_documents([_doc(REPO_A, "route-a")])
    with pytest.raises(RouteResolutionError):
        registry.resolve_route(
            RepoRef.parse(REPO_A), "builderops-control-plane", "verification"
        )


def test_ambiguous_manifest_fails_closed() -> None:
    ambiguous = {
        "repository": REPO_A,
        "routes": [
            {"stack": "s1", "task_class": "implementation", "policy": {"a": 1}},
            {"stack": "s1", "task_class": "implementation", "policy": {"a": 2}},
        ],
    }
    with pytest.raises(ManifestError):
        DeliveryManifestRegistry.from_documents([ambiguous])


def test_duplicate_repo_manifests_fail_closed() -> None:
    with pytest.raises(ManifestError):
        DeliveryManifestRegistry.from_documents([_doc(REPO_A, "x"), _doc(REPO_A, "y")])


def test_repo_ref_requires_explicit_unambiguous_reference() -> None:
    # No CWD/git inference: a missing or partial reference fails closed.
    for bad in (None, "", "   ", "agentic-pkm-mvp", "owner/", "/name", "a/b/c"):
        with pytest.raises(RepoRefError):
            RepoRef.parse(bad)  # type: ignore[arg-type]


def test_registry_from_directory_round_trip(tmp_path: Path) -> None:
    (tmp_path / "repo-a.json").write_text(json.dumps(_doc(REPO_A, "route-a")), encoding="utf-8")
    registry = DeliveryManifestRegistry.from_directory(tmp_path)
    route = registry.resolve_route(
        RepoRef.parse(REPO_A), "builderops-control-plane", "implementation"
    )
    assert route.policy["tcd_route"] == "route-a"
