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


def test_lint_detects_retired_phrase(tmp_path: Path) -> None:
    root = _seed_tree(tmp_path)
    alpha = root / ".codex" / "skills" / "alpha-skill" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8") + "\nDo not batch to end of task.\n",
        encoding="utf-8",
    )
    errors = run_lint(root)
    assert any("retired phrase" in e for e in errors), errors


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
