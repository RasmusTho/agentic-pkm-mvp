from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


ALWAYS_TARGETS = (
    "tests/ci",
    "tests/governance/test_branch_guardrail_packet.py",
    "tests/ops/test_ci_workflow.py",
    "tests/scripts/test_select_pr_tests.py",
)

FULL_SUITE_REASONS = (
    "shared CI/test/runtime configuration changed",
    "database migration or schema surface changed",
    "no subsystem mapping matched",
)

FULL_SUITE_EXACT = {
    "conftest.py",
    "pytest.ini",
    "pyproject.toml",
    "requirements.txt",
    "dev-requirements.txt",
    "docker-compose.test.yml",
    ".github/workflows/ci.yml",
    "scripts/select_pr_tests.py",
}

FULL_SUITE_PREFIXES = (
    ".github/workflows/",
    "alembic/",
    "tests/conftest.py",
    "app/db/",
    "app/testing/",
)

DOCS_TARGETS = (
    "tests/docs",
    "tests/architecture",
    "tests/governance",
)

GOVERNANCE_TARGETS = (
    "tests/governance",
    "tests/scripts",
    "tests/ops/test_ci_workflow.py",
)

E2E_TARGETS = {
    "companion_ui": (
        "tests/e2e/test_panel_to_promotion_consume.py",
        "tests/e2e/test_panel_watcher_e2e.py",
    ),
    "watcher_sync": (
        "tests/e2e/test_runtime_loop_vault_test.py",
        "tests/e2e/test_watcher_registry_e2e.py",
        "tests/e2e/test_panel_watcher_e2e.py",
    ),
    "orchestration": (
        "tests/e2e/test_pipe_graph.py",
        "tests/e2e/test_runtime_contract_regressions.py",
    ),
    "memory_retrieval": (
        "tests/e2e/test_index_rules_e2e.py",
        "tests/e2e/test_promotion_intent_to_index.py",
        "tests/e2e/test_reality_mvp_pipeline.py",
    ),
    "llm_eval": (
        "tests/e2e/test_llm_routing_e2e.py",
        "tests/e2e/test_panel_llm_e2e.py",
    ),
    "promotion_panel": (
        "tests/e2e/test_panel_to_promotion_consume.py",
        "tests/e2e/test_panel_watcher_e2e.py",
        "tests/e2e/test_promotion_intent_to_index.py",
        "tests/e2e/test_panel_llm_e2e.py",
    ),
    "ops_deploy": (
        "tests/e2e/test_operator_workflows.py",
        "tests/e2e/test_human_need_uat.py",
    ),
}

E2E_OWNER_BY_FILE = {
    target: subsystem for subsystem, targets in E2E_TARGETS.items() for target in targets
}

SUBSYSTEMS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "settings",
        ("app/settings/", "docs/settings/", "tests/settings/", "tests/config/"),
        ("tests/settings", "tests/config"),
    ),
    (
        "vault",
        ("app/vault/", "tests/vault/", "tests/knowledge/", "docs/VAULT", "docs/builderops/BUILDEROPS_VAULT"),
        ("tests/vault", "tests/knowledge", "tests/ports"),
    ),
    (
        "companion_ui",
        ("companion-ui/", "app/api/", "tests/companion_ui/", "tests/api/"),
        ("tests/companion_ui", "tests/api", *E2E_TARGETS["companion_ui"]),
    ),
    (
        "watcher_sync",
        (
            "app/watcher/",
            "app/sync/",
            "scripts/run_live_watcher.sh",
            "tests/watcher/",
            "tests/sync/",
            "tests/e2e/test_runtime_loop_vault_test.py",
            "tests/e2e/test_watcher_registry_e2e.py",
            "tests/e2e/test_panel_watcher_e2e.py",
        ),
        ("tests/watcher", "tests/sync", *E2E_TARGETS["watcher_sync"]),
    ),
    (
        "orchestration",
        (
            "app/orchestrator/",
            "app/orchestration/",
            "tests/orchestrator/",
            "tests/orchestration/",
            "tests/e2e/test_pipe_graph.py",
            "tests/e2e/test_runtime_contract_regressions.py",
        ),
        ("tests/orchestrator", "tests/orchestration", *E2E_TARGETS["orchestration"]),
    ),
    (
        "memory_retrieval",
        (
            "app/memory/",
            "app/retrieval/",
            "app/index/",
            "tests/agent_memory/",
            "tests/retrieval/",
            "tests/indexer/",
            "tests/e2e/test_index_rules_e2e.py",
            "tests/e2e/test_promotion_intent_to_index.py",
            "tests/e2e/test_reality_mvp_pipeline.py",
        ),
        ("tests/agent_memory", "tests/retrieval", "tests/indexer", "tests/search", *E2E_TARGETS["memory_retrieval"]),
    ),
    (
        "llm_eval",
        (
            "app/llm/",
            "app/eval/",
            "docs/eval/",
            "tests/llm/",
            "tests/eval/",
            "tests/evals/",
            "tests/e2e/test_llm_routing_e2e.py",
            "tests/e2e/test_panel_llm_e2e.py",
        ),
        ("tests/llm", "tests/eval", "tests/evals", *E2E_TARGETS["llm_eval"]),
    ),
    (
        "events_receipts",
        ("app/events/", "app/receipts/", "docs/contracts/events/", "tests/events/", "tests/receipts/"),
        ("tests/events", "tests/receipts", "tests/contracts"),
    ),
    (
        "promotion_panel",
        (
            "app/promotion/",
            "app/panel/",
            "tests/promotion/",
            "tests/panel/",
            "tests/e2e/test_panel_to_promotion_consume.py",
            "tests/e2e/test_panel_watcher_e2e.py",
            "tests/e2e/test_promotion_intent_to_index.py",
            "tests/e2e/test_panel_llm_e2e.py",
        ),
        ("tests/promotion", "tests/panel", *E2E_TARGETS["promotion_panel"]),
    ),
    (
        "ops_deploy",
        ("scripts/", "ops/", "tests/ops/", "tests/scripts/", "tests/deploy/"),
        ("tests/ops", "tests/scripts", "tests/deploy"),
    ),
)


