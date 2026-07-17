"""Pure routing rules for the docs-guard temporal-owner check."""

from __future__ import annotations

TEMPORAL_DOCS = frozenset(
    {
        "docs/STATUS.md",
        "docs/ROADMAP.md",
        "docs/ARCHITECTURE.md",
        "docs/OPERATIONS.md",
        "docs/HUMAN-FLOWS.md",
        "docs/AGENT-FLOWS.md",
    }
)
TEMPORAL_CODE_PREFIXES = ("app/", "scripts/", "config/", "docs/settings/")
# Maps each governance-only enforcement script to its docs/development/ owner
# doc. None means no doc has been assigned yet for that script: it falls back
# to accepting any docs/development/ touch (the pre-existing, looser
# behavior) instead of a false claim of a specific pairing that doesn't exist.
GOVERNANCE_TEMPORAL_ENFORCEMENT: dict[str, str | None] = {
    "scripts/docs_guard.py": None,
    "scripts/docs_guard_logic.py": None,
    "scripts/git_hygiene.py": None,
    "scripts/select_pr_tests.py": "docs/development/TEST_STRATEGY_HOT_PATH.md",
}


def requires_temporal_owner_doc(changed: list[str]) -> bool:
    """Return true unless a changed temporal surface has an owner-doc writeback.

    A governance-only change to one of these enforcement scripts may use its
    `docs/development/` contract as the owner writeback. Presence of governance
    files is insufficient: every changed temporal surface must be one of those
    scripts, so a mixed runtime/config PR cannot inherit the exception. A
    script with an explicit paired doc in GOVERNANCE_TEMPORAL_ENFORCEMENT
    requires that exact doc; a script mapped to None accepts any
    docs/development/ touch until its own contract doc is assigned.
    """

    temporal_paths = [
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in TEMPORAL_CODE_PREFIXES)
    ]
    if not temporal_paths or any(path in TEMPORAL_DOCS for path in changed):
        return False

    governance_only = all(
        path in GOVERNANCE_TEMPORAL_ENFORCEMENT for path in temporal_paths
    )
    if not governance_only:
        return True

    changed_set = set(changed)
    any_development_doc_touched = any(
        path.startswith("docs/development/") for path in changed
    )

    def owner_doc_satisfied(path: str) -> bool:
        owner_doc = GOVERNANCE_TEMPORAL_ENFORCEMENT[path]
        if owner_doc is None:
            return any_development_doc_touched
        return owner_doc in changed_set

    owner_docs_satisfied = all(owner_doc_satisfied(path) for path in temporal_paths)
    return not owner_docs_satisfied
