"""Production-near tests for the read-only VM-102 DevUI receipt adapter."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.builderops.devui_receipts import (
    REQUIRED_RECEIPT_TYPES,
    Vm102ReceiptError,
    read_vm102_receipt_evidence,
    read_vm102_receipt_provider,
)


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
SOURCE_SHA = "8914d51a6551e8ebfe132c3bf1bc22a8938d7872"


def _receipt(
    receipt_type: str,
    *,
    observed_at: str = "2026-09-10T11:00:00Z",
    source_refs: list[str] | None = None,
) -> dict:
    payload = {
        "receipt_type": receipt_type,
        "receipt_version": 1,
        "target_vm": {"vmid": 102, "name": "builder-system"},
        "component_id": "devui_projection",
        "candidate_identity": {"source_sha": SOURCE_SHA},
        "source_refs": source_refs
        or ["receipt:devsystem_vm102_component_inventory.v1:" + "a" * 64],
        "observed_at": observed_at,
        "secret_material": "absent",
        "gaps": [],
        "refusals": [],
        "verdict": "pass",
    }
    unsigned = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    payload["evidence_fingerprint"] = hashlib.sha256(
        unsigned.encode("utf-8")
    ).hexdigest()
    return payload


def _write_chain(root: Path, *, observed_at: str = "2026-09-10T11:00:00Z") -> None:
    root.mkdir(parents=True, exist_ok=True)
    inventory_ref = "receipt:devsystem_vm102_component_inventory.v1:" + "a" * 64

    def source_ref(payload: dict) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return f"receipt:{payload['receipt_type']}:{hashlib.sha256(encoded.encode()).hexdigest()}"

    qualification = _receipt(REQUIRED_RECEIPT_TYPES[0], observed_at=observed_at, source_refs=[inventory_ref])
    qualification_ref = source_ref(qualification)
    deploy = _receipt(
        REQUIRED_RECEIPT_TYPES[1],
        observed_at=observed_at,
        source_refs=[inventory_ref, qualification_ref],
    )
    deploy_ref = source_ref(deploy)
    health = _receipt(
        REQUIRED_RECEIPT_TYPES[2],
        observed_at=observed_at,
        source_refs=[inventory_ref, deploy_ref],
    )
    for index, payload in enumerate((qualification, deploy, health)):
        (root / f"{index}-{payload['receipt_type']}.json").write_text(
            json.dumps(payload) + "\n", encoding="utf-8"
        )


def test_reads_valid_vm102_qualification_deploy_health_chain(tmp_path: Path) -> None:
    _write_chain(tmp_path)

    evidence = read_vm102_receipt_evidence(tmp_path, now=NOW)

    assert evidence["target_vm"] == {"vmid": 102, "name": "builder-system"}
    assert evidence["component_id"] == "devui_projection"
    assert evidence["candidate_source_sha"] == SOURCE_SHA
    assert evidence["chain"] == "qualification→deploy→health"
    assert len(evidence["receipt_refs"]) == 3


def test_withdraws_target_or_candidate_mismatch(tmp_path: Path) -> None:
    _write_chain(tmp_path)
    deploy_path = tmp_path / f"1-{REQUIRED_RECEIPT_TYPES[1]}.json"
    deploy = json.loads(deploy_path.read_text(encoding="utf-8"))
    deploy["target_vm"] = {"vmid": 101, "name": "wrong-host"}
    deploy_path.write_text(json.dumps(deploy), encoding="utf-8")
    assert read_vm102_receipt_provider(tmp_path, now=NOW)["status"] == "refused"

    deploy["target_vm"] = {"vmid": 102, "name": "builder-system"}
    deploy["candidate_identity"]["source_sha"] = "0" * 40
    deploy_path.write_text(json.dumps(deploy), encoding="utf-8")
    assert read_vm102_receipt_provider(tmp_path, now=NOW)["status"] == "refused"


def test_withdraws_missing_or_unavailable_receipt(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    for index, receipt_type in enumerate(REQUIRED_RECEIPT_TYPES[:2]):
        (tmp_path / f"{index}.json").write_text(
            json.dumps(_receipt(receipt_type)), encoding="utf-8"
        )
    assert read_vm102_receipt_provider(tmp_path, now=NOW)["status"] == "refused"
    assert read_vm102_receipt_provider(tmp_path / "missing", now=NOW)["status"] == "refused"


def test_withdraws_stale_receipt(tmp_path: Path) -> None:
    _write_chain(tmp_path, observed_at="2026-09-08T11:00:00Z")

    provider = read_vm102_receipt_provider(tmp_path, now=NOW)

    assert provider["status"] == "refused"
    assert provider["refusal"]["details"] == {"reason": "receipt-backed status withdrawn"}


def test_withdraws_unlinked_receipt(tmp_path: Path) -> None:
    _write_chain(tmp_path)
    path = tmp_path / f"0-{REQUIRED_RECEIPT_TYPES[0]}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_refs"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Vm102ReceiptError):
        read_vm102_receipt_evidence(tmp_path, now=NOW)


def test_withdraws_tampered_evidence_fingerprint(tmp_path: Path) -> None:
    _write_chain(tmp_path)
    path = tmp_path / f"2-{REQUIRED_RECEIPT_TYPES[2]}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["verdict"] = "healthy"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_vm102_receipt_provider(tmp_path, now=NOW)["status"] == "refused"


def test_withdraws_missing_or_blocking_gaps_or_refusals(tmp_path: Path) -> None:
    _write_chain(tmp_path)
    path = tmp_path / f"2-{REQUIRED_RECEIPT_TYPES[2]}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    payload.pop("gaps")
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_vm102_receipt_provider(tmp_path, now=NOW)["status"] == "refused"

    payload["gaps"] = []
    payload["refusals"] = ["deployment_not_proven"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_vm102_receipt_provider(tmp_path, now=NOW)["status"] == "refused"


def test_accepts_first_deployment_no_baseline_refusal(tmp_path: Path) -> None:
    _write_chain(tmp_path)
    deploy_path = tmp_path / f"1-{REQUIRED_RECEIPT_TYPES[1]}.json"
    deploy = json.loads(deploy_path.read_text(encoding="utf-8"))
    deploy["rollback_baseline_state"] = "no_baseline"
    deploy["refusals"] = ["no_compatible_baseline"]
    unsigned = {key: value for key, value in deploy.items() if key != "evidence_fingerprint"}
    deploy["evidence_fingerprint"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    deploy_path.write_text(json.dumps(deploy), encoding="utf-8")

    health_path = tmp_path / f"2-{REQUIRED_RECEIPT_TYPES[2]}.json"
    health = json.loads(health_path.read_text(encoding="utf-8"))
    deploy_digest = hashlib.sha256(
        json.dumps(deploy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    health["source_refs"][-1] = f"receipt:{deploy['receipt_type']}:{deploy_digest}"
    unsigned = {key: value for key, value in health.items() if key != "evidence_fingerprint"}
    health["evidence_fingerprint"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    health_path.write_text(json.dumps(health), encoding="utf-8")

    assert read_vm102_receipt_provider(tmp_path, now=NOW)["status"] == "available"


def test_withdraws_first_deployment_with_previous_identity(tmp_path: Path) -> None:
    _write_chain(tmp_path)
    deploy_path = tmp_path / f"1-{REQUIRED_RECEIPT_TYPES[1]}.json"
    deploy = json.loads(deploy_path.read_text(encoding="utf-8"))
    deploy["rollback_baseline_state"] = "no_baseline"
    deploy["refusals"] = ["no_compatible_baseline"]
    deploy["previous_source_sha"] = SOURCE_SHA
    unsigned = {key: value for key, value in deploy.items() if key != "evidence_fingerprint"}
    deploy["evidence_fingerprint"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    deploy_path.write_text(json.dumps(deploy), encoding="utf-8")

    assert read_vm102_receipt_provider(tmp_path, now=NOW)["status"] == "refused"
