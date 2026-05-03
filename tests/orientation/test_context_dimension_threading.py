from __future__ import annotations

from app.orientation.runtime import pass_through_context_dimensions


def test_orientation_does_not_collapse_dimensions() -> None:
    record = {
        "context_dimensions": {
            "scope": "work",
            "sphere_memberships": ["team", "learning"],
            "situated_identity": "maker",
        }
    }

    dims = pass_through_context_dimensions(record)

    assert dims["scope"] == "work"
    assert dims["sphere_memberships"] == ["team", "learning"]
    assert dims["situated_identity"] == "maker"
    assert "domain" not in dims
