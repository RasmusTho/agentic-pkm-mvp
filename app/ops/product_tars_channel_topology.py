"""Pure validation for the Product Runtime TARS channel-topology input.

The input is a repository-side qualification contract, not a deployment receipt.
It carries explicit identity, evidence, gap, and refusal fields while refusing
local-workstation and Builder System VM-102 placement claims.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_VERSION = "product_tars_channel_topology.v1"
SCHEMA_PATH = Path("config/platform/product_tars_channel_topology.v1.schema.json")
CHANNELS = ("dev", "test", "prod")
_ROOT = Path(__file__).resolve().parents[2]
_SENSITIVE_KEY = re.compile(
    r"(?:password|token|credential|private[_-]?key|api[_-]?key|secret|authorization|dsn)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:bearer\s+|gh[pousr]_|sk-[A-Za-z0-9]|pve[ta]=|"
    r"[A-Za-z][A-Za-z0-9+.-]*://[^\s@]+@|"
    r"(?:password|passwd|pwd|secret|token|api[_-]?key)\s*=\s*(?!\[REDACTED\])\S+)",
    re.IGNORECASE,
)
_LOCAL_WORKSTATION = re.compile(
    r"(?:demerzel|mac[ -]?mini|colima|workspace-prod|localhost|127\.0\.0\.1|"
    r"\bloopback\b|docker-desktop|pkm-(?:dev|test|prod))",
    re.IGNORECASE,
)
_VM102 = re.compile(r"(?:vm[-_ ]?102|builder[-_ ]?system)", re.IGNORECASE)


class ProductTarsChannelTopologyError(ValueError):
    """Raised when a topology input is not safe to consume."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProductTarsChannelTopologyError("duplicate topology input key")
        result[key] = value
    return result


def _schema() -> Mapping[str, Any]:
    return json.loads((_ROOT / SCHEMA_PATH).read_text(encoding="utf-8"))


def _walk_forbidden(value: Any, *, key: str | None = None, path: str = "input") -> None:
    if key is not None and _SENSITIVE_KEY.search(key):
        raise ProductTarsChannelTopologyError("sensitive topology field is not allowed")
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            _walk_forbidden(child, key=str(child_key), path=f"{path}.{child_key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        if _SENSITIVE_VALUE.search(value):
            raise ProductTarsChannelTopologyError("secret-bearing topology evidence is not allowed")
        if _LOCAL_WORKSTATION.search(value):
            raise ProductTarsChannelTopologyError("local-workstation runtime proof is not allowed")


def _validate_schema(payload: Mapping[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_schema(), format_checker=FormatChecker()).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ProductTarsChannelTopologyError(errors[0].message)


def validate_product_tars_channel_topology(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a copy of one redaction-safe topology input.

    No host, network, Docker, Proxmox, or subprocess operation is performed.
    The returned value is suitable for a caller that needs a validated
    qualification input; it is never a claim that a channel is deployed.
    """

    if not isinstance(payload, Mapping):
        raise ProductTarsChannelTopologyError("topology input must be an object")
    candidate = dict(payload)
    _walk_forbidden(candidate)
    _validate_schema(candidate)
    channels = candidate["channels"]
    if {entry["channel"] for entry in channels} != set(CHANNELS):
        raise ProductTarsChannelTopologyError("topology input must cover dev, test, and prod exactly once")
    for entry in channels:
        if _VM102.search(entry["vm_identity"]):
            raise ProductTarsChannelTopologyError("Product Runtime cannot use Builder System VM 102")
        if _VM102.search(entry["engine_identity"]):
            raise ProductTarsChannelTopologyError("Product Runtime cannot use the Builder System engine")
        identity_evidence = (
            entry["vm_identity"],
            entry["engine_identity"],
            entry["source_image_identity"],
            entry["ingress_auth_class"],
            entry["health_version"],
        )
        unresolved = any(value == "unknown" for value in identity_evidence)
        gaps_or_refusals = entry["gaps"] or entry["refusals"]
        if unresolved and not gaps_or_refusals:
            raise ProductTarsChannelTopologyError(
                "unknown topology evidence requires an explicit gap or refusal"
            )
        if entry["data_backup_rollback_boundary"] == "explicit-gap" and not gaps_or_refusals:
            raise ProductTarsChannelTopologyError(
                "an explicit data/backup/rollback gap requires a gap or refusal"
            )
        if entry["data_backup_rollback_boundary"] == "qualified" and (
            not candidate["source_ref"].startswith("qualification:")
            or unresolved
            or gaps_or_refusals
        ):
            raise ProductTarsChannelTopologyError(
                "qualified data/backup/rollback evidence requires a clean qualification reference"
            )
    return candidate


def load_and_validate_product_tars_channel_topology(path: Path) -> dict[str, Any]:
    """Load JSON with duplicate-key rejection and validate it."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except ProductTarsChannelTopologyError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductTarsChannelTopologyError("invalid topology JSON") from exc
    return validate_product_tars_channel_topology(payload)
