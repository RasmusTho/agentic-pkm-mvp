from __future__ import annotations

import json
import hashlib
import subprocess

import pytest

from app.builderops.devui_focus_inputs import FocusInputError, read_focus_inputs


REPOSITORY = "RasmusTho/agentic-pkm-mvp"
SUBJECT = f"github:{REPOSITORY}#5527"
ISSUE_URL = "https://github.com/RasmusTho/agentic-pkm-mvp/issues/5527"
UPDATED_AT = "2026-09-14T00:00:00Z"


def _issue(body: str, *, updated_at: str = UPDATED_AT) -> dict[str, object]:
    return {
        "number": 5527,
        "title": "Bounded source projection",
        "html_url": ISSUE_URL,
        "updated_at": updated_at,
        "body": body,
    }


def _read(body: str, *, updated_at: str = UPDATED_AT) -> dict[str, object]:
    issue = _issue(body, updated_at=updated_at)
    return read_focus_inputs(
        SUBJECT,
        repository=REPOSITORY,
        issue_reader=lambda _repository, _number: issue,
    )


def test_issue_inputs_project_explicit_intent_and_criteria_with_source_revision() -> None:
    body = """## Context

Owner needs the selected source text.

## Scope

Project only the bounded declarations.

## Acceptance Criteria

- [ ] Preserve the criterion wording across reads.
  - Verify: `tests/example.py::test_source_projection`

## Source Anchors

- `docs/DEVUI.md :: Intent and evidence continuity`

## Source Docs

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
"""
    result = _read(body)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()

    reference = result["subject"]["authority_ref"]  # type: ignore[index]
    assert reference["source_id"] == f"{REPOSITORY}#5527"
    assert reference["version"] == UPDATED_AT
    assert reference["content_hash"] == digest
    assert "Owner needs the selected source text." in result["owner_intent"]["summary"]  # type: ignore[index]
    criteria = [
        item
        for item in result["evidence"]  # type: ignore[index]
        if "Acceptance Criteria" in item.get("claim", "")  # type: ignore[union-attr]
    ]
    assert len(criteria) == 1
    assert "Verify: `tests/example.py::test_source_projection`" in criteria[0]["claim"]
    assert criteria[0]["source_ref"]["content_hash"] == digest
    assert criteria[0]["claim_id"].startswith("issue-declaration:acceptance-criteria:r1-")

    changed = _read(body.replace("criterion wording", "changed criterion wording"))
    old_ids = {
        item["claim_id"]
        for item in result["evidence"]  # type: ignore[index]
        if item["claim_id"] != "subject-read"
    }
    new_ids = {
        item["claim_id"]
        for item in changed["evidence"]  # type: ignore[index]
        if item["claim_id"] != "subject-read"
    }
    assert old_ids.isdisjoint(new_ids)


def test_issue_declarations_do_not_infer_requirement_coverage_or_document_read() -> None:
    result = _read(
        """## Acceptance Criteria

- [x] A checked box is still a declaration.
  - Verify: `tests/example.py::test_declared_only`

## Source Anchors

- `docs/DEVUI.md :: Understand a capability`

## Source Docs

- `docs/DEVUI.md`
"""
    )

    declarations = [
        item for item in result["governing_sources"] + result["evidence"]  # type: ignore[operator]
        if item["claim_id"].startswith("issue-declaration:")
    ]
    assert declarations
    assert all(item["coverage"] == "partial" for item in declarations)
    assert all(item["cardinality"] == "not_countable" for item in declarations)
    assert all(item["limitation"] for item in declarations)
    assert any("Verify:" in item["claim"] for item in result["evidence"])  # type: ignore[index]
    assert any(item["kind"] == "criterion_results_unassessed" for item in result["limitations"])  # type: ignore[index]
    assert not any(
        word in item["claim"].casefold()
        for item in declarations
        for word in ("passed", "accepted", "covered")
    )


