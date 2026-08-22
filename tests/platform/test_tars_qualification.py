from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.ops.tars_qualification import (
    DEFAULT_POLICY,
    emit_redacted_evidence_bundle,
    evaluate_qualification,
)


def _evidence(*, collected_at: datetime | None = None) -> dict[str, object]:
    observed_at = collected_at or datetime.now(timezone.utc)
    return {
        "collected_at": observed_at.isoformat().replace("+00:00", "Z"),
        "host": {
            "cpu_virtualization": True,
            "thermals_ok": True,
            "unattended_boot": True,
            "recovery_proven": True,
            "nic_vlan": {"management_vlan": 11, "guest_vlan": 42, "bridge": "vmbr0"},
            "storage": {"free_gib": 20, "minimum_free_gib": 16},
            "listeners": [{"exposure": "private"}],
        },
        "vm_102": {
            "vmid": 102,
            "name": "builder-system",
            "cores": 2,
            "memory_mib": 4096,
            "disk_gib": 60,
            "bridge": "vmbr0",
            "vlan_tag": 42,
            "firewall_enabled": True,
            "onboot": True,
            "qemu_agent_enabled": True,
            "network_scope": "guest-vlan-42",
        },
        "builderops": {
            "builder_engine_id": "engine-builder-102",
            "product_engine_id": "engine-product-100",
            "compose_projects": ["builderops-control-plane"],
            "secret_refs": ["keychain:builderops.api-token"],
            "prod_credential_refs": [],
            "prod_vault_refs": [],
            "prod_network_identities": [],
        },
    }


def test_qualification_receipt_fails_closed_on_missing_or_stale_evidence() -> None:
    missing = emit_redacted_evidence_bundle(_evidence())
    del missing["evidence"]["host"]["recovery_proven"]
    missing_receipt = evaluate_qualification(missing)
    assert missing_receipt["candidate_verdict"] == "fail"
    assert any("recovery_proven" in refusal for refusal in missing_receipt["refusals"])

    stale_bundle = emit_redacted_evidence_bundle(
        _evidence(collected_at=datetime.now(timezone.utc) - timedelta(hours=25))
    )
    stale_receipt = evaluate_qualification(stale_bundle)
    assert stale_receipt["candidate_verdict"] == "fail"
    assert any("stale" in refusal for refusal in stale_receipt["refusals"])

    unverifiable = emit_redacted_evidence_bundle(_evidence())
    unverifiable["evidence_fingerprints"]["host"] = "0" * 64
    unverifiable_receipt = evaluate_qualification(unverifiable)
    assert unverifiable_receipt["candidate_verdict"] == "fail"
    assert any("fingerprint" in refusal for refusal in unverifiable_receipt["refusals"])


def test_builder_system_baseline_rejects_product_overlap() -> None:
    bundle = emit_redacted_evidence_bundle(_evidence())
    bundle["evidence"]["builderops"]["product_engine_id"] = "engine-builder-102"
    receipt = evaluate_qualification(bundle)

    assert receipt["candidate_verdict"] == "fail"
    assert any("Product Docker engine" in refusal for refusal in receipt["refusals"])

    overlap = emit_redacted_evidence_bundle(_evidence())
    overlap["evidence"]["builderops"]["compose_projects"] = ["pkm-prod"]
    receipt = evaluate_qualification(overlap)
    assert receipt["candidate_verdict"] == "fail"
    assert any("Product Compose project" in refusal for refusal in receipt["refusals"])


def test_evidence_bundle_redacts_credentials_and_secrets() -> None:
    evidence = _evidence()
    evidence["builderops"]["api_token"] = "super-secret-token-value"
    evidence["builderops"]["nested"] = {"password": "also-secret"}

    bundle = emit_redacted_evidence_bundle(evidence)
    serialized = str(bundle)
    assert "super-secret-token-value" not in serialized
    assert "also-secret" not in serialized
    assert bundle["evidence"]["builderops"]["api_token"] == "[REDACTED]"
    assert bundle["evidence"]["builderops"]["nested"]["password"] == "[REDACTED]"


def test_qualification_policy_has_no_gpu_or_test_tailnet_prerequisite() -> None:
    serialized = str(DEFAULT_POLICY).lower()
    assert "gpu" not in serialized
    assert "tailscale" not in serialized
    assert "test_tailnet" not in serialized


def test_complete_evidence_only_passes_candidate_policy_not_live_qualification() -> None:
    receipt = evaluate_qualification(emit_redacted_evidence_bundle(_evidence()))

    assert receipt["candidate_verdict"] == "pass"
    assert receipt["live_qualified"] is False
    assert receipt["live_qualification_reason"] == "requires a governed live operations receipt"


def test_secret_bearing_evidence_is_refused_even_if_fingerprint_is_recomputed() -> None:
    bundle = emit_redacted_evidence_bundle(_evidence())
    bundle["evidence"]["builderops"]["token"] = "unredacted-secret"
    receipt = evaluate_qualification(bundle)

    assert receipt["candidate_verdict"] == "fail"
    assert any("secret-bearing" in refusal for refusal in receipt["refusals"])
