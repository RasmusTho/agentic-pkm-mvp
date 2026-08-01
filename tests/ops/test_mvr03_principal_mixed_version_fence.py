"""MVR-03 (#3857): the principal cutover fence and its production-derived inventory.

Two separate obligations, deliberately kept as two tests:

- *ordering*: nothing durable is written until every enabled legacy auth producer is
  drained, stopped, and restart-fenced,
- *completeness*: the inventory is derived from production truth, so an added auth producer
  cannot escape the fence by simply not being on a hand-written list.
"""

from __future__ import annotations

import json

import pytest
import yaml

from app.instance.local_operator_principal import (
    MINIMUM_RUNTIME_PRINCIPAL_KEY,
    AuthPosture,
    PrincipalFloorNotRecordedError,
)
from app.instance.principal_fence import (
    AUTH_PRODUCER_ROLES,
    COMPOSE_AUTH_SERVICES,
    NATIVE_AUTH_PRODUCERS,
    AuthProducer,
    PrincipalFenceError,
    build_fence_inventory,
    discover_auth_producers,
    inventory_from_quiescence,
    principal_floor_recorded,
    record_principal_floor,
    require_complete_fence,
)
from app.instance.runtime import open_local_operator_principal_store
from tests._mvr03_principal_harness import (
    complete_inventory,
    principal_record_path,
    quiesced_producers,
    record_floor_through_cli,
)
from tests._mvr_default_vault_harness import REPO_ROOT, active_runtime
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def _mutate(
    producers: tuple[AuthProducer, ...], name: str, **changes: object
) -> tuple[AuthProducer, ...]:
    return tuple(
        AuthProducer(
            name=producer.name,
            role=producer.role,
            source=producer.source,
            enabled=bool(changes.get("enabled", producer.enabled)),
            stopped=bool(changes.get("stopped", producer.stopped)),
            restart_fenced=bool(changes.get("restart_fenced", producer.restart_fenced)),
            write_handle_released=bool(
                changes.get("write_handle_released", producer.write_handle_released)
            ),
        )
        if producer.name == name
        else producer
        for producer in producers
    )


