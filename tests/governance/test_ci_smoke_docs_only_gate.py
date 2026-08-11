"""Guard against the #4281 false-green defect on the required check.

`pr-unit-tests-not-pg` (`Unit tests (not pg)`) is a required PR check that
gates every merge to `main`. Its `code` paths-filter used to omit
`.github/**`, `AGENTS.md`, `CLAUDE.md`, `.codex/**`, and `docs/**` -- paths that
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

from fnmatch import fnmatchcase
from pathlib import Path

import yaml

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


def _unit_tests_job_text() -> dict[str, object]:
    workflow = yaml.safe_load(_smoke_text())
    return workflow["jobs"]["pr-unit-tests-not-pg"]


def _code_filter_block() -> dict[str, list[str]]:
    job = _unit_tests_job_text()
    filter_step = next(
        step
        for step in job["steps"]
        if step.get("uses") == "dorny/paths-filter@v3"
    )
    return yaml.safe_load(filter_step["with"]["filters"])


def _code_filter_globs() -> list[str]:
    return _code_filter_block()["code"]


def test_unit_test_filter_or_skip_conclusion_is_corrected() -> None:
    # Static parse of the `pr-unit-tests-not-pg` job's `code` dorny/paths-filter
    # (.github/workflows/ci-smoke.yaml, originally lines 573-593): its glob
    # list must now be a superset of the agent-contract/doc surface that has
    # real asserting test coverage.
    job = _unit_tests_job_text()
    assert any(step.get("name") == "Detect unit-test surface" for step in job["steps"])
    assert any(step.get("uses") == "dorny/paths-filter@v3" for step in job["steps"])

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
    conditions = {step.get("if") for step in job["steps"]}
    names = {step.get("name") for step in job["steps"]}
    assert "steps.changes.outputs.code == 'true'" in conditions
    assert "steps.changes.outputs.code != 'true'" in conditions
    assert "Skip unit tests for docs-only PR" in names


def test_code_filter_covers_github_surface() -> None:
    globs = _code_filter_globs()
    for github_path in (
        ".github/pull_request_template.md",
        ".github/workflows/issue-pr-governance.yml",
    ):
        assert any(fnmatchcase(github_path, pattern) for pattern in globs), (
            f"code filter does not cover {github_path!r}; a PR touching only "
            "this asserted-on surface would self-skip the required check"
        )


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


def _smoke_job_text() -> str:
    workflow = _smoke_text()
    return workflow[workflow.index("  smoke:") : workflow.index("  smoke-docker:")]


def test_docs_only_lane_runs_the_governance_suite_that_asserts_on_docs() -> None:
    # Companion gap to #4281 on the docs side. Only `docs/development/**` matches
    # `_is_governance_only`'s prefixes, so every other governance-relevant doc
    # routed to the docs branch -- whose targets omitted `tests/governance`
    # entirely. Editing any of these files could therefore break the governance
    # test that reads it while the required check stayed green.
    docs_read_by_governance_tests = (
        # test_project_pickup_deprecation.py, test_autonomous_escalation_contract.py
        "docs/AGENT_ISSUE_DISPATCHER.md",
        # test_project_pickup_deprecation.py
        "docs/ARCHITECTURE.md",
        # test_codex_agents_contract.py
        "docs/architecture/SBS_OPERATING_MODEL.md",
        # test_known_defects_registry.py
        "docs/STATUS.md",
        "docs/ROADMAP.md",
        # test_issue_pr_governance.py
        "docs/DESIGN_HANDOFF_GOVERNANCE.md",
        # test_vault_multiwriter_frontmatter.py
        "docs/adr/ADR-0055-vault-multiwriter-consistency-model.md",
        "docs/testing/invariant-tests.md",
    )
    for changed_file in docs_read_by_governance_tests:
        selection = select_tests([changed_file])
        assert selection.full_suite is False, (
            f"{changed_file} must stay on a scoped lane, not the full suite"
        )
        assert "tests/governance" in selection.targets, (
            f"{changed_file} is read directly by a tests/governance module but "
            "did not select tests/governance; a change to it could break that "
            "test with a green required check"
        )


def test_docs_guard_runs_on_the_pr_path_for_governance_and_doc_changes() -> None:
    # scripts/docs_guard.py's only caller was architecture-ci.yaml, which is
    # workflow_dispatch-only (#3892) -- so the guard ran on no pull request at
    # all. The smoke job now runs it for the governance/docs-only shape.
    job = _smoke_job_text()
    assert "scripts/docs_guard.py" in job, (
        "scripts/docs_guard.py has no PR-triggered caller; architecture-ci.yaml "
        "is workflow_dispatch-only"
    )

    # The filter it is gated on must cover the same four path classes as the
    # required check's `code` filter, or the two gates drift apart.
    filters = job[job.index("filters: |") : job.index("- name: Install system deps")]
    governance_docs = filters[filters.index("governance_docs:") :]
    for expected in PREVIOUSLY_EXCLUDED_GLOBS:
        assert f"- '{expected}'" in governance_docs, (
            f"governance_docs filter is missing {expected!r}"
        )

    # Scope guard: the step must stay off the runtime surface. docs_guard's
    # app/**-vs-docs and temporal-owner rules fire on app/**, scripts/**, and
    # config/** changes, so an unscoped step would newly fail ordinary runtime
    # PRs -- a different change from closing the docs-side coverage gap.
    guard_step = job[job.index("- name: Docs guard") :]
    guard_step = guard_step[: guard_step.index("- name: Doc integrity")]
    assert "steps.changes.outputs.governance_docs == 'true'" in guard_step
    assert "steps.changes.outputs.heavy_smoke != 'true'" in guard_step


def test_documentation_language_guard_runs_on_every_pr_shape() -> None:
    job = _smoke_job_text()
    start = job.index("- name: Documentation language guard")
    end = job.index("- name: Docs guard", start)
    step = job[start:end]

    assert "python3 scripts/docs_guard.py --language-only" in step
    assert "if:" not in step, (
        "the English documentation policy must also cover docs changed by "
        "implementation PRs"
    )


def test_heavy_smoke_stays_off_the_docs_surface() -> None:
    # The inverse assertion: heavy_smoke must NOT be widened to the doc surface.
    # Every step it gates is runtime-code-only, so including docs/** there would
    # cost a docs typo the full runtime smoke while adding no assertion that
    # reads the changed file (AGENTS.md :: Total Cost of Development). The
    # coverage those paths need comes from the selector and the guard above.
    job = _smoke_job_text()
    heavy = job[job.index("heavy_smoke:") : job.index("governance_docs:")]
    for docs_glob in ("docs/**", "AGENTS.md", "CLAUDE.md", ".codex/**"):
        assert f"- '{docs_glob}'" not in heavy, (
            f"heavy_smoke must not include {docs_glob!r}: it gates only "
            "runtime-code test slices, none of which read that surface"
        )


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
    #
    # #4335 widened `_is_docs_only` to accept `.codex/**` (previously only a
    # pure `.codex/skills/`+`docs/contracts/` mix routed through the
    # `docs_authoring` subsystem loop; `docs/DOCS_INDEX.md` in this diff kept
    # `_is_docs_only` False before that fix). This diff now classifies as
    # docs-only up front, with `docs_authoring` still unioned in as a foreign
    # subsystem match (#4336) since its targets are not a subset of
    # `DOCS_TARGETS` -- a strict superset of the previous coverage, not a
    # narrowing.
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
    assert selection.subsystems == ("docs", "docs_authoring")
    assert "tests/governance" in selection.targets
    assert "tests/scripts" in selection.targets
    assert "tests/ops/test_ci_workflow.py" in selection.targets
    assert "tests/architecture" in selection.targets
    assert "tests/ops/test_review_before_ci_gate.py" in selection.targets
    assert "tests/docs" in selection.targets
