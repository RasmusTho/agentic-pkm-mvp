from __future__ import annotations
import os, re, json, uuid
from typing import Any
import psycopg
from psycopg.rows import dict_row
from app.agents.base.audit import audit_log

CITATION_RE = re.compile(r"(https?://\S+)|(\[[^\]]+\]\([^)]+\))|(\[\^\d+\])|(\bdoi:\S+)|(\barXiv:\S+)", re.I)
CLAIM_RE = re.compile(r"\b(\d{4}|\d+%|\baccording to\b|\benligt\b|\bestimate|\bestimat|\bclaim|\bpåstår)\b", re.I)

def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")

def _fetch_object(oid: str) -> dict[str, Any] | None:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, payload FROM objects WHERE id=%s", (oid,))
            return cur.fetchone()

def _latest_classification(oid: str) -> dict[str, Any] | None:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM decisions WHERE object_id=%s AND key='classification' ORDER BY created_at DESC LIMIT 1",
                (oid,),
            )
            row = cur.fetchone()
            return row["value"] if row else None

def _has_citations(text: str) -> bool:
    return bool(CITATION_RE.search(text))

def _has_claims(text: str) -> bool:
    return bool(CLAIM_RE.search(text))

def check_citations(object_id: str, *, trace_id: str) -> dict[str, Any]:
    row = _fetch_object(object_id)
    if not row:
        raise ValueError("object not found")
    payload = row["payload"] or {}
    text = payload.get("text") or payload.get("content") or ""

    has_claims = _has_claims(text)
    has_cites = _has_citations(text)
    missing = bool(has_claims and not has_cites)

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO decisions (id, object_id, key, value, created_at) VALUES (%s,%s,%s,%s::jsonb, now())",
                (str(uuid.uuid4()), object_id, "missing_citations", json.dumps({"value": missing})),
            )

    cls = _latest_classification(object_id) or {}
    trust = (cls.get("trust") or "provisional").lower()
    blocked = False
    reason = None
    if missing and trust in {"external", "conflict"}:
        blocked = True
        reason = "missing_citations_with_low_trust"
        with psycopg.connect(_dsn(), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO decisions (id, object_id, key, value, created_at) VALUES (%s,%s,%s,%s::jsonb, now())",
                    (str(uuid.uuid4()), object_id, "promotion_block", json.dumps({"reason": reason})),
                )

    audit_log(object_id=object_id, agent="citation_checker", action="check", trace_id=trace_id, details={"has_claims": has_claims, "has_citations": has_cites, "missing": missing, "trust": trust, "blocked": blocked})
    return {"object_id": object_id, "missing_citations": missing, "blocked": blocked, "reason": reason}

def run(object_id: str, *, trace_id: str) -> dict[str, Any]:
    return check_citations(object_id, trace_id=trace_id)