def test_every_legacy_auth_producer_stops_before_principal_floor_write(tmp_path) -> None:
    """No floor and no role write while any producer can still race.

    Fault injection walks each way a producer can remain dangerous -- still running, able
    to restart, or still holding an auth-state write handle -- and asserts each one blocks
    the floor. After each refusal the registry revision and the absent principal record are
    both re-checked, so a partial write cannot hide behind the raised exception.
    """

    runtime, registration, _ = active_runtime(tmp_path)
    store = open_local_operator_principal_store(runtime.layout.registry_path)
    producers, digest = quiesced_producers()
    revision_before = runtime.registry.load().revision

    def _attempt(inventory) -> None:
        with pytest.raises(PrincipalFenceError):
            record_principal_floor(
                runtime.registry,
                inventory=inventory,
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
        # Nothing moved: old auth state stays authoritative and the migration untouched.
        assert runtime.registry.load().revision == revision_before
        assert not principal_floor_recorded(runtime.registry)
        assert not principal_record_path(runtime).exists()

    # -- operations not fenced ----------------------------------------------------------
    _attempt(
        build_fence_inventory(
            channel_id="prod",
            producers=producers,
            source_digest=digest,
            operations_fenced=False,
            probe_count=2,
        )
    )

    # -- inventory not reproduced by a second probe -------------------------------------
    _attempt(
        build_fence_inventory(
            channel_id="prod",
            producers=producers,
            source_digest=digest,
            operations_fenced=True,
            probe_count=1,
        )
    )

    # -- one producer still live / restartable / holding a write handle -----------------
    for target in ("api", "worker", "companion-ui", "app.instance.runtime"):
        for failure in ("stopped", "restart_fenced", "write_handle_released"):
            _attempt(
                build_fence_inventory(
                    channel_id="prod",
                    producers=_mutate(producers, target, **{failure: False}),
                    source_digest=digest,
                    operations_fenced=True,
                    probe_count=2,
                )
            )

    # -- a whole producer role missing from the inventory -------------------------------
    without_rotation = tuple(
        producer for producer in producers if producer.role != "credential-rotation"
    )
    _attempt(
        build_fence_inventory(
            channel_id="prod",
            producers=without_rotation,
            source_digest=digest,
            operations_fenced=True,
            probe_count=2,
        )
    )

    # -- the role write is refused independently, even with the fence complete ----------
    posture = AuthPosture(
        configured_credentials=0,
        credential_fingerprint=None,
        loopback_listener_proven=True,
        companion_proxy_configured=False,
    )
    with pytest.raises(PrincipalFloorNotRecordedError):
        store.bootstrap(
            credential_fingerprint=None,
            subjects=posture.subjects(),
            migration_provenance=posture.migration_provenance(existing_install=True),
            floor_recorded=False,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert not principal_record_path(runtime).exists()

    # -- the complete fence lets the floor land, and only then the role write ------------
    # Recorded through the shipped CLI producer, not a direct call: an invariant whose only
    # producer is a test fixture is a latent outage the moment an operator runs the real
    # deployment (`AGENTS.md :: Required rules`, invariant -> producers).
    receipt = record_floor_through_cli(runtime)
    assert receipt["_exit_code"] == 0, receipt
    assert receipt["floor_recorded"] is True
    assert receipt["fenced_producers"] == len(complete_inventory().producers)
    assert principal_floor_recorded(runtime.registry)
    floor_revision = runtime.registry.load().revision
    assert floor_revision > revision_before

    record = store.bootstrap(
        credential_fingerprint=None,
        subjects=posture.subjects(),
        migration_provenance=posture.migration_provenance(existing_install=True),
        floor_recorded=True,
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert record.revision == 1
    assert principal_record_path(runtime).exists()

    # The floor is durable across a reopen: an old producer cannot come back after the new
    # role state became authoritative.
    reopened = type(runtime.registry)(runtime.layout.registry_path)
    assert (
        reopened.load().extensions["runtimeFloors"][MINIMUM_RUNTIME_PRINCIPAL_KEY]
        == "mvr-03"
    )


def test_principal_fence_inventory_covers_every_enabled_auth_producer(tmp_path) -> None:
    """The inventory is derived from production truth, not hand-listed.

    The failure this prevents: someone adds an auth-bearing service to
    `docker-compose.yaml` and the fence keeps passing because a static list never learned
    about it. The mapping is asserted *against the real compose file*, so the two cannot
    drift apart silently.
    """

    compose_path = REPO_ROOT / "docker-compose.yaml"
    producers, digest = discover_auth_producers(
        compose_path=compose_path, repo_root=REPO_ROOT
    )
    inventory = build_fence_inventory(
        channel_id="prod",
        producers=producers,
        source_digest=digest,
        operations_fenced=True,
        probe_count=2,
    )

    # Every declared auth-producer role is represented.
    assert inventory.missing_roles == frozenset()
    assert inventory.covered_roles == AUTH_PRODUCER_ROLES

    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    services = compose.get("services") or {}

    # Every mapped compose service actually exists in the production compose file, and is
    # discovered as enabled. A rename would fail here rather than silently shrinking the
    # fence.
    for service_name in COMPOSE_AUTH_SERVICES:
        assert service_name in services, f"{service_name} is no longer a compose service"
    discovered = {producer.name: producer for producer in producers}
    for service_name, role in COMPOSE_AUTH_SERVICES.items():
        assert discovered[service_name].enabled is True
        assert discovered[service_name].role == role

    # Every native producer path exists on disk (a module entry is always present).
    for relative in NATIVE_AUTH_PRODUCERS:
        if relative.startswith("scripts/"):
            assert (REPO_ROOT / relative).is_file(), f"{relative} is missing"
        assert discovered[relative].enabled is True

    # The four #2223-gated channel runtimes that resolve a principal are all covered. This
    # is the same consumer set MVR-01B fenced for registry writes; a divergence between the
    # two would mean one fence covers a process the other does not.
    from app.instance.instance_state import _REQUIRED_CONSUMERS

    assert _REQUIRED_CONSUMERS <= inventory.covered_roles

    # The digest is a real function of production truth: a changed compose file changes it.
    assert len(digest) == 64
    stripped_path = tmp_path / "docker-compose.stripped.yaml"
    stripped = {
        "services": {
            name: value
            for name, value in services.items()
            if name not in {"api", "companion-ui"}
        }
    }
    stripped_path.write_text(yaml.safe_dump(stripped), encoding="utf-8")
    reduced_producers, reduced_digest = discover_auth_producers(
        compose_path=stripped_path, repo_root=REPO_ROOT
    )
    assert reduced_digest != digest

    # A compose file that dropped an auth service is discovered as *disabled*, not as
    # silently absent: the producer row still exists and still carries its role.
    reduced_by_name = {producer.name: producer for producer in reduced_producers}
    assert reduced_by_name["api"].enabled is False
    assert reduced_by_name["companion-ui"].enabled is False

    reduced = build_fence_inventory(
        channel_id="prod",
        producers=tuple(
            AuthProducer(
                name=p.name,
                role=p.role,
                source=p.source,
                enabled=p.enabled,
                stopped=True,
                restart_fenced=True,
                write_handle_released=True,
            )
            for p in reduced_producers
        ),
        source_digest=reduced_digest,
        operations_fenced=True,
        probe_count=2,
    )
    # A producer that is not deployed at all is legitimately quiesced, so completeness
    # still holds by role while the *enabled* set is smaller. That is the honest
    # distinction the fence draws between "not present" and "not checked".
    require_complete_fence(reduced)
    assert any(not producer.enabled for producer in reduced.producers)
    assert reduced.missing_roles == frozenset()

    # The payload is receipt-safe: no credential, fingerprint, or host path.
    payload = json.dumps(inventory.as_payload())
    assert "credential_fingerprint" not in payload
    assert str(REPO_ROOT) not in payload

    # -- an ADDED service cannot escape the fence ---------------------------------------
    # This is the failure a hand-written list misses: enumerate-and-classify catches it,
    # check-the-list-against-compose does not.
    added_path = tmp_path / "docker-compose.added.yaml"
    added = {"services": dict(services)}
    added["services"]["api-v2"] = dict(services["api"])
    added_path.write_text(yaml.safe_dump(added), encoding="utf-8")
    with pytest.raises(PrincipalFenceError) as unclassified:
        discover_auth_producers(compose_path=added_path, repo_root=REPO_ROOT)
    assert "api-v2" in str(unclassified.value)
    assert "classify each service" in unclassified.value.provisioning_action

    # The digest is recomputed at the moment the floor is recorded rather than carried in
    # from a caller, so there is no window in which a recorded digest can go stale: the
    # producer set the fence approves is the one just read off production sources.
    assert (
        inventory_from_quiescence(
            channel_id="prod",
            quiescence_proof={"channel_id": "prod", "nonce": "n"},
            legacy_owner_inventory={
                "inventory_complete": True,
                "writers_drained": True,
                "validated_after_quiescence": True,
                "source_probe_count": 2,
            },
            compose_path=compose_path,
            repo_root=REPO_ROOT,
        ).source_digest
        == digest
    )

    # -- the shipped deployment wrapper actually invokes the producer -------------------
    # An ordering assertion against the REAL shell wrapper, mirroring MVR-01B's
    # `test_real_deployment_wrapper_probes_all_domains_twice_before_proof`. Without this the
    # CLI could exist while no deployment ever calls it -- which is how the round-1 P0
    # happened.
    wrapper = (REPO_ROOT / "scripts/lib/instance_state_deployment.sh").read_text(
        encoding="utf-8"
    )
    assert "principal-record-floor" in wrapper
    assert "principal-bootstrap" in wrapper
    assert "MVR03_PRINCIPAL_CUTOVER" in wrapper, (
        "advancing the floor must be explicit, never an inferred side effect of deploying "
        "a capable image"
    )
    # It runs inside the stopped window: after the quiescence proof, before finish.
    assert wrapper.index("deployment-prove") < wrapper.index("principal-record-floor")
    assert wrapper.index("principal-record-floor") < wrapper.index("principal-bootstrap")
    assert wrapper.index("principal-bootstrap") < wrapper.rindex(
        "python -m app.instance.runtime deployment-finish"
    )
    # It consumes THIS window's proof and drained-owner inventory rather than probing again.
    floor_call = wrapper[
        wrapper.index("principal-record-floor") : wrapper.index("principal-bootstrap")
    ]
    assert "deployment-quiescence-proof.json" in floor_call
    assert "--inventory-path" in floor_call
    # Sources are explicit mounted paths: the runtime image has no repo checkout.
    assert "--compose-base" in floor_call and "--native-producer-root" in floor_call

    # -- fail-closed inputs to the reworked inventory ------------------------------------
    good_proof = {"channel_id": "prod", "nonce": "n1"}
    good_owners = {
        "inventory_complete": True,
        "writers_drained": True,
        "validated_after_quiescence": True,
        "source_probe_count": 2,
    }
    built = inventory_from_quiescence(
        channel_id="prod",
        quiescence_proof=good_proof,
        legacy_owner_inventory=good_owners,
        compose_path=compose_path,
        repo_root=REPO_ROOT,
    )
    require_complete_fence(built)
    assert built.missing_roles == frozenset()

    for bad_proof, bad_owners, expected in (
        ({"channel_id": "dev", "nonce": "n1"}, good_owners, "another channel"),
        (good_proof, {**good_owners, "inventory_complete": False}, "incomplete"),
        (good_proof, {**good_owners, "writers_drained": False}, "not drained"),
        (
            good_proof,
            {**good_owners, "validated_after_quiescence": False},
            "not revalidated",
        ),
    ):
        with pytest.raises(PrincipalFenceError, match=expected):
            inventory_from_quiescence(
                channel_id="prod",
                quiescence_proof=bad_proof,
                legacy_owner_inventory=bad_owners,
                compose_path=compose_path,
                repo_root=REPO_ROOT,
            )

    # One probe is not production truth, and it is rejected at the fence gate.
    single_probe = inventory_from_quiescence(
        channel_id="prod",
        quiescence_proof=good_proof,
        legacy_owner_inventory={**good_owners, "source_probe_count": 1},
        compose_path=compose_path,
        repo_root=REPO_ROOT,
    )
    with pytest.raises(PrincipalFenceError, match="two reproducing probes"):
        require_complete_fence(single_probe)
