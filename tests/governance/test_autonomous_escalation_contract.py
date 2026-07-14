"""Regression coverage for the autonomous owner-escalation boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE_CONTRACT = ROOT / "docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md"
PROCESS_MAP = ROOT / "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"
AGENTS = ROOT / "AGENTS.md"


def test_retry_exhaustion_alone_cannot_require_human_exception() -> None:
    contract = GATE_CONTRACT.read_text(encoding="utf-8")

    assert "## Escalation Classifier" in contract
    assert "A retry counter alone must never select" in contract
    assert "`needs_owner`" in contract
    for route in ("`auto_repair`", "`auto_backoff`", "`blocked_technical`"):
        assert route in contract


def test_host_preflight_failure_routes_to_disabled_technical_recovery() -> None:
    process_map = PROCESS_MAP.read_text(encoding="utf-8")

    assert "### Verification dispatch recovery" in process_map
    assert "disabled -> preflight -> observe-only -> pilot ->" in process_map
    assert "returns to `disabled` as `blocked_technical`" in process_map


def test_agent_policy_reserves_owner_interruptions_for_authority() -> None:
    agents = AGENTS.read_text(encoding="utf-8")

    assert "A retry count, a failed local/CI/type check" in agents
    assert "only its explicit authority categories may create `agent:needs-human`" in agents
