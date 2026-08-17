from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]


def test_classifier_allows_only_exact_shipped_pattern_and_token_reuse() -> None:
    skill = _read(".codex/skills/yggdrasil-design-handoff/SKILL.md")
    classifier = _section(
        skill,
        "### Design-work classifier",
        "### Constrained reuse gate",
    )
    normalized = " ".join(classifier.split()).lower()

    for scope_class in ("exact_shipped_reuse", "novel", "mixed", "unknown"):
        assert f"`{scope_class}`" in classifier

    assert "Only `exact_shipped_reuse` may enter the constrained-reuse route" in classifier
    assert "every visual and interaction decision" in normalized
    assert "exact shipped source component or pattern" in normalized
    assert "exact accepted token declaration" in normalized


def test_novel_mixed_and_unknown_scope_remain_live_gate_blocked() -> None:
    skill = _read(".codex/skills/yggdrasil-design-handoff/SKILL.md")
    classifier = _section(
        skill,
        "### Design-work classifier",
        "### Constrained reuse gate",
    )
    live_gate = _section(
        skill,
        "### Live design-system gate",
        "## Workflow",
    )

    for scope_class in ("novel", "mixed", "unknown"):
        assert f"| `{scope_class}` | `live_handoff_required` |" in classifier
    assert "A proposed extension is `novel`" in classifier
    assert "MCP unavailability does not reclassify" in classifier
    assert "No successful gate means no design generation" in live_gate


def test_reuse_receipt_requires_complete_content_addressed_provenance() -> None:
    governance = _read("companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md")
    schema = _section(
        governance,
        "### `yggdrasil-constrained-reuse.v1` receipt",
        "### Constrained-reuse validation and refusal rules",
    )
    normalized = " ".join(schema.split())

    for required_field in (
        "contract_version: yggdrasil-constrained-reuse.v1",
        "payload_sha256: sha256:<64 lowercase hex>",
        "receipt_sha256:",
        "repository_commit:",
        "author_identity:",
        "sources:",
        "source_path:",
        "stable_ref:",
        "content_sha256:",
        "tokens:",
        "declaration:",
        "declaration_sha256:",
        "allowed_transformations:",
        "zero_novel_visual_language:",
        "no_egress:",
        "cross_origin_request_count: 0",
        "source_declaration_sha256:",
        "normalized_declaration_sha256:",
        "network_evidence_ref:",
        "state_matrix:",
        "accessibility_matrix:",
        "evidence_ref:",
        "independent_review:",
        "reviewed_payload_sha256:",
        "independent_from_author: true",
        "verdict: pass",
    ):
        assert required_field in schema

    assert "RFC 8785 JSON Canonicalization Scheme" in normalized
    assert "object keys are lexicographically sorted" in normalized
    assert "arrays preserved in declared order" in normalized
    assert "hashes exactly `provenance_payload`" in normalized
    assert "hashes exactly the object containing `payload_sha256` and `independent_review`" in normalized


def test_reuse_receipt_cannot_impersonate_live_handoff_receipt() -> None:
    skill = _read(".codex/skills/yggdrasil-design-handoff/SKILL.md")
    governance = _read("companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md")

    for surface in (skill, governance):
        normalized = " ".join(surface.split()).lower()
        assert (
            "`yggdrasil-constrained-reuse.v1` is not "
            "`yggdrasil-design-handoff.v1`"
        ) in normalized
        assert "a copied token sheet" in normalized
        assert "cannot satisfy a live handoff receipt" in normalized

    for non_claim in (
        "live_design_system_selection: not_claimed",
        "live_mcp_system_id: not_claimed",
        "live_project: not_claimed",
        "live_token_parity: not_claimed",
    ):
        assert non_claim in governance


def test_devui_plan_binds_reuse_exit_to_stable_fixtures_and_novel_delta_gate() -> None:
    devui = _read("docs/DEVUI.md")
    stage = _read("docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md")
    task = _read(
        "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/VALIDATE_OVERVIEW_YGGDRASIL_DESIGN.md"
    )
    parent = _read("docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/PARENT_FEATURE_ISSUE.md")
    index = _read("docs/DOCS_INDEX.md")
    joined = " ".join(
        (devui + "\n" + stage + "\n" + task + "\n" + parent + "\n" + index).split()
    )
    joined_lower = joined.lower()

    assert "#4834" in joined
    assert "#4768" in joined
    assert "yggdrasil-constrained-reuse.v1" in joined
    assert "independent review" in joined
    assert "#4746 remains blocked" in joined
    assert "does not accept #4746" in joined
    assert "novel, mixed, or unknown" in joined
    assert "live Yggdrasil design-system gate" in joined
    assert "#4834 is delivered" not in joined
    assert "either `yggdrasil-constrained-reuse.v1` or `yggdrasil-design-handoff.v1`" in joined
    assert "exact shipped reuse does not run or claim the live system/token preflight" in joined_lower
    assert "#4834 plus delivered #4768" in joined
