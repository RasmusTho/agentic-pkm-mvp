from __future__ import annotations

from pathlib import Path
import sqlite3

from app.dispatcher.store import SqliteStore
from app.dispatcher.verification_dispatch import VerificationDispatchLedger
from scripts.build_verification_dispatch_request import build_request


HEAD = "a" * 40
REPO = "RasmusTho/agentic-pkm-mvp"


def downgrade_verification_schema_to_v3(conn: sqlite3.Connection) -> None:
    """Turn a current test database into the exact pre-repair-budget v3 shape."""
    conn.execute("ALTER TABLE verification_attempts DROP COLUMN finding_id")
    conn.execute("ALTER TABLE verification_attempts DROP COLUMN failure_domain")
    conn.execute("ALTER TABLE verification_attempts DROP COLUMN mechanism_id")
    conn.execute("ALTER TABLE verification_runs DROP COLUMN repair_budget_policy")
    conn.execute("UPDATE dispatcher_meta SET value='3' WHERE key='schema_version'")


def request(head: str = HEAD) -> dict[str, object]:
    result = build_request(
        event={
            "repository": {"full_name": REPO},
            "artifact_workflow_run": {"id": 123, "repository_id": 456},
            "workflow_run": {
                "id": 99,
                "run_attempt": 1,
                "name": "CI",
                "event": "pull_request",
                "conclusion": "success",
                "head_sha": head,
                "updated_at": "2026-07-13T12:00:00Z",
            },
        },
        pr={
            "number": 3603,
            "state": "open",
            "body": "Governing-Issue: #3603\n\nRefs #3603",
            "base": {"ref": "main"},
            "head": {"ref": "codex/issue-3603", "sha": head},
        },
        issue={"number": 3603},
    )
    assert result is not None
    return result


def pre_trust_request(head: str = HEAD) -> dict[str, object]:
    """Return the exact producer shape deployed before artifact authority."""
    result = request(head)
    result.pop("supporting_issues")
    result.pop("artifact_provenance")
    result["base_ref"] = "main"
    result["head_ref"] = "codex/issue-3603"
    return result


def ledger(tmp_path: Path) -> VerificationDispatchLedger:
    return VerificationDispatchLedger(SqliteStore(tmp_path / "dispatcher.sqlite3"))