def test_issue_section_boundaries_preserve_partial_and_unread_states() -> None:
    body = """## Context

Readable context survives hostile sections.

## Acceptance Criteria

```markdown
## Acceptance Criteria
- [ ] This fenced example must not become a claim.
```

## Source Anchors

- `docs/DEVUI.md :: Intent and evidence continuity`

## Source Docs

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`

## Source Docs

- `docs/other.md`

## Scope

"""
    result = _read(body)

    assert "Readable context survives hostile sections." in result["owner_intent"]["summary"]  # type: ignore[index]
    assert not any(
        "fenced example must not become a claim" in item.get("claim", "").casefold()
        for item in result["evidence"] + result["governing_sources"]  # type: ignore[index]
    )
    kinds = {item["kind"] for item in result["limitations"]}  # type: ignore[index]
    assert "issue_section_ambiguous" in kinds
    assert "issue_section_unread" in kinds
    assert "fenced_example_ignored" in kinds
    assert all(
        item.get("cardinality") != "measured_empty"
        for group in (result["evidence"], result["governing_sources"])  # type: ignore[index]
        for item in group
    )

    oversized = _read("## Context\n\n" + ("x" * 20_000) + "\n\n## Source Docs\n\n- `docs/DEVUI.md`\n")
    assert "docs/DEVUI.md" in " ".join(
        item["claim"] for item in oversized["governing_sources"]  # type: ignore[index]
    )
    assert any(item["kind"] == "issue_section_partial" for item in oversized["limitations"])  # type: ignore[index]


def test_issue_parser_keeps_nested_headings_and_discards_overflow_continuations() -> None:
    criteria = "\n".join(
        [
            "## Context",
            "",
            "### Assumptions",
            "Nested heading text remains source content.",
            "",
            "## Acceptance Criteria",
            *[f"- [ ] Criterion {index}" for index in range(40)],
            "  - Verify: this continuation belongs to the omitted 41st item",
            "",
            "## Source Docs",
            "",
            "```markdown extra",
            "- `docs/fenced.md`",
            "```still-fenced",
            "- `docs/still-fenced.md`",
            "```",
            "- `docs/DEVUI.md`",
        ]
    )
    result = _read(criteria)

    assert "### Assumptions" in result["owner_intent"]["summary"]  # type: ignore[index]
    evidence_claims = [
        item["claim"] for item in result["evidence"] if isinstance(item.get("claim"), str)  # type: ignore[index]
    ]
    assert not any("omitted 41st item" in claim for claim in evidence_claims)
    assert any("Criterion 38" in claim for claim in evidence_claims)
    assert not any(
        "omitted 41st item" in item["claim"]
        for item in result["evidence"]  # type: ignore[index]
    )
    source_claims = [
        item["claim"]
        for item in result["governing_sources"]  # type: ignore[index]
        if isinstance(item.get("claim"), str)
    ]
    assert any("docs/DEVUI.md" in claim for claim in source_claims)
    assert not any("fenced.md" in claim or "still-fenced.md" in claim for claim in source_claims)
    assert any(item["kind"] == "issue_declarations_truncated" for item in result["limitations"])  # type: ignore[index]


def test_focus_inputs_require_exact_configured_repository_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "title": "Source-authorized Issue",
                    "html_url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4835",
                    "updated_at": "2026-08-13T12:00:00Z",
                }
            ),
            stderr="",
        )

    monkeypatch.setenv("COCKPIT_GITHUB_REPO", "RasmusTho/agentic-pkm-mvp")
    monkeypatch.setattr("app.builderops.devui_focus_inputs.subprocess.run", fake_run)

    result = read_focus_inputs("github:RasmusTho/agentic-pkm-mvp#4835")
    assert result["subject"]["stable_id"] == "github:RasmusTho/agentic-pkm-mvp#4835"
    assert calls == [["gh", "api", "repos/RasmusTho/agentic-pkm-mvp/issues/4835"]]

    calls.clear()
    with pytest.raises(FocusInputError, match="repository is not configured"):
        read_focus_inputs("github:someone-else/agentic-pkm-mvp#4835")
    assert calls == [], "a repository mismatch must refuse before any GitHub read"
