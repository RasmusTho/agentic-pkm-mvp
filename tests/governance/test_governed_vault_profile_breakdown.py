from pathlib import Path

import yaml


CAPABILITY = Path("docs/GOVERNED_VAULT_PROFILE")
TASKS = (
    "DEFINE_PROFILE_AUTHORITY_AND_PERSISTENCE.md",
    "GOVERN_PROFILE_UPDATE_PROPOSALS_AND_CONFIRMED_WRITES.md",
    "PROJECT_APPROVED_PROFILE_TO_SAME_SCOPE_CONSUMERS.md",
)


def _document(name: str) -> str:
    return (CAPABILITY / name).read_text(encoding="utf-8")


def _metadata(name: str) -> dict[str, object]:
    return yaml.safe_load(_document(name).split("---", 2)[1])


def test_profile_breakdown_defines_authority_and_partial_failure_invariants() -> None:
    readme = _document("README.md")
    youtube_readme = Path("docs/YOUTUBE_SOURCE_NOTE_V2/README.md").read_text(encoding="utf-8")
    docs_index = Path("docs/DOCS_INDEX.md").read_text(encoding="utf-8")

    for required_text in (
        "ProfileAgent is the only system agent permitted to write",
        "ProfileUpdateCandidate",
        "visible unchecked proposal",
        "owner confirmation",
        "terminal receipt",
        "Direct owner correction has precedence",
        "same-scope projection",
        "Partial failures stay visible and retry-safe",
        "Restart recovers only durable, receipt-linked state",
    ):
        assert required_text in readme
    assert "../GOVERNED_VAULT_PROFILE/README.md" in youtube_readme
    assert "docs/GOVERNED_VAULT_PROFILE/README.md" in docs_index


def test_profile_tasks_are_bounded_dependency_ordered_and_verifiable() -> None:
    metadata = {name: _metadata(name) for name in TASKS}

    assert metadata[TASKS[0]]["prerequisites"] == []
    assert metadata[TASKS[1]]["prerequisites"] == ["GOVPROF-01"]
    assert metadata[TASKS[2]]["prerequisites"] == ["GOVPROF-02"]
    for name in TASKS:
        text = _document(name)
        assert "## Acceptance Criteria" in text
        assert "Verify: `tests/governance/" in text
        assert "## How to Verify (Pre-Merge)" in text
        assert "## Out of Scope" in text


def test_profile_task_frontmatter_records_filed_issue_joins() -> None:
    for name in TASKS:
        metadata = _metadata(name)
        assert isinstance(metadata["github_issue"], int)
        assert metadata["github_issue"] > 0
        assert metadata["parent_capability"] == "Governed Vault Profile"
        assert metadata["source_anchor"]


def test_profile_breakdown_makes_no_shipped_runtime_claim() -> None:
    readme = _document("README.md")

    assert "defines no shipped ProfileAgent" in readme
    assert "makes no runtime delivery claim" in readme
    assert "target-state contract" in readme
