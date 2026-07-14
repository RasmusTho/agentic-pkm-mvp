from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from tests.invariants._helpers import load_defs


def _validator() -> Draft202012Validator:
    definitions = load_defs()["$defs"]
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": definitions,
            "$ref": "#/$defs/cross_scope_flow_ref",
        }
    )


def _flow(operation: str) -> dict[str, object]:
    return {
        "flow_id": "flow:episode-fuse:work-private",
        "source_scope": "scope:work/project-alpha",
        "target_scope": "scope:private/journal",
        "allowed_operations": [operation],
        "source_roles_allowed": ["work_project"],
        "authority_states_allowed": ["accepted"],
        "evidence_roles_allowed": ["background"],
        "confirmation_required": True,
        "audit_required": True,
    }


def test_cross_scope_flow_allows_episode_fuse_operation() -> None:
    _validator().validate(_flow("episode_fuse"))


def test_cross_scope_flow_rejects_unknown_operation() -> None:
    with pytest.raises(ValidationError):
        _validator().validate(_flow("unknown_operation"))
