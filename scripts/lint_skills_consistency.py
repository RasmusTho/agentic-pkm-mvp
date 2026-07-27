#!/usr/bin/env python3
"""Skills consistency lint — drift insurance for `.codex/skills/`.

Deterministic, stdlib-only, read-only. Catches the defect classes found by the
2026-06-10 skills review (issue #1810, parent #1805):

1. Every skill directory (except `_shared/`) has a `SKILL.md` whose `name:`
   frontmatter matches the directory name.
2. Every backticked kebab-case token in the README and the SKILL.md files that
   looks like a skill reference resolves to an existing skill directory, a
   `_shared/` file, a known non-skill term, or carries an explicit `(planned)`
   marker on the same line.
3. The README "Skill routing" section lists every skill directory.
4. Every full agent-label taxonomy block (a bullet list of six or more
   `type:`/`prio:`/`agent:` labels) is identical to the canonical taxonomy.
5. No skill file contains the retired phrase "Do not batch to end of task"
   (regression guard for #1806).
6. Frontmatter `description:` is non-empty and single-line.
7. `feature-breakdown/SKILL.md`, when present, keeps its `docs/DOCS_INDEX.md`
   registration instruction (regression guard for #3559).
8. The `SBS Impact` field list is identical, in the same order, across
   `.codex/skills/_shared/ISSUE_CONTRACT.md`, `.github/ISSUE_TEMPLATE/task.yml`,
   `.github/pull_request_template.md`, and `scripts/pr_body_generator.py ::
   SBS_FIELDS` (regression guard for #4188 — the `Boundary risk` field drift).
9. The JS `required` section-name array in
   `.github/workflows/issue-pr-governance.yml` and the Python
   `REQUIRED_SECTIONS` tuple in `scripts/validate_issue_readiness.py` hold the
   same section names in the same order (regression guard for #4188).

Exit 0 with no output when clean; exit 1 with one error per line otherwise.

This is drift insurance, not a style enforcer — keep the check list small and
high-signal (proportionality: docs/development/GOVERNANCE_PROPORTIONALITY.md).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Callable

# Canonical label taxonomy. Single source after the `_shared/` extraction
# (#1809); until then this mirrors the list in docs-to-issue/SKILL.md.
CANONICAL_LABELS = [
    "type:task",
    "type:bug",
    "type:refactor",
    "prio:high",
    "prio:med",
    "prio:low",
    "agent:ready",
    "agent:blocked",
    "agent:needs-human",
]

# Backticked kebab-case tokens that are not skill names. A token not listed
# here, not a skill directory, not a `_shared/` file, and not marked
# `(planned)` on its line is reported as an unknown skill reference — fix the
# reference, mark it planned, or add the term here if it is plain vocabulary.
KNOWN_NON_SKILL_TERMS = {
    "agentic-pkm-mvp",  # repository name
    "blocked-ci-failure",  # PR escalation classifications
    "blocked-contract-drift",
    "blocked-merge-conflict",
    "blocked-review-feedback",
    "create-or-update-breakdown",  # feature-breakdown mode name
    "docs-roadmap-update",  # branch-name examples
    "fix-auth-token-expiry",
    "governance-skill-updates",
    "enrich-docs",  # docs-to-issue mode name
    "learning-summary",  # BuilderOps projection name
    "pkm-prod",  # compose project names
    "pkm-test",
    "harness-selfverify",  # CI workflow/gate name (added by #2001)
    "pr-contract",  # CI check names
    "smoke-docker",
    "ready-for-verification",  # workflow state phrase
    "stable-prev",  # release-channel ref name
    "test-candidate",  # promotion vocabulary
    "generate-projections",  # builderops CLI subcommand
    "create-learning-signal",  # builderops CLI subcommand
}

RETIRED_PHRASE = "Do not batch to end of task"

KEBAB_TOKEN_RE = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`")
ROUTING_ENTRY_RE = re.compile(r"^- `([a-z][a-z0-9-]+)`\s*$", re.MULTILINE)
LABEL_ITEM_RE = re.compile(r"^\s*[-*]\s+`((?:type|prio|agent):[a-z-]+)`\s*\|?\s*$")
BLOCK_SCALAR_DESCRIPTION_RE = re.compile(r"^[|>](?:[+-]?\d*|\d+[+-]?)$")
FULL_TAXONOMY_MIN_ITEMS = 6


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Return frontmatter key/value pairs, or None when no frontmatter exists."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        match = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if match:
            fields[match.group(1)] = match.group(2).strip().strip('"')
    return None  # unterminated frontmatter


def _skill_dirs(skills_root: Path) -> list[Path]:
    return sorted(
        d for d in skills_root.iterdir() if d.is_dir() and d.name != "_shared"
    )


def check_skill_frontmatter(skills_root: Path) -> list[str]:
    """Checks 1 and 6: SKILL.md presence, name match, description shape."""
    errors: list[str] = []
    for skill_dir in _skill_dirs(skills_root):
        skill_md = skill_dir / "SKILL.md"
        rel = skill_md.relative_to(skills_root.parent.parent)
        if not skill_md.is_file():
            errors.append(f"{skill_dir.name}: missing SKILL.md")
            continue
        fields = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        if fields is None:
            errors.append(f"{rel}: missing or unterminated frontmatter block")
            continue
        name = fields.get("name", "")
        if name != skill_dir.name:
            errors.append(
                f"{rel}: frontmatter name '{name}' does not match directory "
                f"'{skill_dir.name}'"
            )
        description = fields.get("description", "")
        if not description:
            errors.append(f"{rel}: frontmatter description is empty or missing")
        elif BLOCK_SCALAR_DESCRIPTION_RE.match(description):
            errors.append(
                f"{rel}: frontmatter description must be a non-empty single line"
            )
    return errors


def check_skill_references(skills_root: Path) -> list[str]:
    """Check 2: backticked kebab tokens resolve to something real."""
    errors: list[str] = []
    skill_names = {d.name for d in _skill_dirs(skills_root)}
    shared_dir = skills_root / "_shared"
    shared_names = (
        {p.stem for p in shared_dir.iterdir() if p.is_file()}
        | {p.name for p in shared_dir.iterdir() if p.is_file()}
        if shared_dir.is_dir()
        else set()
    )
    known = skill_names | shared_names | KNOWN_NON_SKILL_TERMS
    readme = skills_root / "README.md"
    files = ([readme] if readme.is_file() else []) + [
        d / "SKILL.md" for d in _skill_dirs(skills_root) if (d / "SKILL.md").is_file()
    ]
    for path in files:
        rel = path.relative_to(skills_root.parent.parent)
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for token in KEBAB_TOKEN_RE.findall(line):
                if token in known or "(planned)" in line:
                    continue
                errors.append(
                    f"{rel}:{lineno}: unknown skill-like reference `{token}` — "
                    "fix the reference, mark it (planned), or add it to "
                    "KNOWN_NON_SKILL_TERMS if it is plain vocabulary"
                )
    return errors


def check_readme_routing_complete(skills_root: Path) -> list[str]:
    """Check 3: README Skill routing section covers every skill directory."""
    errors: list[str] = []
    readme = skills_root / "README.md"
    rel = readme.relative_to(skills_root.parent.parent)
    if not readme.is_file():
        return [f"{rel}: missing"]
    text = readme.read_text(encoding="utf-8")
    match = re.search(r"^## Skill routing$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return [f"{rel}: no '## Skill routing' section found"]
    routed = set(ROUTING_ENTRY_RE.findall(match.group(1)))
    for skill_dir in _skill_dirs(skills_root):
        if skill_dir.name not in routed:
            errors.append(
                f"{rel}: Skill routing section has no entry for `{skill_dir.name}`"
            )
    return errors


def check_label_taxonomy(skills_root: Path) -> list[str]:
    """Check 4: full label-taxonomy bullet blocks match the canonical list."""
    errors: list[str] = []
    for skill_dir in _skill_dirs(skills_root):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        rel = skill_md.relative_to(skills_root.parent.parent)
        block: list[str] = []
        block_start = 0
        lines = skill_md.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines + [""], start=1):
            item = LABEL_ITEM_RE.match(line)
            if item:
                if not block:
                    block_start = lineno
                block.append(item.group(1))
                continue
            if len(block) >= FULL_TAXONOMY_MIN_ITEMS and block != CANONICAL_LABELS:
                errors.append(
                    f"{rel}:{block_start}: label taxonomy block diverges from the "
                    f"canonical list ({', '.join(CANONICAL_LABELS)}); found: "
                    f"{', '.join(block)}"
                )
            block = []
    return errors


def check_retired_phrases(skills_root: Path) -> list[str]:
    """Check 5: regression guard for phrases removed by #1806."""
    errors: list[str] = []
    for path in sorted(skills_root.rglob("*.md")):
        rel = path.relative_to(skills_root.parent.parent)
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if RETIRED_PHRASE in line:
                errors.append(
                    f"{rel}:{lineno}: contains retired phrase '{RETIRED_PHRASE}' "
                    "(capture-learning owns invocation timing; see #1806)"
                )
    return errors


