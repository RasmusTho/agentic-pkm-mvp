"""Finite synthetic inputs at the managed Focus source-read boundary."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

SUBJECT = "github:example/fixture#501"
WIDTHS = (1366, 900)
NOW = datetime(2026, 8, 9, 13, 0, tzinfo=timezone.utc)
CASES = {
    "fresh-populated": {},
    "fresh-empty": {"cardinality": "measured_empty", "read_watermark": "fixture-scope:0"},
    "stale-empty": {"cardinality": "measured_empty", "read_watermark": "fixture-scope:0", "freshness": "stale"},
    "unknown-empty": {"cardinality": "measured_empty", "read_watermark": "fixture-scope:0", "freshness": "unknown"},
    "partial": {"coverage": "partial"},
    "unavailable": {"claim": None, "availability": "unavailable", "freshness": "unknown",
                    "coverage": "missing", "cardinality": "not_measured", "linkage": "not_assessed"},
    "unread": {"claim": None, "coverage": "unread", "cardinality": "not_measured", "linkage": "not_assessed"},
    "governing-unavailable": {},
}


def _source_ref(source_id: str) -> dict[str, str]:
    return {"source_type": "owner_document", "source_id": source_id, "content_hash": "b" * 64, "locator": source_id}


def _claim(claim_id: str, **overrides: Any) -> dict[str, Any]:
    return {"claim_id": claim_id, "claim": "Supported bounded evidence.",
        "source_ref": _source_ref("docs/example.md#" + claim_id), "availability": "available",
        "freshness": "fresh", "coverage": "complete", "cardinality": "nonempty", "linkage": "linked",
        "captured_at": "2026-08-09T12:59:00+00:00", "limitation": None, **overrides}


def expected(case_id: str) -> dict[str, Any]:
    return {"focus_state": "focus_blocked" if case_id == "governing-unavailable" else
            "focus_ready" if case_id in {"fresh-populated", "fresh-empty"} else "focus_partial",
            "warning": case_id not in {"fresh-populated", "fresh-empty"},
            "zero_result": case_id in {"fresh-empty", "stale-empty", "unknown-empty"},
            "action_authorized": False}


def inputs(case_id: str) -> dict[str, Any]:
    overrides = deepcopy(CASES[case_id])
    if "claim" not in overrides:
        overrides["claim"] = "No receipts exist in the measured subject scope." if expected(case_id)["zero_result"] else "Supported bounded evidence."
    evidence = _claim("fixture-evidence", **overrides)
    if evidence["claim"] is None:
        evidence["limitation"] = "This source cannot support an evidence claim."
    governing = _claim("governing")
    if case_id == "governing-unavailable":
        governing = _claim("governing", **CASES["unavailable"])
        governing["limitation"] = "This source cannot support an evidence claim."
    subject = {"kind": "issue", "stable_id": SUBJECT, "title": "Synthetic bounded evidence",
        "authority_ref": {"source_type": "github_issue", "source_id": "example/fixture#501",
        "version": "fixture:v1", "locator": "https://github.com/Example/Fixture/issues/501"}}
    return {"subject": subject,
        "owner_intent": {"summary": "Inspect the bounded synthetic evidence.", "source_ref": _source_ref("docs/example.md#intent")},
        "governing_sources": [governing], "evidence": [evidence], "receipts": [], "risks": [],
        "next_legal_step": {"workflow_ref": None, "actor_class": "agent", "legality": "unavailable",
            "reason": "No operation is authorized by this read-only evidence."},
        "execution_observations": [], "conversation_port": {"availability": "unsupported", "reason": "Read-only fixture."},
        "limitations": [], "now": lambda: NOW}
