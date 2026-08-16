"""MVR-04 (#3858): dimension -> context resolution, and the authority boundary.

Contract: `docs/MULTI_VAULT_RUNTIME/GROUP_VAULT_BINDINGS_BY_DIMENSION.md`;
`docs/MULTI_VAULT_RUNTIME/README.md :: Cross-Task Invariants / Interaction Safety`
("Selection cannot upgrade authority. Every binding is independently authorized by GOV.").

The invariant under test is negative -- *a dimension grants nothing* -- so these tests prove
it three ways rather than asserting it once:

- **equivalence**: resolving a dimension produces byte-identical per-binding verdict epochs
  to naming the same bindings explicitly, so grouping is not an input to the decision;
- **all-or-nothing**: one bad member fails the whole resolution, with no partial set, no
  exclusion, no substitution, and no fallback to the instance default;
- **structural**: the dimension module never constructs a verdict, and no dimension record
  carries an authority-shaped field.
"""

from __future__ import annotations

import ast
import inspect

import pytest
from fastapi.testclient import TestClient

import app.api.routes.active_context_selection as selection_routes
import app.instance.vault_dimensions as dimension_module
from app.api.app import app
from app.governance.binding_authority import (
    BindingAuthorizationRequest,
    RegistryBindingAuthorizer,
    _test_revocation_capability,
)
from app.instance.active_context_service import (
    ACTION_DIMENSION_RESOLVE,
    PERMISSION_SELECTION_MANAGE,
    WRITE_CLASS_READ,
    ActiveContextSelectionService,
    build_authorizer,
    resolve_principal,
)
from app.instance.context_selection import ContextSelectionStore
from app.instance.runtime import (
    open_local_operator_principal_store,
    open_vault_dimension_service,
)
from app.instance.vault_dimensions import (
    REASON_MEMBER_UNAUTHORIZED,
    DimensionResolutionError,
    VaultDimensionService,
)
from app.instance.vault_registry import VaultRegistryStore
from app.vault.active_context_v1 import DimensionFilter, PrincipalContext
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

DIMENSIONS_URL = "/api/instance/dimensions"
SELECTION_URL = "/api/companion/active-context/selection"


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    runtime, first, extra, record = provisioned_instance(tmp_path, extra_roots=("two", "three"))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    selection_routes.reset_selection_store_for_tests()
    return runtime, first, extra[0], extra[1], record


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _principal(runtime, record):
    return resolve_principal(record, "trusted_loopback")


def _dimension_service(runtime) -> VaultDimensionService:
    return open_vault_dimension_service(runtime.layout.registry_path)


def test_dimension_resolution_authorizes_each_binding(instance, client) -> None:
    """Resolution returns explicit per-vault bindings, each independently authorized."""

    runtime, first, second, third, record = instance
    client.post(
        DIMENSIONS_URL,
        json={
            "dimension_id": "work",
            "display_name": "Work",
            "vault_binding_ids": [second.vault_binding_id, first.vault_binding_id],
        },
    )

    resolved = client.get(f"{DIMENSIONS_URL}/work/resolve")
    assert resolved.status_code == 200, resolved.text
    members = resolved.json()["members"]

    # Explicit per-vault bindings, in the stored order, each with its own identity,
    # provenance, revision, and verdict epoch. Nothing is merged into a group identity.
    assert [member["vault_binding_id"] for member in members] == [
        second.vault_binding_id,
        first.vault_binding_id,
    ]
    assert len({member["vault_binding_id"] for member in members}) == 2
    assert len({member["local_instance_id"] for member in members}) == 2
    assert all(member["binding_revision"] >= 1 for member in members)
    assert all(len(member["authorization_epoch"]) == 32 for member in members)

    # -- GOV was really consulted once per member, with the dimension nowhere in sight --
    snapshot = runtime.registry.load()
    seen: list[BindingAuthorizationRequest] = []

    class RecordingAuthorizer(RegistryBindingAuthorizer):
        def authorize(self, request):  # type: ignore[override]
            seen.append(request)
            return super().authorize(request)

    recording = RecordingAuthorizer({binding_id: 1 for binding_id in snapshot.registrations})
    principal = _principal(runtime, record)
    resolution = _dimension_service(runtime).resolve(
        "work",
        principal=principal,
        action=ACTION_DIMENSION_RESOLVE,
        write_class=WRITE_CLASS_READ,
        required_permission=PERMISSION_SELECTION_MANAGE,
        authorizer=recording,
        snapshot=snapshot,
    )
    assert [request.vault_binding_id for request in seen] == [
        second.vault_binding_id,
        first.vault_binding_id,
    ]
    # The decision inputs are the caller's endpoint contract, unchanged, and no field of
    # the request carries the dimension. GOV cannot tell that a group was involved.
    for request in seen:
        assert request.action == ACTION_DIMENSION_RESOLVE
        assert request.write_class == WRITE_CLASS_READ
        assert request.required_permission == PERMISSION_SELECTION_MANAGE
        assert request.principal == principal
        assert "work" not in str(request)
    assert resolution.dimension_revision == 1


