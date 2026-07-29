"""Governance tests for the skills consistency lint (issue #1810, parent #1805).

The lint is drift insurance for `.codex/skills/`: it must pass on the repaired
tree and detect each defect class found by the 2026-06-10 skills review when
seeded into a synthetic tree.
"""

from __future__ import annotations

from pathlib import Path

from scripts.lint_skills_consistency import run_lint

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_skill(skills_root: Path, name: str, body: str = "") -> None:
    skill_dir = skills_root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "Test skill {name}."\n---\n\n# {name}\n{body}',
        encoding="utf-8",
    )


def _write_readme(skills_root: Path, routed: list[str], extra: str = "") -> None:
    entries = "\n".join(f"- `{name}`\n  - test entry" for name in routed)
    (skills_root / "README.md").write_text(
        f"State: test index\n\n# Skills\n\n## Skill routing\n\n{entries}\n{extra}\n",
        encoding="utf-8",
    )


def _seed_tree(tmp_path: Path) -> Path:
    """A minimal clean tree: two skills, both routed, no defects."""
    skills_root = tmp_path / ".codex" / "skills"
    _write_skill(skills_root, "alpha-skill")
    _write_skill(skills_root, "beta-skill")
    _write_readme(skills_root, ["alpha-skill", "beta-skill"])
    return tmp_path


def test_skills_consistency_lint_passes() -> None:
    """The lint is green on the current repaired tree (post #1806/#1808)."""
    errors = run_lint(REPO_ROOT)
    assert errors == [], "skills consistency lint reported errors:\n" + "\n".join(errors)


def test_seeded_clean_tree_passes(tmp_path: Path) -> None:
    assert run_lint(_seed_tree(tmp_path)) == []


def test_lint_detects_seeded_defects(tmp_path: Path) -> None:
    root = _seed_tree(tmp_path)
    skills_root = root / ".codex" / "skills"

    # Defect class 1: skill directory missing from the README routing index.
    _write_skill(skills_root, "gamma-skill")

    # Defect class 2: reference to a skill that does not exist (the
    # git-hygiene-preflight pattern from the review).
    alpha = skills_root / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8")
        + "\nUse the `git-hygiene-preflight` skill before claiming.\n",
        encoding="utf-8",
    )

    # Defect class 3: label taxonomy block diverged from the canonical list.
    beta = skills_root / "beta-skill" / "SKILL.md"
    beta.write_text(
        beta.read_text(encoding="utf-8")
        + (
            "\nAllowed labels:\n\n"
            "- `type:task`\n- `type:bug`\n- `type:refactor`\n"
            "- `prio:high`\n- `prio:med`\n- `prio:low`\n"
            "- `agent:ready`\n- `agent:blocked`\n"  # agent:needs-human missing
        ),
        encoding="utf-8",
    )

    errors = run_lint(root)
    assert any("no entry for `gamma-skill`" in e for e in errors), errors
    assert any("`git-hygiene-preflight`" in e for e in errors), errors
    assert any("label taxonomy block diverges" in e for e in errors), errors


def test_lint_detects_frontmatter_defects(tmp_path: Path) -> None:
    root = _seed_tree(tmp_path)
    skills_root = root / ".codex" / "skills"

    # name: does not match the directory name.
    alpha = skills_root / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8").replace("name: alpha-skill", "name: wrong-name"),
        encoding="utf-8",
    )
    # description: empty.
    beta = skills_root / "beta-skill" / "SKILL.md"
    beta.write_text(
        beta.read_text(encoding="utf-8").replace(
            'description: "Test skill beta-skill."', "description:"
        ),
        encoding="utf-8",
    )

    errors = run_lint(root)
    assert any("does not match directory 'alpha-skill'" in e for e in errors), errors
    assert any("description is empty" in e for e in errors), errors


def test_multiline_frontmatter_description_fails(tmp_path: Path) -> None:
    root = _seed_tree(tmp_path)
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        "---\n"
        "name: alpha-skill\n"
        "description: |\n"
        "  First line is not the whole description.\n"
        "  Second line must not be accepted silently.\n"
        "---\n\n"
        "# alpha-skill\n",
        encoding="utf-8",
    )

    errors = run_lint(root)

    assert any("description must be a non-empty single line" in e for e in errors), errors


