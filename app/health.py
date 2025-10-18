from __future__ import annotations

from pathlib import Path
from typing import Dict

import duckdb
from sqlalchemy import text
from sqlalchemy.orm import Session

DUCKDB_PATH = Path("storage/agent.duckdb")
PROVENANCE_PATH = Path("provenance.jsonl")


def _check_database(db: Session) -> Dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # pragma: no cover - executed via caller tests
        return {"status": "error", "detail": str(exc)}


def _check_duckdb() -> Dict[str, str]:
    try:
        DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(DUCKDB_PATH), read_only=False) as con:
            con.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_provenance() -> Dict[str, str]:
    try:
        PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PROVENANCE_PATH.open("a", encoding="utf-8"):
            pass
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def health_summary(db: Session) -> Dict[str, Dict[str, str] | str]:
    checks = {
        "database": _check_database(db),
        "duckdb": _check_duckdb(),
        "provenance": _check_provenance(),
    }
    status = "ok" if all(c["status"] == "ok" for c in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
