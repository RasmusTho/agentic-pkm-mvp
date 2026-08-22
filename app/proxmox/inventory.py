"""Narrow, read-only PVE inventory boundary.

This module intentionally has no generic request method.  Adding one would turn a
capability-scoped inventory token into an arbitrary PVE proxy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import urlparse


TARS_NODE = "TARS"
ALLOWED_VM_IDS = frozenset({100, 101, 102, 104})
ALLOWED_STORAGES = frozenset({"local", "local-lvm"})
RECEIPT_VERSION = "proxmox.inventory.receipt.v1"
MCP_DESCRIPTOR_ID = "mcp.proxmox.inventory.v1"
INVENTORY_SCOPE_CAPABILITY = "inventory-read-only"


class _InventoryOperation(Enum):
    HEALTH_CHECK = "health_check"
    GET_CLUSTER_SUMMARY = "get_cluster_summary"
    LIST_ALLOWED_VMS = "list_allowed_vms"
    GET_VM_STATUS = "get_vm_status"
    GET_STORAGE_STATUS = "get_storage_status"
    LIST_RECENT_TASKS = "list_recent_tasks"


_READ_PATH_TEMPLATES: Mapping[_InventoryOperation, str] = MappingProxyType(
    {
        _InventoryOperation.HEALTH_CHECK: "/api2/json/version",
        _InventoryOperation.GET_CLUSTER_SUMMARY: "/api2/json/cluster/status",
        _InventoryOperation.LIST_ALLOWED_VMS: "/api2/json/nodes/{node}/qemu",
        _InventoryOperation.GET_VM_STATUS: "/api2/json/nodes/{node}/qemu/{identifier}/status/current",
        _InventoryOperation.GET_STORAGE_STATUS: "/api2/json/nodes/{node}/storage/{identifier}/status",
        _InventoryOperation.LIST_RECENT_TASKS: "/api2/json/nodes/{node}/tasks",
    }
)


class ProxmoxInventoryError(RuntimeError):
    """Raised when the inventory boundary refuses a request."""


class PVEAuthenticatedReadSession(Protocol):
    """Capability for reads on the same connection that passed pin verification."""

    def get(self, *, path: str, token: str) -> Mapping[str, Any]: ...


class PVETransport(Protocol):
    """Opens one connection-bound, pin-verified read session."""

    def open_pinned_session(
        self,
        *,
        endpoint: str,
        expected_fingerprint: str,
    ) -> PVEAuthenticatedReadSession: ...


SecretResolver = Callable[[str], str]


@dataclass(frozen=True)
class InventoryPolicy:
    node: str = TARS_NODE
    vm_ids: frozenset[int] = ALLOWED_VM_IDS
    storage_names: frozenset[str] = ALLOWED_STORAGES

    def __post_init__(self) -> None:
        if self.node != TARS_NODE:
            raise ProxmoxInventoryError("unknown Proxmox node")
        if not self.vm_ids.issubset(ALLOWED_VM_IDS):
            raise ProxmoxInventoryError("VM allowlist exceeds TARS inventory policy")
        if not self.storage_names.issubset(ALLOWED_STORAGES):
            raise ProxmoxInventoryError("storage allowlist exceeds TARS inventory policy")


@dataclass(frozen=True)
class InventoryConfig:
    endpoint_secret_ref: str
    token_secret_ref: str
    principal_scope_secret_ref: str
    token_fingerprint: str
    endpoint_identity: str
    tls_fingerprint: str
    principal_scope_digest: str
    policy: InventoryPolicy = InventoryPolicy()

    def __post_init__(self) -> None:
        if not self.endpoint_secret_ref or not self.token_secret_ref or not self.principal_scope_secret_ref:
            raise ProxmoxInventoryError("endpoint, token, and scope secret references are required")
        if not self.token_fingerprint or not self.tls_fingerprint:
            raise ProxmoxInventoryError("token and TLS fingerprints are required")
        if not self.endpoint_identity or not self.principal_scope_digest:
            raise ProxmoxInventoryError("endpoint identity and principal/scope digest are required")


@dataclass(frozen=True)
class InventoryReceipt:
    version: str
    endpoint_identity: str
    tls_fingerprint: str
    principal_scope_digest: str
    allowlist_policy: Mapping[str, Any]
    operation: str
    outcome: str
    result_digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InventoryResult:
    result: Mapping[str, Any]
    receipt: InventoryReceipt


@dataclass(frozen=True)
class ProxmoxInventoryDescriptor:
    """Explicit local-only descriptor; deliberately absent from remote MCP registry."""

    id: str = MCP_DESCRIPTOR_ID
    admission: str = "local_typed_executor_only"
    operations: tuple[str, ...] = (
        "health_check",
        "get_cluster_summary",
        "list_allowed_vms",
        "get_vm_status",
        "get_storage_status",
        "list_recent_tasks",
    )


class LocalProxmoxInventoryExecutor:
    """Admission seam for a loopback-only, typed local caller.

    The executor is intentionally not a RemoteMCPProvider and does not accept an
    operation name/path supplied by a remote caller.
    """

    descriptor = ProxmoxInventoryDescriptor()

    def __init__(self, client: "ProxmoxInventoryClient") -> None:
        self._client = client

    def execute(self, *, caller_host: str, operation: str, identifier: int | str | None = None) -> InventoryResult:
        if caller_host not in {"127.0.0.1", "::1"}:
            raise ProxmoxInventoryError("only direct loopback callers are admitted")
        methods: Mapping[str, Callable[..., InventoryResult]] = {
            "health_check": self._client.health_check,
            "get_cluster_summary": self._client.get_cluster_summary,
            "list_allowed_vms": self._client.list_allowed_vms,
            "get_vm_status": self._client.get_vm_status,
            "get_storage_status": self._client.get_storage_status,
            "list_recent_tasks": self._client.list_recent_tasks,
        }
        method = methods.get(operation)
        if method is None:
            raise ProxmoxInventoryError("operation is not admitted")
        if operation == "get_vm_status":
            return method(identifier)  # type: ignore[misc]
        if operation == "get_storage_status":
            return method(identifier)  # type: ignore[misc]
        return method()


class ProxmoxInventoryClient:
    """Typed PVE read-only client with deny-before-transport enforcement."""

    def __init__(self, *, config: InventoryConfig, resolve_secret: SecretResolver, transport: PVETransport) -> None:
        self._config = config
        self._resolve_secret = resolve_secret
        self._transport = transport

    def health_check(self) -> InventoryResult:
        return self._read(_InventoryOperation.HEALTH_CHECK)

    def get_cluster_summary(self) -> InventoryResult:
        return self._read(_InventoryOperation.GET_CLUSTER_SUMMARY)

    def list_allowed_vms(self) -> InventoryResult:
        result = self._read(_InventoryOperation.LIST_ALLOWED_VMS)
        rows = result.result.get("data", [])
        if not isinstance(rows, Sequence):
            rows = []
        filtered = [row for row in rows if isinstance(row, Mapping) and row.get("vmid") in self._config.policy.vm_ids]
        return self._result("list_allowed_vms", {"data": filtered}, endpoint_identity=result.receipt.endpoint_identity)

    def get_vm_status(self, vm_id: int | object) -> InventoryResult:
        return self._read(_InventoryOperation.GET_VM_STATUS, identifier=vm_id)

    def get_storage_status(self, storage: str | object) -> InventoryResult:
        return self._read(_InventoryOperation.GET_STORAGE_STATUS, identifier=storage)

    def list_recent_tasks(self) -> InventoryResult:
        return self._read(_InventoryOperation.LIST_RECENT_TASKS)

    def _read(self, operation: _InventoryOperation, *, identifier: object | None = None) -> InventoryResult:
        path = self._path_for_operation(operation, identifier=identifier)
        endpoint = self._endpoint()
        token = self._resolve_secret(self._config.token_secret_ref)
        if not isinstance(token, str) or not token:
            raise ProxmoxInventoryError("token secret reference did not resolve")
        if sha256(token.encode("utf-8")).hexdigest() != self._config.token_fingerprint:
            raise ProxmoxInventoryError("token fingerprint mismatch")
        self._validate_inventory_scope()
        # `session` is an object capability bound to the same connection whose
        # certificate pin was verified.  There is deliberately no token-bearing
        # transport-level `get` that could reconnect after verification.
        session = self._transport.open_pinned_session(
            endpoint=endpoint,
            expected_fingerprint=self._config.tls_fingerprint,
        )
        payload = session.get(path=path, token=token)
        return self._result(operation.value, payload, endpoint_identity=sha256(endpoint.encode("utf-8")).hexdigest())

    def _path_for_operation(self, operation: _InventoryOperation, *, identifier: object | None) -> str:
        if not isinstance(operation, _InventoryOperation):
            raise ProxmoxInventoryError("operation is not admitted")
        if operation is _InventoryOperation.GET_VM_STATUS:
            if not isinstance(identifier, int) or identifier not in self._config.policy.vm_ids:
                raise ProxmoxInventoryError("unknown VMID")
        elif operation is _InventoryOperation.GET_STORAGE_STATUS:
            if not isinstance(identifier, str) or identifier not in self._config.policy.storage_names:
                raise ProxmoxInventoryError("unknown storage")
        elif identifier is not None:
            raise ProxmoxInventoryError("operation does not accept an identifier")
        return _READ_PATH_TEMPLATES[operation].format(
            node=self._config.policy.node,
            identifier=identifier,
        )

    def _endpoint(self) -> str:
        endpoint = self._resolve_secret(self._config.endpoint_secret_ref)
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ProxmoxInventoryError("PVE endpoint must be a bare HTTPS authority")
        if parsed.username or parsed.password:
            raise ProxmoxInventoryError("PVE endpoint must not contain user credentials")
        normalized = endpoint.rstrip("/")
        if sha256(normalized.encode("utf-8")).hexdigest() != self._config.endpoint_identity:
            raise ProxmoxInventoryError("PVE endpoint does not match fixed TARS endpoint identity")
        return normalized

    def _validate_inventory_scope(self) -> None:
        raw_scope = self._resolve_secret(self._config.principal_scope_secret_ref)
        try:
            scope = json.loads(raw_scope)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProxmoxInventoryError("inventory token scope is not valid JSON") from exc
        if not isinstance(scope, Mapping):
            raise ProxmoxInventoryError("inventory token scope is not an object")
        if sha256(_canonical_bytes(scope)).hexdigest() != self._config.principal_scope_digest:
            raise ProxmoxInventoryError("principal/scope digest mismatch")
        operations = scope.get("operations")
        vm_ids = scope.get("vm_ids")
        storage_names = scope.get("storage_names")
        if (
            scope.get("capability") != INVENTORY_SCOPE_CAPABILITY
            or scope.get("node") != self._config.policy.node
            or not isinstance(operations, list)
            or set(operations) != set(ProxmoxInventoryDescriptor().operations)
            or not isinstance(vm_ids, list)
            or not set(vm_ids).issubset(self._config.policy.vm_ids)
            or not isinstance(storage_names, list)
            or not set(storage_names).issubset(self._config.policy.storage_names)
        ):
            raise ProxmoxInventoryError("token scope is broader than inventory policy")

    def _result(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        endpoint_identity: str | None = None,
    ) -> InventoryResult:
        safe_payload = dict(payload)
        digest = sha256(_canonical_bytes(safe_payload)).hexdigest()
        receipt = InventoryReceipt(
            version=RECEIPT_VERSION,
            endpoint_identity=endpoint_identity or sha256(self._config.endpoint_secret_ref.encode()).hexdigest(),
            tls_fingerprint=self._config.tls_fingerprint,
            principal_scope_digest=self._config.principal_scope_digest,
            allowlist_policy={
                "node": self._config.policy.node,
                "vm_ids": sorted(self._config.policy.vm_ids),
                "storage_names": sorted(self._config.policy.storage_names),
            },
            operation=operation,
            outcome="ok",
            result_digest=digest,
        )
        return InventoryResult(result=safe_payload, receipt=receipt)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


__all__ = [
    "ALLOWED_STORAGES",
    "ALLOWED_VM_IDS",
    "InventoryConfig",
    "InventoryPolicy",
    "InventoryReceipt",
    "InventoryResult",
    "LocalProxmoxInventoryExecutor",
    "MCP_DESCRIPTOR_ID",
    "PVETransport",
    "PVEAuthenticatedReadSession",
    "ProxmoxInventoryClient",
    "ProxmoxInventoryDescriptor",
    "ProxmoxInventoryError",
    "TARS_NODE",
]
