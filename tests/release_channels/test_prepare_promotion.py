"""Tests for prepare-promotion plan generation.

Covers Issue #612: implement prepare-promotion plan generation.
All tests are non-pg and require no live infrastructure.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.release_channels.prepare_promotion import (
    MissingRefError,
    PromotionPlan,
    generate_plan,
)

REQUIRED_SECTIONS = [
    "promotion_target",
    "code_delta",
    "migration_delta",
    "config_delta",
    "risk_notes",
    "rollback_path",
    "operator_acknowledgments",
]


def test_plan_artifact_has_required_sections(tmp_path: Path) -> None:
    """AC1: generate_plan returns a plan with all seven required sections."""
    plan = generate_plan(
        stable_ref="abc1234",
        target_ref="def5678",
        output_dir=tmp_path,
    )

    assert isinstance(plan, PromotionPlan)
    for section in REQUIRED_SECTIONS:
        assert hasattr(plan, section), f"PromotionPlan missing section: {section}"

    assert plan.promotion_target["stable_ref"] == "abc1234"
    assert plan.promotion_target["target_ref"] == "def5678"


def test_plan_artifact_is_deterministic(tmp_path: Path) -> None:
    """Same inputs produce identical plan shape (deterministic fields)."""
    plan_a = generate_plan(stable_ref="abc1234", target_ref="def5678", output_dir=tmp_path)
    plan_b = generate_plan(stable_ref="abc1234", target_ref="def5678", output_dir=tmp_path)

    assert plan_a.promotion_target == plan_b.promotion_target
    assert plan_a.rollback_path == plan_b.rollback_path


def test_plan_generation_fails_on_missing_preconditions(tmp_path: Path) -> None:
    """AC2: generate_plan raises MissingRefError when stable_ref or target_ref is empty."""
    with pytest.raises(MissingRefError, match="stable_ref"):
        generate_plan(stable_ref="", target_ref="def5678", output_dir=tmp_path)

    with pytest.raises(MissingRefError, match="target_ref"):
        generate_plan(stable_ref="abc1234", target_ref="", output_dir=tmp_path)


def test_plan_receipt_written_to_ops_promotions(tmp_path: Path) -> None:
    """AC3: plan artifact is written to output_dir/YYYY-MM-DD-<short-sha>.md and path returned."""
    plan = generate_plan(
        stable_ref="abc1234",
        target_ref="def5678",
        output_dir=tmp_path,
    )

    assert plan.artifact_path is not None
    path = Path(plan.artifact_path)
    assert path.exists(), f"Plan artifact not written: {path}"
    assert path.suffix == ".md"
    # filename matches YYYY-MM-DD-<short-sha> pattern
    assert re.match(r"\d{4}-\d{2}-\d{2}-[a-f0-9]+\.md", path.name), (
        f"Unexpected artifact filename: {path.name}"
    )

    content = path.read_text()
    for section in ("Promotion target", "Code delta", "Migration delta", "Config", "Risk notes", "Rollback path", "Operator acknowledgments"):
        assert section in content, f"Plan markdown missing section: {section}"
