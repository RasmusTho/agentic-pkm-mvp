"""MVR-03 (#3857): request/session-scoped active-context resolution.

Every session transition here goes through the **production** create/replace/inspect/clear
endpoints, as `docs/MULTI_VAULT_RUNTIME/VERSION_ACTIVE_CONTEXT_SELECTION.md :: Concretely`
requires -- the store is never seeded directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.governance.binding_authority import (
    BindingAuthorizationError,
    BindingAuthorizationRequest,
    RegistryBindingAuthorizer,
)
from app.instance.active_context_service import (
    ACTION_SELECTION_INSPECT,
    PERMISSION_SELECTION_READ,
    WRITE_CLASS_READ,
    binding_facts,
    build_authorizer,
    resolve_principal,
)
from app.instance.context_selection import (
    ActiveContextSelectionResolver,
    ContextSelectionStore,
    SelectionPrincipalMismatchError,
)
from app.instance.local_operator_principal import AuthPosture, PrincipalPreflightError
from app.vault.active_context_v1 import (
    ActiveContextSetV1,
    DegradedContextError,
    PrincipalContext,
    WorkspaceState,
)
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.revoked_binding_authorizer import RevokedBindingAuthorizer

SELECTION_URL = "/api/companion/active-context/selection"

_READ_GOV_INPUTS = dict(
    action=ACTION_SELECTION_INSPECT,
    write_class=WRITE_CLASS_READ,
    required_permission=PERMISSION_SELECTION_READ,
)


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    """An authoritative registry, a provisioned delegated role, two registered vaults."""

    runtime, first, extra, record = provisioned_instance(tmp_path, extra_roots=("two",))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    selection_routes.reset_selection_store_for_tests()
    return runtime, first, extra[0], record


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _create(client: TestClient, binding_ids: list[str]) -> dict:
    response = client.post(SELECTION_URL, json={"vault_binding_ids": binding_ids})
    assert response.status_code == 201, response.text
    return response.json()


def _service_resolver(runtime, record):
    """A resolver over live registry truth, matching what the request path builds."""

    snapshot = runtime.registry.load()
    return ActiveContextSelectionResolver(
        binding_facts=lambda: binding_facts(runtime.registry.load()),
        registry_revision=lambda: runtime.registry.load().revision,
        authorizer=build_authorizer(snapshot),
        instance_identity=snapshot.app_install_id,
    )


def _record_for(store: ContextSelectionStore, raw_id: str, principal, instance_identity):
    return store.inspect(raw_id, principal=principal, instance_identity=instance_identity)


def test_concurrent_sessions_are_isolated(instance, client) -> None:
    """Two sessions select different vaults without mutating each other or the default."""

    runtime, first, second, record = instance
    default_before = runtime.registry.load().default_vault_binding_id

    session_a = _create(client, [first.vault_binding_id])
    session_b = _create(client, [second.vault_binding_id])

    assert session_a["context_selection_id"] != session_b["context_selection_id"]
    assert session_a["context"]["context_id"] != session_b["context"]["context_id"]
    assert session_a["context"]["vault_binding_ids"] == [first.vault_binding_id]
    assert session_b["context"]["vault_binding_ids"] == [second.vault_binding_id]

    # Reading either session back through the production inspect command shows the other
    # untouched.
    for session, expected in (
        (session_a, first.vault_binding_id),
        (session_b, second.vault_binding_id),
    ):
        read = client.get(
            SELECTION_URL,
            headers={"X-Active-Context-Session": session["context_selection_id"]},
        )
        assert read.status_code == 200, read.text
        assert read.json()["context"]["vault_binding_ids"] == [expected]
        assert read.json()["context"]["generation"] == 1

    # The instance default was not touched by either selection.
    assert runtime.registry.load().default_vault_binding_id == default_before

    # And the process-global VaultManager was never bound by any of it.
    from app.vault.manager import get_vault_manager

    assert get_vault_manager().context.active_vault_path in (None, "")


def test_session_switch_is_generation_atomic(instance, client) -> None:
    """Switching a session advances its generation; in-flight work keeps its snapshot.

    "In-flight" is modelled the way the runtime actually behaves: a request resolves one
    immutable snapshot object and holds it. The switch cannot reach into that object, so an
    in-flight request finishing after the switch still reports the prior generation and the
    prior binding.
    """

    runtime, first, second, principal_record = instance
    session_a = _create(client, [first.vault_binding_id])
    session_b = _create(client, [second.vault_binding_id])
    bearer_a = session_a["context_selection_id"]

    store = selection_routes.get_selection_store()
    principal = principal_record.principal_for("trusted_loopback")
    instance_identity = runtime.registry.load().app_install_id
    resolver = _service_resolver(runtime, principal_record)

    before = _record_for(store, bearer_a, principal, instance_identity)
    in_flight = resolver.resolve(selection=before, principal=principal, **_READ_GOV_INPUTS).snapshot
    assert in_flight.generation == 1
    assert in_flight.binding_ids == (first.vault_binding_id,)

    switch = client.put(
        SELECTION_URL,
        json={"vault_binding_ids": [second.vault_binding_id]},
        headers={"X-Active-Context-Session": bearer_a},
    )
    assert switch.status_code == 200, switch.text
    assert switch.json()["context"]["generation"] == 2
    assert switch.json()["context"]["vault_binding_ids"] == [second.vault_binding_id]
    # Same context id: this is a new generation of one context, not a new context.
    assert switch.json()["context"]["context_id"] == session_a["context"]["context_id"]

    # The already-resolved snapshot is unchanged -- no in-flight rebinding.
    assert in_flight.generation == 1
    assert in_flight.binding_ids == (first.vault_binding_id,)

    after = _record_for(store, bearer_a, principal, instance_identity)
    subsequent = resolver.resolve(selection=after, principal=principal, **_READ_GOV_INPUTS).snapshot
    assert subsequent.generation == 2
    assert subsequent.binding_ids == (second.vault_binding_id,)

    # Session B is untouched by A's switch.
    read_b = client.get(
        SELECTION_URL,
        headers={"X-Active-Context-Session": session_b["context_selection_id"]},
    )
    assert read_b.json()["context"]["generation"] == 1
    assert read_b.json()["context"]["vault_binding_ids"] == [second.vault_binding_id]


def test_session_expiry_and_restart_are_truthful(instance, client, monkeypatch) -> None:
    """Omitted id resolves the default or no-vault; a presented stale id fails closed.

    Neither path resurrects last-active state or another session. All three stale shapes --
    expired, unknown, and pre-restart -- are covered, because the contract treats them
    identically on purpose.
    """

    runtime, first, second, principal_record = instance
    session = _create(client, [first.vault_binding_id])
    bearer = session["context_selection_id"]

    # -- expiry ------------------------------------------------------------------------
    now = {"t": 1_000.0}
    expiring = ContextSelectionStore(ttl_seconds=60, clock=lambda: now["t"])
    monkeypatch.setattr(selection_routes, "_STORE", expiring)
    fresh = _create(client, [first.vault_binding_id])
    now["t"] += 61
    expired = client.get(
        SELECTION_URL,
        headers={"X-Active-Context-Session": fresh["context_selection_id"]},
    )
    assert expired.status_code == 401
    assert "reselection_required" in expired.json()["detail"]

    # -- process restart ---------------------------------------------------------------
    selection_routes.reset_selection_store_for_tests()
    restarted = client.get(SELECTION_URL, headers={"X-Active-Context-Session": bearer})
    assert restarted.status_code == 401
    assert "reselection_required" in restarted.json()["detail"]

    # -- unknown -----------------------------------------------------------------------
    unknown = client.get(
        SELECTION_URL, headers={"X-Active-Context-Session": "not-a-real-selection"}
    )
    assert unknown.status_code == 401
    assert "reselection_required" in unknown.json()["detail"]
    # The failure never echoes the presented bearer back.
    assert "not-a-real-selection" not in unknown.text

    # -- omitted: the explicit instance default, or no-vault ---------------------------
    principal = principal_record.principal_for("trusted_loopback")
    resolver = _service_resolver(runtime, principal_record)
    snapshot = runtime.registry.load()

    no_selection = resolver.resolve(
        selection=None,
        principal=principal,
        default_binding_id=snapshot.default_vault_binding_id,
        **_READ_GOV_INPUTS,
    ).snapshot
    assert snapshot.default_vault_binding_id is not None
    assert no_selection.binding_ids == (snapshot.default_vault_binding_id,)
    assert no_selection.selection_provenance == "instance_default"
    # Crucially: it did not resurrect the expired session's binding by accident.
    assert no_selection.selection_capability_digest is None

    no_default = resolver.resolve(
        selection=None,
        principal=principal,
        default_binding_id=None,
        **_READ_GOV_INPUTS,
    ).snapshot
    assert no_default.binding_ids == ()
    assert no_default.selection_provenance == "no_vault"
    assert no_default.is_no_vault


def test_each_binding_is_authorized_independently(instance, client) -> None:
    """Zero, one, and many bindings are valid; each member is separately GOV-authorized."""

    runtime, first, second, principal_record = instance
    principal = principal_record.principal_for("trusted_loopback")
    instance_identity = runtime.registry.load().app_install_id
    store = selection_routes.get_selection_store()

    zero = _create(client, [])
    one = _create(client, [first.vault_binding_id])
    many = _create(client, [first.vault_binding_id, second.vault_binding_id])
    assert zero["context"]["vault_binding_ids"] == []
    assert len(many["context"]["vault_binding_ids"]) == 2

    resolver = _service_resolver(runtime, principal_record)
    for payload, expected in (
        (zero, 0),
        (one, 1),
        (many, 2),
    ):
        record = _record_for(store, payload["context_selection_id"], principal, instance_identity)
        snapshot = resolver.resolve(
            selection=record, principal=principal, **_READ_GOV_INPUTS
        ).snapshot
        assert len(snapshot.source_bindings) == expected
        # Each member carries its own verdict epoch: they are separate decisions, not one
        # decision copied across the set.
        epochs = {binding.authorization_epoch for binding in snapshot.source_bindings}
        assert len(epochs) == expected

    # Each of the three deny branches is real and reachable.
    authorizer = RevokedBindingAuthorizer(RegistryBindingAuthorizer({first.vault_binding_id: 1}))
    unresolved = BindingAuthorizationRequest(
        principal=PrincipalContext(
            principal_id="x", principal_kind="delegated_operator_role", subject="trusted_loopback"
        ),
        vault_binding_id="never-registered",
        action="read",
        write_class="read",
        required_permission="wsp.read",
    )
    assert authorizer.authorize(unresolved).reason == "binding_unknown"
    authorizer.revoke_for_test(first.vault_binding_id)
    denied_revoked = authorizer.authorize(
        BindingAuthorizationRequest(
            principal=unresolved.principal,
            vault_binding_id=first.vault_binding_id,
            action="read",
            write_class="read",
            required_permission="wsp.read",
        )
    )
    assert denied_revoked.reason == "binding_revoked"

    # Availability is NOT an authorization input: an unreachable content root is still a
    # binding this principal may use, and it degrades rather than denying. Folding it into
    # GOV would make the degraded posture unreachable in production wiring.
    authorizer.restore_for_test(first.vault_binding_id)
    authorizer.set_binding(first.vault_binding_id, 1, available=False)
    still_allowed = authorizer.authorize(
        BindingAuthorizationRequest(
            principal=unresolved.principal,
            vault_binding_id=first.vault_binding_id,
            action="read",
            write_class="read",
            required_permission="wsp.read",
        )
    )
    assert still_allowed.allowed

    # Denying one member of a many-binding set fails the whole resolution: no partial set
    # is returned and no member is silently excluded.
    partial = RevokedBindingAuthorizer(
        RegistryBindingAuthorizer({first.vault_binding_id: 1, second.vault_binding_id: 1})
    )
    partial.revoke_for_test(second.vault_binding_id)
    partial_resolver = ActiveContextSelectionResolver(
        binding_facts=lambda: binding_facts(runtime.registry.load()),
        registry_revision=lambda: runtime.registry.load().revision,
        authorizer=partial,
        instance_identity=instance_identity,
    )
    many_record = _record_for(store, many["context_selection_id"], principal, instance_identity)
    with pytest.raises(BindingAuthorizationError):
        partial_resolver.resolve(selection=many_record, principal=principal, **_READ_GOV_INPUTS)


def test_degraded_posture_distinguishes_valid_no_vault_from_unavailable_binding(
    instance, client
) -> None:
    """A healthy zero-binding no-vault context is not the same value as a degraded one."""

    runtime, first, second, principal_record = instance
    principal = principal_record.principal_for("trusted_loopback")
    instance_identity = runtime.registry.load().app_install_id
    store = selection_routes.get_selection_store()

    healthy_empty = _create(client, [])
    record = _record_for(store, healthy_empty["context_selection_id"], principal, instance_identity)
    resolver = _service_resolver(runtime, principal_record)
    healthy = resolver.resolve(selection=record, principal=principal, **_READ_GOV_INPUTS).snapshot
    assert healthy.posture == "healthy"
    assert healthy.degraded_reason is None
    assert healthy.is_no_vault
    healthy.require_effect_capable()  # does not raise

    # Now the same shape, but with a binding whose content root became unreachable. This is
    # reached through the *production* wiring: `build_authorizer` still allows the binding
    # (availability is not an authorization input), so the resolver degrades rather than the
    # authorizer denying.
    import shutil

    selected = _create(client, [first.vault_binding_id])
    selected_record = _record_for(
        store, selected["context_selection_id"], principal, instance_identity
    )
    root = Path(runtime.registry.lookup(first.vault_binding_id).path)
    moved = root.with_name(root.name + "-moved")
    shutil.move(str(root), str(moved))
    try:
        production_resolver = _service_resolver(runtime, principal_record)
        degraded = production_resolver.resolve(
            selection=selected_record, principal=principal, **_READ_GOV_INPUTS
        ).snapshot
    finally:
        shutil.move(str(moved), str(root))

    assert degraded.posture == "degraded"
    assert degraded.degraded_reason == "binding_unavailable"
    # It cannot masquerade as ordinary no-vault ...
    assert not degraded.is_no_vault
    # ... and it cannot authorize an effect.
    with pytest.raises(DegradedContextError):
        degraded.require_effect_capable()

    # The degraded reason vocabulary is bounded, not free-form prose.
    with pytest.raises(Exception):
        ActiveContextSetV1(
            context_id="ctx",
            generation=1,
            workspace=WorkspaceState.none(),
            scope="default",
            sphere_memberships=(),
            situated_identity=None,
            principal_context=principal,
            instance_identity=instance_identity,
            source_bindings=(),
            registry_revision=1,
            authorization_epoch="e",
            selection_provenance="session_selection",
            posture="degraded",
            degraded_reason="the disk was a bit slow today",
        )


def test_selection_id_is_single_user_bearer_with_server_derived_context(instance, client) -> None:
    """The bearer is expiring, high-entropy, and additional to #2223 -- never authority."""

    runtime, first, second, principal_record = instance
    created = _create(client, [first.vault_binding_id])
    bearer = created["context_selection_id"]
    context = created["context"]

    # High-entropy server-minted id; nothing client-supplied and nothing guessable.
    assert len(bearer) >= 40
    other = _create(client, [first.vault_binding_id])["context_selection_id"]
    assert bearer != other

    # Bound to the server-resolved delegated-role principal, separate instance identity,
    # explicit workspace/no-workspace state, bindings, and cognitive dimensions.
    assert context["principal_kind"] == "delegated_operator_role"
    assert context["principal_id"] == principal_record.local_operator_role_id
    assert context["instance_identity"] == runtime.registry.load().app_install_id
    assert context["instance_identity"] != context["principal_id"]
    assert context["workspace"] == "no_workspace:"
    assert context["scope"] == "default"
    assert context["sphere_memberships"] == []
    assert context["situated_identity"] is None

    # It stores no operation authority: no action, write class, or permission field exists.
    for authority_field in ("action", "write_class", "permission", "required_permission"):
        assert authority_field not in context

    # Expiring.
    assert context["expires_at"] > 0

    # The same selection serves a separately authorized read and a separately authorized
    # write, because action/write class/permission are per-call GOV inputs rather than
    # stored scope.
    store = selection_routes.get_selection_store()
    principal = principal_record.principal_for("trusted_loopback")
    instance_identity = runtime.registry.load().app_install_id
    record = store.inspect(bearer, principal=principal, instance_identity=instance_identity)
    resolver = _service_resolver(runtime, principal_record)
    read_snapshot = resolver.resolve(
        selection=record,
        principal=principal,
        action="wsp.read_note",
        write_class="read",
        required_permission="wsp.read",
    ).snapshot
    write_snapshot = resolver.resolve(
        selection=record,
        principal=principal,
        action="hka.write_note",
        write_class="governed_content",
        required_permission="hka.write",
    ).snapshot
    # Same preserved cognitive dimensions across both -- the scope did not widen or narrow.
    assert read_snapshot.scope == write_snapshot.scope == "default"
    assert read_snapshot.workspace == write_snapshot.workspace
    assert read_snapshot.sphere_memberships == write_snapshot.sphere_memberships

    # Arbitrary client correlation / principal / context / permission input is rejected
    # outright rather than silently ignored.
    for spoof in (
        {"vault_binding_ids": [], "scope": "private"},
        {"vault_binding_ids": [], "principal_id": "someone-else"},
        {"vault_binding_ids": [], "workspace_id": "w-1"},
        {"vault_binding_ids": [], "sphere_memberships": ["secret"]},
        {"vault_binding_ids": [], "situated_identity": "root"},
        {"vault_binding_ids": [], "required_permission": "hka.write"},
        {"vault_binding_ids": [], "action": "hka.write_note"},
        {"vault_binding_ids": [], "correlation_id": "c-1"},
        # MVR-04 unsealed `dimension_id` as selection intent, but only as an *id already
        # stored in the instance registry*. A client-authored dimension projection is
        # still 422, exactly as it was while the field was sealed.
        {"vault_binding_ids": [], "dimension_filter": ["dim-1"]},
        {"vault_binding_ids": [], "dimension": {"members": ["binding-1"]}},
        {"vault_binding_ids": [], "dimension_revision": 7},
    ):
        response = client.post(SELECTION_URL, json=spoof)
        assert response.status_code == 422, f"{spoof} was not rejected: {response.text}"

    # An unknown `dimension_id` is a fail-closed 404 rather than a 422, because the field
    # is now legitimate intent. It still mints nothing and still cannot become a
    # dimension: only stored membership resolves (MVR-04, #3858).
    unknown = client.post(SELECTION_URL, json={"dimension_id": "dim-1"})
    assert unknown.status_code == 404, unknown.text

    # A different id cannot reach this selection.
    assert (
        client.get(
            SELECTION_URL, headers={"X-Active-Context-Session": "someone-elses-bearer"}
        ).status_code
        == 401
    )

    # A *valid* bearer bound to another principal, or to another instance, cannot reach this
    # selection either. Over the wire the answer is byte-identical to the unknown-bearer
    # answer, so the endpoint is not a bearer-existence oracle; the store still raises a
    # distinguishable type internally for audit purposes.
    from tests._mvr03_principal_harness import principal_store
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

    updated, added = principal_store(runtime).add_role(
        kind="human", label="second-principal", _capability=STORAGE_MUTATION_CAPABILITY
    )
    other_principal = updated.additional_principal(added.role_id, "trusted_loopback")
    with pytest.raises(SelectionPrincipalMismatchError):
        store.inspect(bearer, principal=other_principal, instance_identity=instance_identity)
    with pytest.raises(SelectionPrincipalMismatchError):
        store.replace_bindings(
            bearer,
            principal=other_principal,
            instance_identity=instance_identity,
            binding_ids=(second.vault_binding_id,),
        )
    with pytest.raises(SelectionPrincipalMismatchError):
        store.inspect(bearer, principal=principal, instance_identity="another-install")
    # The mismatch did not mutate the selection.
    assert store.inspect(
        bearer, principal=principal, instance_identity=instance_identity
    ).binding_ids == (first.vault_binding_id,)

    unknown_response = client.get(
        SELECTION_URL, headers={"X-Active-Context-Session": "someone-elses-bearer"}
    )
    assert unknown_response.status_code == 401
    assert unknown_response.json()["detail"] == (
        "reselection_required: selection is not resolvable for this caller"
    )

    # appInstallId is never principal identity: presenting it as a bearer resolves nothing.
    assert (
        client.get(
            SELECTION_URL,
            headers={"X-Active-Context-Session": context["instance_identity"]},
        ).status_code
        == 401
    )


