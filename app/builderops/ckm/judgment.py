"""Builder-owned CKM intent and a separate dev-only authenticated MARR caller."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import ipaddress
import json
import os
import ssl
from urllib.parse import urlsplit

import httpx

from llm_contract import (
    ModelAccessIntent, ModelCapabilityRequirements, ModelResolutionRequest, SystemOneJudgmentRequest,
)
from app.config.environment import active_environment
from app.model_access.ckm_judgment_contract import (
    CKM_JUDGMENT_RESPONSE_BYTES, BuilderJudgmentResult, encode_ckm_request, validate_ckm_request,
)


CKM_JUDGMENT_SCHEMA_REF = "builderops.ckm.candidate-judgment.v1"


def ckm_judgment_intent() -> ModelResolutionRequest:
    return ModelResolutionRequest(
        intent=ModelAccessIntent(
            capability_tier="frontier", reasoning_effort="low", determinism_required=False,
            output_schema_ref=CKM_JUDGMENT_SCHEMA_REF, independence="none",
            fallback_requirement="fallback_forbidden", side_effect_class="derived_candidate_evidence",
        ),
        role_profile="ckm_semantic", resolution_group_id="ckm-semantic-association",
        requirements=ModelCapabilityRequirements(structured_output=True),
    )


class BuilderJudgmentUnavailable(RuntimeError):
    """Safe refusal; never carries endpoint, credential or provider response text."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _endpoint(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname
    if (
        parsed.scheme != "https" or not host or parsed.username is not None
        or parsed.password is not None or parsed.path not in {"", "/"}
        or parsed.query or parsed.fragment or host.endswith(".ts.net")
    ):
        raise ValueError("invalid Builder ingress")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("invalid Builder ingress")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass  # The host-local CA and hostname validation authenticate private DNS names.
    else:
        if not address.is_private or address.is_loopback or address.is_unspecified:
            raise ValueError("invalid Builder ingress")
    return value.rstrip("/") + "/v1/ckm-judgment"


class BuilderCkmJudgmentClient:
    """Only Builder mTLS file references are consumed; no provider-key source exists."""

    def __init__(
        self, environment: Mapping[str, str], *, transport: httpx.BaseTransport | None = None,
    ) -> None:
        try:
            if active_environment(environment) != "dev":
                raise ValueError("Builder judgment is dev-only")
            self._url = _endpoint(environment["BUILDER_CKM_MARR_ENDPOINT"])
            context = ssl.create_default_context(cafile=environment["BUILDER_CKM_MARR_CA_BUNDLE"])
            context.verify_mode = ssl.CERT_REQUIRED
            context.check_hostname = True
            context.load_cert_chain(
                certfile=environment["BUILDER_CKM_MARR_CLIENT_CERT"],
                keyfile=environment["BUILDER_CKM_MARR_CLIENT_KEY"],
            )
            self._client = httpx.Client(
                transport=transport or httpx.HTTPTransport(verify=context, retries=0, trust_env=False),
                timeout=httpx.Timeout(40.0, connect=10.0), follow_redirects=False, trust_env=False,
            )
        except Exception:
            raise BuilderJudgmentUnavailable("Builder dev MARR caller binding unavailable") from None

    def judge(self, request: SystemOneJudgmentRequest) -> BuilderJudgmentResult:
        try:
            request = validate_ckm_request(request)
            body = encode_ckm_request(request)
        except (ValueError, TypeError, UnicodeError):
            return BuilderJudgmentResult(outcome="unavailable_before_send")
        try:
            with self._client.stream("POST", self._url, content=body,
                                     headers={"Content-Type": "application/json"}) as response:
                if response.status_code in {400, 403, 411, 413, 415, 422, 429}:
                    return BuilderJudgmentResult(outcome="unavailable_before_send")
                if response.status_code != 200:
                    return BuilderJudgmentResult(outcome="outcome_unknown_after_dispatch")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if len(raw) + len(chunk) > CKM_JUDGMENT_RESPONSE_BYTES:
                        return BuilderJudgmentResult(outcome="response_invalid")
                    raw.extend(chunk)
            result = BuilderJudgmentResult.model_validate(json.loads(raw, object_pairs_hook=_unique_object))
            if result.judgment is not None:
                result.judgment.validate_against(request)
            return result
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return BuilderJudgmentResult(outcome="unavailable_before_send")
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return BuilderJudgmentResult(outcome="response_invalid")
        except Exception:
            return BuilderJudgmentResult(outcome="outcome_unknown_after_dispatch")

    def close(self) -> None:
        self._client.close()


class BuilderCkmJudgmentResolver:
    """One exact Builder intent resolves one caller binding, never Product policy."""

    def __init__(
        self, *, environment: Mapping[str, str] | None = None,
        client_factory: Callable[[Mapping[str, str]], BuilderCkmJudgmentClient] = BuilderCkmJudgmentClient,
    ) -> None:
        self._environment = dict(os.environ if environment is None else environment)
        self._client_factory = client_factory

    def resolve(self, request: ModelResolutionRequest) -> BuilderCkmJudgmentClient:
        if request != ckm_judgment_intent() or active_environment(self._environment) != "dev":
            raise BuilderJudgmentUnavailable("Builder judgment intent or dev channel unavailable")
        return self._client_factory(self._environment)
