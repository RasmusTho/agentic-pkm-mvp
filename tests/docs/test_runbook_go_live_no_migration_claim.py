"""Doc-truth guard for OBSSTAB-06 (#2603).

RUNBOOK_GO_LIVE.md historically claimed `/readyz` was "gated by migrations and
startup checks". The actual implementation (`app/api/routes/health_contract.py`)
returns 503 purely from `HealthContract.evaluate()` — a readiness-state check plus
a live Postgres ping (OBSSTAB-01) — with no migration gate. This test keeps the
runbook from re-introducing the false migration-gate claim.

See `docs/HEALTH.md :: False-green register`.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "RUNBOOK_GO_LIVE.md"


def test_no_false_migration_gate_claim() -> None:
    assert RUNBOOK.exists(), f"missing runbook: {RUNBOOK}"
    text = RUNBOOK.read_text(encoding="utf-8")

    # The exact historical false phrasing must be gone.
    assert "readiness probe gated by migrations" not in text, (
        "RUNBOOK_GO_LIVE.md still claims /readyz is migration-gated; /readyz is driven "
        "by HealthContract.evaluate() (readiness state + live DB ping), not migrations."
    )

    # Resilient to rewordings: do not tie /readyz to a migration gate anywhere.
    lowered = text.lower()
    assert not ("/readyz" in lowered and "gated by migration" in lowered), (
        "RUNBOOK_GO_LIVE.md still ties /readyz to a migration gate."
    )
