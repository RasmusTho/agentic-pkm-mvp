"""Filing-time join invariant for spec task docs (INV-DG-5, #4444).

Every task doc in the exemplar specification directories that carries a
``task_id:`` (i.e. is a filed implementation task, not a README or parent
hub doc) must also carry a populated ``github_issue:`` frontmatter key —
the machine join between the docs plane's dependency DAG and the GitHub
delivery plane. The audit that motivated this
(``docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md`` F6) found the
field populated in one exemplar dir out of three; this test pins all three
so the join cannot silently regress. New spec dirs inherit the invariant
from ``feature-breakdown``'s filing-time writeback step rather than from
this list.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

EXEMPLAR_SPEC_DIRS = (
    "docs/DETERMINISTIC_DELIVERY_ORCHESTRATION",
    "docs/BUILDEROPS_CONTROL_PLANE",
    "docs/CKM_DESIGN_AGENT_INTEGRATION",
)

_TASK_ID = re.compile(r"^task_id:\s*\S+", re.MULTILINE)
_GITHUB_ISSUE = re.compile(r"^github_issue:\s*[1-9][0-9]*\s*$", re.MULTILINE)


def _frontmatter(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    return text[4:end] if end != -1 else None


def _task_docs(spec_dir: str) -> list[Path]:
    docs = []
    for path in sorted((REPO_ROOT / spec_dir).glob("*.md")):
        frontmatter = _frontmatter(path.read_text(encoding="utf-8"))
        if frontmatter is not None and _TASK_ID.search(frontmatter):
            docs.append(path)
    return docs


@pytest.mark.parametrize("spec_dir", EXEMPLAR_SPEC_DIRS)
def test_exemplar_spec_dirs_carry_github_issue_frontmatter(spec_dir: str) -> None:
    task_docs = _task_docs(spec_dir)
    assert task_docs, f"no task docs with task_id frontmatter found under {spec_dir}"

    missing = [
        str(path.relative_to(REPO_ROOT))
        for path in task_docs
        if not _GITHUB_ISSUE.search(_frontmatter(path.read_text(encoding="utf-8")) or "")
    ]
    assert not missing, (
        "task docs missing a populated github_issue: frontmatter key "
        f"(INV-DG-5): {missing}"
    )
