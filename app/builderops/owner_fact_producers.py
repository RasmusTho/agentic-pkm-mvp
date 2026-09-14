"""Finite FCA-05 source adapters and FCA-09 admission; no outcome persistence here.

The deployment owner supplies the typed receipt chain and immutable acceptance
profile in its existing prerequisites artifact. The API transaction owner alone
records outcomes. Missing source material never selects a local fallback.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.builderops.control_plane.models import canonical_repository
from app.builderops.devui_receipts import (
    AUTHORITY, RUNTIME_PREREQUISITES_FILE, _receipt_dir,
    _load_latest_by_type, read_vm102_receipt_evidence,
)

CONTRACT = "builder_owner_outcome.v1"
OUTCOME_PREFIX = "owner-outcome:"
REQUEST_FIELDS = frozenset({
    "fact_kind", "outcome", "repository", "subject_ref", "source_revision",
    "candidate_ref", "environment_ref", "readiness_receipt_ref", "acceptance_profile_ref",
    "criterion_refs", "owner_actor", "authorization_ref", "observed_at", "decided_at",
    "observation", "limitation_refs", "trial_receipt_ref", "expected_previous_receipt_id",
    "supersedes_receipt_id", "correction_reason", "retention_policy_ref",
})
BINDING_FIELDS = (
    "repository", "subject_ref", "source_revision", "candidate_ref", "environment_ref",
    "readiness_receipt_ref", "acceptance_profile_ref", "criterion_refs", "owner_actor",
    "authorization_ref", "limitation_refs", "retention_policy_ref",
)
PROFILE_FIELDS = frozenset({
    "id", "version", "repository", "subject_ref", "source_owner", "owner_actor",
    "authorization_ref", "criterion_refs", "limitation_refs", "retention_policy_ref",
})


class OwnerFactRefusal(ValueError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class OwnerOutcomeAdmission:
    request: dict[str, Any]
    request_sha256: str
    confirmed_at: str
    revalidate: Callable[[int], dict[str, Any]]


def _json_value(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise OwnerFactRefusal("invalid_owner_outcome")
    if value is None or type(value) is int:
        return
    if type(value) is str and len(value.encode()) <= 2048:
        return
    if isinstance(value, list) and len(value) <= 128:
        for item in value:
            _json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict) and len(value) <= 64 and all(type(k) is str for k in value):
        for item in value.values():
            _json_value(item, depth=depth + 1)
        return
    raise OwnerFactRefusal("invalid_owner_outcome")


def canonical_json(value: Any) -> str:
    _json_value(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def outcome_request_hash(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(CONTRACT.encode() + b"\0" + canonical_json(dict(request)).encode()).hexdigest()


def strict_json(raw: bytes | str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise OwnerFactRefusal("duplicate_owner_outcome_key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OwnerFactRefusal("invalid_owner_outcome") from exc


def _closed(value: Any, fields: set[str] | frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise OwnerFactRefusal("invalid_owner_outcome")
    _json_value(value)
    return value


def _text(value: Any) -> str:
    if type(value) is not str or not value.strip() or len(value.encode()) > 2048:
        raise OwnerFactRefusal("invalid_owner_outcome")
    return value


def _refs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 128:
        raise OwnerFactRefusal("invalid_owner_outcome")
    seen: set[str] = set()
    for ref in value:
        _closed(ref, {"id", "sha256"})
        identity = _text(ref["id"])
        sha = _text(ref["sha256"])
        if identity in seen or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise OwnerFactRefusal("invalid_owner_outcome")
        seen.add(identity)
    return value


def _time(value: Any) -> datetime:
    try:
        text = _text(value)
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", text):
            raise ValueError
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError
        return stamp.astimezone(timezone.utc)
    except ValueError as exc:
        raise OwnerFactRefusal("invalid_owner_outcome_time") from exc


def read_owner_profiles() -> list[dict[str, Any]]:
    """Read only the existing host-owned runtime prerequisite source."""
    try:
        path = _receipt_dir(None) / RUNTIME_PREREQUISITES_FILE
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError
        profiles = strict_json(path.read_bytes())["owner_acceptance_profiles"]
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 64:
            raise ValueError
        seen = set()
        for profile in profiles:
            _closed(profile, PROFILE_FIELDS)
            repo = canonical_repository(profile["repository"])
            if repo != profile["repository"] or profile["source_owner"] != AUTHORITY:
                raise ValueError
            for key in ("id", "version", "subject_ref"):
                _text(profile[key])
            if not profile["subject_ref"].startswith("github:" + repo + "#"):
                raise ValueError
            identity = (repo, profile["subject_ref"])
            if identity in seen:
                raise ValueError
            seen.add(identity)
            actor = _closed(profile["owner_actor"], {"actor_type", "id"})
            if actor["actor_type"] != "human":
                raise ValueError
            _text(actor["id"])
            authority = _closed(profile["authorization_ref"], {"ref", "version", "authority_epoch"})
            _text(authority["ref"])
            _text(authority["version"])
            if type(authority["authority_epoch"]) is not int or authority["authority_epoch"] <= 0:
                raise ValueError
            if not _refs(profile["criterion_refs"]):
                raise ValueError
            _refs(profile["limitation_refs"])
            policy = _closed(profile["retention_policy_ref"], {"ref", "version"})
            _text(policy["ref"])
            _text(policy["version"])
        return copy.deepcopy(profiles)
    except Exception as exc:
        raise OwnerFactRefusal("owner_source_unavailable", 503) from exc


def read_owner_binding(
    repository: str, subject_ref: str, *, authority_epoch: int,
    allow_withdrawn_readiness: bool = False,
) -> dict[str, Any]:
    """Produce readiness only from the deployment owner's current typed chain."""
    try:
        repo = canonical_repository(repository)
        profile = next(p for p in read_owner_profiles() if p["repository"] == repo and p["subject_ref"] == subject_ref)
        if profile["authorization_ref"]["authority_epoch"] != authority_epoch:
            raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
        readiness_status = "current"
        try:
            evidence = read_vm102_receipt_evidence(require_typed_runtime=True)
        except Exception:
            if not allow_withdrawn_readiness:
                raise
            # The existing source may retain an exact, formerly valid chain
            # after its freshness window expires. Revalidate those same bytes
            # at their source observation time; never invent missing history.
            retained = _load_latest_by_type(_receipt_dir(None))
            observed = _time(retained["devsystem_vm102_health.v1"]["observed_at"])
            if observed >= datetime.now(timezone.utc):
                raise ValueError
            evidence = read_vm102_receipt_evidence(require_typed_runtime=True, now=observed)
            readiness_status = "withdrawn"
        health = evidence["receipts"]["devsystem_vm102_health.v1"]
        candidate = health["candidate_identity"]
        if set(candidate) != {"source_sha", "devui_image_digest", "devui_config_fingerprint"}:
            raise ValueError
        binding = {
            "repository": repo, "subject_ref": subject_ref, "source_revision": evidence["candidate_source_sha"],
            "candidate_ref": candidate,
            "environment_ref": {**evidence["target_vm"], "component_id": evidence["component_id"]},
            "readiness_receipt_ref": {"id": health["source_ref"], "sha256": health["source_ref"].rsplit(":", 1)[-1], "source_owner": AUTHORITY},
            "acceptance_profile_ref": {"id": profile["id"], "version": profile["version"], "sha256": digest(profile), "source_owner": AUTHORITY},
            **{key: profile[key] for key in ("criterion_refs", "owner_actor", "authorization_ref", "limitation_refs", "retention_policy_ref")},
        }
        return {**copy.deepcopy(binding), "binding_hash": digest(binding), "readiness_status": readiness_status, "observed_at": datetime.now(timezone.utc).isoformat(), "source_refs": evidence["receipt_refs"]}
    except OwnerFactRefusal:
        raise
    except Exception as exc:
        raise OwnerFactRefusal("owner_source_unavailable", 503) from exc


