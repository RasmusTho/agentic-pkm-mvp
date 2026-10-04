from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_contract import (
    ChoiceJudgmentAnswer,
    ChoiceQuestion,
    JudgmentProvenance,
    NoulJudgmentAnswer,
    NoulQuestion,
    ScoreJudgmentAnswer,
    ScoreQuestion,
    SystemOneJudgmentRequest,
    SystemOneJudgmentResponse,
    validate_system_one_judgment_response,
)


def _request() -> SystemOneJudgmentRequest:
    return SystemOneJudgmentRequest.model_validate(
        {
            "state": {"message": "Please review this request."},
            "questions": [
                {
                    "question_id": "is_urgent",
                    "kind": "noul",
                    "instructions": "Is the request urgent?",
                    "criteria": {
                        "true": "Needs attention soon.",
                        "false": "Can wait.",
                    },
                },
                {
                    "question_id": "intent",
                    "kind": "choice",
                    "instructions": "Choose the best intent.",
                    "criteria": {
                        "support": "The user requests help.",
                        "feedback": "The user reports an opinion.",
                    },
                },
                {
                    "question_id": "priority",
                    "kind": "score",
                    "instructions": "Rate the priority.",
                    "criteria": ["low", "medium", "high"],
                },
            ],
        }
    )


def _response() -> SystemOneJudgmentResponse:
    return SystemOneJudgmentResponse.model_validate(
        {
            "answers": [
                {"question_id": "is_urgent", "kind": "noul", "noul": 0.8},
                {
                    "question_id": "intent",
                    "kind": "choice",
                    "choice": "support",
                    "confidence": 0.9,
                    "probabilities": {"support": 0.9, "feedback": 0.1},
                },
                {
                    "question_id": "priority",
                    "kind": "score",
                    "score": 1.7,
                    "confidence": 0.8,
                    "legend": {"0": "low", "1": "medium", "2": "high"},
                    "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8},
                },
            ],
            "provenance": {"provider": "example-provider", "model": "example-model"},
        }
    )


def test_judgment_contract_round_trips_typed_answers() -> None:
    request = SystemOneJudgmentRequest.model_validate_json(_request().model_dump_json())
    response = SystemOneJudgmentResponse.model_validate_json(_response().model_dump_json())

    assert [type(question) for question in request.questions] == [
        NoulQuestion,
        ChoiceQuestion,
        ScoreQuestion,
    ]
    assert [type(answer) for answer in response.answers] == [
        NoulJudgmentAnswer,
        ChoiceJudgmentAnswer,
        ScoreJudgmentAnswer,
    ]
    assert response.provenance == JudgmentProvenance(
        provider="example-provider", model="example-model"
    )
    assert validate_system_one_judgment_response(request, response) == response


def test_invalid_judgment_payloads_are_rejected() -> None:
    request_data = _request().model_dump(mode="json")
    request_data["questions"][1]["question_id"] = request_data["questions"][0]["question_id"]
    with pytest.raises(ValidationError, match="question IDs must be unique"):
        SystemOneJudgmentRequest.model_validate(request_data)

    with pytest.raises(ValidationError, match="must sum to 1"):
        ChoiceJudgmentAnswer.model_validate(
            {
                "question_id": "intent",
                "kind": "choice",
                "choice": "support",
                "confidence": 0.5,
                "probabilities": {"support": 0.4, "feedback": 0.4},
            }
        )

    with pytest.raises(ValidationError, match="finite"):
        NoulJudgmentAnswer.model_validate(
            {"question_id": "is_urgent", "kind": "noul", "noul": float("nan")}
        )

    request = _request()
    unknown_id = _response().model_copy(
        update={
            "answers": (
                _response().answers[0],
                _response().answers[1].model_copy(update={"question_id": "other"}),
                _response().answers[2],
            )
        }
    )
    with pytest.raises(ValueError, match="exactly match request question IDs"):
        validate_system_one_judgment_response(request, unknown_id)

    mismatched_type = _response().model_copy(
        update={
            "answers": (
                _response().answers[0].model_copy(update={"kind": "choice"}),
                _response().answers[1],
                _response().answers[2],
            )
        }
    )
    with pytest.raises(ValueError, match="does not match its question"):
        validate_system_one_judgment_response(request, mismatched_type)

    with pytest.raises(ValidationError, match="serialized UTF-8 bytes"):
        SystemOneJudgmentRequest.model_validate(
            {
                "state": "x" * 17_000,
                "questions": [
                    {"question_id": "q", "kind": "noul", "instructions": "check"}
                ],
            }
        )

    oversized_response = _response().model_dump(mode="json")
    oversized_response["provenance"]["provider"] = "p" * 17_000
    with pytest.raises(ValidationError, match="serialized UTF-8 bytes"):
        SystemOneJudgmentResponse.model_validate(oversized_response)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ChoiceQuestion.model_validate(
            {
                "question_id": "intent",
                "kind": "choice",
                "instructions": "Choose.",
                "criteria": {"support": "Help request."},
                "provider": "must-not-be-part-of-the-question",
            }
        )