def check_feature_breakdown_docs_index(skills_root: Path) -> list[str]:
    """Check 7: feature-breakdown must keep its DOCS_INDEX registration rule.

    Regression guard for #3559 (from the PR #3154 / #3167 / #3193 miss): when a
    breakdown creates a `docs/<CAPABILITY>/` specification directory it must
    register it in `docs/DOCS_INDEX.md`. Anchoring on the stable path token
    keeps this non-brittle — it survives rewording but fails if the instruction
    is dropped.

    Like the other per-skill checks, this tolerates the skill being absent
    (e.g. synthetic trees seeded by the lint's own tests): it only asserts the
    instruction when `feature-breakdown/SKILL.md` actually exists.
    """
    errors: list[str] = []
    skill = skills_root / "feature-breakdown" / "SKILL.md"
    if not skill.is_file():
        return errors
    rel = skill.relative_to(skills_root.parent.parent)
    if "docs/DOCS_INDEX.md" not in skill.read_text(encoding="utf-8"):
        errors.append(
            f"{rel}: missing the DOCS_INDEX registration instruction "
            "(must reference 'docs/DOCS_INDEX.md'; see #3559)"
        )
    return errors


def _extract_labeled_fields(text: str, start: str, end: str) -> list[str] | None:
    """Extract `- <Label>:` bullet labels between two markers, in order.

    Returns None when `start` is not found (caller decides whether that means
    "file/section absent, skip this check" or an error).
    """
    match = re.search(
        re.escape(start) + r"\n(.*?)\n\n" + re.escape(end), text, re.DOTALL
    )
    if not match:
        return None
    return re.findall(r"^\s*-\s*([^:\n]+):", match.group(1), re.MULTILINE)


