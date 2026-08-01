"""MVR-04 (#3858): durable dimension membership over the instance registry.

Contract: `docs/MULTI_VAULT_RUNTIME/GROUP_VAULT_BINDINGS_BY_DIMENSION.md`.
"""

from __future__ import annotations

import pytest

from app.instance._storage_boundary import CapabilityNotReadyError
from app.instance.vault_dimensions import (
    DIMENSION_SCHEMA,
    VaultDimensionService,
    parse_dimensions,
)
from app.instance.vault_registry import (
    VaultRegistration,
    VaultRegistryStore,
)
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def _registry(tmp_path):
    """Two local clones of one logical vault, plus a third unrelated binding.

    The clone pair is the case the AC names: one `vault_id`, two distinct
    `vault_binding_id` values. Membership must key on the *binding*, never collapse to the
    logical vault, or a dimension would silently reach both clones when the operator named
    one.
    """

    store = VaultRegistryStore(tmp_path / "instance-state" / "vault-registry.md")
    for binding_id, ref, local_instance in (
        ("binding-clone-a", "path:/vault/a", "clone-a"),
        ("binding-clone-b", "path:/vault/b", "clone-b"),
    ):
        store.register(
            VaultRegistration(
                vault_binding_id=binding_id,
                ref=ref,
                path=ref.removeprefix("path:"),
                vault_id="logical-shared",
                local_instance_id=local_instance,
            ),
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    store.register(
        VaultRegistration(
            vault_binding_id="binding-other",
            ref="path:/vault/other",
            path="/vault/other",
            vault_id="logical-other",
            local_instance_id="other",
        ),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    return store


def _service(store) -> VaultDimensionService:
    return VaultDimensionService(store, capability=STORAGE_MUTATION_CAPABILITY)


def test_dimension_membership_round_trip(tmp_path) -> None:
    """Membership survives restart with stable, ordered binding ids."""

    store = _registry(tmp_path)
    service = _service(store)

    # Deliberately not alphabetical: the stored order is the operator's stated order.
    receipt = service.create(
        "work",
        display_name="Work",
        members=["binding-other", "binding-clone-b", "binding-clone-a"],
    )
    assert receipt.changed is True
    assert receipt.dimension is not None
    assert receipt.dimension.members == (
        "binding-other",
        "binding-clone-b",
        "binding-clone-a",
    )
    assert receipt.dimension.revision == 1

    # A restart: a brand-new store object over the same durable file. Nothing in memory
    # carries over.
    reopened = VaultRegistryStore(store.path)
    restarted = _service(reopened)
    survived = restarted.inspect("work")
    assert survived.display_name == "Work"
    assert survived.members == (
        "binding-other",
        "binding-clone-b",
        "binding-clone-a",
    )
    assert survived.revision == 1

    # The two clones stay distinguishable: they share one logical vault id but are two
    # separate members, and dropping one leaves the other in place.
    snapshot = reopened.load()
    assert (
        snapshot.registrations["binding-clone-a"].vault_id
        == snapshot.registrations["binding-clone-b"].vault_id
    )
    restarted.set_members("work", ["binding-clone-a", "binding-other"])
    assert restarted.inspect("work").members == ("binding-clone-a", "binding-other")
    assert "binding-clone-b" in reopened.load().registrations

    # Rename preserves membership and order and advances only the dimension revision.
    before = restarted.inspect("work")
    renamed = restarted.rename("work", display_name="Work (renamed)")
    assert renamed.dimension is not None
    assert renamed.dimension.members == before.members
    assert renamed.dimension.revision == before.revision + 1

    # The durable payload is the versioned MVR-04 schema, not an opaque blob.
    stored = reopened.load().extensions["dimensions"]
    assert stored["schema"] == DIMENSION_SCHEMA
    assert stored["entries"]["work"]["members"] == ["binding-clone-a", "binding-other"]

    # A second dimension is independent; neither one touches the other's order.
    restarted.create("reading", display_name="Reading", members=["binding-clone-b"])
    assert [item.dimension_id for item in restarted.list()] == ["reading", "work"]
    assert restarted.inspect("work").members == ("binding-clone-a", "binding-other")


def test_dimension_and_registration_removal_are_safe(tmp_path) -> None:
    """Dimension deletion never touches registrations; removal repairs membership.

    Two separate claims, and the AC keeps them apart on purpose:

    1. Deleting a *dimension* is non-destructive to registrations and content.
    2. Removing a *registration* transactionally repairs every dimension that listed it --
       but production registration removal is still `capability_not_ready` until MVR-06B,
       so the hook cannot be reached through an early production bypass.
    """

    store = _registry(tmp_path)
    service = _service(store)
    service.create(
        "work",
        display_name="Work",
        members=["binding-clone-a", "binding-clone-b", "binding-other"],
    )
    service.create("solo", display_name="Solo", members=["binding-other"])

    # -- 1. deleting a dimension leaves registrations and content untouched ------------
    registrations_before = dict(store.load().registrations)
    deleted = service.delete("solo")
    assert deleted.dimension is None
    assert deleted.as_dict()["deleted"] is True
    after = store.load()
    assert after.registrations == registrations_before
    assert "solo" not in parse_dimensions(after.extensions)
    # The surviving dimension is untouched by an unrelated deletion.
    assert service.inspect("work").members == (
        "binding-clone-a",
        "binding-clone-b",
        "binding-other",
    )

    # -- 2. registration removal repairs membership in the same transaction ------------
    before = store.load()
    work_before = parse_dimensions(before.extensions)["work"]
    removed = store.remove_registration(
        "binding-clone-b",
        expected_revision=before.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert "binding-clone-b" not in removed.registrations
    work_after = parse_dimensions(removed.extensions)["work"]
    # Order of the survivors is preserved exactly: repair removes an entry, it does not
    # rebuild the list.
    assert work_after.members == ("binding-clone-a", "binding-other")
    assert work_after.revision == work_before.revision + 1
    assert work_after.last_repair == {
        "reason": "registration_removed",
        "removedVaultBindingId": "binding-clone-b",
        "registryRevision": removed.revision,
    }
    # One transaction: the registry file on disk already shows both effects, so a dangling
    # member was never observable between two writes.
    durable = parse_dimensions(VaultRegistryStore(store.path).load().extensions)
    assert durable["work"].members == ("binding-clone-a", "binding-other")

    # Removing a binding no dimension lists leaves every dimension's revision alone.
    steady = store.load()
    quiet = store.remove_registration(
        "binding-clone-a",
        expected_revision=steady.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert parse_dimensions(quiet.extensions)["work"].members == ("binding-other",)

    # -- the repair hook is not reachable through an early production bypass -----------
    # Production registration removal requires the sealed capability, which no route or
    # CLI command hands to a removal path; without it the store fails closed with
    # `capability_not_ready` and writes nothing.
    frozen = store.path.read_bytes()
    with pytest.raises(CapabilityNotReadyError):
        store.remove_registration("binding-other")
    assert store.path.read_bytes() == frozen
    # ... and the same seal covers the dimension writer itself.
    with pytest.raises(CapabilityNotReadyError):
        VaultDimensionService(store).create("readonly", display_name="Read only")
    assert store.path.read_bytes() == frozen


def test_unrelated_extension_writers_cannot_reach_dimension_state(tmp_path) -> None:
    """The 01B mechanical extension writer cannot wipe or race durable dimensions.

    Two separate protections, and the AC's durability posture needs both:

    1. **Shape.** `set_extension_state` writes the 01B mechanical slots and no longer
       accepts `dimensions` at all, so a caller that reads the slots, edits one, and
       re-supplies the rest cannot destroy durable grouping on a stale or empty payload.
       MVR-02 removed `default_vault_binding_id` from that writer for the same reason.
    2. **Race.** `expected_revision` lets a caller pin the revision it actually read, so a
       write that spans two reads fails closed instead of losing the interleaved one.
    """

    import inspect

    from app.instance.vault_registry import RegistryRevisionConflict

    store = _registry(tmp_path)
    service = _service(store)
    service.create("work", display_name="Work", members=["binding-clone-a"])
    before = parse_dimensions(store.load().extensions)

    # 1. The wipe is unrepresentable: the parameter is gone from the signature.
    assert "dimensions" not in inspect.signature(store.set_extension_state).parameters
    current = store.load()
    store.set_extension_state(
        principal_state={"operator": "local"},
        background_state={"mode": "compatibility"},
        runtime_floors={"registry": "01b"},
        expected_revision=current.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    after = store.load()
    assert parse_dimensions(after.extensions) == before
    assert after.extensions["principalState"] == {"operator": "local"}

    # 2. A stale pinned revision fails closed rather than committing over newer state.
    stale = after.revision
    service.create("reading", display_name="Reading", members=["binding-other"])
    frozen = store.path.read_bytes()
    with pytest.raises(RegistryRevisionConflict):
        store.set_extension_state(
            principal_state={"operator": "raced"},
            background_state={},
            runtime_floors={},
            expected_revision=stale,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert store.path.read_bytes() == frozen
    assert set(parse_dimensions(store.load().extensions)) == {"reading", "work"}

    # The same conflict protects the dimension writer itself.
    conflicting = store.load().revision - 1
    with pytest.raises(RegistryRevisionConflict):
        store.set_dimension_state(
            {"schema": DIMENSION_SCHEMA, "entries": {}},
            expected_revision=conflicting,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert set(parse_dimensions(store.load().extensions)) == {"reading", "work"}


def test_dimension_administration_fails_closed_on_bad_input(tmp_path) -> None:
    """Validation refusals, each of which would otherwise be a way to smuggle state in."""

    from app.instance.vault_dimensions import VaultDimensionError

    store = _registry(tmp_path)
    service = _service(store)

    # An unregistered member cannot be added: additions fail closed. This is input
    # validation on a proposed membership, so it is a plain refusal rather than a
    # resolution conflict over stored state.
    with pytest.raises(VaultDimensionError, match="not a current registration"):
        service.create("bad", display_name="Bad", members=["binding-missing"])
    assert service.list() == ()

    # Ids are bounded so they can never look like a path or carry a separator.
    for bad_id in ("../escape", "Work", "a" * 65, "", "with space"):
        with pytest.raises(VaultDimensionError):
            service.create(bad_id, display_name="X")

    service.create("work", display_name="Work", members=["binding-other"])
    with pytest.raises(VaultDimensionError, match="already exists"):
        service.create("work", display_name="Duplicate")
    with pytest.raises(VaultDimensionError, match="duplicate dimension member"):
        service.set_members("work", ["binding-other", "binding-other"])
    with pytest.raises(VaultDimensionError, match="display name is required"):
        service.rename("work", display_name="   ")

    # A foreign payload in the reserved MVR-01B slot is refused, never reinterpreted as
    # membership: guessing membership is exactly what the spec forbids.
    current = store.load()
    store.set_dimension_state(
        {"focus": ["future-default"]},
        expected_revision=current.revision,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    with pytest.raises(VaultDimensionError, match="unsupported schema"):
        service.list()
