from __future__ import annotations

from pathlib import Path

from scripts.lint_skills_consistency import run_lint


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _section_between(text: str, start: str, end: str) -> str:
    return text.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]


def _canonical_branch_truth_branch_capture() -> str:
    text = _read(".codex/skills/_shared/BRANCH_TRUTH_GATE.md")
    procedure = _section_between(text, "## Procedure", "## Fallback")
    capture_block = procedure.split("```bash", maxsplit=1)[1].split("```", maxsplit=1)[0]
    lines = [line.strip() for line in capture_block.splitlines()]

    branch_capture = next(line for line in lines if line.startswith("EXPECTED_BRANCH="))
    return branch_capture


def test_canonical_agents_entrypoint_routes_to_repo_skill_index() -> None:
    text = _read("AGENTS.md")
    assert ".codex/skills/README.md" in text
    assert ".codex/skills/issue-to-code/SKILL.md" in text
    assert ".codex/skills/deliver-issue-set/SKILL.md" in text
    assert "In Progress" in text
    assert "remove `agent:ready`" in text
    assert "Transition-period bug-delivery policy" in text
    assert "Known Defects registry Issue #4172" in text


def test_shared_issue_contract_requires_duplicate_search_before_issue_creation() -> None:
    contract = _read(".codex/skills/_shared/ISSUE_CONTRACT.md")
    self_sufficiency = " ".join(
        _section_between(contract, "## Issue self-sufficiency rule", "## Child to parent reference").split()
    )

    assert "Before creating or normalizing a governance or contract Issue" in self_sufficiency
    assert "open Issues, recently merged PRs, and closed Issues" in self_sufficiency
    assert "do not require GraphQL or ProjectV2 operations" in self_sufficiency


def test_duplicate_search_rule_is_present_in_canonical_agent_instructions() -> None:
    agents = _read("AGENTS.md")
    delivery_governance = " ".join(
        _section_between(agents, "## GitHub delivery governance", "## Dispatcher policy").split()
    )

    assert "Before creating or normalizing a governance or contract Issue" in delivery_governance
    assert "open Issues, recently merged PRs, and closed Issues" in delivery_governance
    assert "Use GitHub CLI/REST search; do not require GraphQL or ProjectV2 operations" in delivery_governance


def test_shared_issue_contract_bounds_producer_and_caller_surfaces() -> None:
    contract = _read(".codex/skills/_shared/ISSUE_CONTRACT.md")
    bounded_surfaces = " ".join(
        _section_between(contract, "## Bounded producer and caller surfaces", "## Body template").split()
    )

    assert "enumerate the concrete production entrypoints" in bounded_surfaces
    assert "unprovable-in-PR" in bounded_surfaces
    assert "absolute quantifiers over an open caller set" in bounded_surfaces
    assert "Concrete rewrite:" in bounded_surfaces


def test_dormant_capability_proofs_stay_with_the_activation_slice() -> None:
    gate = _read("docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md")
    placement = " ".join(
        _section_between(gate, "### Dormant-capability proof placement", "### Stateful fallback boundary matrix").split()
    )
    implementation = _read(".codex/skills/issue-to-code/SKILL.md")

    assert "belongs to the bounded slice that activates that path" in placement
    assert "far-future activation proof" in placement
    assert "Bounded producer and caller surfaces" in implementation


def test_bug_delivery_transition_policy_is_linked_across_workflows() -> None:
    canonical = "AGENTS.md :: Transition-period bug-delivery policy"
    for path in (
        ".codex/skills/README.md",
        ".codex/skills/deliver-issue-set/SKILL.md",
        ".codex/skills/issue-to-code/SKILL.md",
        ".codex/skills/bug-to-issue/SKILL.md",
        ".codex/skills/resume-work/SKILL.md",
        "docs/development/DEV_WORKFLOW.md",
        "docs/development/AGENT_OPERATING_PROTOCOL.md",
    ):
        assert canonical in " ".join(_read(path).split())

    verification = _read(".codex/skills/verification-and-closure/SKILL.md")
    assert "rolling Known Defects\n  registry Issue #4172" in verification

    coordinator = _read(".codex/agents/issue-set-coordinator.toml")
    assert 'model = "gpt-5.6-luna"' in coordinator
    assert 'model_reasoning_effort = "low"' in coordinator
    assert canonical in coordinator


