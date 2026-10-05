"""Pinned SDK boundary for one terminal TypeSafe request; never a completion route."""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import version
import json
import logging
from typing import Any

import httpx2
from pydantic import BaseModel, ConfigDict
from typesafe_sdk import (
    RetryPolicy,
    TypeSafeAPIError,
    TypeSafeAPIResponseValidationError,
    TypeSafeClient,
)

from llm_contract import SystemOneJudgmentRequest, SystemOneJudgmentResponse

from app.model_access.remote_contract import JudgmentOutcome, JudgmentUsage


TYPESAFE_SDK_VERSION = "0.7.2"
TYPESAFE_API_ROOT = "https://api.typesafe.ai"
MAX_PROVIDER_RESPONSE_BYTES = 16384


class TypeSafeAdapterError(RuntimeError):
    def __init__(self, outcome: JudgmentOutcome) -> None:
        self.outcome = outcome
        super().__init__(outcome)


def strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class _WireResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str
    answers: dict[str, dict[str, Any]]
    usage: JudgmentUsage


class _SingleAttemptTransport(httpx2.BaseTransport):
    """Bound bytes before the SDK eagerly buffers/logs/parses a response."""

    def __init__(self, inner: httpx2.BaseTransport) -> None:
        self.inner = inner
        self.attempted = False

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        if self.attempted:
            raise TypeSafeAdapterError("outcome_unknown_after_dispatch")
        if (
            request.method != "POST"
            or str(request.url) != TYPESAFE_API_ROOT + "/v1/systemone"
            or len(request.content) > 4096
        ):
            raise TypeSafeAdapterError("unavailable_before_send")
        self.attempted = True
        try:
            response = self.inner.handle_request(request)
        except (httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.PoolTimeout):
            raise TypeSafeAdapterError("unavailable_before_send") from None
        try:
            # A status rejection is terminal even when its body is hostile or unreadable.
            if response.status_code != 200:
                raise TypeSafeAdapterError("provider_rejected")
            body = bytearray()
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > MAX_PROVIDER_RESPONSE_BYTES:
                    raise TypeSafeAdapterError("response_invalid")
                body.extend(chunk)
            # JSON duplicate keys must not be silently normalized by the SDK.
            json.loads(body, object_pairs_hook=strict_json_object)
            return httpx2.Response(200, content=bytes(body), request=request)
        except (ValueError, UnicodeError, RecursionError):
            raise TypeSafeAdapterError("response_invalid") from None
        finally:
            response.close()

    def close(self) -> None:
        self.inner.close()


class TypeSafeAdapter:
    """Only this module knows SDK configuration, wire types and exception behavior."""

    def __init__(
        self, *, transport_factory: Callable[[], httpx2.BaseTransport] | None = None
    ) -> None:
        self._transport_factory = transport_factory or (
            lambda: httpx2.HTTPTransport(retries=0, trust_env=False)
        )

    def execute(
        self,
        request: SystemOneJudgmentRequest,
        *,
        model: str,
        api_key: str,
    ) -> tuple[SystemOneJudgmentResponse, JudgmentUsage]:
        if version("typesafe-sdk") != TYPESAFE_SDK_VERSION:
            raise TypeSafeAdapterError("unavailable_before_send")
        # The pinned SDK uses this exact logger, including at debug level. Do not
        # temporarily restore it: concurrent requests must never expose bodies.
        for name in ("typesafe_sdk", "httpx2", "httpcore2"):
            logging.getLogger(name).disabled = True
        transport = _SingleAttemptTransport(self._transport_factory())
        try:
            with httpx2.Client(
                transport=transport, timeout=30.0, trust_env=False, follow_redirects=False
            ) as http_client:
                with TypeSafeClient(
                    api_key=api_key,
                    model=model,
                    base_url=TYPESAFE_API_ROOT,
                    http_client=http_client,
                    retry=RetryPolicy(max_retries=0),
                    timeout=30.0,
                ) as client:
                    questions: dict[str, Any] = {}
                    for question in request.questions:
                        wire = question.model_dump(mode="json", exclude_none=True)
                        question_id = wire.pop("question_id")
                        wire["type"] = wire.pop("kind")
                        questions[question_id] = wire
                    raw = client.system_one(
                        state=request.state, questions=questions, response_model=_WireResponse
                    )
            if raw.model != model:
                raise ValueError("model mismatch")
            answers = []
            for question_id, answer in raw.answers.items():
                fields = {
                    "choice": {"type", "choice", "confidence", "probabilities"},
                    "score": {"type", "score", "confidence", "legend", "probabilities"},
                    "noul": {"type", "noul"},
                }
                kind = answer.get("type")
                if not isinstance(kind, str) or set(answer) != fields.get(kind, set()):
                    raise ValueError("invalid answer fields")
                translated = dict(answer)
                translated["kind"] = translated.pop("type")
                translated["question_id"] = question_id
                answers.append(translated)
            result = SystemOneJudgmentResponse.model_validate(
                {
                    "answers": answers,
                    "provenance": {"provider": "typesafe", "model": raw.model},
                }
            ).validate_against(request)
            return result, raw.usage
        except TypeSafeAdapterError:
            raise
        except TypeSafeAPIResponseValidationError:
            raise TypeSafeAdapterError("response_invalid") from None
        except TypeSafeAPIError:
            raise TypeSafeAdapterError("provider_rejected") from None
        except (ValueError, KeyError, TypeError):
            outcome: JudgmentOutcome = (
                "response_invalid" if transport.attempted else "unavailable_before_send"
            )
            raise TypeSafeAdapterError(outcome) from None
        except Exception:
            outcome = (
                "outcome_unknown_after_dispatch"
                if transport.attempted
                else "unavailable_before_send"
            )
            raise TypeSafeAdapterError(outcome) from None
