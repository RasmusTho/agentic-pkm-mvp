from __future__ import annotations

from pathlib import Path
from typing_extensions import TypedDict

import duckdb
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.repository import AgentRepository

DUCKDB_PATH = Path("storage/agent.duckdb")
PROVENANCE_PATH = Path("provenance.jsonl")


class CheckResult(TypedDict, total=False):
    status: str
    detail: str


class HealthSummary(TypedDict):
    status: str
    checks: dict[str, CheckResult]


def _check_database(db: Session) -> CheckResult:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # pragma: no cover - executed via caller tests
        return {"status": "error", "detail": str(exc)}


def _check_duckdb() -> CheckResult:
    try:
        DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(DUCKDB_PATH), read_only=False) as con:
            con.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_provenance() -> CheckResult:
    try:
        PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PROVENANCE_PATH.open("a", encoding="utf-8"):
            pass
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_agent(agent_repo: AgentRepository | None) -> CheckResult:
    if agent_repo is None:
        return {"status": "degraded", "detail": "agent repository unavailable"}
    heartbeat = agent_repo.get_last_heartbeat()
    if not heartbeat:
        return {"status": "degraded", "detail": "no heartbeat recorded"}
    detail = f"{heartbeat['status']} @ {heartbeat['last_seen']}"
    return {"status": "ok", "detail": detail}


def health_summary(db: Session, agent_repo: AgentRepository | None = None) -> HealthSummary:
    checks = {
        "database": _check_database(db),
        "duckdb": _check_duckdb(),
        "provenance": _check_provenance(),
    }
    checks["agent"] = _check_agent(agent_repo)
    status = "ok" if all(c["status"] == "ok" for c in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
