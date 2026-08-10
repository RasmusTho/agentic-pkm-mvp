"""Governance tests for the skills consistency lint (issue #1810, parent #1805).

The lint is drift insurance for `.codex/skills/`: it must pass on the repaired
tree and detect each defect class found by the 2026-06-10 skills review when
seeded into a synthetic tree.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
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


def test_registered_portable_skill_reference_passes(tmp_path: Path) -> None:
    root = _seed_tree(tmp_path)
    (root / ".codex" / "skills" / "portable-skills.list").write_text(
        "decision-quality\n", encoding="utf-8"
    )
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8")
        + "\nLoad and follow the portable `decision-quality` skill.\n",
        encoding="utf-8",
    )

    assert run_lint(root) == []


def test_portable_skill_registry_rejects_invalid_duplicate_and_local_names(
    tmp_path: Path,
) -> None:
    root = _seed_tree(tmp_path)
    (root / ".codex" / "skills" / "portable-skills.list").write_text(
        "alpha-skill\ndecision_quality\ndecision-quality\ndecision-quality\n",
        encoding="utf-8",
    )

    errors = run_lint(root)

    assert any("collides with a repo-local skill" in error for error in errors)
    assert any("invalid portable skill name `decision_quality`" in error for error in errors)
    assert any("duplicate portable skill name `decision-quality`" in error for error in errors)


def test_install_skills_provisions_registered_portable_dependency(tmp_path: Path) -> None:
    portable_root = tmp_path / "portable"
    source_skill = portable_root / "decision-quality"
    source_skill.mkdir(parents=True)
    source_text = "---\nname: decision-quality\ndescription: test\n---\n"
    (source_skill / "SKILL.md").write_text(source_text, encoding="utf-8")
    destination = tmp_path / "installed"
    env = os.environ | {
        "CLAUDE_SKILLS_DIR": str(destination),
        "PKM_PORTABLE_SKILLS_DIR": str(portable_root),
    }

    result = subprocess.run(
        ["bash", "scripts/install_skills.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (destination / "decision-quality" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == source_text


def test_install_skills_fails_closed_when_portable_dependency_is_missing(
    tmp_path: Path,
) -> None:
    portable_root = tmp_path / "portable"
    portable_root.mkdir()
    env = os.environ | {
        "CLAUDE_SKILLS_DIR": str(tmp_path / "installed"),
        "PKM_PORTABLE_SKILLS_DIR": str(portable_root),
    }

    result = subprocess.run(
        ["bash", "scripts/install_skills.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Registered portable skill is unavailable: decision-quality" in result.stderr
    assert not Path(env["CLAUDE_SKILLS_DIR"]).exists()
    assert not (Path(env["CLAUDE_SKILLS_DIR"]) / "owner-decision-brief").exists()


def test_install_skills_fails_closed_when_portable_enumeration_fails(
    tmp_path: Path,
) -> None:
    portable_root = tmp_path / "portable"
    source_skill = portable_root / "decision-quality"
    source_skill.mkdir(parents=True)
    (source_skill / "SKILL.md").write_text(
        "---\nname: decision-quality\ndescription: test\n---\n", encoding="utf-8"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_find = fake_bin / "find"
    fake_find.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${1%/}" == "$FAIL_FIND_PATH" ]]; then\n'
        '  echo "forced portable enumeration failure" >&2\n'
        "  exit 73\n"
        "fi\n"
        'exec "$REAL_FIND" "$@"\n',
        encoding="utf-8",
    )
    fake_find.chmod(0o755)
    destination = tmp_path / "installed"
    real_find = shutil.which("find")
    assert real_find is not None
    env = os.environ | {
        "CLAUDE_SKILLS_DIR": str(destination),
        "PKM_PORTABLE_SKILLS_DIR": str(portable_root),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAIL_FIND_PATH": str(source_skill),
        "REAL_FIND": real_find,
    }

    result = subprocess.run(
        ["bash", "scripts/install_skills.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "forced portable enumeration failure" in result.stderr
    assert "Unable to enumerate source skill: decision-quality" in result.stderr
    assert not (destination / "decision-quality").exists()
    assert not (destination / "owner-decision-brief").exists()
    assert "Skills installed to" not in result.stdout


def test_install_skills_fails_closed_when_skill_disappears_before_enumeration(
    tmp_path: Path,
) -> None:
    portable_root = tmp_path / "portable"
    source_skill = portable_root / "decision-quality"
    source_skill.mkdir(parents=True)
    skill_file = source_skill / "SKILL.md"
    skill_file.write_text(
        "---\nname: decision-quality\ndescription: test\n---\n", encoding="utf-8"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_find = fake_bin / "find"
    fake_find.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${1%/}" == "$MOVE_FIND_PATH" ]]; then\n'
        '  mv "$MOVE_SKILL_FILE" "$MOVE_SKILL_FILE.removed"\n'
        "fi\n"
        'exec "$REAL_FIND" "$@"\n',
        encoding="utf-8",
    )
    fake_find.chmod(0o755)
    destination = tmp_path / "installed"
    real_find = shutil.which("find")
    assert real_find is not None
    env = os.environ | {
        "CLAUDE_SKILLS_DIR": str(destination),
        "PKM_PORTABLE_SKILLS_DIR": str(portable_root),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "MOVE_FIND_PATH": str(source_skill),
        "MOVE_SKILL_FILE": str(skill_file),
        "REAL_FIND": real_find,
    }

    result = subprocess.run(
        ["bash", "scripts/install_skills.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert (source_skill / "SKILL.md.removed").exists()
    assert "enumeration omitted required SKILL.md: decision-quality" in result.stderr
    assert not (destination / "decision-quality").exists()
    assert not (destination / "owner-decision-brief").exists()
    assert "Skills installed to" not in result.stdout


def test_portable_registry_cli_uses_the_lint_normalization(tmp_path: Path) -> None:
    root = _seed_tree(tmp_path)
    (root / ".codex" / "skills" / "portable-skills.list").write_text(
        "  # indented comment\n\n  decision-quality  \n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "python3",
            str(REPO_ROOT / "scripts" / "lint_skills_consistency.py"),
            "--root",
            str(root),
            "--print-portable-skills",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert result.stdout == "decision-quality\n"


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


def test_lint_detects_bash4_only_builtin(tmp_path: Path) -> None:
    root = _seed_tree(tmp_path)
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8")
        + (
            "\nmapfile in prose is allowed.\n"
            "```python\n"
            "mapfile = []\n"
            "```\n"
            "```bash\n"
            "# mapfile in a shell comment is allowed.\n"
            "mapfile -t values < input\n"
            "readarray -t more < input\n"
            "declare -A lookup\n"
            "lower=${name,,}\n"
            "upper=${name^^}\n"
            "```\n"
        ),
        encoding="utf-8",
    )

    errors = run_lint(root)

    for construct in ("mapfile", "readarray", "declare -A", "${var,,}", "${var^^}"):
        assert any(f"`{construct}`" in error for error in errors), errors
    assert len([error for error in errors if "bash-4-only construct" in error]) == 5


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


def test_lint_fails_when_pr_contract_validator_flags_diverge_from_workflow(
    tmp_path: Path,
) -> None:
    """Dropping a regex *flag* (not pattern text) on one side must fail the lint.

    Reproduces the exact drift class from issue #4342: Check 10 previously
    compared only regex pattern text and discarded the JS trailing flag
    suffix / the Python flags argument entirely, so a flag-only divergence
    (e.g. losing `re.IGNORECASE` from `TIER1_LANE_PATTERN` while the
    workflow's JS `tier1LanePattern` stays `/im`) passed silently.
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

    # Drift the Python TIER1_LANE_PATTERN alone: drop `re.IGNORECASE`,
    # leaving the workflow's JS `tier1LanePattern` at `/im` unchanged. The
    # pattern text on both sides is still byte-identical.
    drifted = contract.read_text(encoding="utf-8").replace(
        'TIER1_LANE_PATTERN = re.compile(\n'
        r'    r"^\-\s+\[x\]\s+(?:Docs authoring|Governance) lane\b", re.IGNORECASE | re.MULTILINE'
        "\n)",
        'TIER1_LANE_PATTERN = re.compile(\n'
        r'    r"^\-\s+\[x\]\s+(?:Docs authoring|Governance) lane\b", re.MULTILINE'
        "\n)",
    )
    assert drifted != contract.read_text(encoding="utf-8"), "fixture swap did not apply"
    (dest_app / "verification_contract.py").write_text(drifted, encoding="utf-8")

    errors = run_lint(root)
    assert any(
        "TIER1_LANE_PATTERN" in e and "flags" in e for e in errors
    ), errors


def test_bug_to_issue_duplicate_search_requires_all_available_ci_discriminators() -> None:
    """CI/test duplicate search must key on stable failure identity, not prose.

    Regression guard for issue #4607 (LearningSignal
    lrn_20260731204320_6025370c): #4463 was filed as distinct from #4371
    because the prose symptoms differed, although both described the same
    failing workflow/job/step. The `bug-to-issue` workflow must require
    comparing stable CI failure identity (workflow name, job name, step name,
    script/test target, exception/error class when available) before relying
    on prose title/symptom or attributed subsystem. The assertions below are
    semantic markers: they fail if the instruction regresses to
    title/symptom-only matching, but tolerate rewording and reformatting.
    """
    skill = REPO_ROOT / ".codex" / "skills" / "bug-to-issue" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    match = re.search(
        r"^## Normal bounded bug-Issue workflow$(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, (
        f"{skill}: section '## Normal bounded bug-Issue workflow' not found"
    )
    section = match.group(1)
    lowered = section.lower()

    # Every stable CI identity key must be named in the duplicate-search step.
    for identity_key in ("workflow name", "job name", "step name"):
        assert identity_key in lowered, (
            f"duplicate-search guidance no longer names the stable CI identity "
            f"key '{identity_key}'"
        )
    assert "test target" in lowered or "script" in lowered, (
        "duplicate-search guidance no longer names the failing script/test target"
    )
    assert "error class" in lowered or "exception" in lowered, (
        "duplicate-search guidance no longer names the raised exception/error class"
    )

    # Identity must be the primary key: stated as compared before prose evidence.
    assert re.search(r"stable\s+(failure\s+)?identity", lowered), (
        "duplicate-search guidance no longer keys on stable failure identity"
    )
    assert re.search(r"before\s+(?:\S+\s+){0,8}(?:prose|title|symptom)", lowered), (
        "duplicate-search guidance no longer orders stable-identity comparison "
        "before prose title/symptom matching"
    )

    # Duplicate classification is conjunctive: one matching target cannot
    # outweigh a different error class (PR #4628 review r3712645788).
    assert re.search(
        r"(?:all|every)\s+(?:\S+\s+){0,5}available\s+(?:\S+\s+){0,5}"
        r"(?:agree|match)",
        lowered,
    ), "every available stable CI discriminator must agree before deduping"
    assert re.search(
        r"(?:any|one)\s+(?:\S+\s+){0,16}(?:differ|mismatch|missing)\S*"
        r"(?:\S+\s+){0,16}(?:distinct|separate|not\s+(?:a\s+)?duplicate)",
        lowered,
    ), "one available discriminator mismatch must keep failures distinct"
    assert not re.search(
        r"same\s+(?:script/)?test\s+target\s+or\s+(?:exception/)?error\s+class",
        lowered,
    ), "target-or-error matching reintroduces the contradictory duplicate rule"

    # The pre-existing same-symptom/title search stays as the secondary key.
    assert "symptom" in lowered and "title" in lowered, (
        "the existing same-symptom/title search must remain as secondary evidence"
    )

    # Distinct failures sharing a workflow must not be collapsed.
    assert re.search(r"(differ|distinct|not\s+collapse|do\s+not\s+collapse)", lowered), (
        "guidance must keep failures that share a workflow but differ by "
        "job/step/script/error class as distinct issues"
    )

    # The motivating duplicate class is named, without reopening either issue.
    assert "#4371" in section and "#4463" in section, (
        "guidance must name #4371/#4463 as the motivating duplicate class"
    )
    assert re.search(r"(do\s+not\s+reopen|not\s+reopen|without\s+reopening)", lowered), (
        "guidance must state the motivating issues are precedent, not reopened"
    )


def test_lint_detects_unresolvable_section_citation(tmp_path: Path) -> None:
    """Check 11 (issue #4297): a `path :: Heading` citation must resolve.

    A citation whose path does not exist, or whose heading does not match a
    Markdown heading in the cited file, is reported as an error.
    """
    root = _seed_tree(tmp_path)
    docs = root / "docs"
    docs.mkdir()
    (docs / "GUIDE.md").write_text(
        "# Guide\n\n## Real Section\n\nBody.\n\n### Deep Subsection\n\nMore.\n",
        encoding="utf-8",
    )
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8")
        + (
            "\nSee `docs/GUIDE.md :: Real Section` and"
            " `docs/GUIDE.md :: Renamed Away Section` and"
            " `docs/MISSING.md :: Real Section`.\n"
        ),
        encoding="utf-8",
    )

    errors = run_lint(root)

    citation_errors = [e for e in errors if "section citation" in e]
    assert any(
        "`docs/GUIDE.md :: Renamed Away Section`" in e and "no Markdown heading" in e
        for e in citation_errors
    ), errors
    assert any(
        "`docs/MISSING.md :: Real Section`" in e and "does not exist" in e
        for e in citation_errors
    ), errors
    # The resolving citation is not flagged.
    assert not any("`docs/GUIDE.md :: Real Section`" in e for e in citation_errors), errors