def _extract_sbs_fields_issue_contract(text: str) -> list[str] | None:
    return _extract_labeled_fields(text, "## SBS Impact", "##")


def _extract_sbs_fields_task_yml(text: str) -> list[str] | None:
    match = re.search(
        r"id: sbs_impact.*?placeholder: \|\n(.*?)\n\s*validations:", text, re.DOTALL
    )
    if not match:
        return None
    return re.findall(r"^\s*-\s*([^:\n]+):", match.group(1), re.MULTILINE)


def _extract_sbs_fields_pr_template(text: str) -> list[str] | None:
    return _extract_labeled_fields(text, "## SBS Impact", "## Owner-Doc Writeback")


def _extract_sbs_fields_pr_body_generator(text: str) -> list[str] | None:
    match = re.search(r"SBS_FIELDS = \(\n(.*?)\n\)", text, re.DOTALL)
    if not match:
        return None
    return re.findall(r'\(\s*"[a-z_]+"\s*,\s*"([^"]+)"\s*\)', match.group(1))


SBS_FIELD_SOURCES: tuple[tuple[str, Callable[[str], list[str] | None]], ...] = (
    (".codex/skills/_shared/ISSUE_CONTRACT.md", _extract_sbs_fields_issue_contract),
    (".github/ISSUE_TEMPLATE/task.yml", _extract_sbs_fields_task_yml),
    (".github/pull_request_template.md", _extract_sbs_fields_pr_template),
    ("scripts/pr_body_generator.py", _extract_sbs_fields_pr_body_generator),
)