@dataclass(frozen=True)
class Selection:
    full_suite: bool
    subsystems: tuple[str, ...]
    targets: tuple[str, ...]
    reason: str

    @property
    def pytest_args(self) -> str:
        if self.full_suite:
            return '-q -m "not pg"'
        return " ".join(("-q", '-m "not pg"', *self.targets))


def _normalize(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _dedupe(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def _is_full_suite_file(path: str) -> bool:
    return path in FULL_SUITE_EXACT or any(path.startswith(prefix) for prefix in FULL_SUITE_PREFIXES)


def _is_docs_only(paths: tuple[str, ...]) -> bool:
    # Changed tests/** files never disqualify a docs-only PR: they are scope
    # signal from the PR's non-test files, appended separately (see
    # _changed_test_targets) rather than folded into this classification.
    non_test = tuple(path for path in paths if not path.startswith("tests/"))
    return bool(non_test) and all(
        path.startswith("docs/") or path in {"README.md", "AGENTS.md"} for path in non_test
    )


def _is_governance_only(paths: tuple[str, ...]) -> bool:
    governance_prefixes = (".github/", "docs/development/", "AGENTS.md", ".codex/")
    non_test = tuple(path for path in paths if not path.startswith("tests/"))
    return bool(non_test) and all(path.startswith(governance_prefixes) for path in non_test)


def _changed_test_targets(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(path for path in paths if path.startswith("tests/"))


def select_tests(changed_files: list[str]) -> Selection:
    paths = tuple(path for path in (_normalize(item) for item in changed_files) if path)
    if not paths:
        return Selection(True, (), (), "no changed files were provided")

    if any(_is_full_suite_file(path) for path in paths):
        return Selection(True, (), (), FULL_SUITE_REASONS[0])

    if any(path.startswith("tests/e2e/") and path not in E2E_OWNER_BY_FILE for path in paths):
        return Selection(True, (), (), "unowned e2e test changed")

    if any(path.startswith("alembic/") or path.startswith("tests/migrations/") for path in paths):
        return Selection(True, (), (), FULL_SUITE_REASONS[1])

    changed_tests = _changed_test_targets(paths)
    targets = list(ALWAYS_TARGETS)
    subsystems: list[str] = []

    if _is_docs_only(paths):
        return Selection(
            False, ("docs",), _dedupe([*targets, *DOCS_TARGETS, *changed_tests]), "docs-only PR"
        )

    if _is_governance_only(paths):
        return Selection(
            False,
            ("governance",),
            _dedupe([*targets, *GOVERNANCE_TARGETS, *changed_tests]),
            "governance-only PR",
        )

    for name, prefixes, subsystem_targets in SUBSYSTEMS:
        if any(path.startswith(prefix) for path in paths for prefix in prefixes):
            subsystems.append(name)
            targets.extend(subsystem_targets)

    if not subsystems:
        return Selection(True, (), (), FULL_SUITE_REASONS[2])

    return Selection(False, _dedupe(subsystems), _dedupe([*targets, *changed_tests]), "matched subsystem SoI")


def changed_files_from_git(base_ref: str, head_ref: str) -> list[str]:
    # --diff-filter=d excludes deleted paths: only files that still exist at
    # head are candidates for the changed-tests-always-selected invariant.
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=d", f"{base_ref}...{head_ref}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _write_github_output(path: str, selection: Selection) -> None:
    output = Path(path)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(f"full_suite={'true' if selection.full_suite else 'false'}\n")
        handle.write(f"subsystems={','.join(selection.subsystems) or 'all'}\n")
        handle.write(f"pytest_args={selection.pytest_args}\n")
        handle.write(f"reason={selection.reason}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Select PR pytest targets from changed subsystem files.")
    parser.add_argument("--changed-file", action="append", default=[], help="Changed file path. Repeatable.")
    parser.add_argument("--base-ref", default="", help="Base git ref for diff selection.")
    parser.add_argument("--head-ref", default="HEAD", help="Head git ref for diff selection.")
    parser.add_argument("--github-output", default="", help="Optional GITHUB_OUTPUT path.")
    args = parser.parse_args()

    changed = args.changed_file
    if not changed and args.base_ref:
        changed = changed_files_from_git(args.base_ref, args.head_ref)

    selection = select_tests(changed)
    print(f"full_suite={'true' if selection.full_suite else 'false'}")
    print(f"subsystems={','.join(selection.subsystems) or 'all'}")
    print(f"pytest_args={selection.pytest_args}")
    print(f"reason={selection.reason}")

    if args.github_output:
        _write_github_output(args.github_output, selection)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
