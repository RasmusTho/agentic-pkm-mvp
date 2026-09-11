"""Read-only adapter for the authoritative VM-102 evidence receipts.

The receipt directory belongs to the BuilderOps deployment/operator boundary.
This module only rereads it; it does not validate by writing, cache a copy, or
replace the receipt contracts with a DevUI-owned schema.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
PROVIDER = "builderops_vm102_receipts"
AUTHORITY = "builderops_vm102_receipt_source"
DEFAULT_RECEIPT_DIR = Path("/opt/builderops/receipts")
RECEIPT_DIR_ENV = "DEVUI_VM102_RECEIPT_DIR"
MAX_AGE_ENV = "DEVUI_VM102_RECEIPT_MAX_AGE_SECONDS"
RUNTIME_PREREQUISITES_FILE = "devui-runtime-prerequisites.json"
TARGET_VM = {"vmid": 102, "name": "builder-system"}
SUBJECT_COMPONENT = "devui_projection"
REQUIRED_RECEIPT_TYPES = (
    "devui_vm102_runtime_qualification.v1",
    "devsystem_vm102_deploy.v1",
    "devsystem_vm102_health.v1",
)
_POSITIVE_VERDICTS = {
    "pass",
    "passed",
    "qualified",
    "deployed",
    "healthy",
    "success",
    "succeeded",
}
_SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")


class Vm102ReceiptError(ValueError):
    """Raised when the source cannot support a VM-102 evidence claim."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise Vm102ReceiptError(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Vm102ReceiptError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Vm102ReceiptError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_ref(receipt_type: str, digest: str) -> str:
    return f"receipt:{receipt_type}:{digest}"


def _has_previous_identity(receipt: Mapping[str, Any]) -> bool:
    for key, value in receipt.items():
        normalized = key.casefold().replace("-", "_")
        if normalized.startswith("previous_") or normalized in {
            "prior_identity",
            "previous_identity",
            "rollback_baseline",
        }:
            if value is not None:
                return True
    return False


def _component_id(receipt: Mapping[str, Any]) -> str:
    direct = receipt.get("component_id")
    if isinstance(direct, str) and direct.strip():
        return direct
    subject = receipt.get("subject")
    if isinstance(subject, Mapping):
        component = subject.get("component_id") or subject.get("component")
        if isinstance(component, str) and component.strip():
            return component
    subject_ref = receipt.get("subject_ref")
    if isinstance(subject_ref, Mapping):
        component = subject_ref.get("component_id") or subject_ref.get("source_id")
        if isinstance(component, str) and component.strip():
            return component
    return ""


