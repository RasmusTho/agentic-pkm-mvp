from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.ops.product_tars_channel_topology import (
    ProductTarsChannelTopologyError,
    load_and_validate_product_tars_channel_topology,
    validate_product_tars_channel_topology,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/product_tars_channel_topology/valid.json"


def _fixture() -> dict[str, object]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["observed_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def test_contract_binds_all_channels_to_explicit_identity_evidence_and_gaps(tmp_path: Path) -> None:
    candidate = _fixture()
    fixture_copy = tmp_path / "valid-test-copy.json"
    fixture_copy.write_text(json.dumps(candidate), encoding="utf-8")
    validated = load_and_validate_product_tars_channel_topology(fixture_copy)

    assert validated["schema_version"] == "product_tars_channel_topology.v1"
    assert {entry["channel"] for entry in validated["channels"]} == {"dev", "test", "prod"}
    for entry in validated["channels"]:
        assert set(entry) == {
            "channel",
            "vm_identity",
            "engine_identity",
            "source_image_identity",
            "ingress_auth_class",
            "health_version",
            "data_backup_rollback_boundary",
            "gaps",
            "refusals",
        }
        assert entry["gaps"]
        assert entry["refusals"]


def test_contract_rejects_secret_local_and_cross_boundary_evidence() -> None:
    cases: list[dict[str, object]] = []

    secret = _fixture()
    secret["source_ref"] = "repo:sk-live"
    with pytest.raises(ProductTarsChannelTopologyError, match="secret-bearing"):
        validate_product_tars_channel_topology(secret)

    local = _fixture()
    local["channels"][0]["vm_identity"] = "tars-vm:mac-mini"
    cases.append(local)

    workstation = _fixture()
    workstation["channels"][0]["ingress_auth_class"] = "loopback"
    cases.append(workstation)

    missing_channel = _fixture()
    missing_channel["channels"] = missing_channel["channels"][:2]
    cases.append(missing_channel)

    unknown_field = _fixture()
    unknown_field["channels"][0]["evidence"] = "not-allowed"
    cases.append(unknown_field)

    for candidate in cases:
        with pytest.raises(ProductTarsChannelTopologyError):
            validate_product_tars_channel_topology(candidate)


def test_contract_rejects_builder_system_vm102_identity() -> None:
    for field in ("vm_identity", "engine_identity"):
        candidate = _fixture()
        candidate["channels"][0][field] = "tars-vm:102" if field == "vm_identity" else "docker-engine:builder-system"
        with pytest.raises(ProductTarsChannelTopologyError, match="Builder System"):
            validate_product_tars_channel_topology(candidate)


def test_contract_rejects_stale_or_future_observed_at() -> None:
    stale = _fixture()
    stale["observed_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ProductTarsChannelTopologyError, match="stale"):
        validate_product_tars_channel_topology(stale)

    future = _fixture()
    future["observed_at"] = "2999-01-01T00:00:00Z"
    with pytest.raises(ProductTarsChannelTopologyError, match="future"):
        validate_product_tars_channel_topology(future)

    bounded_skew = _fixture()
    bounded_skew["observed_at"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    assert validate_product_tars_channel_topology(bounded_skew)["observed_at"]


def test_contract_rejects_duplicate_channel_vm_identity() -> None:
    duplicate = _fixture()
    duplicate["channels"][1]["vm_identity"] = duplicate["channels"][0]["vm_identity"] = "tars-vm:shared"
    with pytest.raises(ProductTarsChannelTopologyError, match="distinct VM identities"):
        validate_product_tars_channel_topology(duplicate)

    unknowns = _fixture()
    unknowns["channels"][0]["vm_identity"] = unknowns["channels"][1]["vm_identity"] = "unknown"
    assert validate_product_tars_channel_topology(unknowns)["channels"][0]["vm_identity"] == "unknown"


def test_contract_rejects_unresolved_evidence_without_gap_or_refusal() -> None:
    candidate = _fixture()
    candidate["channels"][0]["gaps"] = []
    candidate["channels"][0]["refusals"] = []

    with pytest.raises(ProductTarsChannelTopologyError, match="explicit gap or refusal"):
        validate_product_tars_channel_topology(candidate)

    qualified = _fixture()
    qualified["channels"][0]["data_backup_rollback_boundary"] = "qualified"
    with pytest.raises(ProductTarsChannelTopologyError, match="clean qualification reference"):
        validate_product_tars_channel_topology(qualified)


def test_qualified_topology_requires_clean_qualification_reference() -> None:
    candidate = _fixture()
    candidate["source_ref"] = "repo:complete"
    for entry in candidate["channels"]:
        entry["vm_identity"] = f"tars-vm:{entry['channel']}"
        entry["engine_identity"] = "docker-engine:qualified"
        entry["source_image_identity"] = "image:registry.example/app@sha256:" + "a" * 64
        entry["ingress_auth_class"] = "private-tailscale"
        entry["health_version"] = "version:qualified"
        entry["data_backup_rollback_boundary"] = "qualified"
        entry["gaps"] = []
        entry["refusals"] = []

    with pytest.raises(ProductTarsChannelTopologyError, match="clean qualification reference"):
        validate_product_tars_channel_topology(candidate)

    candidate["source_ref"] = "qualification:tars-2026-08-31"
    assert validate_product_tars_channel_topology(candidate)["source_ref"] == candidate["source_ref"]


def test_contract_rejects_provider_and_model_fields() -> None:
    for field in ("provider", "model", "provider_id", "model_id"):
        candidate = _fixture()
        candidate[field] = "named-provider"
        with pytest.raises(ProductTarsChannelTopologyError):
            validate_product_tars_channel_topology(candidate)


def test_topology_contract_is_provider_neutral() -> None:
    profile = (ROOT / "docs/deployment/profiles/TARS_PROXMOX.md").read_text(encoding="utf-8").lower()
    schema = (ROOT / "config/platform/product_tars_channel_topology.v1.schema.json").read_text(encoding="utf-8").lower()

    assert "provider/model selection is outside placement" in profile
    assert "no named provider, model, or codex-only architecture decision" in profile
    assert "provider:" not in profile
    assert "model:" not in profile
    assert '"provider"' not in schema
    assert '"model"' not in schema


def test_validator_does_not_perform_host_or_network_access() -> None:
    source = (ROOT / "app/ops/product_tars_channel_topology.py").read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "subprocess.run" not in source
    assert "ssh" not in source.lower()
    assert "proxmox" in source.lower()  # documentation of the intentionally absent integration
