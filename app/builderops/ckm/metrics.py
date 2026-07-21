"""Snapshot-bound, non-authoritative CKM metric observations.

This is deliberately an outer adapter over :mod:`query_service`: it accepts an
already-returned complete query envelope and never opens the CKM source store.
Retained payloads live in a small, separately versioned SQLite receipt store;
they are derived BuilderOps evidence, never Product or policy authority.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from app.builderops.ckm.contracts import CkmContractError, ENVELOPE_SCHEMA_VERSION, ResultEnvelope, canonical_digest, canonical_json
from app.builderops.ckm.schema import CKM_SCHEMA_VERSION

METRIC_REGISTRY_VERSION = 1
RETENTION_POLICY_VERSION = "ckm-metric-sample-retention-v1"
RETENTION_DAYS = 365
_VOLATILE_FIELDS = frozenset({"generated_at"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _definition(metric_id: str, purpose: str, formula: str) -> dict[str, Any]:
    value = {
        "id": metric_id,
        "semantic_version": "1.0.0",
        "purpose": purpose,
        "intended_uses": ["single-operator descriptive CKM review"],
        "prohibited_uses": ["ranking", "gating", "prioritization", "agent_scoring", "prediction", "automation", "action"],
        "approval_owner": "BuilderOps governance / Capability Knowledge Model",
        "output_schema": {"value_state": ["measured", "missing", "unassessed", "unsupported"], "shape": "tagged_vector"},
        "eligible_population": {"resource_type": "capability", "cohort": "complete_snapshot", "denominator": "resources_by_lifecycle"},
        "formula": formula,
        "detector_bindings": {"query_service": "ckm-q1b-v1"},
        "configuration_bindings": {"registry_version": METRIC_REGISTRY_VERSION},
        "limitations": ["descriptive projection only", "not causal", "candidate material remains separate"],
        "not_for_gating": True,
        "goodhart_warnings": ["Do not optimize this proxy", "Not a machine decision input", "Never use as a sole human decision input"],
    }
    value["definition_digest"] = canonical_digest(value)
    return value


METRIC_REGISTRY = {
    item["id"]: item for item in (
        _definition("capability_population", "Describe confirmed and candidate CKM population composition.", "count resources by lifecycle"),
        _definition("provenance_coverage", "Describe presence of provenance records in the snapshot.", "resources with non-empty provenance / lifecycle cohort"),
        _definition("value_state_distribution", "Describe tagged field-state distribution without coercing absence to zero.", "count tagged states by lifecycle cohort"),
    )
}


def metric_definition(metric_id: str, semantic_version: str = "1.0.0") -> Mapping[str, Any]:
    definition = METRIC_REGISTRY.get(metric_id)
    if definition is None:
        raise CkmContractError("unknown_metric_definition", "unknown CKM metric definition", {"metric_id": metric_id})
    if semantic_version != definition["semantic_version"]:
        raise CkmContractError("unsupported_metric_version", "unsupported CKM metric version", {"metric_id": metric_id, "requested": semantic_version, "supported": [definition["semantic_version"]]})
    return definition


def _tagged_distribution(resources: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {state: 0 for state in ("measured", "missing", "unassessed", "unsupported")}
    for resource in resources:
        for value in resource["values"].values():
            counts[value["state"]] += 1
    return counts


def build_observation(result: ResultEnvelope, *, metric_id: str = "capability_population", generated_at: str | None = None) -> dict[str, Any]:
    """Build deterministic semantic observation content from one Q1 result."""
    if not isinstance(result, ResultEnvelope):
        raise CkmContractError("unsupported_metric_semantics", "metric requires a supported complete query result", {})
    definition = dict(metric_definition(metric_id))
    payload = result.to_dict()
    if payload["schema_version"] != ENVELOPE_SCHEMA_VERSION or payload["snapshot"]["ckm_schema_version"] != CKM_SCHEMA_VERSION:
        raise CkmContractError("unsupported_metric_schema", "metric cannot coerce an unknown query schema bundle", {})
    if payload["resource_type"] != "capability" or not payload["snapshot"]["completeness"]["complete"]:
        raise CkmContractError("unsupported_metric_semantics", "metric requires a complete capability snapshot", {})
    resources = payload["resources"]
    confirmed = [item for item in resources if not item["candidate"]]
    candidates = [item for item in resources if item["candidate"]]
    vector = {
        "confirmed_population": {"state": "measured", "value": len(confirmed)},
        "candidate_population": {"state": "measured", "value": len(candidates)},
        "provenance_coverage": {"state": "measured", "value": len([item for item in resources if item["provenance"]])},
    }
    observation = {
        "observation_schema_version": 1,
        "projection": {"status": "derived_projection", "authoritative": False},
        "metric_definition": definition,
        "snapshot": payload["snapshot"],
        "query": {"digest": payload["query_digest"], "resource_type": payload["resource_type"]},
        "bindings": {
            "schema": {"envelope": payload["schema_version"], "resource": payload["snapshot"]["resource_schema_version"], "ckm": payload["snapshot"]["ckm_schema_version"]},
            "taxonomy_digest": payload["snapshot"]["taxonomy_digest"],
            "formula_digest": canonical_digest(definition["formula"]),
            "detector_digest": canonical_digest(definition["detector_bindings"]),
            "configuration_digest": canonical_digest(definition["configuration_bindings"]),
            "watermark_digest": canonical_digest(payload["snapshot"]["watermarks"]),
            "provenance_digest": canonical_digest(payload["snapshot"]["provenance"]),
        },
        "vector": vector,
        "distributions": {"confirmed": _tagged_distribution(confirmed), "candidate": _tagged_distribution(candidates)},
        "composition": {"confirmed_public_ids": [item["public_id"] for item in confirmed], "candidate_public_ids": [item["public_id"] for item in candidates]},
        "citations": payload["snapshot"]["provenance"],
        "freshness": {"state_revision": payload["snapshot"]["state_revision"], "watermarks": payload["snapshot"]["watermarks"]},
        "confidence": {"state": "unassessed", "reason": "metric does not infer confidence from descriptive CKM data"},
        "limitations": definition["limitations"],
        "goodhart_warnings": definition["goodhart_warnings"],
        "aggregate": {"label": "human_advisory_only", "value": None, "sole_input_prohibited": True, "machine_authority_prohibited": True},
        "generated_at": generated_at or _utc_now(),
    }
    semantic = {key: value for key, value in observation.items() if key not in _VOLATILE_FIELDS}
    observation["semantic_digest"] = canonical_digest(semantic)
    observation["observation_id"] = f"ckm_observation_{observation['semantic_digest'][:24]}"
    return observation


@dataclass(frozen=True)
class RetainedSample:
    sample_id: str
    observation_id: str
    lifecycle: str
    source_available: bool


class MetricRetentionStore:
    """Explicit post-read persistence with non-content lifecycle markers."""
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS ckm_metric_sample_v1 (
                sample_id TEXT PRIMARY KEY, observation_id TEXT NOT NULL, observation_json TEXT NOT NULL,
                source_payload BLOB, source_digest TEXT NOT NULL, watermarks_json TEXT NOT NULL,
                finding_evaluations_json TEXT NOT NULL, policy_version TEXT NOT NULL, retained_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, lifecycle TEXT NOT NULL, lifecycle_marker_json TEXT NOT NULL,
                supersedes_sample_id TEXT, deleted_at TEXT)""")

    def retain(self, result: ResultEnvelope, *, metric_id: str = "capability_population", finding_evaluations: Mapping[str, Any] | None = None, retained_at: str | None = None, supersedes_sample_id: str | None = None) -> RetainedSample:
        """Persist only an already-returned result; this method never invokes Q1."""
        self.initialize()
        observation = build_observation(result, metric_id=metric_id, generated_at=retained_at)
        source = result.to_dict()
        source_bytes = canonical_json(source).encode("utf-8")
        retained = retained_at or _utc_now()
        expires = (datetime.fromisoformat(retained.replace("Z", "+00:00")) + timedelta(days=RETENTION_DAYS)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        sample_id = f"ckm_sample_{canonical_digest({'observation': observation['observation_id'], 'source': source['snapshot']['snapshot_digest'], 'retained_at': retained, 'supersedes': supersedes_sample_id})[:24]}"
        marker = {"event": "retained", "payload_removed": False, "policy_version": RETENTION_POLICY_VERSION}
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT OR IGNORE INTO ckm_metric_sample_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (sample_id, observation["observation_id"], canonical_json(observation), source_bytes, source["snapshot"]["snapshot_digest"], canonical_json(source["snapshot"]["watermarks"]), canonical_json(dict(finding_evaluations or {})), RETENTION_POLICY_VERSION, retained, expires, "retained", canonical_json(marker), supersedes_sample_id, None))
        return RetainedSample(sample_id, observation["observation_id"], "retained", True)

    def storage_usage(self) -> dict[str, int]:
        self.initialize()
        with sqlite3.connect(self.path) as conn:
            count, bytes_ = conn.execute("SELECT COUNT(*), COALESCE(SUM(COALESCE(length(source_payload), 0) + length(observation_json)), 0) FROM ckm_metric_sample_v1 WHERE lifecycle = 'retained'").fetchone()
        return {"count": int(count), "bytes": int(bytes_)}

    def preview_prune(self, *, now: str, earlier_than_365_days: bool = False) -> list[dict[str, Any]]:
        self.initialize()
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT sample_id, expires_at FROM ckm_metric_sample_v1 WHERE lifecycle = 'retained' ORDER BY sample_id").fetchall()
        if earlier_than_365_days:
            return [{"sample_id": row[0], "reason": "explicit_operator_prune_preview"} for row in rows]
        return [{"sample_id": row[0], "reason": "retention_expired"} for row in rows if row[1] <= now]

    def prune(self, sample_ids: list[str], *, reason: str, at: str, previewed_sample_ids: list[str] | None = None) -> None:
        self.initialize()
        previewed = set(previewed_sample_ids or [])
        with sqlite3.connect(self.path) as conn:
            for sample_id in sample_ids:
                row = conn.execute("SELECT expires_at FROM ckm_metric_sample_v1 WHERE sample_id = ? AND lifecycle = 'retained'", (sample_id,)).fetchone()
                if row is None:
                    raise CkmContractError("missing_retained_sample", "retained metric sample is unavailable for pruning", {"sample_id": sample_id})
                if row[0] > at and sample_id not in previewed:
                    raise CkmContractError("prune_preview_required", "early payload pruning requires an explicit operator preview", {"sample_id": sample_id})
                marker = {"event": reason, "payload_removed": True, "at": at}
                conn.execute("UPDATE ckm_metric_sample_v1 SET source_payload = NULL, lifecycle = ?, lifecycle_marker_json = ?, deleted_at = ? WHERE sample_id = ? AND lifecycle = 'retained'", (reason, canonical_json(marker), at, sample_id))

    def correct(self, sample_id: str, result: ResultEnvelope, *, finding_evaluations: Mapping[str, Any] | None = None, retained_at: str | None = None) -> RetainedSample:
        self.initialize()
        with sqlite3.connect(self.path) as conn:
            exists = conn.execute("SELECT 1 FROM ckm_metric_sample_v1 WHERE sample_id = ?", (sample_id,)).fetchone()
        if exists is None:
            raise CkmContractError("missing_retained_sample", "retained metric sample is unknown", {"sample_id": sample_id})
        replacement = self.retain(result, finding_evaluations=finding_evaluations, retained_at=retained_at, supersedes_sample_id=sample_id)
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE ckm_metric_sample_v1 SET lifecycle = 'superseded', lifecycle_marker_json = ? WHERE sample_id = ?", (canonical_json({"event": "superseded", "successor": replacement.sample_id, "payload_removed": False}), sample_id))
        return replacement

    def replay(self, sample_id: str) -> dict[str, Any]:
        self.initialize()
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT source_payload, lifecycle, lifecycle_marker_json FROM ckm_metric_sample_v1 WHERE sample_id = ?", (sample_id,)).fetchone()
        if row is None:
            raise CkmContractError("missing_retained_sample", "retained metric sample is unknown", {"sample_id": sample_id})
        if row[0] is None:
            raise CkmContractError("source_unavailable", "retained source payload is unavailable", {"sample_id": sample_id, "lifecycle": row[1], "marker": json.loads(row[2])})
        return json.loads(bytes(row[0]).decode("utf-8"))