def _source_sha(receipt: Mapping[str, Any]) -> str:
    candidate = receipt.get("candidate_identity")
    if isinstance(candidate, Mapping):
        source_sha = candidate.get("source_sha") or candidate.get("candidate_source_sha")
        if isinstance(source_sha, str) and source_sha.strip():
            return source_sha
    for key in ("source_sha", "candidate_source_sha", "candidate_sha"):
        value = receipt.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _verdict(receipt: Mapping[str, Any]) -> str:
    for key in ("verdict", "qualification_verdict", "deployment_verdict", "health_verdict", "status"):
        value = receipt.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _validate_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_type: str,
    now: datetime,
    max_age: timedelta,
) -> dict[str, Any]:
    if receipt.get("receipt_type") != expected_type:
        raise Vm102ReceiptError(f"receipt type is not {expected_type}")
    if receipt.get("receipt_version") != 1:
        raise Vm102ReceiptError(f"receipt {expected_type} has an unsupported version")
    if receipt.get("secret_material") != "absent":
        raise Vm102ReceiptError("receipt secret-material posture is not absent")
    if receipt.get("target_vm") != TARGET_VM:
        raise Vm102ReceiptError("receipt target does not match VM 102 builder-system")
    observed_at = _parse_timestamp(receipt.get("observed_at"), label=f"{expected_type}.observed_at")
    age = now - observed_at
    if age < timedelta(0) or age > max_age:
        raise Vm102ReceiptError(f"receipt {expected_type} is stale or future-dated")
    if _component_id(receipt) != SUBJECT_COMPONENT:
        raise Vm102ReceiptError(f"receipt {expected_type} is not linked to {SUBJECT_COMPONENT}")
    source_sha = _source_sha(receipt)
    if not _SOURCE_SHA.fullmatch(source_sha):
        raise Vm102ReceiptError(f"receipt {expected_type} has no candidate/source SHA")
    source_refs = receipt.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs or any(
        not isinstance(ref, str) or not ref.strip() for ref in source_refs
    ):
        raise Vm102ReceiptError(f"receipt {expected_type} has no source linkage")
    evidence_fingerprint = receipt.get("evidence_fingerprint")
    if not isinstance(evidence_fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", evidence_fingerprint
    ):
        raise Vm102ReceiptError(f"receipt {expected_type} has no evidence fingerprint")
    unsigned = {
        key: value for key, value in receipt.items() if key != "evidence_fingerprint"
    }
    if not hmac.compare_digest(evidence_fingerprint, _digest(unsigned)):
        raise Vm102ReceiptError(f"receipt {expected_type} evidence fingerprint is invalid")
    gaps = receipt.get("gaps")
    refusals = receipt.get("refusals")
    first_deployment_refusal = (
        expected_type == "devsystem_vm102_deploy.v1"
        and receipt.get("rollback_baseline_state") == "no_baseline"
        and gaps == []
        and refusals == ["no_compatible_baseline"]
        and not _has_previous_identity(receipt)
    )
    if (gaps != [] or refusals != []) and not first_deployment_refusal:
        raise Vm102ReceiptError(f"receipt {expected_type} contains blocking gaps or refusals")
    verdict = _verdict(receipt)
    if verdict not in _POSITIVE_VERDICTS:
        raise Vm102ReceiptError(f"receipt {expected_type} has no positive verdict")
    digest = _digest(receipt)
    candidate_identity = {"source_sha": source_sha}
    raw_identity = receipt.get("candidate_identity")
    if isinstance(raw_identity, Mapping):
        for field in ("devui_image_digest", "devui_config_fingerprint"):
            value = raw_identity.get(field)
            if isinstance(value, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", value):
                candidate_identity[field] = value
    return {
        "receipt_type": expected_type,
        "receipt_version": receipt.get("receipt_version"),
        "observed_at": observed_at.isoformat(),
        "source_sha": source_sha,
        "candidate_identity": candidate_identity,
        "component_id": SUBJECT_COMPONENT,
        "verdict": verdict,
        "source_ref": _source_ref(expected_type, digest),
        "source_refs": list(source_refs),
        "evidence_fingerprint": evidence_fingerprint,
    }


def _max_age() -> timedelta:
    raw = os.environ.get(MAX_AGE_ENV, "86400")
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise Vm102ReceiptError("receipt freshness bound is invalid") from exc
    if seconds <= 0:
        raise Vm102ReceiptError("receipt freshness bound must be positive")
    return timedelta(seconds=seconds)


def _receipt_dir(receipt_dir: Path | str | None) -> Path:
    if receipt_dir is not None:
        return Path(receipt_dir)
    configured = os.environ.get(RECEIPT_DIR_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_RECEIPT_DIR


def _load_latest_by_type(receipt_dir: Path) -> dict[str, Mapping[str, Any]]:
    if not receipt_dir.is_dir():
        raise Vm102ReceiptError("authoritative VM-102 receipt source is unavailable")
    found: dict[str, list[tuple[datetime, Mapping[str, Any]]]] = {kind: [] for kind in REQUIRED_RECEIPT_TYPES}
    try:
        paths = sorted(receipt_dir.glob("*.json"))
    except OSError as exc:
        raise Vm102ReceiptError("authoritative VM-102 receipt source is unavailable") from exc
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            LOGGER.warning("VM-102 receipt read failed for %s", path.name)
            raise Vm102ReceiptError("authoritative VM-102 receipt source is unavailable") from exc
        if not isinstance(payload, Mapping):
            raise Vm102ReceiptError("authoritative VM-102 receipt is malformed")
        receipt_type = payload.get("receipt_type")
        if receipt_type not in found:
            continue
        observed_at = _parse_timestamp(payload.get("observed_at"), label=f"{receipt_type}.observed_at")
        found[receipt_type].append((observed_at, payload))
    missing = [kind for kind, values in found.items() if not values]
    if missing:
        raise Vm102ReceiptError("required VM-102 receipt is missing")
    return {kind: max(values, key=lambda item: item[0])[1] for kind, values in found.items()}


def read_vm102_receipt_evidence(
    receipt_dir: Path | str | None = None,
    *,
    now: datetime | None = None,
    require_typed_runtime: bool = False,
) -> dict[str, Any]:
    """Read and bind the current VM-102 qualification/deploy/health chain."""

    captured = (now or _utc_now()).astimezone(timezone.utc)
    max_age = _max_age()
    receipts = _load_latest_by_type(_receipt_dir(receipt_dir))
    if require_typed_runtime:
        # Use the owner's retained producer prerequisites and the same raw receipts
        # that will be normalized below; never reread a second, unvalidated chain.
        from app.ops.devui_vm102_runtime_receipts import validate_receipt

        path = _receipt_dir(receipt_dir) / RUNTIME_PREREQUISITES_FILE
        if path.is_symlink() or not path.is_file():
            raise Vm102ReceiptError("typed runtime verification prerequisites are unavailable")
        prerequisites = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(prerequisites, Mapping):
            raise Vm102ReceiptError("typed runtime verification prerequisites are malformed")
        for receipt in receipts.values():
            validate_receipt(receipt, prerequisites, now=captured)
    normalized = {
        kind: _validate_receipt(
            receipts[kind], expected_type=kind, now=captured, max_age=max_age
        )
        for kind in REQUIRED_RECEIPT_TYPES
    }
    qualification_ref = normalized[REQUIRED_RECEIPT_TYPES[0]]["source_ref"]
    deploy_refs = normalized[REQUIRED_RECEIPT_TYPES[1]]["source_refs"]
    health_refs = normalized[REQUIRED_RECEIPT_TYPES[2]]["source_refs"]
    if qualification_ref not in deploy_refs:
        raise Vm102ReceiptError("deployment receipt is not linked to qualification receipt")
    if normalized[REQUIRED_RECEIPT_TYPES[1]]["source_ref"] not in health_refs:
        raise Vm102ReceiptError("health receipt is not linked to deployment receipt")
    source_shas = {item["source_sha"] for item in normalized.values()}
    if len(source_shas) != 1:
        raise Vm102ReceiptError("VM-102 receipt chain candidate/source SHA mismatch")
    observed = {item["observed_at"] for item in normalized.values()}
    return {
        "captured_at": captured.isoformat(),
        "target_vm": dict(TARGET_VM),
        "component_id": SUBJECT_COMPONENT,
        "candidate_source_sha": source_shas.pop(),
        "receipt_refs": [normalized[kind]["source_ref"] for kind in REQUIRED_RECEIPT_TYPES],
        "receipts": normalized,
        "chain": "qualification→deploy→health",
        "observed_at": sorted(observed)[-1],
    }


def read_vm102_receipt_provider(
    receipt_dir: Path | str | None = None,
    *,
    now: datetime | None = None,
    require_typed_runtime: bool = False,
) -> dict[str, Any]:
    """Return a composition contribution, refusing without diagnostic leakage."""

    try:
        evidence = read_vm102_receipt_evidence(
            receipt_dir, now=now, require_typed_runtime=require_typed_runtime
        )
    except Exception as exc:
        LOGGER.info("VM-102 DevUI evidence withdrawn: %s", exc.__class__.__name__)
        return {
            "provider": PROVIDER,
            "status": "refused",
            "authority": AUTHORITY,
            "captured_at": None,
            "snapshot": None,
            "completeness": None,
            "refusal": {
                "code": "evidence_unavailable",
                "message": "VM-102 deployment evidence is unavailable or invalid",
                "details": {"reason": "receipt-backed status withdrawn"},
            },
        }
    return {
        "provider": PROVIDER,
        "status": "available",
        "authority": AUTHORITY,
        "captured_at": evidence["captured_at"],
        "snapshot": {
            "target_vm": evidence["target_vm"],
            "component_id": evidence["component_id"],
            "candidate_source_sha": evidence["candidate_source_sha"],
            "receipt_refs": evidence["receipt_refs"],
            "chain": evidence["chain"],
        },
        "completeness": {
            "required_receipts": list(REQUIRED_RECEIPT_TYPES),
            "observed_at": evidence["observed_at"],
            "linkage": "linked",
        },
        "payload": evidence,
    }


__all__ = [
    "AUTHORITY",
    "DEFAULT_RECEIPT_DIR",
    "PROVIDER",
    "RECEIPT_DIR_ENV",
    "REQUIRED_RECEIPT_TYPES",
    "SUBJECT_COMPONENT",
    "TARGET_VM",
    "Vm102ReceiptError",
    "read_vm102_receipt_evidence",
    "read_vm102_receipt_provider",
]
