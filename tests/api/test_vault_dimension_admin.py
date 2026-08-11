"""MVR-04 (#3858): the production dimension administration producers.

Contract: `docs/MULTI_VAULT_RUNTIME/GROUP_VAULT_BINDINGS_BY_DIMENSION.md`.

Both producers named by the spec are exercised as production surfaces: the authenticated
Companion API and the headless `python -m app.instance.runtime dimension-*` CLI. Nothing
here seeds the store -- "no store seeding counts" is the AC's own wording, and the
`Invariant -> producers` rule is only satisfied if the shipped commands are what move the
state.

The router is also checked for *reachability*, not merely existence: `app/api/app.py`
imports every router inside a `try/except ImportError` that silently degrades to `None`, so
a module that exists but fails to import would ship an app with no dimension endpoints and
every direct-service test would still pass.
"""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.instance.runtime import main as instance_runtime_main
from app.instance.vault_dimensions import parse_dimensions
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
from tests._route_introspection import openapi_paths

DIMENSIONS_URL = "/api/instance/dimensions"


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    runtime, first, extra, record = provisioned_instance(
        tmp_path, extra_roots=("two", "three")
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    return runtime, first, extra[0], extra[1], record


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _cli(*argv: str) -> dict:
    buffer = StringIO()
    with redirect_stdout(buffer):
        code = instance_runtime_main(list(argv))
    payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    payload["_exit_code"] = code
    return payload


def test_production_dimension_commands_drive_registry(instance, client) -> None:
    """Create / rename / replace / delete / list / resolve through the shipped producers."""

    runtime, first, second, third, _ = instance
    registry_path = str(runtime.layout.registry_path)

    # -- the router is actually mounted in the live app -------------------------------
    mounted = set(openapi_paths(app))
    assert DIMENSIONS_URL in mounted
    assert f"{DIMENSIONS_URL}/{{dimension_id}}/resolve" in mounted

    # -- create through the authenticated API ------------------------------------------
    created = client.post(
        DIMENSIONS_URL,
        json={
            "dimension_id": "work",
            "display_name": "Work",
            "vault_binding_ids": [second.vault_binding_id, first.vault_binding_id],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["changed"] is True
    assert body["dimension_revision"] == 1
    assert body["vault_binding_ids"] == [
        second.vault_binding_id,
        first.vault_binding_id,
    ]
    # The API moved *durable registry* state, not a process-local cache.
    durable = parse_dimensions(runtime.registry.load().extensions)
    assert durable["work"].members == (second.vault_binding_id, first.vault_binding_id)

    # -- a client-authored extra field is a 422, never a silently-ignored field --------
    rejected = client.post(
        DIMENSIONS_URL,
        json={
            "dimension_id": "sneaky",
            "display_name": "Sneaky",
            "required_permission": "vault.write",
        },
    )
    assert rejected.status_code == 422
    assert "sneaky" not in parse_dimensions(runtime.registry.load().extensions)

    # -- rename through the CLI, over the same durable state ---------------------------
    renamed = _cli(
        "dimension-rename",
        "--registry-path",
        registry_path,
        "--dimension-id",
        "work",
        "--display-name",
        "Work (2026)",
        "--consumer",
        "api",
    )
    assert renamed["_exit_code"] == 0 and renamed["ok"] is True
    assert renamed["display_name"] == "Work (2026)"
    assert renamed["dimension_revision"] == 2
    assert client.get(f"{DIMENSIONS_URL}/work").json()["display_name"] == "Work (2026)"

    # -- replace membership through the CLI; order is the operator's ------------------
    replaced = _cli(
        "dimension-set-members",
        "--registry-path",
        registry_path,
        "--dimension-id",
        "work",
        "--vault-binding-id",
        third.vault_binding_id,
        "--vault-binding-id",
        first.vault_binding_id,
        "--consumer",
        "api",
    )
    assert replaced["_exit_code"] == 0
    assert replaced["vault_binding_ids"] == [
        third.vault_binding_id,
        first.vault_binding_id,
    ]
    assert replaced["previous_vault_binding_ids"] == [
        second.vault_binding_id,
        first.vault_binding_id,
    ]

    # A replacement naming an unregistered binding fails closed and changes nothing.
    before = runtime.registry.load().revision
    refused = _cli(
        "dimension-set-members",
        "--registry-path",
        registry_path,
        "--dimension-id",
        "work",
        "--vault-binding-id",
        "binding-does-not-exist",
        "--consumer",
        "api",
    )
    assert refused["_exit_code"] == 1 and refused["ok"] is False
    # A proposed member that is not a current registration is a client input error, not a
    # conflict over stored state, so it is reported as a plain refusal.
    assert "not a current registration" in refused["error"]
    assert runtime.registry.load().revision == before

    # -- CLI create + list, then API list, agree -------------------------------------
    _cli(
        "dimension-create",
        "--registry-path",
        registry_path,
        "--dimension-id",
        "reading",
        "--display-name",
        "Reading",
        "--vault-binding-id",
        second.vault_binding_id,
        "--consumer",
        "api",
    )
    listed = _cli("dimension-list", "--registry-path", registry_path, "--consumer", "api")
    assert [item["dimension_id"] for item in listed["dimensions"]] == ["reading", "work"]
    api_listed = client.get(DIMENSIONS_URL).json()["dimensions"]
    assert [item["dimension_id"] for item in api_listed] == ["reading", "work"]

    # -- resolve through both producers, with authorization ---------------------------
    resolved = client.get(f"{DIMENSIONS_URL}/work/resolve")
    assert resolved.status_code == 200, resolved.text
    payload = resolved.json()
    assert [member["vault_binding_id"] for member in payload["members"]] == [
        third.vault_binding_id,
        first.vault_binding_id,
    ]
    assert all(member["authorization_epoch"] for member in payload["members"])
    cli_resolved = _cli(
        "dimension-resolve",
        "--registry-path",
        registry_path,
        "--dimension-id",
        "work",
        "--consumer",
        "api",
    )
    assert cli_resolved["_exit_code"] == 0
    assert cli_resolved["vault_binding_ids"] == [
        third.vault_binding_id,
        first.vault_binding_id,
    ]

    # -- delete leaves registrations and content intact --------------------------------
    registrations_before = dict(runtime.registry.load().registrations)
    deleted = client.delete(f"{DIMENSIONS_URL}/reading")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert runtime.registry.load().registrations == registrations_before
    assert client.get(f"{DIMENSIONS_URL}/reading").status_code == 404

    # -- receipts stay redacted: no content root escapes any surface -------------------
    roots = {first.path, second.path, third.path}
    surfaces = [
        json.dumps(listed),
        json.dumps(cli_resolved),
        client.get(DIMENSIONS_URL).text,
        resolved.text,
        deleted.text,
        created.text,
    ]
    for surface in surfaces:
        for root in roots:
            assert root not in surface

    # -- #2223 authentication is enforced on this router too --------------------------
    from app.settings import settings

    remote = TestClient(app, client=("203.0.113.9", 5000))
    original_key = settings.api_key
    try:
        settings.api_key = "configured-key"
        assert remote.get(DIMENSIONS_URL).status_code == 401
        assert (
            remote.post(
                DIMENSIONS_URL, json={"dimension_id": "x", "display_name": "X"}
            ).status_code
            == 401
        )
    finally:
        settings.api_key = original_key


def test_admin_can_repair_stale_dimension_membership(instance, client) -> None:
    """Instance-authorized repair clears a stale member without resolving a subset."""

    runtime, first, second, third, _ = instance
    registry_path = str(runtime.layout.registry_path)

    client.post(
        DIMENSIONS_URL,
        json={
            "dimension_id": "work",
            "display_name": "Work",
            "vault_binding_ids": [
                first.vault_binding_id,
                second.vault_binding_id,
                third.vault_binding_id,
            ],
        },
    )

    # First, the happy path: de-registering `second` repairs membership inside the same
    # locked transaction, so the *normal* route to a stale member does not leave one.
    # (Production registration removal is still sealed until MVR-06B, so this drives the
    # store's own transaction with the explicit test capability -- the transaction MVR-06B
    # will activate.)
    snapshot = runtime.registry.load()
    runtime.registry.remove_registration(
        second.vault_binding_id,
        expected_revision=snapshot.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert parse_dimensions(runtime.registry.load().extensions)["work"].members == (
        first.vault_binding_id,
        third.vault_binding_id,
    )

    # Now the case the AC is really about: durable membership that went stale *without*
    # passing through the repair hook -- a restored backup, a hand-edited registry, a
    # future producer. That is the operator-visible inconsistency `remove-member` exists
    # to clear, and it is unreachable if the only stale members are ones the hook cleaned.
    current = runtime.registry.load()
    stale_payload = {
        "schema": "agentic-pkm.instance-vault-dimensions.v1",
        "entries": {
            "work": {
                "displayName": "Work",
                "revision": 4,
                "members": [
                    first.vault_binding_id,
                    "binding-vanished",
                    third.vault_binding_id,
                ],
            }
        },
    }
    runtime.registry.set_dimension_state(
        stale_payload,
        expected_revision=current.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

    # Inspection reports the stale row: administration must be able to *see* it.
    inspected = client.get(f"{DIMENSIONS_URL}/work")
    assert inspected.status_code == 200
    assert inspected.json()["vault_binding_ids"] == [
        first.vault_binding_id,
        "binding-vanished",
        third.vault_binding_id,
    ]

    # Resolution still fails closed on the whole dimension, and exposes no partial set.
    failed = client.get(f"{DIMENSIONS_URL}/work/resolve")
    assert failed.status_code == 409, failed.text
    detail = failed.json()["detail"]
    assert "dimension_member_unregistered" in detail
    assert "binding-vanished" in detail
    assert first.vault_binding_id not in detail
    assert third.vault_binding_id not in detail

    # An addition also fails closed while the dimension is broken: a replacement is an
    # addition path, so it refuses the stale id rather than accepting it. 400 rather than
    # 409 because the refusal is about the *proposed* membership the client just sent.
    still_closed = client.put(
        f"{DIMENSIONS_URL}/work/members",
        json={"vault_binding_ids": [first.vault_binding_id, "binding-vanished"]},
    )
    assert still_closed.status_code == 400
    # ... and the broken stored membership is untouched by the refusal.
    assert client.get(f"{DIMENSIONS_URL}/work").json()["vault_binding_ids"] == [
        first.vault_binding_id,
        "binding-vanished",
        third.vault_binding_id,
    ]

    # Instance-authorized repair clears the stale member without resolving it, and the
    # surviving order is preserved.
    repaired = client.delete(f"{DIMENSIONS_URL}/work/members/binding-vanished")
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["vault_binding_ids"] == [
        first.vault_binding_id,
        third.vault_binding_id,
    ]
    assert repaired.json()["removed_vault_binding_ids"] == ["binding-vanished"]
    assert repaired.json()["dimension_revision"] == 5

    # With the dimension healthy again, resolution succeeds -- and only now.
    healed = client.get(f"{DIMENSIONS_URL}/work/resolve")
    assert healed.status_code == 200
    assert [member["vault_binding_id"] for member in healed.json()["members"]] == [
        first.vault_binding_id,
        third.vault_binding_id,
    ]

    # Deleting a dimension that still holds a stale member is also allowed, and destroys
    # no registration.
    _cli(
        "dimension-create",
        "--registry-path",
        registry_path,
        "--dimension-id",
        "broken",
        "--display-name",
        "Broken",
        "--vault-binding-id",
        first.vault_binding_id,
        "--consumer",
        "api",
    )
    current = runtime.registry.load()
    entries = dict(current.extensions["dimensions"]["entries"])
    entries["broken"] = {
        "displayName": "Broken",
        "revision": 1,
        "members": ["binding-vanished"],
    }
    runtime.registry.set_dimension_state(
        {"schema": "agentic-pkm.instance-vault-dimensions.v1", "entries": entries},
        expected_revision=current.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    registrations_before = dict(runtime.registry.load().registrations)
    dropped = _cli(
        "dimension-delete",
        "--registry-path",
        registry_path,
        "--dimension-id",
        "broken",
        "--consumer",
        "api",
    )
    assert dropped["_exit_code"] == 0 and dropped["deleted"] is True
    assert runtime.registry.load().registrations == registrations_before
