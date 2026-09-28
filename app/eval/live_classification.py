"""Opt-in, exact-route golden classification evaluation; no content persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import re
from typing import Any

from app.components.llm.constrained import registered_schema, validate_payload
from app.components.llm.intent_classifier import INTENT_CLASSIFICATION_SCHEMA_REF
from app.components.settings.models_loader import load_models
from app.eval.classification import (
    CLASSIFICATION_GOLDEN_PATH,
    evaluate_classification_golden_set,
    load_classification_cases,
)
from app.eval.llm_client import EvalLLMConfig, configure_eval_openai_env


class LiveEvaluationError(RuntimeError):
    """Static errors only: provider messages, keys and content are never echoed."""


def configure_classification_eval() -> EvalLLMConfig:
    if os.getenv("EVAL_LLM_MODE", "").strip().lower() != "run":
        raise LiveEvaluationError("live classification requires EVAL_LLM_MODE=run")
    if not os.getenv("EVAL_LLM_MODEL", "").strip():
        raise LiveEvaluationError("live classification requires EVAL_LLM_MODEL")
    # Only this measured API path supplies the billing evidence used below.
    if os.getenv("EVAL_LLM_TRANSPORT", "").strip() != "openai_api":
        raise LiveEvaluationError("live classification requires EVAL_LLM_TRANSPORT=openai_api")
    try:
        cfg = configure_eval_openai_env()
        if cfg.chat_client is None or cfg.chat_client.route.provider != "openai":
            raise ValueError("unsupported route")
        if not cfg.api_key.strip():
            raise ValueError("missing credential")
        # Standard OpenAI prices cannot attest a compatible proxy's billing.
        if cfg.base_url.rstrip("/") != "https://api.openai.com/v1":
            raise ValueError("unpriced endpoint")
    except Exception:
        raise LiveEvaluationError(
            "live classification route or credentials are unavailable"
        ) from None
    return cfg


class ClassificationCompletion:
    """One run-scoped completion seam; validated metadata never stores raw output."""

    def __init__(self, cfg: EvalLLMConfig) -> None:
        client = cfg.chat_client
        if cfg.mode != "run" or client is None:
            raise LiveEvaluationError("live evaluation is disabled")
        route = client.route
        if (
            route.provider != "openai"
            or route.transport_id != "openai_api"
            or route.model != cfg.model
        ):
            raise LiveEvaluationError("live evaluation requires its exact API route")
        self.client = client
        self.model = route.model
        self.records: list[dict[str, Any]] = []
        self.failures = 0
        self.completed_calls = 0

    def __call__(
        self, *, system: str, user: str, trace_id: str | None = None, max_tokens: int | None = None
    ) -> str:
        if self.failures:
            raise LiveEvaluationError("live evaluation stopped after provider failure")
        observed: list[dict[str, Any]] = []
        try:
            raw = self.client.chat(
                "classification_eval",
                {"system": system, "user": user},
                kind="eval",
                trace_id=trace_id,
                max_tokens=max_tokens,
                response_format=registered_schema(INTENT_CLASSIFICATION_SCHEMA_REF),
                usage_observer=observed.append,
                record_content=False,
            )
        except Exception:
            self.failures += 1
            raise LiveEvaluationError("live evaluation provider call failed") from None
        self.completed_calls += 1
        self.records.append(_billing_record(observed, self.model))
        # Sanitize before the cognition's logging boundary. Its own constrained
        # validation still runs on every result, including UNKNOWN safe-fails.
        try:
            validate_payload(INTENT_CLASSIFICATION_SCHEMA_REF, json.loads(raw))
        except Exception:
            return ""
        return raw


def _billing_record(observed: list[dict[str, Any]], model: str) -> dict[str, Any]:
    if len(observed) != 1:
        return {"valid": False}
    event = observed[0]
    served = event.get("model")
    if not isinstance(served, str) or not (
        served == model or re.fullmatch(re.escape(model) + r"-\d{4}-\d{2}-\d{2}", served)
    ):
        return {"valid": False}
    usage = event.get("usage")
    if not isinstance(usage, dict) or event.get("service_tier") != "default":
        return {"valid": False}
    details = usage.get("prompt_tokens_details")
    if not isinstance(details, dict):
        return {"valid": False}
    values = {
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cached_input_tokens": details.get("cached_tokens"),
    }
    if any(type(v) is not int or v < 0 for v in values.values()):
        return {"valid": False}
    if not (
        0 < values["input_tokens"] <= 272_000
        and values["cached_input_tokens"] <= values["input_tokens"]
        and values["input_tokens"] + values["output_tokens"] == values["total_tokens"]
    ):
        return {"valid": False}
    # The bounded runner does not request cache writes/audio/tools or long context.
    if any(
        details.get(k, 0) != 0
        for k in ("audio_tokens", "cache_write_tokens", "cache_creation_tokens")
    ):
        return {"valid": False}
    return {"valid": True, "served_model": served, **values}


def run_live_classification(cfg: EvalLLMConfig | None = None) -> dict[str, Any]:
    cfg = cfg if cfg is not None else configure_classification_eval()
    completion = ClassificationCompletion(cfg)
    dataset_bytes = CLASSIFICATION_GOLDEN_PATH.read_bytes()
    cases = load_classification_cases()
    metrics = evaluate_classification_golden_set(live=True, live_completion=completion)
    records = completion.records
    usage_complete = (
        not completion.failures and len(records) == len(cases) and all(r["valid"] for r in records)
    )
    descriptor = next(
        (m for m in load_models().values() if m.provider == "openai" and m.model == cfg.model), None
    )
    pricing = descriptor.pricing if descriptor else None
    priced = (
        pricing is not None and pricing.standard_cached_input_usd_per_million_tokens is not None
    )
    complete = usage_complete and priced
    usage = None
    cost = None
    if usage_complete:
        usage = {
            key: sum(r[key] for r in records)
            for key in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
        }
    if complete and usage is not None and pricing is not None:
        uncached = usage["input_tokens"] - usage["cached_input_tokens"]
        amount = (
            Decimal(uncached) * Decimal(str(pricing.standard_input_usd_per_million_tokens))
            + Decimal(usage["cached_input_tokens"])
            * Decimal(str(pricing.standard_cached_input_usd_per_million_tokens))
            + Decimal(usage["output_tokens"])
            * Decimal(str(pricing.standard_output_usd_per_million_tokens))
        ) / Decimal(1_000_000)
        cost = {
            "usd": str(amount),
            "basis": "standard-text-token-estimate",
            "pricing": pricing.model_dump(mode="json"),
        }
    return {
        "schema_version": "classification_live_run.v1",
        "complete": complete,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "route": {
            "provider": "openai",
            "model": cfg.model,
            "transport": "openai_api",
            "reasoning_effort": "none",
            "service_tier": "default",
        },
        "served_models": sorted({r["served_model"] for r in records if r["valid"]}),
        "dataset": {
            "path": str(CLASSIFICATION_GOLDEN_PATH),
            "sha256": hashlib.sha256(dataset_bytes).hexdigest(),
            "expected_cases": len(cases),
            "completed_calls": completion.completed_calls,
        },
        "metrics": metrics,
        "hard_gate_passed": not metrics["mutation_side_confusions"],
        "usage": usage,
        "cost": cost,
        "failure": None if complete else "incomplete_usage_or_missing_price_provenance",
    }


def main() -> int:
    try:
        receipt = run_live_classification()
    except Exception:
        print(
            json.dumps(
                {
                    "schema_version": "classification_live_run.v1",
                    "complete": False,
                    "failure": "live_evaluation_unavailable",
                }
            )
        )
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["complete"] and receipt["hard_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