def test_compatibility_entrypoints_route_to_skill_index() -> None:
    codex_text = _read(".codex/AGENTS.md")
    claude_text = _read("CLAUDE.md")

    assert ".codex/skills/README.md" in codex_text
    assert ".codex/skills/issue-to-code/SKILL.md" in codex_text
    assert ".codex/skills/README.md" in claude_text
    assert ".codex/skills/issue-to-code/SKILL.md" in claude_text


def test_repo_skill_index_describes_connected_workflow_paths() -> None:
    text = _read(".codex/skills/README.md")
    for name in (
        "agentic-pkm",
        "issue-to-code",
        "deliver-issue-set",
        "publish-pr",
        "issue-maintenance-change-control",
        "pr-integration",
        "verification-and-closure",
    ):
        assert name in text
    assert "agentic-pkm -> issue-to-code -> publish-pr -> [pr-integration when repair/readiness is needed] -> verification-and-closure" in text


def _owner_decision_contract_preflight() -> str:
    return _section_between(
        _read(".codex/skills/owner-decision-brief/SKILL.md"),
        "## Contract-dominance preflight",
        "## Local vault-binding preflight",
    )


def test_owner_decision_preflight_selects_applicable_contract_without_manufacturing_issue_authority() -> None:
    preflight = " ".join(_owner_decision_contract_preflight().split())

    assert "live contract that actually governs the work" in preflight
    assert "governing Issue" in preflight
    assert "acceptance criteria" in preflight
    assert "`Verify:` targets" in preflight
    assert "Direct Repair" in preflight
    assert "workflow contract" in preflight
    assert "Do not manufacture an Issue or acceptance-criterion dependency" in preflight
    assert "protected invariant" in preflight
    assert "operator gate" in preflight


def test_owner_decision_preflight_allows_evidence_backed_owner_reserved_reopening() -> None:
    preflight = " ".join(_owner_decision_contract_preflight().split())

    assert "evidence-backed proposal to change the established contract" in preflight
    assert "owner-reserved value, mandate, or scope" in preflight
    assert "genuinely requires the owner to decide" in preflight
    assert "Do not require the owner to have already approved the change" in preflight


def test_owner_decision_preflight_keeps_technical_drift_blocked_without_missing_authority() -> None:
    preflight = " ".join(_owner_decision_contract_preflight().split())

    for technical_evidence in (
        "missing implementation",
        "integration or rebase conflict",
        "source drift",
        "failed recovery",
    ):
        assert technical_evidence in preflight
    assert "technical evidence" in preflight
    assert "no authority is missing" in preflight
    assert "`blocked_technical`" in preflight


def test_owner_decision_preflight_preserves_escalation_classifier_authority() -> None:
    preflight = " ".join(_owner_decision_contract_preflight().split())

    assert (
        "docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: "
        "Escalation Classifier"
    ) in preflight
    assert "Contradictory source authority remains `needs_owner`" in preflight
    assert "every other explicit `needs_owner` authority category in that classifier" in preflight
    assert "every other explicit category in that classifier" not in preflight
    assert "Every non-`needs_owner` route" in preflight
    assert "protected-finding, follow-up, or deferred disposition" in preflight
    assert "must not be reclassified here" in preflight


def test_owner_decision_profile_delegates_classification_and_preserves_operator_gates() -> None:
    profile = _read(".codex/skills/owner-decision-brief/SKILL.md")
    preflight = _owner_decision_contract_preflight()
    normalized = " ".join(preflight.split())
    classifier = _section_between(
        _read("docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md"),
        "## Escalation Classifier",
        "### Packet Schema",
    )

    assert "delegate terminal routing to the canonical classifier" in normalized
    assert "do not copy or redefine its route table here" in normalized.lower()
    assert "| `auto_repair` |" not in preflight
    assert "| `auto_backoff` |" not in preflight
    for route in ("auto_repair", "auto_backoff", "blocked_technical", "needs_owner"):
        assert f"| `{route}` |" in classifier
    assert "## Contractual operator gates" in profile
    assert "Never use the decision ownership gate to remove an unconditional operator gate" in profile
    assert "Contractual operator gates still fire exactly as their owning workflows define" in preflight