def test_instance_identity_never_substitutes_for_principal_context(instance, client) -> None:
    """Principal derivation uses only the auth/GOV-owned role record.

    Two installations are two instance identities, not two humans; and two roles on one
    instance stay distinct in GOV decisions, cache keys, and receipts.
    """

    runtime, first, second, principal_record = instance
    snapshot = runtime.registry.load()

    principal = principal_record.principal_for("trusted_loopback")
    assert principal.principal_id == principal_record.local_operator_role_id
    assert principal.principal_id != snapshot.app_install_id
    assert principal.principal_kind == "delegated_operator_role"
    # Not derived from the instance: the role id shares no substring with appInstallId.
    assert snapshot.app_install_id not in principal.principal_id

    # An unbound subject fails closed rather than falling back to the instance.
    with pytest.raises(PrincipalPreflightError):
        principal_record.principal_for("api_key_credential")

    # A second explicitly added role gets a distinct principal, and GOV, cache keys, and
    # receipts all see the difference.
    from tests._mvr03_principal_harness import principal_store
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

    store = principal_store(runtime)
    updated, added = store.add_role(
        kind="human", label="owner", _capability=STORAGE_MUTATION_CAPABILITY
    )
    human = updated.additional_principal(added.role_id, "trusted_loopback")
    assert human.principal_id != principal.principal_id
    assert human.principal_kind == "human"

    authorizer = build_authorizer(snapshot)
    delegated_verdict = authorizer.authorize(
        BindingAuthorizationRequest(
            principal=principal,
            vault_binding_id=first.vault_binding_id,
            action="read",
            write_class="read",
            required_permission="wsp.read",
        )
    )
    human_verdict = authorizer.authorize(
        BindingAuthorizationRequest(
            principal=human,
            vault_binding_id=first.vault_binding_id,
            action="read",
            write_class="read",
            required_permission="wsp.read",
        )
    )
    assert delegated_verdict.allowed and human_verdict.allowed
    assert (
        delegated_verdict.epoch != human_verdict.epoch
    ), "two principals must produce distinguishable GOV decisions"

    # And distinguishable full-context identity (the cache-key input).
    from app.retrieval.context_cache import context_cache_identity

    resolver = _service_resolver(runtime, principal_record)
    delegated_snapshot = resolver.resolve(
        selection=None,
        principal=principal,
        default_binding_id=first.vault_binding_id,
        **_READ_GOV_INPUTS,
    ).snapshot
    human_snapshot = resolver.resolve(
        selection=None,
        principal=human,
        default_binding_id=first.vault_binding_id,
        **_READ_GOV_INPUTS,
    ).snapshot
    assert (
        context_cache_identity(delegated_snapshot, settings_bundle_digest="s").key
        != context_cache_identity(human_snapshot, settings_bundle_digest="s").key
    )

    # A raw credential can never be mistaken for a principal.
    with pytest.raises(PrincipalPreflightError):
        resolve_principal(updated, "api_key_credential", presented_credential="hunter2")

    # A different install has a different instance identity but says nothing about who the
    # principal is: the role id is minted per record, not derived from the install.
    other_posture = AuthPosture(
        configured_credentials=0,
        credential=None,
        loopback_listener_proven=True,
        companion_proxy_configured=False,
    )
    assert other_posture.subjects() == ("trusted_loopback",)
