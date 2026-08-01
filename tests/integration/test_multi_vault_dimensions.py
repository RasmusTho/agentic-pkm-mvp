"""MVR-04 (#3858): the parent dimension contract, end to end.

Contract: `docs/MULTI_VAULT_RUNTIME/GROUP_VAULT_BINDINGS_BY_DIMENSION.md :: Concretely`
("A `work` dimension contains vaults A and B. Resolving it yields two separate bindings,
each with its own GOV verdict and provenance. Deleting `work` leaves A and B registered and
untouched.").

This is the whole-contract proof: stored membership preserves each binding's independent
authority and provenance, and grouping never upgrades access.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.active_context_selection as selection_routes
from app.api.app import app
from app.instance.active_context_service import (
    ACTION_DIMENSION_RESOLVE,
    PERMISSION_SELECTION_MANAGE,
    WRITE_CLASS_READ,
    build_authorizer,
    resolve_principal,
)
from app.instance.runtime import open_vault_dimension_service
from app.instance.vault_dimensions import (
    FORBIDDEN_DIMENSION_FIELDS,
    DimensionResolution,
    ResolvedMember,
    VaultDimension,
    parse_dimensions,
)
from tests._mvr03_principal_harness import provisioned_instance

DIMENSIONS_URL = "/api/instance/dimensions"
SELECTION_URL = "/api/companion/active-context/selection"


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    runtime, first, extra, record = provisioned_instance(tmp_path, extra_roots=("two",))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    selection_routes.reset_selection_store_for_tests()
    return runtime, first, extra[0], record


def test_dimension_preserves_per_binding_authority_and_provenance(instance) -> None:
    """A `work` dimension over A and B: two bindings, two verdicts, two provenances."""

    runtime, vault_a, vault_b, record = instance
    client = TestClient(app)

    created = client.post(
        DIMENSIONS_URL,
        json={
            "dimension_id": "work",
            "display_name": "Work",
            "vault_binding_ids": [vault_a.vault_binding_id, vault_b.vault_binding_id],
        },
    )
    assert created.status_code == 201, created.text

    # -- resolving yields two separate bindings, each with its own verdict --------------
    resolved = client.get(f"{DIMENSIONS_URL}/work/resolve").json()
    members = resolved["members"]
    assert len(members) == 2
    assert [member["vault_binding_id"] for member in members] == [
        vault_a.vault_binding_id,
        vault_b.vault_binding_id,
    ]
    # Two distinct verdict epochs: the decision was made per binding, not once for the
    # group and copied. Nothing about A's admission was reused for B.
    assert members[0]["authorization_epoch"] != members[1]["authorization_epoch"]
    # Per-binding provenance survives grouping: identity is not merged into a group id.
    assert members[0]["local_instance_id"] != members[1]["local_instance_id"]
    assert {member["vault_binding_id"] for member in members} == {
        vault_a.vault_binding_id,
        vault_b.vault_binding_id,
    }

    # -- the snapshot the selection endpoint stores carries the same per-binding truth --
    selection = client.post(SELECTION_URL, json={"dimension_id": "work"}).json()["context"]
    assert selection["vault_binding_ids"] == [
        vault_a.vault_binding_id,
        vault_b.vault_binding_id,
    ]
    assert selection["dimension_id"] == "work"

    # -- grouping upgraded nothing -----------------------------------------------------
    # The dimension resolved exactly the bindings an operator had already registered and
    # already stored as members. It reached no third binding, and the resolved set equals
    # the stored membership.
    snapshot = runtime.registry.load()
    stored = parse_dimensions(snapshot.extensions)["work"]
    assert tuple(member["vault_binding_id"] for member in members) == stored.members
    assert set(stored.members) <= set(snapshot.registrations)

    # The verdicts are identical to the ones an explicit, dimension-free authorization
    # produces for the same principal and the same bindings.
    principal = resolve_principal(record, "trusted_loopback")
    direct = open_vault_dimension_service(runtime.layout.registry_path).resolve(
        "work",
        principal=principal,
        action=ACTION_DIMENSION_RESOLVE,
        write_class=WRITE_CLASS_READ,
        required_permission=PERMISSION_SELECTION_MANAGE,
        authorizer=build_authorizer(snapshot),
        snapshot=snapshot,
    )
    assert [member.authorization_epoch for member in direct.members] == [
        member["authorization_epoch"] for member in members
    ]

    # -- no dimension type carries an authority-shaped field ---------------------------
    for record_type in (VaultDimension, ResolvedMember, DimensionResolution):
        names = {field.name for field in dataclasses.fields(record_type)}
        assert not (names & FORBIDDEN_DIMENSION_FIELDS), record_type

    # -- deleting `work` leaves A and B registered and untouched -----------------------
    registrations_before = dict(snapshot.registrations)
    contents = {
        vault_a.vault_binding_id: sorted(p.name for p in Path(vault_a.path).iterdir()),
        vault_b.vault_binding_id: sorted(p.name for p in Path(vault_b.path).iterdir()),
    }
    deleted = client.delete(f"{DIMENSIONS_URL}/work")
    assert deleted.status_code == 200
    after = runtime.registry.load()
    assert after.registrations == registrations_before
    assert parse_dimensions(after.extensions) == {}
    for binding_id, listing in contents.items():
        path = after.registrations[binding_id].path
        assert sorted(p.name for p in Path(path).iterdir()) == listing

    # The bindings remain independently selectable after the grouping is gone -- deleting
    # a dimension removed a convenience, not access.
    still_reachable = client.post(
        SELECTION_URL,
        json={"vault_binding_ids": [vault_a.vault_binding_id, vault_b.vault_binding_id]},
    )
    assert still_reachable.status_code == 201
    assert still_reachable.json()["context"]["vault_binding_ids"] == [
        vault_a.vault_binding_id,
        vault_b.vault_binding_id,
    ]