def test_frontmatter_description_keep_chomping_block_scalars_fail(tmp_path: Path) -> None:
    for scalar in ("|+", ">+"):
        case_dir = scalar.replace("+", "plus").replace("|", "pipe").replace(">", "folded")
        root = _seed_tree(tmp_path / case_dir)
        alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
        alpha.write_text(
            "---\n"
            "name: alpha-skill\n"
            f"description: {scalar}\n"
            "  First line is not the whole description.\n"
            "---\n\n"
            "# alpha-skill\n",
            encoding="utf-8",
        )

        errors = run_lint(root)

        assert any("description must be a non-empty single line" in e for e in errors), (
            scalar,
            errors,
        )


def test_valid_single_line_frontmatter_description_passes(tmp_path: Path) -> None:
    assert run_lint(_seed_tree(tmp_path)) == []


def test_missing_skills_readme_reports_lint_error(tmp_path: Path) -> None:
    root = _seed_tree(tmp_path)
    (root / ".codex" / "skills" / "README.md").unlink()

    errors = run_lint(root)

    assert errors == [".codex/skills/README.md: missing"]


def test_lint_detects_retired_phrase(tmp_path: Path) -> None:
    root = _seed_tree(tmp_path)
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8") + "\nDo not batch to end of task.\n",
        encoding="utf-8",
    )
    errors = run_lint(root)
    assert any("retired phrase" in e for e in errors), errors


def test_sbs_impact_fields_consistent_on_real_repo() -> None:
    """The four real SBS Impact copies must agree (issue #4188)."""
    errors = run_lint(REPO_ROOT)
    sbs_errors = [e for e in errors if "SBS Impact field list" in e]
    assert sbs_errors == [], sbs_errors


def test_required_sections_consistent_on_real_repo() -> None:
    """The JS `required` array and Python `REQUIRED_SECTIONS` tuple must agree (issue #4188)."""
    errors = run_lint(REPO_ROOT)
    section_errors = [e for e in errors if "required-sections lists diverge" in e]
    assert section_errors == [], section_errors


