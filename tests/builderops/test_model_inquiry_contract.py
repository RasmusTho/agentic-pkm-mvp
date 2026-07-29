"""Regression boundary: design runs share hashing, never inquiry semantics."""

from __future__ import annotations

import inspect

import app.builderops.design_run_contract as design_run_contract
from app.builderops.design_run_contract import CuratedDesignBrief, DesignSourceRef, parse_design_run_contract
from app.builderops.model_inquiry_contract import ModelTurnResponse


def test_design_contract_reuses_hashing_without_inheriting_inquiry_roles() -> None:
    source = inspect.getsource(design_run_contract)
    assert "model_inquiry" not in source

    inquiry_response = ModelTurnResponse(
        schema_version="builderops.model-turn-response.v1",
        stance="draft",
        content="Keep inquiry semantics isolated.",
        claims=[], risks=[], blocking_questions=[], reviewed_artifact_refs=[], accepted_artifact_hash=None,
    )
    assert inquiry_response.schema_version == "builderops.model-turn-response.v1"

    brief = CuratedDesignBrief(
        brief_id="brief.design.one", projection_id="ckm.projection.one",
        requested_deliverable="interaction_specification",
        source_refs=(DesignSourceRef(source_type="ckm_observation", source_id="ckm:observation:one", content_hash="a" * 64),),
        attachment_refs=(), constraints=("Use bounded context.",),
        non_visual_exemption=True,
    )
    assert isinstance(parse_design_run_contract(brief.canonical_json()), CuratedDesignBrief)