def test_selection_endpoint_resolves_dimension_and_derives_context_server_side(
    instance, client
) -> None:
    """`dimension_id` is intent; the server derives everything else and stores bindings."""

    runtime, first, second, third, _ = instance
    client.post(
        DIMENSIONS_URL,
        json={
            "dimension_id": "work",
            "display_name": "Work",
            "vault_binding_ids": [third.vault_binding_id, first.vault_binding_id],
        },
    )

    created = client.post(SELECTION_URL, json={"dimension_id": "work"})
    assert created.status_code == 201, created.text
    context = created.json()["context"]

    # What got persisted is the *validated explicit binding set* plus the dimension
    # revision -- not the dimension id as something to re-expand later.
    assert context["vault_binding_ids"] == [
        third.vault_binding_id,
        first.vault_binding_id,
    ]
    assert context["dimension_id"] == "work"
    assert context["dimension_revision"] == 1

    # Every cognitive/authority field is server-derived exactly as in MVR-03. The
    # dimension changed none of them.
    explicit = client.post(
        SELECTION_URL,
        json={"vault_binding_ids": [third.vault_binding_id, first.vault_binding_id]},
    ).json()["context"]
    for field in (
        "principal_kind",
        "principal_id",
        "instance_identity",
        "workspace",
        "scope",
        "sphere_memberships",
        "situated_identity",
    ):
        assert context[field] == explicit[field]
    assert explicit["dimension_id"] is None

    # -- a client cannot author context, a member list, or a projection ----------------
    for payload in (
        {"dimension_id": "work", "scope": "admin"},
        {"dimension_id": "work", "sphere_memberships": ["private"]},
        {"dimension_id": "work", "principal_id": "root"},
        {"dimension_id": {"members": [first.vault_binding_id]}},
        {"dimension_filter": "work"},
    ):
        assert client.post(SELECTION_URL, json=payload).status_code == 422, payload

    # Explicit bindings and a dimension together is refused, not merged: a union would be
    # a client-authored projection wearing a stored dimension's name.
    both = client.post(
        SELECTION_URL,
        json={"dimension_id": "work", "vault_binding_ids": [second.vault_binding_id]},
    )
    assert both.status_code == 400
    assert "never both" in both.json()["detail"]

    # An unknown dimension is a 404 and mints nothing -- no fallback to the default.
    assert client.post(SELECTION_URL, json={"dimension_id": "nope"}).status_code == 404

    # A present-but-blank `dimension_id` is a malformed request, not an absent field. It is
    # refused rather than coerced to "no dimension" -- otherwise a blank value would both be
    # silently ignored and slip past the both-forms refusal above.
    for blank in ("", "   ", "\t"):
        empty = client.post(SELECTION_URL, json={"dimension_id": blank})
        assert empty.status_code == 400, f"{blank!r} was silently ignored: {empty.text}"
        smuggled = client.post(
            SELECTION_URL,
            json={"dimension_id": blank, "vault_binding_ids": [second.vault_binding_id]},
        )
        assert smuggled.status_code == 400, smuggled.text

    # -- replace also accepts a dimension, and restates provenance ---------------------
    bearer = created.json()["context_selection_id"]
    headers = {"X-Active-Context-Session": bearer}
    client.post(
        DIMENSIONS_URL,
        json={
            "dimension_id": "reading",
            "display_name": "Reading",
            "vault_binding_ids": [second.vault_binding_id],
        },
    )
    replaced = client.put(SELECTION_URL, json={"dimension_id": "reading"}, headers=headers)
    assert replaced.status_code == 200
    assert replaced.json()["context"]["vault_binding_ids"] == [second.vault_binding_id]
    assert replaced.json()["context"]["dimension_id"] == "reading"
    assert replaced.json()["context"]["generation"] == 2

    # Replacing with explicit bindings clears the stale dimension provenance rather than
    # leaving the record claiming a group it no longer reflects.
    back = client.put(
        SELECTION_URL,
        json={"vault_binding_ids": [first.vault_binding_id]},
        headers=headers,
    )
    assert back.json()["context"]["dimension_id"] is None
    assert back.json()["context"]["dimension_revision"] is None


