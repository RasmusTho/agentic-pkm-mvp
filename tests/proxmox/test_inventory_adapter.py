from __future__ import annotations

import json
from hashlib import sha256

import pytest

from app.orchestrator.mcp_tool_provider import MCPToolProvider
from app.proxmox.inventory import (
    InventoryConfig,
    LocalProxmoxInventoryExecutor,
    MCP_DESCRIPTOR_ID,
    ProxmoxInventoryClient,
    ProxmoxInventoryError,
)


class Transport:
    def __init__(self, fingerprint: str = "sha256:certificate") -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.verifications: list[tuple[str, str]] = []
        self.fingerprint = fingerprint

    def verify_tls(self, *, endpoint: str, expected_fingerprint: str) -> None:
        self.verifications.append((endpoint, expected_fingerprint))
        if self.fingerprint != expected_fingerprint:
            raise ProxmoxInventoryError("TLS certificate fingerprint mismatch")

    def get(self, *, endpoint: str, path: str, token: str):
        self.calls.append((endpoint, path, token))
        return {"data": [{"vmid": 100}, {"vmid": 999}]}


def _client(transport: Transport, endpoint: str = "https://tars.internal") -> ProxmoxInventoryClient:
    scope = {
        "capability": "inventory-read-only",
        "node": "TARS",
        "operations": ["health_check", "get_cluster_summary", "list_allowed_vms", "get_vm_status", "get_storage_status", "list_recent_tasks"],
        "vm_ids": [100, 101, 102, 104],
        "storage_names": ["local", "local-lvm"],
    }
    scope_json = json.dumps(scope, sort_keys=True, separators=(",", ":"))
    refs = {
        "keychain:pve-endpoint": endpoint,
        "keychain:pve-token": "PVEAPIToken=never-receipt",
        "keychain:pve-scope": scope_json,
    }
    return ProxmoxInventoryClient(
        config=InventoryConfig(
            endpoint_secret_ref="keychain:pve-endpoint",
            token_secret_ref="keychain:pve-token",
            principal_scope_secret_ref="keychain:pve-scope",
            token_fingerprint="37b5e65338de4c500502f4c424ba0785f3d8178afbdf468103e560e27eee41f7",
            endpoint_identity=sha256(b"https://tars.internal").hexdigest(),
            tls_fingerprint="sha256:certificate",
            principal_scope_digest=sha256(scope_json.encode("utf-8")).hexdigest(),
        ),
        resolve_secret=refs.__getitem__,
        transport=transport,
    )


def test_named_inventory_operations_are_allowlisted() -> None:
    transport = Transport()
    client = _client(transport)

    assert client.health_check().receipt.operation == "health_check"
    assert client.get_cluster_summary().receipt.operation == "get_cluster_summary"
    assert client.list_allowed_vms().result == {"data": [{"vmid": 100}]}
    assert client.get_vm_status(100).receipt.operation == "get_vm_status"
    assert client.get_storage_status("local").receipt.operation == "get_storage_status"
    assert client.list_recent_tasks().receipt.operation == "list_recent_tasks"
    assert all("/nodes/TARS/" in path or path == "/api2/json/version" or path == "/api2/json/cluster/status" for _, path, _ in transport.calls)
    assert len(transport.verifications) == len(transport.calls)


def test_forbidden_requests_fail_before_http() -> None:
    transport = Transport()
    client = _client(transport)
    for invalid_call in (
        lambda: client.get_vm_status(103),
        lambda: client.get_storage_status("zfs"),
        lambda: _client(transport, "http://tars.internal").health_check(),
        lambda: _client(transport, "https://tars.internal/api2/json/nodes/TARS/qemu/100/status/start").health_check(),
        lambda: _client(transport, "https://untrusted.internal").health_check(),
    ):
        with pytest.raises(ProxmoxInventoryError):
            invalid_call()
    assert transport.calls == []
    assert transport.verifications == []


def test_scope_or_tls_refusals_happen_before_http() -> None:
    transport = Transport(fingerprint="sha256:wrong")
    with pytest.raises(ProxmoxInventoryError, match="TLS"):
        _client(transport).health_check()
    assert transport.verifications == [("https://tars.internal", "sha256:certificate")]
    assert transport.calls == []

    scope_transport = Transport()
    client = _client(scope_transport)
    client._resolve_secret = lambda ref: "{}" if ref == "keychain:pve-scope" else {  # noqa: SLF001
        "keychain:pve-endpoint": "https://tars.internal",
        "keychain:pve-token": "PVEAPIToken=never-receipt",
    }[ref]
    with pytest.raises(ProxmoxInventoryError, match="scope"):
        client.health_check()
    assert scope_transport.verifications == []
    assert scope_transport.calls == []


def test_receipts_never_persist_raw_credentials() -> None:
    result = _client(Transport()).health_check()
    receipt = repr(result.receipt.to_dict())
    assert "PVEAPIToken" not in receipt
    assert "keychain:pve-token" not in receipt
    assert "Authorization" not in receipt
    assert result.receipt.endpoint_identity != "keychain:pve-endpoint"


def test_mcp_admission_requires_explicit_descriptor() -> None:
    transport = Transport()
    executor = LocalProxmoxInventoryExecutor(_client(transport))
    assert executor.descriptor.id == MCP_DESCRIPTOR_ID
    assert executor.descriptor.admission == "local_typed_executor_only"
    assert MCP_DESCRIPTOR_ID not in MCPToolProvider().list_descriptors({"mcp_remote_multiplex_enable": True})
    with pytest.raises(ProxmoxInventoryError, match="loopback"):
        executor.execute(caller_host="10.0.0.2", operation="health_check")
    assert executor.execute(caller_host="127.0.0.1", operation="health_check").receipt.operation == "health_check"
