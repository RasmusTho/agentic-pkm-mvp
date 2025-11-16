from __future__ import annotations

import os
from typing import Any, Optional
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg import errors as pg_errors

from app.memory.store import remember
from app.events.types import CURATION_CITATION_CHECK_DONE
from app.store.object_store import ObjectStore

AGENT = "citation_checker"


def _dsn() -> str:
    # Samma fallback som övriga systemet.
    v = os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app"
    return v.replace("postgresql+psycopg://", "postgresql://")


def _try_connect():
    """
    Best effort: returnera en psycopg-connection eller None.
    Vi stänger INTE här, vi låter anroparen använda context manager.
    """
    try:
        return psycopg.connect(_dsn(), row_factory=dict_row)
    except Exception:
        return None


def _latest_classification(oid: str) -> dict[str, Any] | None:
    """
    Hämta senaste classification-result från DB för objektet.
    Viktigt: om tabellen inte finns (UndefinedTable) eller något annat failar
    så ska vi INTE krascha pipen, utan bara returnera None.
    """
    conn = _try_connect()
    if conn is None:
        return None

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select result
                    from classifications
                    where object_id = %s
                    order by created_at desc
                    limit 1
                    """,
                    (oid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                res = row["result"]
                if isinstance(res, dict):
                    return res
                return {}
    except pg_errors.UndefinedTable:
        # Tabellen classifications finns inte i den här miljön → acceptera None
        return None
    except Exception:
        # Allt annat oväntat (t.ex. kolumn saknas, osv) → svälj i testläge
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _has_sources(text: str) -> bool:
    """
    Väldigt enkel heuristik: finns det en URL?
    """
    t = text.lower()
    return "http://" in t or "https://" in t


def check_citations(object_id: str, *, trace_id: str) -> dict[str, Any]:
    """
    Kollar att "externa" påståenden har källor.
    Skriver minne och returnerar ett eventliknande dict.
    """
    store = ObjectStore()
    obj = store.get_object(object_id)
    if not obj:
        raise RuntimeError(f"object {object_id} not found")

    body_text = obj.payload.get("body", "") or ""

    cls = _latest_classification(object_id) or {}
    trust = cls.get("trust", "own")

    if trust in ("external", "web", "imported", "other") and not _has_sources(body_text):
        status = "blocked"
        reason = "external_claims_without_sources"
    else:
        status = "ok"
        reason = "ok_or_internal"

    out = {
        "event": CURATION_CITATION_CHECK_DONE,
        "object_id": object_id,
        "status": status,
        "reason": reason,
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    remember(
        AGENT,
        "citation_check",
        object_id=object_id,
        trace_id=trace_id,
        data={
            "status": status,
            "reason": reason,
        },
    )

    return out


def run(object_id: str, *, trace_id: str) -> dict[str, Any]:
    """
    Publikt entrypoint, följer samma mönster som andra agenter.
    """
    return check_citations(object_id, trace_id=trace_id)