def check_sbs_impact_fields_consistent(repo_root: Path) -> list[str]:
    """Check 8: the SBS Impact field list agrees, in order, across all copies.

    Tolerates a missing source file (synthetic test trees under `.codex/skills/`
    only) by skipping the check entirely rather than reporting a false defect —
    this lint's contract is drift *between existing copies*, not file presence.
    """
    errors: list[str] = []
    found: list[tuple[str, list[str]]] = []
    for rel_path, extractor in SBS_FIELD_SOURCES:
        path = repo_root / rel_path
        if not path.is_file():
            return errors
        fields = extractor(path.read_text(encoding="utf-8"))
        if fields is None:
            errors.append(f"{rel_path}: could not locate the SBS Impact field list")
            continue
        found.append((rel_path, fields))
    if errors:
        return errors
    canonical_path, canonical_fields = found[0]
    for rel_path, fields in found[1:]:
        if fields != canonical_fields:
            errors.append(
                f"{rel_path}: SBS Impact field list ({', '.join(fields)}) does not "
                f"match {canonical_path} ({', '.join(canonical_fields)})"
            )
    return errors


def _extract_required_sections_js(text: str) -> list[str] | None:
    match = re.search(r"const required = \[\n(.*?)\n\s*\];", text, re.DOTALL)
    if not match:
        return None
    return re.findall(r'"([^"]+)"', match.group(1))


def _extract_required_sections_python(text: str) -> list[str] | None:
    match = re.search(
        r"REQUIRED_SECTIONS: tuple\[str, \.\.\.\] = \(\n(.*?)\n\)", text, re.DOTALL
    )
    if not match:
        return None
    return re.findall(r'"([^"]+)"', match.group(1))


def check_required_sections_consistent(repo_root: Path) -> list[str]:
    """Check 9: the JS `required` array and Python `REQUIRED_SECTIONS` tuple agree.

    Tolerates missing source files the same way as check 8 (see its docstring).
    """
    js_path = repo_root / ".github" / "workflows" / "issue-pr-governance.yml"
    py_path = repo_root / "scripts" / "validate_issue_readiness.py"
    if not js_path.is_file() or not py_path.is_file():
        return []
    js_sections = _extract_required_sections_js(js_path.read_text(encoding="utf-8"))
    py_sections = _extract_required_sections_python(py_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if js_sections is None:
        errors.append(
            f"{js_path.name}: could not locate the JS `required` sections array"
        )
    if py_sections is None:
        errors.append(
            f"{py_path.name}: could not locate the Python `REQUIRED_SECTIONS` tuple"
        )
    if errors:
        return errors
    if js_sections != py_sections:
        errors.append(
            "required-sections lists diverge: "
            f"issue-pr-governance.yml required={js_sections} vs "
            f"validate_issue_readiness.py REQUIRED_SECTIONS={py_sections}"
        )
    return errors


def run_lint(repo_root: Path) -> list[str]:
    skills_root = repo_root / ".codex" / "skills"
    if not skills_root.is_dir():
        return [f"{skills_root}: not a directory"]
    errors: list[str] = []
    errors += check_skill_frontmatter(skills_root)
    errors += check_skill_references(skills_root)
    errors += check_readme_routing_complete(skills_root)
    errors += check_label_taxonomy(skills_root)
    errors += check_retired_phrases(skills_root)
    errors += check_feature_breakdown_docs_index(skills_root)
    errors += check_sbs_impact_fields_consistent(repo_root)
    errors += check_required_sections_consistent(repo_root)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root to lint (default: this repo)",
    )
    args = parser.parse_args(argv)
    errors = run_lint(args.root)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
