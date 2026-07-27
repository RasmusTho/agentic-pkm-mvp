"""Regression coverage for the autonomous owner-escalation boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE_CONTRACT = ROOT / "docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md"
PROCESS_MAP = ROOT / "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"
AGENTS = ROOT / "AGENTS.md"
CLOSURE_SKILL = ROOT / ".codex/skills/verification-and-closure/SKILL.md"


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


def test_review_severity_routing_blocks_only_p0_and_p1() -> None:
    contract = GATE_CONTRACT.read_text(encoding="utf-8")
    closure_skill = CLOSURE_SKILL.read_text(encoding="utf-8")

    for surface in (contract, closure_skill):
        normalized = " ".join(surface.split())
        normalized_lower = normalized.lower()
        assert "no valid `blocking p2`" in normalized_lower
        assert "only p0/p1 findings" in normalized_lower
        assert ".codex/skills/bug-to-issue/SKILL.md" in surface
        assert "leave the pr code unchanged" in normalized_lower
        assert (
            "reply on the original review finding/thread with the issue reference"
            in normalized_lower
        )
        assert "without another review round" in normalized_lower
        assert "P3" in surface and "informational" in normalized_lower


def test_protected_review_invariants_cannot_be_downgraded_to_p2() -> None:
    contract = " ".join(GATE_CONTRACT.read_text(encoding="utf-8").split())
    closure_skill = " ".join(CLOSURE_SKILL.read_text(encoding="utf-8").split())

    for surface in (contract, closure_skill):
        assert "must be P0 or P1" in surface
        for protected_fragment in (
            "data loss or corruption",
            "source, vault, or authority",
            "secrets, authentication, or authorization",
            "migration durability",
            "concurrency or multi-writer safety",
            "irreversible or external",
            "false-green CI",
            "failed governing acceptance criterion",
            "`Verify:`",
            "closure gate",
        ):
            assert protected_fragment in surface


def test_nonblocking_findings_do_not_consume_repair_or_convergence_budget() -> None:
    contract = " ".join(GATE_CONTRACT.read_text(encoding="utf-8").split())
    closure_skill = " ".join(CLOSURE_SKILL.read_text(encoding="utf-8").split())

    for surface in (contract, closure_skill):
        assert "P2/P3 findings" in surface
        assert "consume no" in surface
        assert "trigger mechanism convergence" in surface
        assert "low-convergence" in surface


def test_severity_routing_preserves_fail_closed_delivery_gates() -> None:
    contract = " ".join(GATE_CONTRACT.read_text(encoding="utf-8").split())
    closure_skill = " ".join(CLOSURE_SKILL.read_text(encoding="utf-8").split())

    assert "independent review" in contract
    assert "current-head-SHA CI" in contract
    assert "issue acceptance/`Verify:` evidence" in contract
    assert "verified-merge controls" in contract
    assert "closure gates" in contract

    assert "reviewer remains independent" in closure_skill
    assert "current-SHA CI remains mandatory" in closure_skill
    assert "issue acceptance/`Verify:`" in closure_skill
    assert "verified-merge" in closure_skill
    assert "closure gates remain fail-closed" in closure_skill