def test_builder_thread_contract_is_executable_and_discoverable() -> None:
    index = _read(".codex/skills/README.md")
    contract = _read(".codex/skills/_shared/BUILDER_THREAD_CONTRACT.md")
    thread_skill = _read(".codex/skills/builder-thread/SKILL.md")
    inbox_skill = _read(".codex/skills/builder-inbox/SKILL.md")

    assert "builder-thread" in index
    assert "builder-inbox" in index
    assert "serialized writer" in contract.lower()
    assert "shared_non_sensitive" in contract
    assert "named recipient" in contract.lower()
    assert "builder-thread" in thread_skill
    assert "builder-inbox" in inbox_skill
    assert "read-only" in inbox_skill.lower()


def test_builder_thread_hooks_are_non_authoritative() -> None:
    contract = " ".join(
        _read(".codex/skills/_shared/BUILDER_THREAD_CONTRACT.md").lower().split()
    )
    store_doc = _read("docs/builderops/BUILDEROPS_VAULT_STORE.md").lower()

    for authority in ("issue", "pr", "ci", "merge", "approval", "promotion", "receipt"):
        assert f"{authority} authority" in contract
    assert "devui" in contract
    assert "external builderops vault" in store_doc
    assert "repository `vault/` is a fixture" in store_doc


def test_skill_readme_resume_work_summary_matches_recovery_order() -> None:
    index = _read(".codex/skills/README.md")
    skill = _read(".codex/skills/resume-work/SKILL.md")

    summary = _section_between(index, "- `resume-work`", "- `issue-to-code`")
    recovery_contract = _section_between(
        skill,
        "## Orchestrated runs: resume the engine before rebuilding from git",
        "## Decide: continue or escalate",
    )

    assert "resumable orchestration journals/runs" in summary
    assert "git reconstruction as the fallback" in summary
    assert recovery_contract.index("Check for a resumable run") < recovery_contract.index(
        "Fall back to git"
    )


def test_yggdrasil_design_handoff_is_routed_and_fail_closed() -> None:
    agents = _read("AGENTS.md")
    index = _read(".codex/skills/README.md")
    skill = _read(".codex/skills/yggdrasil-design-handoff/SKILL.md")
    principles = _read("docs/DESIGN_PRINCIPLES.md")
    governance = _read("companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md")
    prompts = _read("companion-ui/prompts/claude-design/README.md")
    epic_runner = _read(
        "companion-ui/prompts/codex/deliver-epic-autonomous-runner.md"
    )
    template = _read(
        "companion-ui/prompts/claude-design/YGGDRASIL_HANDOFF_TEMPLATE.md"
    )

    skill_path = ".codex/skills/yggdrasil-design-handoff/SKILL.md"
    token_path = "companion-ui/companion-app/colors_and_type.css"
    design_system_name = "Yggdrasil Design System"
    principles_flat = " ".join(principles.split())

    assert skill_path in agents
    assert "yggdrasil-design-handoff" in index
    assert (
        "yggdrasil-design-handoff -> governed exploration/handoff"
        in index
    )
    assert "other surface: local owner doc/spec" in index

    for surface in (skill, principles, governance, prompts, template):
        assert design_system_name in surface
        assert token_path in surface

    for required_gate in (
        "mcp__claude-design__list_design_systems",
        "f2b13410-af14-4875-8029-445352123f57",
        "They must match byte for byte",
        "No successful gate means no design generation",
    ):
        assert required_gate in skill

    assert "failed or ambiguous gate blocks generation and Crossing B" in governance
    assert "This gate does not retroactively change" in governance
    assert "does not retroactively downgrade" in governance
    assert "Packages accepted before PR #4239 retain their recorded maturity" in _read(
        "companion-ui/design_handoff/README.md"
    )
    assert "Do not let Claude Design use its generic" in prompts
    assert "Visual resemblance alone is not compliance" in template
    assert ".codex/skills/yggdrasil-design-handoff/SKILL.md" in epic_runner
    assert "YGGDRASIL_HANDOFF_TEMPLATE.md" in epic_runner
    assert "For another Product or Builder surface" in epic_runner
    assert (
        "whether it belongs to a Product surface or a Builder surface"
        in principles_flat
    )
    assert (
        "it does not claim that every historical surface already conforms"
        in principles_flat
    )
    assert "For other Product or Builder surfaces" in skill