def test_sbs_impact_lint_fails_when_one_copy_edited_alone(tmp_path: Path) -> None:
    """Editing exactly one SBS Impact copy (dropping `Boundary risk`) must fail the lint.

    This is the regression this issue closes: agent-authored issues silently
    omitted `Boundary risk` because only one of the four copies drifted.
    """
    root = _seed_tree(tmp_path)

    issue_contract = REPO_ROOT / ".codex" / "skills" / "_shared" / "ISSUE_CONTRACT.md"
    task_yml = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "task.yml"
    pr_template = REPO_ROOT / ".github" / "pull_request_template.md"
    pr_body_generator = REPO_ROOT / "scripts" / "pr_body_generator.py"

    dest_shared = root / ".codex" / "skills" / "_shared"
    dest_shared.mkdir(parents=True, exist_ok=True)
    (dest_shared / "ISSUE_CONTRACT.md").write_text(
        issue_contract.read_text(encoding="utf-8"), encoding="utf-8"
    )
    dest_github_templates = root / ".github" / "ISSUE_TEMPLATE"
    dest_github_templates.mkdir(parents=True, exist_ok=True)
    (dest_github_templates / "task.yml").write_text(
        task_yml.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / ".github" / "pull_request_template.md").write_text(
        pr_template.read_text(encoding="utf-8"), encoding="utf-8"
    )
    dest_scripts = root / "scripts"
    dest_scripts.mkdir(parents=True, exist_ok=True)
    (dest_scripts / "pr_body_generator.py").write_text(
        pr_body_generator.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Sanity: the unmodified copies (seeded verbatim from the real repo) are consistent.
    baseline_errors = run_lint(root)
    assert not any("SBS Impact field list" in e for e in baseline_errors), baseline_errors

    # Now drift exactly one copy alone: drop `Boundary risk` from ISSUE_CONTRACT.md only.
    (dest_shared / "ISSUE_CONTRACT.md").write_text(
        issue_contract.read_text(encoding="utf-8").replace(
            "- Boundary risk: <the one thing that must not cross a boundary "
            "because of this change, or none>\n",
            "",
        ),
        encoding="utf-8",
    )
    errors = run_lint(root)
    assert any(
        "ISSUE_CONTRACT.md" in e and "SBS Impact field list" in e for e in errors
    ), errors


def test_required_sections_lint_fails_when_one_copy_edited_alone(tmp_path: Path) -> None:
    """Reordering the Python `REQUIRED_SECTIONS` tuple alone must fail the lint."""
    root = _seed_tree(tmp_path)

    workflow = REPO_ROOT / ".github" / "workflows" / "issue-pr-governance.yml"
    validate = REPO_ROOT / "scripts" / "validate_issue_readiness.py"

    dest_workflows = root / ".github" / "workflows"
    dest_workflows.mkdir(parents=True, exist_ok=True)
    (dest_workflows / "issue-pr-governance.yml").write_text(
        workflow.read_text(encoding="utf-8"), encoding="utf-8"
    )
    dest_scripts = root / "scripts"
    dest_scripts.mkdir(parents=True, exist_ok=True)

    # Baseline: verbatim copies agree.
    (dest_scripts / "validate_issue_readiness.py").write_text(
        validate.read_text(encoding="utf-8"), encoding="utf-8"
    )
    baseline_errors = run_lint(root)
    assert not any("required-sections lists diverge" in e for e in baseline_errors), (
        baseline_errors
    )

    # Drift the Python copy alone: swap two section names' order.
    drifted = validate.read_text(encoding="utf-8").replace(
        '    "Context",\n    "Scope",\n',
        '    "Scope",\n    "Context",\n',
    )
    assert drifted != validate.read_text(encoding="utf-8"), "fixture swap did not apply"
    (dest_scripts / "validate_issue_readiness.py").write_text(drifted, encoding="utf-8")

    errors = run_lint(root)
    assert any("required-sections lists diverge" in e for e in errors), errors


def test_pr_contract_validator_matches_workflow_on_real_repo() -> None:
    """The canonical Python twins must agree with the workflow's JS (issue #4272)."""
    errors = run_lint(REPO_ROOT)
    pr_contract_errors = [e for e in errors if "verification_contract.py" in e]
    assert pr_contract_errors == [], pr_contract_errors


def test_lint_fails_when_pr_contract_validator_diverges_from_workflow(tmp_path: Path) -> None:
    """Editing exactly one side of a pr-contract regex twin must fail the lint.

    Mirrors `test_required_sections_lint_fails_when_one_copy_edited_alone`:
    seed both real files verbatim (baseline passes), then drift only the
    Python side and confirm the lint catches it.
    """
    root = _seed_tree(tmp_path)

    workflow = REPO_ROOT / ".github" / "workflows" / "issue-pr-governance.yml"
    contract = REPO_ROOT / "app" / "dispatcher" / "verification_contract.py"

    dest_workflows = root / ".github" / "workflows"
    dest_workflows.mkdir(parents=True, exist_ok=True)
    (dest_workflows / "issue-pr-governance.yml").write_text(
        workflow.read_text(encoding="utf-8"), encoding="utf-8"
    )
    dest_app = root / "app" / "dispatcher"
    dest_app.mkdir(parents=True, exist_ok=True)
    (dest_app / "verification_contract.py").write_text(
        contract.read_text(encoding="utf-8"), encoding="utf-8"
    )

    baseline_errors = run_lint(root)
    assert not any("verification_contract.py" in e for e in baseline_errors), baseline_errors

    # Drift the Python Final-Review-Rounds valid-line pattern alone: loosen
    # `[012]` to `[0-9]` as if someone widened the rule on only one side.
    drifted = contract.read_text(encoding="utf-8").replace(
        r'r"^Final-Review-Rounds:[ \t]*[012][ \t]*$"',
        r'r"^Final-Review-Rounds:[ \t]*[0-9][ \t]*$"',
    )
    assert drifted != contract.read_text(encoding="utf-8"), "fixture swap did not apply"
    (dest_app / "verification_contract.py").write_text(drifted, encoding="utf-8")

    errors = run_lint(root)
    assert any(
        "PR_CONTRACT_FINAL_REVIEW_ROUNDS_VALID_LINE_PATTERN" in e
        and "does not match" in e
        for e in errors
    ), errors


def test_planned_marker_allows_unknown_reference(tmp_path: Path) -> None:
    root = _seed_tree(tmp_path)
    skills_root = root / ".codex" / "skills"
    _write_readme(
        root / ".codex" / "skills",
        ["alpha-skill", "beta-skill"],
        extra="\n- `future-skill` (planned)\n  - not yet implemented\n",
    )
    assert run_lint(root) == []
    # And the same reference without the marker is flagged.
    _write_readme(skills_root, ["alpha-skill", "beta-skill"], extra="\nUse `future-skill` for this.\n")
    errors = run_lint(root)
    assert any("`future-skill`" in e for e in errors), errors
