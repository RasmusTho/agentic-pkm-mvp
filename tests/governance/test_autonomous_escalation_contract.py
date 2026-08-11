"""Regression coverage for the autonomous owner-escalation boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE_CONTRACT = ROOT / "docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md"
PROCESS_MAP = ROOT / "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"
AGENTS = ROOT / "AGENTS.md"
OWNER_DECISION_PROFILE = ROOT / ".codex/skills/owner-decision-brief/SKILL.md"


def test_retry_exhaustion_alone_cannot_require_human_exception() -> None:
    contract = GATE_CONTRACT.read_text(encoding="utf-8")
    normalized = " ".join(contract.split())

    assert "## Escalation Classifier" in contract
    assert "A retry counter alone must never select" in contract
    assert "`needs_owner`" in contract
    for route in ("`auto_repair`", "`auto_backoff`", "`blocked_technical`"):
        assert route in contract
    assert "before capability escalation" in normalized
    assert "classifier-based repair triage" in normalized


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


def test_contract_dominates_source_drift_before_owner_escalation() -> None:
    profile = OWNER_DECISION_PROFILE.read_text(encoding="utf-8")
    normalized = " ".join(profile.split())

    assert "## Contract-dominance preflight" in profile
    assert "current governing Issue body" in profile
    assert "acceptance criteria and `Verify:` targets" in normalized
    assert "missing implementation on current `main`" in normalized
    assert "integration or rebase conflict" in normalized
    assert "technical evidence, not as proof that product value is undecided" in normalized
    assert "bounded integration or recovery" in normalized
    assert "leave a `blocked_technical` receipt" in normalized
    assert "do not convert it to an owner ask" in normalized


def test_platform_containment_recovery_scenario_forbids_manufactured_owner_choice() -> None:
    profile = OWNER_DECISION_PROFILE.read_text(encoding="utf-8")
    scenario = profile.split("Regression scenario:", maxsplit=1)[1]
    normalized = " ".join(scenario.split())

    assert "strict platform containment" in normalized
    assert "protected fail-closed invariant" in normalized
    assert "preserved recovery cannot rebase mechanically" in normalized
    assert "bounded port/recovery" in normalized
    assert "current-head verification" in normalized
    assert 'Offering the owner “restore the contract, retire it, or defer” is forbidden' in normalized
    assert "unless current authority explicitly reopened" in normalized


def test_repair_budget_policy_is_consistent_across_governing_surfaces() -> None:
    contract = GATE_CONTRACT.read_text(encoding="utf-8")
    dispatcher = (ROOT / "docs/AGENT_ISSUE_DISPATCHER.md").read_text(
        encoding="utf-8"
    )
    closure_skill = (ROOT / ".codex/skills/verification-and-closure/SKILL.md").read_text(
        encoding="utf-8"
    )

    for surface in (contract, dispatcher, closure_skill):
        normalized = " ".join(surface.split())
        assert "per stable failure mechanism and failure domain" in normalized
        assert "two standard repair attempts" in normalized
        assert "two strongest-capability repair attempts" in normalized
        assert "does not create a Human Exception" in normalized