def test_section_citations_resolve_on_real_repo() -> None:
    """The live instruction chain has no unresolvable citations (issue #4297)."""
    from scripts.lint_skills_consistency import check_section_citations

    errors = check_section_citations(REPO_ROOT)
    assert errors == [], "unresolvable section citations:\n" + "\n".join(errors)


def test_section_citation_resolves_subheading_and_decorated_headings(tmp_path: Path) -> None:
    """Sub-headings, enum prefixes, parentheticals, and backticks all resolve."""
    root = _seed_tree(tmp_path)
    docs = root / "docs"
    docs.mkdir()
    (docs / "GUIDE.md").write_text(
        "# Guide\n\n"
        "## 3. Numbered Section\n\n"
        "### 4b. Deep Rule\n\n"
        "## Total Cost (qualifier here)\n\n"
        "### `Verify:` marker rule\n\n",
        encoding="utf-8",
    )
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8")
        + (
            "\nSee `docs/GUIDE.md :: Numbered Section`,"
            " `docs/GUIDE.md :: Deep Rule`,"
            " `docs/GUIDE.md :: Total Cost`,"
            " `docs/GUIDE.md :: Total Cost (qualifier here)`,"
            " and `docs/GUIDE.md :: Verify: marker rule`.\n"
        ),
        encoding="utf-8",
    )

    errors = run_lint(root)

    assert not any("section citation" in e for e in errors), errors


