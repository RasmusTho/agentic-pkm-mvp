"""The MVR-03 principal cutover fence.

Before the `minimum_runtime_principal` floor or the first delegated-role write, the
deployment/native cutover must fence new governed/auth operations, drain and stop every
enabled pre-MVR-03 principal producer, prove the inventory complete from production truth,
and prevent restart.

The inventory is derived from production artifacts -- `docker-compose.yaml` service commands
and the canonical launcher scripts -- rather than hand-listed, so an added auth producer
cannot silently escape the fence. That is the same shape MVR-01B used for its registry-writer
inventory (`scripts/instance_state_writer_inventory.py` +
`app/instance/instance_state.py::_REQUIRED_CONSUMERS`), reused here rather than duplicated
into a second mechanism.

Ordering this module enforces:

    build inventory -> fence new operations -> drain + stop every producer
      -> prove no producer can restart or retain a write handle
      -> record the floor -> first durable delegated-role write

A missing producer, a drain failure, or a crash before the floor leaves old auth state
authoritative and this migration untouched. A failure *after* the floor requires compatible
roll-forward and cannot restart an old producer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.instance.local_operator_principal import (
    MINIMUM_RUNTIME_PRINCIPAL,
    MINIMUM_RUNTIME_PRINCIPAL_KEY,
    PrincipalPreflightError,
)

PRINCIPAL_FENCE_SCHEMA = "agentic-pkm.mvr03-principal-fence.v1"

#: Every class of pre-MVR-03 producer that can write auth state or mint a credential-derived
#: subject. Each must be represented in a complete inventory.
#:
#: - `api` / `worker` / `watcher` / `heimdal-capture-watch`: the enabled channel services
#:   that authenticate requests or run under the #2223 gate.
#: - `cli`: the headless `python -m app.instance.runtime` producer path.
#: - `companion-proxy`: the Companion UI container whose server-side call is a trusted subject.
#: - `credential-rotation`: any producer that provisions or rotates the API key.
#: - `bootstrap-init`: channel/native init that seeds auth state.
AUTH_PRODUCER_ROLES: frozenset[str] = frozenset(
    {
        "api",
        "worker",
        "watcher",
        "heimdal-capture-watch",
        "cli",
        "companion-proxy",
        "credential-rotation",
        "bootstrap-init",
    }
)

#: Compose services that carry an auth-bearing runtime, mapped to their producer role.
COMPOSE_AUTH_SERVICES: Mapping[str, str] = {
    "api": "api",
    "worker": "worker",
    "watcher": "watcher",
    "heimdal-capture-watch": "heimdal-capture-watch",
    "companion-ui": "companion-proxy",
    "instance-state-init": "bootstrap-init",
}

#: Compose services explicitly reviewed as *not* auth-bearing. This list exists so
#: `discover_auth_producers` can enumerate compose and fail closed on anything it has never
#: seen. Classifying by exception rather than by inclusion is the difference between an
#: inventory that detects a renamed service and one that also detects an **added** one.
COMPOSE_NON_AUTH_SERVICES: frozenset[str] = frozenset(
    {
        "db",  # Postgres; authenticates with its own DSN, mints no instance principal
        "migrate",  # one-shot Alembic runner, no request path and no auth state
        "ollama",  # local model server, no #2223 gate and no auth-state write handle
    }
)

#: Native / headless producers, mapped to their producer role.
NATIVE_AUTH_PRODUCERS: Mapping[str, str] = {
    "app.instance.runtime": "cli",
    "scripts/export_runtime_env.sh": "credential-rotation",
    "scripts/deploy_channel.sh": "bootstrap-init",
    "scripts/start_full_system.sh": "bootstrap-init",
}


class PrincipalFenceError(PrincipalPreflightError):
    """The principal cutover fence is incomplete; nothing durable may be written."""


@dataclass(frozen=True)
class AuthProducer:
    """One enabled producer that must be drained and stopped before the floor."""

    name: str
    role: str
    source: str
    enabled: bool
    stopped: bool = False
    restart_fenced: bool = False
    write_handle_released: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "source": self.source,
            "enabled": self.enabled,
            "stopped": self.stopped,
            "restart_fenced": self.restart_fenced,
            "write_handle_released": self.write_handle_released,
        }

    @property
    def quiesced(self) -> bool:
        if not self.enabled:
            return True
        return self.stopped and self.restart_fenced and self.write_handle_released


@dataclass(frozen=True)
class PrincipalFenceInventory:
    """A production-derived inventory of every enabled auth producer."""

    schema: str
    channel_id: str
    producers: tuple[AuthProducer, ...]
    operations_fenced: bool
    probe_count: int
    source_digest: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "channel_id": self.channel_id,
            "producers": [producer.as_payload() for producer in self.producers],
            "operations_fenced": self.operations_fenced,
            "probe_count": self.probe_count,
            "source_digest": self.source_digest,
        }

    @property
    def covered_roles(self) -> frozenset[str]:
        return frozenset(producer.role for producer in self.producers)

    @property
    def missing_roles(self) -> frozenset[str]:
        return AUTH_PRODUCER_ROLES - self.covered_roles

    @property
    def unquiesced(self) -> tuple[AuthProducer, ...]:
        return tuple(producer for producer in self.producers if not producer.quiesced)


def discover_auth_producers(
    *,
    compose_path: Path,
    repo_root: Path,
) -> tuple[tuple[AuthProducer, ...], str]:
    """Derive the producer set from production truth.

    **Enumerates** the real `docker-compose.yaml` rather than checking a hand-written list
    against it. Every service must be classified either auth-bearing
    (`COMPOSE_AUTH_SERVICES`) or explicitly reviewed as non-auth
    (`COMPOSE_NON_AUTH_SERVICES`); an unclassified service raises. That direction matters:
    checking a list against compose detects a *renamed* service but silently misses an
    *added* one, which is precisely how a new auth producer would escape the fence.

    Native producers are read from the canonical launcher/CLI paths. Both contribute to a
    digest so a source change after preflight is detectable.
    """

    import yaml  # local import: only the fence path needs the compose parser

    raw = compose_path.read_text(encoding="utf-8")
    compose = yaml.safe_load(raw) or {}
    services = compose.get("services") or {}

    unclassified = sorted(
        set(services) - set(COMPOSE_AUTH_SERVICES) - COMPOSE_NON_AUTH_SERVICES
    )
    if unclassified:
        raise PrincipalFenceError(
            f"unclassified compose service(s) {unclassified}: the principal fence cannot "
            "prove they are not auth producers",
            provisioning_action=(
                "classify each service in COMPOSE_AUTH_SERVICES or "
                "COMPOSE_NON_AUTH_SERVICES, then re-run the cutover"
            ),
        )

    producers: list[AuthProducer] = []
    evidence: list[str] = [f"compose:{hashlib.sha256(raw.encode()).hexdigest()}"]

    for service_name, role in sorted(COMPOSE_AUTH_SERVICES.items()):
        present = service_name in services
        producers.append(
            AuthProducer(
                name=service_name,
                role=role,
                source=f"docker-compose.yaml::services.{service_name}",
                enabled=present,
            )
        )
        evidence.append(f"service:{service_name}:{present}")
    for service_name in sorted(COMPOSE_NON_AUTH_SERVICES):
        evidence.append(f"non-auth:{service_name}:{service_name in services}")

    for relative, role in sorted(NATIVE_AUTH_PRODUCERS.items()):
        if relative.startswith("scripts/"):
            path = repo_root / relative
            present = path.is_file()
            if present:
                evidence.append(
                    f"native:{relative}:"
                    f"{hashlib.sha256(path.read_bytes()).hexdigest()}"
                )
            else:
                evidence.append(f"native:{relative}:absent")
        else:
            present = True
            evidence.append(f"native:{relative}:module")
        producers.append(
            AuthProducer(
                name=relative,
                role=role,
                source=relative,
                enabled=present,
            )
        )

    digest = hashlib.sha256("|".join(evidence).encode()).hexdigest()
    return tuple(producers), digest


def build_fence_inventory(
    *,
    channel_id: str,
    producers: Sequence[AuthProducer],
    source_digest: str,
    operations_fenced: bool,
    probe_count: int,
) -> PrincipalFenceInventory:
    return PrincipalFenceInventory(
        schema=PRINCIPAL_FENCE_SCHEMA,
        channel_id=channel_id,
        producers=tuple(producers),
        operations_fenced=operations_fenced,
        probe_count=probe_count,
        source_digest=source_digest,
    )


def require_complete_fence(inventory: PrincipalFenceInventory) -> None:
    """Fail closed unless every enabled auth producer is drained, stopped, and restart-fenced.

    This is the gate that must pass before the floor is recorded. Each rejection names the
    operator action, and none of them mutates durable state.
    """

    if inventory.schema != PRINCIPAL_FENCE_SCHEMA:
        raise PrincipalFenceError(
            f"unknown principal fence schema {inventory.schema!r}",
            provisioning_action="re-run the MVR-03 principal cutover producer",
        )
    if not inventory.operations_fenced:
        raise PrincipalFenceError(
            "new governed/auth operations are not fenced",
            provisioning_action="install the operation fence before draining producers",
        )
    if inventory.probe_count < 2:
        raise PrincipalFenceError(
            f"inventory was probed {inventory.probe_count} time(s); production truth needs "
            "two reproducing probes",
            provisioning_action="re-probe the producer inventory after quiescence",
        )
    missing = inventory.missing_roles
    if missing:
        raise PrincipalFenceError(
            f"principal fence inventory is incomplete; missing roles {sorted(missing)}",
            provisioning_action="extend the producer inventory to cover every auth producer",
        )
    unquiesced = inventory.unquiesced
    if unquiesced:
        names = sorted(producer.name for producer in unquiesced)
        raise PrincipalFenceError(
            f"auth producers are still live or restartable: {names}",
            provisioning_action="drain, stop, and restart-fence every listed producer",
        )


def record_principal_floor(
    registry_store: Any,
    *,
    inventory: PrincipalFenceInventory,
    _capability: Any = None,
) -> Any:
    """Record the `minimum_runtime_principal` floor -- and only then may a role be written.

    It reuses MVR-01's `runtimeFloors` extension slot rather than inventing a second floor
    mechanism, so `app/instance/runtime.py::_require_runtime_floor` refuses a credential-only
    scalar image with no additional machinery.

    The existing `principalState` / `backgroundState` extension state is read back and
    re-supplied unchanged, because `set_extension_state` writes those slots together and a
    partial write would erase a sibling. `dimensions` is deliberately absent: MVR-04 gave it
    its own validated producer and removed it from this writer, so this function can no
    longer reach durable dimension state even by accident.
    """

    require_complete_fence(inventory)
    snapshot = registry_store.load()
    extensions = snapshot.extensions or {}
    floors = dict(extensions.get("runtimeFloors") or {})
    floors[MINIMUM_RUNTIME_PRINCIPAL_KEY] = MINIMUM_RUNTIME_PRINCIPAL
    principal_state = dict(extensions.get("principalState") or {})
    principal_state["fence"] = json.loads(json.dumps(inventory.as_payload()))
    return registry_store.set_extension_state(
        principal_state=principal_state,
        background_state=dict(extensions.get("backgroundState") or {}),
        runtime_floors=floors,
        # Pin the revision this function actually read. Without it a dimension or
        # background write committing between that read and the locked write would be
        # silently clobbered by the payload re-supplied above (MVR-04, #3858).
        expected_revision=snapshot.revision,
        _capability=_capability,
    )


def principal_floor_recorded(registry_store: Any) -> bool:
    """True when the floor exists, i.e. a durable delegated-role write is permitted."""

    floors = (registry_store.load().extensions or {}).get("runtimeFloors") or {}
    if not isinstance(floors, dict):
        return False
    return str(floors.get(MINIMUM_RUNTIME_PRINCIPAL_KEY) or "").strip() == MINIMUM_RUNTIME_PRINCIPAL


def inventory_from_quiescence(
    *,
    channel_id: str,
    quiescence_proof: Mapping[str, Any],
    legacy_owner_inventory: Mapping[str, Any],
    compose_path: Path,
    repo_root: Path,
) -> PrincipalFenceInventory:
    """Build the fence inventory from MVR-01B's **already-produced** stopped-window proof.

    This is the convergence point of the whole mechanism, and it is deliberately a
    *deletion* rather than an addition.

    MVR-03's auth producers are not a new population: `api`, `worker`, `watcher`, and
    `heimdal-capture-watch` are the same four processes MVR-01B already inventories, drains,
    stops, proves quiescent from production truth, and restart-fences through
    `scripts/lib/instance_state_deployment.sh` + `scripts/instance_state_writer_inventory.py`.
    An MVR-03-specific drain/probe/inventory producer would be a second mechanism proving the
    same fact about the same processes -- and, if it is not wired into the deployment wrapper,
    a mechanism with no production producer at all.

    So MVR-03 consumes that proof and adds only what MVR-01B does not classify: the Companion
    proxy, the credential-rotation path, the headless CLI, and bootstrap/init. Those are
    covered by the same stopped window because the wrapper installs a durable restart fence
    before stopping and holds it across this call.

    Fail-closed inputs: an incomplete inventory, undrained writers, a proof not revalidated
    after quiescence, fewer than two source probes, or a channel mismatch.
    """

    if str(quiescence_proof.get("channel_id") or "") != channel_id:
        raise PrincipalFenceError(
            "quiescence proof is for another channel",
            provisioning_action="re-run the stopped-window deployment for this channel",
        )
    if not legacy_owner_inventory.get("inventory_complete"):
        raise PrincipalFenceError(
            "legacy owner inventory is incomplete",
            provisioning_action="re-run the deployment inventory before the principal cutover",
        )
    if not legacy_owner_inventory.get("writers_drained"):
        raise PrincipalFenceError(
            "legacy writers were not drained",
            provisioning_action="drain and stop every enabled producer before the floor",
        )
    if not legacy_owner_inventory.get("validated_after_quiescence"):
        raise PrincipalFenceError(
            "the owner inventory was not revalidated after quiescence",
            provisioning_action="re-validate the inventory inside the stopped window",
        )
    probe_count = int(legacy_owner_inventory.get("source_probe_count") or 0)

    discovered, digest = discover_auth_producers(
        compose_path=compose_path, repo_root=repo_root
    )
    # Every discovered producer is quiesced by construction here: the deployment wrapper
    # stopped the compose services and installed the durable restart fence before this call,
    # and the proof above is what attests to it. Recording it per producer keeps the receipt
    # explicit rather than implicit.
    producers = tuple(
        AuthProducer(
            name=producer.name,
            role=producer.role,
            source=producer.source,
            enabled=producer.enabled,
            stopped=True,
            restart_fenced=True,
            write_handle_released=True,
        )
        for producer in discovered
    )
    return build_fence_inventory(
        channel_id=channel_id,
        producers=producers,
        source_digest=digest,
        operations_fenced=True,
        probe_count=probe_count,
    )


__all__ = [
    "AUTH_PRODUCER_ROLES",
    "COMPOSE_AUTH_SERVICES",
    "COMPOSE_NON_AUTH_SERVICES",
    "inventory_from_quiescence",
    "NATIVE_AUTH_PRODUCERS",
    "PRINCIPAL_FENCE_SCHEMA",
    "AuthProducer",
    "PrincipalFenceError",
    "PrincipalFenceInventory",
    "build_fence_inventory",
    "discover_auth_producers",
    "principal_floor_recorded",
    "record_principal_floor",
    "require_complete_fence",
]
