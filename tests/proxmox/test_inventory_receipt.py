from __future__ import annotations

from app.proxmox.inventory import InventoryReceipt, RECEIPT_VERSION


def test_proxmox_adapter_receipt_v1_round_trip() -> None:
    receipt = InventoryReceipt(
        version=RECEIPT_VERSION,
        endpoint_identity="sha256:endpoint",
        tls_fingerprint="sha256:tls",
        principal_scope_digest="sha256:scope",
        allowlist_policy={"node": "TARS", "vm_ids": [100, 101, 102, 104], "storage_names": ["local", "local-lvm"]},
        operation="health_check",
        outcome="ok",
        result_digest="sha256:result",
    )
    payload = receipt.to_dict()
    assert payload["version"] == "proxmox.inventory.receipt.v1"
    assert InventoryReceipt(**payload) == receipt
