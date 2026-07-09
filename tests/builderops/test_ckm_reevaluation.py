from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.ckm_reevaluation import (
    CkmReevaluationError,
    build_ckm_reevaluation_report,
)


def _ref(ref: str = "docs/CAPABILITY_KNOWLEDGE_MODEL/README.md::INV-CKM-2") -> dict[str, str]:
    return {"ref_type": "ckm_projection", "ref": ref}


def _projection(
    projection_id: str,
    projection_type: str,
    watermark: str = "ckm-watermark:2026-07-09T20:00:00Z",
) -> dict[str, object]:
    return {
        "id": projection_id,
        "projection_type": projection_type,
        "summary": f"{projection_type} finding",
        "watermark": watermark,
        "source_refs": [_ref(f"ckm://projection/{projection_id}")],
    }


def _action(action_id: str, route: str, projection_id: str) -> dict[str, object]:
    projection_ref = f"ckm://projection/{projection_id}"
    return {
        "id": action_id,
        "route": route,
        "summary": f"{route} action",
        "source_projection_id": projection_id,
        "source_projection_ref": projection_ref,
        "watermark": "ckm-watermark:2026-07-09T20:00:00Z",
        "source_refs": [_ref(projection_ref), {"ref_type": "github_issue", "ref": "#3138"}],
        "recommendation": "Route through normal governance gates.",
    }


def _payload() -> dict[str, object]:
    return {
        "projections": [
            _projection("proj-maturity", "capability_maturity"),
            _projection("proj-gap", "gap_tension"),
            _projection("proj-stale", "stale_assessment"),
            _projection("proj-missing", "missing_evidence"),
        ],
        "actions": [
            _action("act-issue", "issue_candidate", "proj-gap"),
            _action("act-debt", "debt_fitness_candidate", "proj-missing"),
            _action("act-promotion", "promotion_proposal", "proj-maturity"),
            _action("act-discard", "discard_supersession", "proj-stale"),
        ],
    }


def test_ckm_reevaluation_marks_projection_only_and_preserves_watermark() -> None:
    report = build_ckm_reevaluation_report(_payload())

    assert report["authority"] == {
        "projection_only": True,
        "product_runtime_authority": False,
        "requires_normal_issue_pr_promotion_gate": True,
        "ckm_parent": "#3138",
    }
    assert report["projection"][0]["watermark"] == "ckm-watermark:2026-07-09T20:00:00Z"
    assert report["candidate"][0]["source_projection_ref"] == "ckm://projection/proj-gap"
    assert report["mutations_performed"] is False


def test_ckm_reevaluation_covers_four_action_classifications() -> None:
    report = build_ckm_reevaluation_report(_payload())

    assert {item["route"] for item in report["candidate"]} == {
        "issue_candidate",
        "debt_fitness_candidate",
        "promotion_proposal",
        "discard_supersession",
    }
    assert "act-promotion=promotion_proposal" in report["receipt_body"]


def test_ckm_reevaluation_rejects_missing_projection_provenance() -> None:
    payload = _payload()
    payload["actions"] = [
        {
            "id": "act-bad",
            "route": "issue_candidate",
            "summary": "Missing projection ref in source refs",
            "source_projection_id": "proj-gap",
            "source_projection_ref": "ckm://projection/proj-gap",
            "watermark": "ckm-watermark:2026-07-09T20:00:00Z",
            "source_refs": [{"ref_type": "github_issue", "ref": "#3138"}],
            "recommendation": "Reject this action.",
        }
    ]

    with pytest.raises(CkmReevaluationError, match="source_projection_ref"):
        build_ckm_reevaluation_report(payload)


def test_ckm_reevaluation_rejects_unknown_projection() -> None:
    payload = _payload()
    payload["actions"] = [_action("act-bad", "issue_candidate", "missing")]

    with pytest.raises(CkmReevaluationError, match="unknown projection"):
        build_ckm_reevaluation_report(payload)


def test_ckm_reevaluation_rejects_cross_wired_projection_ref() -> None:
    payload = _payload()
    bad_action = _action("act-bad", "issue_candidate", "proj-gap")
    bad_action["source_projection_ref"] = "ckm://projection/proj-maturity"
    bad_action["source_refs"] = [
        {"ref_type": "ckm_projection", "ref": "ckm://projection/proj-maturity"}
    ]
    payload["actions"] = [bad_action]

    with pytest.raises(CkmReevaluationError, match="source projection"):
        build_ckm_reevaluation_report(payload)


def test_ckm_reevaluation_rejects_mismatched_watermark() -> None:
    payload = _payload()
    bad_action = _action("act-bad", "issue_candidate", "proj-gap")
    bad_action["watermark"] = "ckm-watermark:stale"
    payload["actions"] = [bad_action]

    with pytest.raises(CkmReevaluationError, match="watermark"):
        build_ckm_reevaluation_report(payload)


def test_ckm_reevaluation_cli_is_observe_only(tmp_path: Path) -> None:
    projection_file = tmp_path / "ckm.json"
    projection_file.write_text(json.dumps(_payload()), encoding="utf-8")

    result = CliRunner().invoke(
        builderops_standalone_root,
        [
            "builderops",
            "ckm-reevaluation",
            "classify",
            "--projection-file",
            str(projection_file),
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["observe_only"] is True
    assert payload["mutation_channels"] == {
        "git_push": False,
        "github_label": False,
        "github_merge": False,
        "github_project": False,
        "product_runtime": False,
        "owner_doc_writeback": False,
        "runtime_memory": False,
    }
    assert payload["authority"]["ckm_parent"] == "#3138"