def test_agent_skills_are_consistent() -> None:
    errors = run_lint(REPO_ROOT)
    assert errors == [], "skills consistency lint reported errors:\n" + "\n".join(errors)

    agents = _read("AGENTS.md")
    skill_index = _read(".codex/skills/README.md")
    docs_index = _read("docs/DOCS_INDEX.md")
    skill_path = ".codex/skills/yggdrasil-design-handoff/SKILL.md"

    assert skill_path in agents
    assert "`yggdrasil-design-handoff`" in skill_index
    assert f"| {skill_path} |" in docs_index


def test_issue_to_code_preflight_captures_expected_branch_and_worktree() -> None:
    text = _read(".codex/skills/issue-to-code/SKILL.md")
    section = _section_between(
        text,
        "15a. **Branch-Truth Gate",
        "15b. **Branch-Truth Gate",
    )

    branch_capture = _canonical_branch_truth_branch_capture()
    worktree_capture = 'EXPECTED_WORKTREE="<absolute-worktree-path>"'
    preflight = "scripts/agent_workspace_preflight.sh"

    assert branch_capture in section
    assert worktree_capture in section
    assert 'EXPECTED_WORKTREE="$(git rev-parse --show-toplevel)"' not in section
    assert preflight in section
    assert section.index(branch_capture) < section.index(preflight)
    assert section.index(worktree_capture) < section.index(preflight)
    assert '--expected-branch "$EXPECTED_BRANCH"' in section
    assert '--expected-worktree "$EXPECTED_WORKTREE"' in section
    assert "|| exit 1" in section
    assert "Do not continue with empty expected values" in section


def test_subagent_role_governance_is_discoverable() -> None:
    agents_text = _read("AGENTS.md")
    claude_text = _read("CLAUDE.md")
    role_doc = "docs/development/BUILDER_SUBAGENT_ROLES.md"

    assert role_doc in agents_text
    assert role_doc in claude_text
    assert ".codex/agents" in agents_text
    assert "skills remain" in agents_text.lower()


def test_independent_fast_lane_has_no_routine_worker_coordination() -> None:
    skill = _read(".codex/skills/deliver-issue-set/SKILL.md")
    runner = _read("companion-ui/prompts/codex/deliver-epic-autonomous-runner.md")
    for surface in (skill, runner):
        assert "Routine worker-to-worker coordination is prohibited" in surface or "Workers do not message one another routinely" in surface
        assert "typed coordinator exception" in surface
        assert "two workers" in surface


