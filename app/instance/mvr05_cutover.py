"""MVR-05A8 cutover inventory and irreversible runtime floor."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.instance.vault_registry import RegistrySnapshot, VaultRegistryStore


MVR05_RUNTIME_FLOOR = "mvr-05"
MVR05_FENCE_SCHEMA = "agentic-pkm.mvr05-cutover-fence.v1"
_SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_DB_ROLE_LABEL = "com.agentic-pkm.mvr05.db-role"
_DB_ROLES = frozenset(
    {"server", "client", "migration-runner", "fence-controller", "non-client"}
)


class Mvr05CutoverError(RuntimeError):
    """The production-derived database producer fence is incomplete."""


@dataclass(frozen=True)
class Mvr05FencePlan:
    schema: str
    db_clients: tuple[str, ...]
    migration_runner: str
    stopped_services: tuple[str, ...]
    source_sha256: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "db_clients": list(self.db_clients),
            "migration_runner": self.migration_runner,
            "stopped_services": list(self.stopped_services),
            "source_sha256": self.source_sha256,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "Mvr05FencePlan":
        db_clients = payload.get("db_clients")
        stopped_services = payload.get("stopped_services")
        if not isinstance(db_clients, list) or not isinstance(stopped_services, list):
            raise Mvr05CutoverError("the MVR-05 fence plan receipt is malformed")
        try:
            plan = cls(
                schema=str(payload["schema"]),
                db_clients=tuple(str(item) for item in db_clients),
                migration_runner=str(payload["migration_runner"]),
                stopped_services=tuple(str(item) for item in stopped_services),
                source_sha256=str(payload["source_sha256"]),
            )
        except (KeyError, TypeError) as exc:
            raise Mvr05CutoverError("the MVR-05 fence plan receipt is malformed") from exc
        if (
            plan.schema != MVR05_FENCE_SCHEMA
            or len(plan.source_sha256) != 64
            or plan.migration_runner not in plan.db_clients
            or set(plan.stopped_services) != set(plan.db_clients) - {plan.migration_runner}
            or any(not _SERVICE_NAME.fullmatch(item) for item in plan.db_clients)
        ):
            raise Mvr05CutoverError("the MVR-05 fence plan receipt is invalid")
        return plan


def _command_text(service: Mapping[str, object]) -> str:
    command = service.get("command")
    if isinstance(command, str):
        return command
    if isinstance(command, list):
        return " ".join(str(item) for item in command)
    return ""


def _service_role(name: str, service: Mapping[str, object]) -> str:
    labels = service.get("labels")
    role: object | None = None
    if isinstance(labels, Mapping):
        role = labels.get(_DB_ROLE_LABEL)
    elif isinstance(labels, list):
        prefix = f"{_DB_ROLE_LABEL}="
        matches = [str(item)[len(prefix):] for item in labels if str(item).startswith(prefix)]
        if len(matches) == 1:
            role = matches[0]
    if role not in _DB_ROLES:
        raise Mvr05CutoverError(
            f"compose service {name!r} lacks one valid {_DB_ROLE_LABEL} classification"
        )
    return str(role)


def discover_db_producer_fence(compose_path: Path) -> Mvr05FencePlan:
    """Derive every enabled DB client and the unique migration runner from Compose."""

    import yaml

    raw = compose_path.read_text(encoding="utf-8")
    document = yaml.safe_load(raw) or {}
    services = document.get("services")
    if not isinstance(services, dict):
        raise Mvr05CutoverError("compose services are missing")

    db_clients: list[str] = []
    migration_runners: list[str] = []
    servers: list[str] = []
    controllers: list[str] = []
    for raw_name, raw_service in services.items():
        name = str(raw_name)
        if not _SERVICE_NAME.fullmatch(name) or not isinstance(raw_service, dict):
            raise Mvr05CutoverError("compose service inventory is malformed")
        role = _service_role(name, raw_service)
        depends_on = raw_service.get("depends_on")
        depends_on_db = (
            "db" in depends_on
            if isinstance(depends_on, (dict, list))
            else False
        )
        if role == "server":
            servers.append(name)
        elif role == "fence-controller":
            controllers.append(name)
        elif role in {"client", "migration-runner"}:
            if not depends_on_db:
                raise Mvr05CutoverError(
                    f"DB producer {name!r} does not depend on the declared server"
                )
            db_clients.append(name)
        if role == "migration-runner":
            if "run_migrations.sh" not in _command_text(raw_service):
                raise Mvr05CutoverError("the migration runner command is not recognized")
            migration_runners.append(name)

    if len(servers) != 1 or len(controllers) != 1:
        raise Mvr05CutoverError(
            "the DB producer inventory requires one server and one fence controller"
        )

    if len(migration_runners) != 1:
        raise Mvr05CutoverError(
            "the DB producer inventory requires exactly one migration runner"
        )
    runner = migration_runners[0]
    stopped = sorted(set(db_clients) - {runner})
    if not stopped:
        raise Mvr05CutoverError("the DB producer inventory found no runtime clients")
    return Mvr05FencePlan(
        schema=MVR05_FENCE_SCHEMA,
        db_clients=tuple(sorted(db_clients)),
        migration_runner=runner,
        stopped_services=tuple(stopped),
        source_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def record_mvr05_runtime_floor(
    registry_store: VaultRegistryStore,
    *,
    fence: Mvr05FencePlan,
    channel_id: str,
    _capability: Any = None,
) -> RegistrySnapshot:
    """Record the irreversible floor only after the derived stopped fence is proved."""

    if fence.schema != MVR05_FENCE_SCHEMA or fence.migration_runner in fence.stopped_services:
        raise Mvr05CutoverError("the MVR-05 fence plan is invalid")
    snapshot = registry_store.load()
    extensions = snapshot.extensions or {}
    floors = dict(extensions.get("runtimeFloors") or {})
    receipt = {
        **fence.as_payload(),
        "channel_id": channel_id,
        "all_old_scalar_clients_stopped": True,
    }
    existing_floor = str(floors.get("minimumRuntimeSchema") or "").strip()
    existing_receipt = floors.get("mvr05CutoverFence")
    if existing_floor:
        if (
            existing_floor != MVR05_RUNTIME_FLOOR
            or not isinstance(existing_receipt, Mapping)
            or existing_receipt.get("schema") != MVR05_FENCE_SCHEMA
            or existing_receipt.get("all_old_scalar_clients_stopped") is not True
        ):
            raise Mvr05CutoverError("the existing runtime floor has different fence evidence")
        return snapshot
    floors["minimumRuntimeSchema"] = MVR05_RUNTIME_FLOOR
    floors["mvr05CutoverFence"] = json.loads(json.dumps(receipt))
    return registry_store.set_extension_state(
        principal_state=dict(extensions.get("principalState") or {}),
        background_state=dict(extensions.get("backgroundState") or {}),
        runtime_floors=floors,
        expected_revision=snapshot.revision,
        _capability=_capability,
    )


def load_mvr05_fence_plan(path: Path) -> Mvr05FencePlan:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise Mvr05CutoverError("the MVR-05 fence plan receipt must be a mapping")
    return Mvr05FencePlan.from_payload(document)


__all__ = [
    "MVR05_RUNTIME_FLOOR",
    "Mvr05CutoverError",
    "Mvr05FencePlan",
    "discover_db_producer_fence",
    "load_mvr05_fence_plan",
    "record_mvr05_runtime_floor",
]