def validate_outcome_request(request: Any, *, confirmed_at: str) -> dict[str, Any]:
    value = _closed(request, REQUEST_FIELDS)
    if canonical_repository(value["repository"]) != value["repository"]:
        raise OwnerFactRefusal("invalid_owner_outcome")
    _text(value["subject_ref"])
    _text(value["source_revision"])
    for key, fields in (
        ("candidate_ref", {"source_sha", "devui_image_digest", "devui_config_fingerprint"}),
        ("environment_ref", {"vmid", "name", "component_id"}),
        ("readiness_receipt_ref", {"id", "sha256", "source_owner"}),
        ("acceptance_profile_ref", {"id", "version", "sha256", "source_owner"}),
        ("owner_actor", {"actor_type", "id"}),
        ("authorization_ref", {"ref", "version", "authority_epoch"}),
        ("retention_policy_ref", {"ref", "version"}),
    ):
        for field, item in _closed(value[key], fields).items():
            if field in {"vmid", "authority_epoch"}:
                if type(item) is not int or item <= 0:
                    raise OwnerFactRefusal("invalid_owner_outcome")
            else:
                _text(item)
    if value["trial_receipt_ref"] is not None:
        _text(value["trial_receipt_ref"])
    outcomes = {"owner_trial": {"tried", "unable_to_try"}, "owner_acceptance": {"accepted", "rejected"}}
    kind = value["fact_kind"]
    if type(kind) is not str or kind not in outcomes or type(value["outcome"]) is not str or value["outcome"] not in outcomes[kind]:
        raise OwnerFactRefusal("invalid_owner_outcome")
    trial = kind == "owner_trial"
    if value["decided_at" if trial else "observed_at"] is not None:
        raise OwnerFactRefusal("invalid_owner_outcome_time")
    if _time(value["observed_at" if trial else "decided_at"]) > _time(confirmed_at):
        raise OwnerFactRefusal("invalid_owner_outcome_time")
    criteria = _refs(value["criterion_refs"])
    if not criteria:
        raise OwnerFactRefusal("invalid_owner_outcome")
    limits = _refs(value["limitation_refs"])
    if trial:
        observation = value["observation"]
        if not isinstance(observation, list) or len(observation) > 128 or value["trial_receipt_ref"] is not None:
            raise OwnerFactRefusal("invalid_owner_outcome")
        seen = set()
        for item in observation:
            _closed(item, {"criterion_ref", "status"})
            ref = item["criterion_ref"]
            if ref not in criteria or type(item["status"]) is not str or item["status"] not in {"observed", "not_observed"} or ref["id"] in seen:
                raise OwnerFactRefusal("invalid_owner_outcome")
            seen.add(ref["id"])
        if value["outcome"] == "unable_to_try" and (not limits or any(o["status"] == "observed" for o in observation)):
            raise OwnerFactRefusal("invalid_owner_outcome")
    elif value["observation"] is not None:
        raise OwnerFactRefusal("invalid_owner_outcome")
    previous = value["expected_previous_receipt_id"]
    if previous is None:
        if value["supersedes_receipt_id"] is not None or value["correction_reason"] is not None:
            raise OwnerFactRefusal("invalid_owner_correction")
    elif _text(previous) != value["supersedes_receipt_id"] or value["correction_reason"] != "owner_correction":
        raise OwnerFactRefusal("invalid_owner_correction")
    return copy.deepcopy(value)


def validate_current_binding(request: dict[str, Any], binding: dict[str, Any]) -> None:
    for key in BINDING_FIELDS:
        if key == "criterion_refs":
            if any(ref not in binding[key] for ref in request[key]):
                raise OwnerFactRefusal("owner_binding_changed", 409)
            if request["outcome"] == "accepted" and {digest(ref) for ref in request[key]} != {digest(ref) for ref in binding[key]}:
                raise OwnerFactRefusal("incomplete_acceptance_scope", 409)
        elif request[key] != binding[key]:
            raise OwnerFactRefusal("owner_binding_changed", 409)


def outcome_record_id(repository: str, key: str) -> str:
    _text(key)
    return OUTCOME_PREFIX + digest({"repository": repository, "operation": CONTRACT, "key": key})


def receipt_hash(receipt: Mapping[str, Any]) -> str:
    return digest({key: value for key, value in receipt.items() if key != "hash"})