def test_section_citation_ignores_fences_placeholders_and_non_paths(tmp_path: Path) -> None:
    """Code fences, placeholder citations, and skill-name citations are not parsed."""
    root = _seed_tree(tmp_path)
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8")
        + (
            "\nThe protocol shape is `FILE :: Section` and"
            " `docs/<path> :: <anchor>` and"
            " `alpha-skill :: Some Runbook Step` and"
            " `docs/learning-log.md :: YYYY-MM-DD entry`.\n"
            "\n```bash\n"
            "echo '`docs/NOPE.md :: Fenced Citation`'\n"
            "```\n"
        ),
        encoding="utf-8",
    )

    errors = run_lint(root)

    assert not any("section citation" in e for e in errors), errors


def test_section_citation_outside_repo_fails(tmp_path: Path) -> None:
    """A citation whose path escapes the repository root is an error."""
    root = _seed_tree(tmp_path)
    # A real file outside the lint root must still not resolve.
    (tmp_path.parent / "escape.md").write_text("# Escaped\n", encoding="utf-8")
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8") + "\nSee `../escape.md :: Escaped`.\n",
        encoding="utf-8",
    )

    errors = run_lint(root)

    assert any(
        "section citation" in e and "outside the repository" in e for e in errors
    ), errors


def test_section_citation_spanning_a_line_break_resolves(tmp_path: Path) -> None:
    """A backticked citation wrapped across a line break still parses."""
    root = _seed_tree(tmp_path)
    docs = root / "docs"
    docs.mkdir()
    (docs / "GUIDE.md").write_text(
        "# Guide\n\n## A Long Heading That Wraps In Prose\n\nBody.\n",
        encoding="utf-8",
    )
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8")
        + (
            "\nSee `docs/GUIDE.md :: A Long Heading That\n"
            "  Wraps In Prose` for details, and the broken"
            " `docs/GUIDE.md :: Not\n  A Heading` twin.\n"
        ),
        encoding="utf-8",
    )

    errors = run_lint(root)

    citation_errors = [e for e in errors if "section citation" in e]
    assert not any("A Long Heading That Wraps In Prose" in e for e in citation_errors), errors
    assert any("Not A Heading" in e for e in citation_errors), errors


def test_section_citation_anchor_id_and_non_markdown_targets(tmp_path: Path) -> None:
    """Stable anchor IDs resolve by presence; non-md targets resolve by content."""
    root = _seed_tree(tmp_path)
    docs = root / "docs"
    docs.mkdir()
    (docs / "STATUS.md").write_text(
        "# Status\n\nShipped PA9-EXAMPLE earlier.\n", encoding="utf-8"
    )
    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "tool.py").write_text(
        "def real_function() -> None:\n    pass\n", encoding="utf-8"
    )
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8")
        + (
            "\nSee `docs/STATUS.md :: PA9-EXAMPLE` and"
            " `docs/STATUS.md :: PA9-GONE` and"
            " `scripts/tool.py :: real_function` and"
            " `scripts/tool.py :: missing_function`.\n"
        ),
        encoding="utf-8",
    )

    errors = run_lint(root)

    citation_errors = [e for e in errors if "section citation" in e]
    assert not any("PA9-EXAMPLE" in e for e in citation_errors), errors
    assert any("PA9-GONE" in e for e in citation_errors), errors
    assert not any("real_function" in e for e in citation_errors), errors
    assert any("missing_function" in e for e in citation_errors), errors


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