def test_dimension_never_upgrades_authority_or_falls_back(instance, client) -> None:
    """The negative invariant, proved three ways."""

    runtime, first, second, third, record = instance
    principal = _principal(runtime, record)
    service = _dimension_service(runtime)

    client.post(
        DIMENSIONS_URL,
        json={
            "dimension_id": "work",
            "display_name": "Work",
            "vault_binding_ids": [first.vault_binding_id, second.vault_binding_id],
        },
    )
    snapshot = runtime.registry.load()

    # -- 1. equivalence: grouping is not an input to the GOV decision ------------------
    via_dimension = service.resolve(
        "work",
        principal=principal,
        action=ACTION_DIMENSION_RESOLVE,
        write_class=WRITE_CLASS_READ,
        required_permission=PERMISSION_SELECTION_MANAGE,
        authorizer=build_authorizer(snapshot),
        snapshot=snapshot,
    )
    direct = build_authorizer(snapshot)
    via_explicit = [
        direct.authorize(
            BindingAuthorizationRequest(
                principal=principal,
                vault_binding_id=binding_id,
                action=ACTION_DIMENSION_RESOLVE,
                write_class=WRITE_CLASS_READ,
                required_permission=PERMISSION_SELECTION_MANAGE,
            )
        )
        for binding_id in (first.vault_binding_id, second.vault_binding_id)
    ]
    # Identical bindings, identical order, identical non-secret verdict epochs. A binding
    # reached through a dimension is decided exactly as one named directly.
    assert [member.vault_binding_id for member in via_dimension.members] == [
        verdict.vault_binding_id for verdict in via_explicit
    ]
    assert [member.authorization_epoch for member in via_dimension.members] == [
        verdict.epoch for verdict in via_explicit
    ]
    # And the group reaches nothing the explicit selection did not: the resolved set is a
    # subset of what the operator had already registered and stored.
    assert set(via_dimension.binding_ids) <= set(snapshot.registrations)
    assert third.vault_binding_id not in via_dimension.binding_ids

    # -- 2. all-or-nothing on a stale member, through production HTTP ------------------
    # A member that is no longer a registration. Registration removal repairs membership
    # transactionally, so this state is reached the way an operator would actually meet it
    # -- durable membership that went stale outside that hook (a restored backup, a
    # hand-edited registry, a future producer) -- rather than by removing a binding and
    # then undoing the repair.
    current = runtime.registry.load()
    runtime.registry.set_dimension_state(
        {
            "schema": "agentic-pkm.instance-vault-dimensions.v1",
            "entries": {
                "work": {
                    "displayName": "Work",
                    "revision": 2,
                    "members": [first.vault_binding_id, "binding-gone"],
                }
            },
        },
        expected_revision=current.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

    failed = client.get(f"{DIMENSIONS_URL}/work/resolve")
    assert failed.status_code == 409
    detail = failed.json()["detail"]
    # Member-specific, bounded, redacted: it names the offending opaque id and neither the
    # authorized member nor any content root.
    assert "dimension_member_unregistered" in detail
    assert "binding-gone" in detail
    assert first.vault_binding_id not in detail
    assert first.path not in detail

    # The selection endpoint fails the *whole* request: no snapshot is minted, no
    # authorized subset is stored, and it does not fall back to the instance default.
    store_before = len(selection_routes.get_selection_store())
    refused = client.post(SELECTION_URL, json={"dimension_id": "work"})
    assert refused.status_code == 409
    assert len(selection_routes.get_selection_store()) == store_before
    assert first.vault_binding_id not in refused.text

    # A separately-created selection over the instance default still works, proving the
    # refusal above was scoped to the dimension and not a global outage.
    healthy = client.post(SELECTION_URL, json={"vault_binding_ids": []})
    assert healthy.status_code == 201
    assert healthy.json()["context"]["vault_binding_ids"] == []

    # -- the revoked-member branch fails the whole resolution too ----------------------
    # The shipped single-user GOV policy has no production revocation producer yet, so
    # this exercises the `binding_revoked` deny branch directly. It is the same seam and
    # the same all-or-nothing path.
    current = runtime.registry.load()
    runtime.registry.set_dimension_state(
        {
            "schema": "agentic-pkm.instance-vault-dimensions.v1",
            "entries": {
                "work": {
                    "displayName": "Work",
                    "revision": 3,
                    "members": [first.vault_binding_id, third.vault_binding_id],
                }
            },
        },
        expected_revision=current.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    snapshot = runtime.registry.load()
    revoking = build_authorizer(snapshot)
    revoking.set_binding(
        third.vault_binding_id,
        1,
        revoked=True,
        _revocation_capability=_test_revocation_capability(),
    )
    with pytest.raises(DimensionResolutionError) as revoked_error:
        service.resolve(
            "work",
            principal=principal,
            action=ACTION_DIMENSION_RESOLVE,
            write_class=WRITE_CLASS_READ,
            required_permission=PERMISSION_SELECTION_MANAGE,
            authorizer=revoking,
            snapshot=snapshot,
        )
    assert revoked_error.value.reason == REASON_MEMBER_UNAUTHORIZED
    assert revoked_error.value.vault_binding_id == third.vault_binding_id

    # An unresolved principal denies every member, so the dimension resolves nothing.
    with pytest.raises(DimensionResolutionError):
        service.resolve(
            "work",
            principal=PrincipalContext(
                principal_id="unknown-principal",
                principal_kind="delegated_operator_role",
                subject="trusted_loopback",
            ),
            action=ACTION_DIMENSION_RESOLVE,
            write_class=WRITE_CLASS_READ,
            required_permission=PERMISSION_SELECTION_MANAGE,
            authorizer=RegistryBindingAuthorizer(),
            snapshot=snapshot,
        )

    # -- 3. structural: the module cannot decide authority ----------------------------
    tree = ast.parse(inspect.getsource(dimension_module))
    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    # It never mints a verdict or a principal: it can only ask GOV and obey the answer.
    # Only names this module actually imports are checked -- asserting the absence of a
    # symbol that could never appear here would be a check that cannot fail.
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    for forbidden in ("BindingVerdict", "PrincipalContext"):
        assert forbidden in imported, f"{forbidden} must be imported for this check to bite"
        assert forbidden not in constructed
    # And it never derives an epoch itself, under any spelling.
    assert "authorization_epoch(" not in inspect.getsource(dimension_module)
    assert "snapshot_authorization_epoch" not in inspect.getsource(dimension_module)

    # The typed provenance record carried into a snapshot holds two scalars and nothing
    # that could be read as a grant.
    assert set(DimensionFilter.__dataclass_fields__) == {
        "dimension_id",
        "dimension_revision",
    }


def test_dimension_service_without_capability_cannot_mutate(instance) -> None:
    """A read-only dimension view fails closed on every mutator."""

    from app.instance._storage_boundary import CapabilityNotReadyError

    runtime, first, _second, _third, _record = instance
    # The dimension must exist first, or four of the five mutators would fail on
    # unknown-dimension *before* reaching the capability seal and prove nothing.
    open_vault_dimension_service(runtime.layout.registry_path).create(
        "x", display_name="X", members=[first.vault_binding_id]
    )
    readonly = VaultDimensionService(VaultRegistryStore(runtime.layout.registry_path))
    frozen = runtime.layout.registry_path.read_bytes()
    for call in (
        lambda: readonly.create("y", display_name="Y"),
        lambda: readonly.rename("x", display_name="Renamed"),
        lambda: readonly.set_members("x", []),
        lambda: readonly.remove_member("x", first.vault_binding_id),
        lambda: readonly.delete("x"),
    ):
        # Every one of these reaches the seal: `CapabilityNotReadyError`, not a
        # cheaper validation refusal that would have masked an unsealed writer.
        with pytest.raises(CapabilityNotReadyError):
            call()
    assert runtime.layout.registry_path.read_bytes() == frozen
    # Reads still work without the capability: the seal is on mutation only.
    assert readonly.inspect("x").members == (first.vault_binding_id,)


def test_dimension_resolution_needs_no_selection_store(instance) -> None:
    """Resolution is global-free: it holds a registry store and a GOV authorizer only."""

    runtime, first, _second, _third, record = instance
    service = ActiveContextSelectionService(
        registry_store=VaultRegistryStore(runtime.layout.registry_path),
        principal_record=record,
        selection_store=ContextSelectionStore(),
    )
    open_vault_dimension_service(runtime.layout.registry_path).create(
        "work", display_name="Work", members=[first.vault_binding_id]
    )
    derived = service.derive("trusted_loopback")
    resolution = service.resolve_dimension("work", derived=derived)
    assert resolution.binding_ids == (first.vault_binding_id,)
    # Resolving mints no selection: resolution is not selection.
    assert len(service.selection_store) == 0
    assert (
        open_local_operator_principal_store(runtime.layout.registry_path)
        .require()
        .principal_for("trusted_loopback")
        == derived.principal
    )
