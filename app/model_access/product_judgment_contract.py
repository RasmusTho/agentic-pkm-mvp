"""Product's closed canvas judgment contract; no provider or credential controls."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from llm_contract import SystemOneJudgmentRequest, SystemOneJudgmentResponse

from app.model_access.remote_contract import JudgmentOutcome, JudgmentUsage


PRODUCT_JUDGMENT_REQUEST_BYTES = 4096
PRODUCT_JUDGMENT_RESPONSE_BYTES = 16384
PRODUCT_JUDGMENT_PROFILE: Literal["product.canvas_intent.v1"] = "product.canvas_intent.v1"


def product_intent_request(intent_text: str) -> SystemOneJudgmentRequest:
    """Build the fixed questions; only bounded intent text is caller-controlled."""
    if not isinstance(intent_text, str) or not intent_text.strip():
        raise ValueError("intent_text_invalid")
    if len(intent_text.encode("utf-8", errors="strict")) > 2000:
        raise ValueError("intent_text_too_large")
    request = SystemOneJudgmentRequest.model_validate(
        {
            "state": {"intent_text": intent_text},
            "questions": [
                {
                    "question_id": "intent_class",
                    "kind": "choice",
                    "instructions": "Classify the user's intent in `intent_text`. This judgment grants no authority to act.",
                    "criteria": {
                        "co_authoring": "Edit only the body of the currently open note.",
                        "governance_bearing": "Change policy metadata, maturity, note lifecycle, multiple notes or commitment state.",
                        "exploratory": "Reason, compare, plan or orient without changing durable state.",
                        "unknown": "The intent is unclear or none of the other categories fits.",
                    },
                },
                {
                    "question_id": "action_type",
                    "kind": "choice",
                    "instructions": "If `intent_text` requests a governance change, classify it; otherwise choose unknown. This grants no authority.",
                    "criteria": {
                        "frontmatter_update": "Change classification or policy-bearing metadata.",
                        "maturity_transition": "Change maturity, promotion or commitment state.",
                        "note_lifecycle": "Create, delete, move or rename a note.",
                        "cross_note": "Change more than one note.",
                        "unknown": "No clear governance action fits.",
                    },
                },
            ],
        }
    )
    if len(encode_product_request(request)) > PRODUCT_JUDGMENT_REQUEST_BYTES:
        raise ValueError("request_too_large")
    return request


def encode_product_request(request: SystemOneJudgmentRequest) -> bytes:
    return json.dumps(
        request.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def validate_product_request(request: SystemOneJudgmentRequest) -> SystemOneJudgmentRequest:
    """Revalidate constructed/mutated models and reject arbitrary question text."""
    value = SystemOneJudgmentRequest.model_validate(request.model_dump(mode="json"))
    if not isinstance(value.state, dict) or set(value.state) != {"intent_text"}:
        raise ValueError("intent_state_invalid")
    expected = product_intent_request(value.state["intent_text"])
    if value != expected:
        raise ValueError("unsupported_questions")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class JudgmentSelection(_Strict):
    profile_id: Literal["product.canvas_intent.v1"] = PRODUCT_JUDGMENT_PROFILE
    provider: Literal["typesafe"] = "typesafe"
    model: str = Field(pattern=r"^jev-[0-9]+\.[0-9]+\.[0-9]+$")
    sdk_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class ProductJudgmentResult(_Strict):
    outcome: JudgmentOutcome
    selection: JudgmentSelection | None = None
    judgment: SystemOneJudgmentResponse | None = Field(default=None, repr=False)
    usage: JudgmentUsage | None = None

    @model_validator(mode="after")
    def _result_is_truthful(self) -> "ProductJudgmentResult":
        if self.outcome == "success":
            if self.selection is None or self.judgment is None or self.usage is None:
                raise ValueError("successful judgment requires provenance")
            if (
                self.judgment.provenance.provider != self.selection.provider
                or self.judgment.provenance.model != self.selection.model
            ):
                raise ValueError("selected and returned identity mismatch")
        elif self.judgment is not None or self.usage is not None:
            raise ValueError("failed judgment cannot carry an answer")
        return self
