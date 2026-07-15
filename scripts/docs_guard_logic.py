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
GOVERNANCE_TEMPORAL_ENFORCEMENT = frozenset(
    {
        "scripts/docs_guard.py",
        "scripts/docs_guard_logic.py",
        "scripts/git_hygiene.py",
    }
)


def requires_temporal_owner_doc(changed: list[str]) -> bool:
    """Return true unless a changed temporal surface has an owner-doc writeback.

    A governance-only change to one of the two enforcement scripts may use its
    `docs/development/` contract as the owner writeback. Presence of governance
    files is insufficient: every changed temporal surface must be one of those
    scripts, so a mixed runtime/config PR cannot inherit the exception.
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
    governance_owner_doc_touched = any(
        path.startswith("docs/development/") for path in changed
    )
    return not (governance_only and governance_owner_doc_touched)
