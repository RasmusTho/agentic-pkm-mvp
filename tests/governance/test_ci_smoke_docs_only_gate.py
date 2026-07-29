"""Guard against the #4281 false-green defect on the required check.

`pr-unit-tests-not-pg` (`Unit tests (not pg)`) is a required PR check that
gates every merge to `main`. Its `code` paths-filter used to omit
`AGENTS.md`, `CLAUDE.md`, `.codex/**`, and `docs/**` -- paths that
`tests/architecture/test_agent_skill_entrypoints.py` and
`tests/ops/test_review_before_ci_gate.py` assert on directly, and that
`tests/governance/**` exists to cover. A PR touching only those paths made the
filter output `false`, every real step (install, mypy, the KERNEL-13 gate, the
selected pytest run) was `skipped`, and the job still concluded `success` -- a
required check that looked green without executing the tests that cover the
change.

Note: `tests/architecture/test_pr_hot_path_governance.py` is NOT part of this
gap -- the `smoke` job's "Hot path governance architecture test" step runs it
unconditionally (no `if:` on that step, and no job-level `if:` on `smoke`), so
it already executes on every PR regardless of this filter. The original issue
text named it as an example of asserting content; it was never actually
skipped.

These tests prove the fix two ways: the paths-filter now includes the
previously-excluded surface (static parse of the workflow), and
`scripts/select_pr_tests.py` actually selects the covering test targets for
that surface -- including `tests/architecture` and
`tests/ops/test_review_before_ci_gate.py`, which the pre-existing
`docs_authoring`/`governance`-only branches did not select even once the
filter itself was fixed -- rather than silently falling through to a
docs-only/unowned no-op (executable check against the real selector).
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.select_pr_tests import select_tests


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_SMOKE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-smoke.yaml"

# The four previously-excluded path classes named in #4281.
PREVIOUSLY_EXCLUDED_GLOBS = ("AGENTS.md", "CLAUDE.md", ".codex/**", "docs/**")

# Concrete example changed-file sets for each previously-excluded class,
# paired with the covering test file/dir that must be selected for that
# class rather than skipped.
COVERING_SELECTIONS = (
    ("AGENTS.md", "tests/architecture"),
    ("AGENTS.md", "tests/ops/test_review_before_ci_gate.py"),
    ("CLAUDE.md", "tests/architecture"),
    (".codex/AGENTS.md", "tests/architecture"),
    (".codex/skills/verify-promotion/SKILL.md", "tests/ops/test_review_before_ci_gate.py"),
    ("docs/TESTING.md", "tests/architecture"),
    ("docs/TESTING.md", "tests/ops/test_review_before_ci_gate.py"),
    (".github/pull_request_template.md", "tests/architecture"),
)


def _smoke_text() -> str:
    return CI_SMOKE_WORKFLOW.read_text(encoding="utf-8")


def _unit_tests_job_text() -> str:
    workflow = _smoke_text()
    return workflow[
        workflow.index("pr-unit-tests-not-pg:") : workflow.index("pr-index-pg-contracts:")
    ]


def _code_filter_block() -> str:
    job = _unit_tests_job_text()
    # The `code` filter block runs from its own "code:" key to the first
    # subsequent step ("- uses: actions/setup-python@v5"), which is gated on
    # this same filter's output.
    start = job.index("filters: |")
    end = job.index("- uses: actions/setup-python@v5")
    return job[start:end]


def _code_filter_globs() -> list[str]:
    block = _code_filter_block()
    return re.findall(r"- '([^']+)'", block)


def test_unit_test_filter_or_skip_conclusion_is_corrected() -> None:
    # Static parse of the `pr-unit-tests-not-pg` job's `code` dorny/paths-filter
    # (.github/workflows/ci-smoke.yaml, originally lines 573-593): its glob
    # list must now be a superset of the agent-contract/doc surface that has
    # real asserting test coverage.
    job = _unit_tests_job_text()
    assert "Detect unit-test surface" in job
    assert "dorny/paths-filter@v3" in job

    globs = _code_filter_globs()
    for expected in PREVIOUSLY_EXCLUDED_GLOBS:
        assert expected in globs, (
            f"code filter is missing {expected!r}; a PR touching only this "
            "surface would still self-skip and report success (#4281)"
        )

    # The pre-existing runtime/test surface must still be present -- this is
    # an extension of the filter, not a narrowing.
    for still_present in ("app/**", "tests/**", "scripts/**", "companion-ui/**"):
        assert still_present in globs

    # The skip step, and every real step it is the mirror image of, must
    # still be driven by this one filter output -- otherwise "extending the
    # filter" and "what actually runs" could silently drift apart.
    assert "if: steps.changes.outputs.code == 'true'" in job
    assert "if: steps.changes.outputs.code != 'true'" in job
    assert 'name: Skip unit tests for docs-only PR' in job


def test_unit_test_lane_covers_agent_contract_and_doc_paths() -> None:
    # A PR that changes only AGENTS.md, CLAUDE.md, a file under .codex/**, or
    # a file under docs/** must not just flip the filter to `true` -- the
    # subsystem-scoped selector consumed by the "Run not-pg unit tests" step
    # must actually pick the test target(s) that assert on that changed path,
    # not fall through to a narrower docs-only/governance-only selection that
    # happens to omit them (the residual gap the plain filter-only fix would
    # have left: AGENTS.md/.codex/** route through the governance-only branch,
    # which did not previously include tests/architecture or
    # tests/ops/test_review_before_ci_gate.py).
    for changed_file, expected_target in COVERING_SELECTIONS:
        selection = select_tests([changed_file])
        assert selection.unowned_paths == (), (
            f"{changed_file} resolved as unowned; it must resolve to a real "
            "test selection"
        )
        assert expected_target in selection.targets, (
            f"{changed_file} did not select {expected_target}; this changed "
            "path has real asserting test coverage there and must not be "
            "silently skipped"
        )

    # None of these previously-excluded-but-covered classes need the blunt
    # "run everything" fallback -- confirms the fix stays scoped rather than
    # inflating cost on every docs/governance PR (AGENTS.md :: Total Cost of
    # Development).
    for changed_file, _ in COVERING_SELECTIONS:
        assert select_tests([changed_file]).full_suite is False

    # A genuinely uncovered docs-only path (no asserting test anywhere) must
    # still stay on the cheap docs-only lane, not escalate to full suite --
    # the fix closes a coverage gap, it does not widen every docs PR's cost.
    cheap_selection = select_tests(["docs/some_freshly_added_note.md"])
    assert cheap_selection.full_suite is False
    assert cheap_selection.subsystems == ("docs",)


def test_pr_4275_shaped_diff_now_selects_architecture_and_ci_gate_coverage() -> None:
    # Live reproduction named in #4281: PR #4275 (head d9c098f0e) changed only
    # .codex/AGENTS.md, .codex/skills/README.md, .codex/skills/_shared/READ_SCOPE.md,
    # .codex/skills/issue-to-code/SKILL.md, AGENTS.md, CLAUDE.md, and
    # docs/DOCS_INDEX.md. Before this fix, scripts/select_pr_tests.py already
    # correctly resolved this mixed set to subsystems=("docs_authoring",) with
    # targets (tests/ci, tests/governance, tests/scripts,
    # tests/ops/test_ci_workflow.py) -- select_pr_tests.py was never the
    # problem for this diff. The gap was twofold: (1) the `code` paths-filter
    # in front of the job suppressed the whole job for this diff (fixed above),
    # and (2) even with the filter fixed, `docs_authoring`'s targets omitted
    # tests/architecture and tests/ops/test_review_before_ci_gate.py, so the
    # architecture/CI-gate tests that actually assert on these paths still
    # would not have run.
    pr_4275_diff = (
        ".codex/AGENTS.md",
        ".codex/skills/README.md",
        ".codex/skills/_shared/READ_SCOPE.md",
        ".codex/skills/issue-to-code/SKILL.md",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/DOCS_INDEX.md",
    )
    selection = select_tests(list(pr_4275_diff))

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert selection.subsystems == ("docs_authoring",)
    assert "tests/governance" in selection.targets
    assert "tests/scripts" in selection.targets
    assert "tests/ops/test_ci_workflow.py" in selection.targets
    assert "tests/architecture" in selection.targets
    assert "tests/ops/test_review_before_ci_gate.py" in selection.targets
