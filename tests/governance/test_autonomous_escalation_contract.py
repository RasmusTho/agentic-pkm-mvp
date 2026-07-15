"""Regression coverage for the autonomous owner-escalation boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE_CONTRACT = ROOT / "docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md"
PROCESS_MAP = ROOT / "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"
AGENTS = ROOT / "AGENTS.md"
VERIFICATION_SKILL = ROOT / ".codex/skills/verification-and-closure/SKILL.md"
SUBAGENT_ROLES = ROOT / "docs/development/BUILDER_SUBAGENT_ROLES.md"
DISPATCHER_CONTRACT = ROOT / "docs/AGENT_ISSUE_DISPATCHER.md"


def test_attempt_count_alone_cannot_require_human_exception() -> None:
    contract = GATE_CONTRACT.read_text(encoding="utf-8")

    assert "## Escalation Classifier" in contract
    assert "A retry counter alone must never select" in contract
    assert "`needs_owner`" in contract
    for route in ("`auto_repair`", "`auto_backoff`", "`blocked_technical`"):
        assert route in contract
    assert "Repeatedly identical findings without new evidence" in contract


def test_host_preflight_failure_routes_to_disabled_technical_recovery() -> None:
    process_map = PROCESS_MAP.read_text(encoding="utf-8")

    assert "### Verification dispatch recovery" in process_map
    assert "disabled -> preflight -> observe-only -> pilot ->" in process_map
    assert "returns to `disabled` as `blocked_technical`" in process_map


def test_repeated_review_findings_route_to_triage_before_owner() -> None:
    process_map = PROCESS_MAP.read_text(encoding="utf-8")

    assert "Capability escalation + classifier triage" in process_map
    assert "Triage -->|technical pause| Block[\"blocked_technical\"]" in process_map
    assert "Triage -->|explicit authority category| Human[\"Human exception\"]" in process_map
    assert "Blocking -->|repeated| Exception[\"Human exception\"]" not in process_map


def test_no_legacy_route_sends_technical_stops_directly_to_owner() -> None:
    contract = GATE_CONTRACT.read_text(encoding="utf-8")
    process_map = PROCESS_MAP.read_text(encoding="utf-8")
    closure_skill = (ROOT / ".codex/skills/verification-and-closure/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "It routes to Human Exception unless" not in contract
    assert "Blocked --> HumanException" not in process_map
    assert "frontier_rescue --> needs_human" not in process_map
    assert 'Classify -->|unresolved| Human["Human exception/block"]' not in process_map
    assert 'Stop["Stop condition"] --> Packet["Human Exception packet"]' not in process_map
    assert "Escalation classifier" in closure_skill
    assert "surface the stall to the owner as a merge-gate decision" not in closure_skill
    assert "surface a merge-gate waiver only when" not in closure_skill
    assert "explicitly waived by the owner" not in closure_skill
    assert "findings-fixed / owner-waived" not in closure_skill
    assert "A technical outage never creates a" in closure_skill
    assert "policy waiver" not in contract
    assert "human waiver" not in contract
    assert "clean/fixed/waived" not in process_map
    assert "owner waiver" not in process_map


def test_agent_policy_reserves_owner_interruptions_for_authority() -> None:
    agents = AGENTS.read_text(encoding="utf-8")

    assert "A retry count, a failed local/CI/type check" in agents
    assert "only its explicit authority categories may create `agent:needs-human`" in agents


def test_review_repair_uses_evidence_based_convergence_without_numeric_budget() -> None:
    contract = GATE_CONTRACT.read_text(encoding="utf-8")
    closure_skill = VERIFICATION_SKILL.read_text(encoding="utf-8")
    roles = SUBAGENT_ROLES.read_text(encoding="utf-8")
    dispatcher = DISPATCHER_CONTRACT.read_text(encoding="utf-8")

    assert "evidence-based convergence" in contract
    assert "no global numeric repair-attempt budget" in closure_skill
    assert "measurable progress" in closure_skill
    assert "evidence-based convergence" in roles
    assert "no fixed repair-attempt cap" in dispatcher

    forbidden = (
        "Maximum attempt budget declared",
        "At most two repair attempts",
        "same failure mechanism survives two repair attempts",
        "Two substantive fix attempts",
        "2 standard fix attempts",
        "at most 2 additional capability-escalated fix attempts",
        "budget of 2 standard plus 2 escalated fix attempts",
        "two standard attempts followed by at most two",
        "2+2 repair budget",
        "cumulative 2+2 budget",
    )
    for fragment in forbidden:
        assert fragment not in contract
        assert fragment not in closure_skill
        assert fragment not in roles
        assert fragment not in dispatcher
