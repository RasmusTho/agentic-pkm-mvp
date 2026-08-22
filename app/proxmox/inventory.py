"""Narrow, read-only PVE inventory boundary.

This module intentionally has no generic request method.  Adding one would turn a
capability-scoped inventory token into an arbitrary PVE proxy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import urlparse


TARS_NODE = "TARS"
ALLOWED_VM_IDS = frozenset({100, 101, 102, 104})
ALLOWED_STORAGES = frozenset({"local", "local-lvm"})
RECEIPT_VERSION = "proxmox.inventory.receipt.v1"
MCP_DESCRIPTOR_ID = "mcp.proxmox.inventory.v1"


class ProxmoxInventoryError(RuntimeError):
    """Raised when the inventory boundary refuses a request."""


class PVETransport(Protocol):
    """A transport that reports the TLS identity observed for every response."""

    def get(self, *, endpoint: str, path: str, token: str) -> tuple[Mapping[str, Any], str]: ...


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
    token_fingerprint: str
    tls_fingerprint: str
    principal_scope_digest: str
    policy: InventoryPolicy = InventoryPolicy()

    def __post_init__(self) -> None:
        if not self.endpoint_secret_ref or not self.token_secret_ref:
            raise ProxmoxInventoryError("endpoint and token secret references are required")
        if not self.token_fingerprint or not self.tls_fingerprint:
            raise ProxmoxInventoryError("token and TLS fingerprints are required")
        if not self.principal_scope_digest:
            raise ProxmoxInventoryError("principal/scope digest is required")


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
        return self._read("health_check", "/api2/json/version")

    def get_cluster_summary(self) -> InventoryResult:
        return self._read("get_cluster_summary", "/api2/json/cluster/status")

    def list_allowed_vms(self) -> InventoryResult:
        result = self._read("list_allowed_vms", f"/api2/json/nodes/{self._config.policy.node}/qemu")
        rows = result.result.get("data", [])
        if not isinstance(rows, Sequence):
            rows = []
        filtered = [row for row in rows if isinstance(row, Mapping) and row.get("vmid") in self._config.policy.vm_ids]
        return self._result("list_allowed_vms", {"data": filtered}, endpoint_identity=result.receipt.endpoint_identity)

    def get_vm_status(self, vm_id: int | object) -> InventoryResult:
        if not isinstance(vm_id, int) or vm_id not in self._config.policy.vm_ids:
            raise ProxmoxInventoryError("unknown VMID")
        return self._read("get_vm_status", f"/api2/json/nodes/{self._config.policy.node}/qemu/{vm_id}/status/current")

    def get_storage_status(self, storage: str | object) -> InventoryResult:
        if not isinstance(storage, str) or storage not in self._config.policy.storage_names:
            raise ProxmoxInventoryError("unknown storage")
        return self._read("get_storage_status", f"/api2/json/nodes/{self._config.policy.node}/storage/{storage}/status")

    def list_recent_tasks(self) -> InventoryResult:
        return self._read("list_recent_tasks", f"/api2/json/nodes/{self._config.policy.node}/tasks")

    def _read(self, operation: str, path: str) -> InventoryResult:
        endpoint = self._endpoint()
        token = self._resolve_secret(self._config.token_secret_ref)
        if not isinstance(token, str) or not token:
            raise ProxmoxInventoryError("token secret reference did not resolve")
        if sha256(token.encode("utf-8")).hexdigest() != self._config.token_fingerprint:
            raise ProxmoxInventoryError("token fingerprint mismatch")
        payload, observed_fingerprint = self._transport.get(endpoint=endpoint, path=path, token=token)
        if observed_fingerprint != self._config.tls_fingerprint:
            raise ProxmoxInventoryError("TLS certificate fingerprint mismatch")
        return self._result(operation, payload, endpoint_identity=sha256(endpoint.encode("utf-8")).hexdigest())

    def _endpoint(self) -> str:
        endpoint = self._resolve_secret(self._config.endpoint_secret_ref)
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ProxmoxInventoryError("PVE endpoint must be a bare HTTPS authority")
        return endpoint.rstrip("/")

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
    "ProxmoxInventoryClient",
    "ProxmoxInventoryDescriptor",
    "ProxmoxInventoryError",
    "TARS_NODE",
]
