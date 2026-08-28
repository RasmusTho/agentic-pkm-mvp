from __future__ import annotations

from pathlib import Path

from app.builderops.devui_exact_reuse_candidate import (
    validate_devui_exact_reuse_candidate,
)


def test_candidate_inventory_git_object_and_transform_binding_fails_closed() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    result = validate_devui_exact_reuse_candidate(repo_root, revision="HEAD")

    assert result == {
        "candidate_subtree": "companion-ui/companion-app/companion_ui/workspace/devui_candidate",
        "inventory_status": "complete",
        "source_objects_status": "verified",
        "transform_binding_status": "closed_allowlist",
        "no_egress_status": "verified",
    }