def test_model_inquiry_local_host_route_is_identity_gated_and_fail_closed() -> None:
    skill = _read(".codex/skills/start-model-inquiry/SKILL.md")
    normalized_skill = " ".join(skill.split())

    assert skill.index("## Route Selection") < skill.index("## Single-Flight Launch")
    for identity_contract in (
        "/usr/bin/ssh -G Tailscale_macmini",
        "/usr/bin/id -un",
        "NFSHomeDirectory",
        "require the current `$HOME` to equal it byte-for-byte",
        "`$HOME/.ssh/known_hosts` and `$HOME/.ssh/known_hosts2`",
        "`/usr/bin/ssh-keygen -F`",
        "`/etc/ssh/ssh_host_*_key.pub`",
        "Never read a private host-key file",
        "Use the **proven-local route** only when alias expansion, principal binding, home binding, and the pinned host-key proof all succeed.",
        "Never infer that the caller is local because",
        "Once selected, do not switch routes during the invocation.",
    ):
        assert identity_contract in normalized_skill

    launcher_invocations = [
        line.strip()
        for line in skill.splitlines()
        if "yggdrasil-model-inquiry" in line and "--question-file" in line
    ]
    assert launcher_invocations == [
        "ssh -T Tailscale_macmini '$HOME/.local/bin/yggdrasil-model-inquiry --question-file /tmp/model-inquiry-question.md'",
        '"$HOME/.local/bin/yggdrasil-model-inquiry" --question-file /tmp/model-inquiry-question.md',
    ]

    lock_invocations = [
        line.strip()
        for line in skill.splitlines()
        if "mkdir /tmp/yggdrasil-model-inquiry.lock" in line
    ]
    assert lock_invocations == [
        "ssh -T Tailscale_macmini 'mkdir /tmp/yggdrasil-model-inquiry.lock'",
        "/bin/mkdir /tmp/yggdrasil-model-inquiry.lock",
    ]

    local_release = _section_between(
        skill,
        "Fixed proven-local release procedure:",
        "The configured inquiry host owns",
    )
    assert "*** Delete File: /tmp/model-inquiry-question.md" in local_release
    assert "/bin/rmdir /tmp/yggdrasil-model-inquiry.lock" in local_release
    assert "rm -f" not in local_release

    for local_contract in (
        '/usr/bin/install -m 0600 "$QUESTION_FILE" /tmp/model-inquiry-question.md',
        "*** Delete File: <absolute QUESTION_FILE>",
        "Do not use `rm`, `unlink`, a glob, or a shell cleanup wrapper for this local temporary file.",
        "sanctioned host-local subscription launcher",
        "non-empty stdout whose entire contents parse as exactly one JSON object",
        "with non-empty string values for `inquiry_id`, `final_state`, `terminal_receipt_id`, and",
        "Any nonzero status",
        "does not satisfy the withdrawn `model_access_substrate.provider_enabled_noninteractive_inquiry.v1`",
        "| Failure after lock acquisition but before step 5 starts | Run the fixed remote release command below; report the original failure and any cleanup failure. | Run the fixed proven-local release procedure below; report the original failure and any cleanup failure. |",
        "| Valid exit-zero terminal response | Preserve the response, then run the fixed remote release command. | Preserve the response, then run the fixed proven-local release procedure. |",
        "| Ambiguous launcher outcome after step 5 starts | Preserve the remote staging file and lock. | Preserve the local staging file and lock. |",
        "a cleanup failure must not replace or reclassify the captured launcher outcome.",
        "The proven-local route may invoke only the fixed sanctioned host-local subscription launcher.",
        "Do not invoke `$HOME/.local/bin/yggdrasil-model-inquiry-provider-api`",
    ):
        assert local_contract in normalized_skill

    for forbidden_bypass in (
        "BUILDEROPS_VAULT_ROOT",
        "BUILDEROPS_INQUIRY_ROLE_INTENT_JSON",
        "scripts/start_model_inquiry.sh",
        "/etc/ssh/ssh_host_ed25519_key",
        "/etc/ssh/ssh_host_rsa_key",
        "tailscale status --json",
        "/bin/rm -f /tmp/model-inquiry-question.md",
    ):
        assert forbidden_bypass not in skill


def test_model_inquiry_subscription_route_is_distinct_from_provider_api_mechanism() -> None:
    codex_skill = _read(".codex/skills/start-model-inquiry/SKILL.md")
    claude_skill = _read("claude-skills/start-model-inquiry/SKILL.md")
    installer = _read("scripts/install_model_inquiry_host.py")

    for skill in (codex_skill, claude_skill):
        assert "sanctioned host-local subscription launcher" in skill
        assert "$HOME/.local/bin/yggdrasil-model-inquiry --question-file" in skill
        assert (
            "Do not invoke `$HOME/.local/bin/yggdrasil-model-inquiry-provider-api`"
            in skill
        )
        assert "treat every nonzero" in skill.lower()

    assert 'FIXED_LAUNCHER_NAME = "yggdrasil-model-inquiry-provider-api"' in installer
    assert 'FIXED_LAUNCHER_NAME = "yggdrasil-model-inquiry"' not in installer

    withdrawn_gate = "model_access_substrate.provider_enabled_noninteractive_inquiry.v1"
    for doc_path in (
        "docs/CKM_DESIGN_AGENT_INTEGRATION/README.md",
        "docs/CKM_DESIGN_AGENT_INTEGRATION/PARENT_FEATURE_ISSUE.md",
        "docs/CKM_DESIGN_AGENT_INTEGRATION/REGISTER_DESIGN_AGENT_ADAPTERS.md",
    ):
        assert withdrawn_gate not in _read(doc_path)
