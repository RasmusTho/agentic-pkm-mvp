from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from app.eval import live_classification as live
from app.eval.classification import CLASSIFICATION_GOLDEN_PATH, load_classification_cases
from app.eval.llm_client import EvalLLMConfig

pytestmark = pytest.mark.not_pg


class Client:
    route = SimpleNamespace(provider="openai", model="gpt-5.6-luna", transport_id="openai_api")

    def __init__(self):
        self.fail = False
        self.metadata = {
            "model": "gpt-5.6-luna",
            "service_tier": "default",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 10},
            },
        }

    def chat(self, name, pack, **kw):
        if self.fail:
            raise RuntimeError("secret-api-key private-completion https://secret.example")
        kw["usage_observer"](self.metadata)
        return '{"intent_class":"exploratory","action_type":null}'


def config(client):
    return EvalLLMConfig(
        model=client.route.model,
        mode="run",
        chat_client=client,
        api_key="secret-api-key",
        base_url="https://secret.example",
    )


def test_receipt_binds_exact_route_dataset_coverage_and_cost_evidence() -> None:
    receipt = live.run_live_classification(config(Client()))
    n = len(load_classification_cases())
    assert receipt["complete"]
    assert receipt["route"] == {
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "transport": "openai_api",
        "reasoning_effort": "none",
        "service_tier": "default",
    }
    assert (
        receipt["dataset"]["sha256"]
        == hashlib.sha256(CLASSIFICATION_GOLDEN_PATH.read_bytes()).hexdigest()
    )
    assert receipt["dataset"]["expected_cases"] == receipt["dataset"]["completed_calls"] == n
    assert receipt["usage"] == {
        "input_tokens": n * 100,
        "cached_input_tokens": n * 10,
        "output_tokens": n * 20,
        "total_tokens": n * 120,
    }
    assert float(receipt["cost"]["usd"]) == pytest.approx(n * 0.0000422)
    assert receipt["cost"]["pricing"]["retrieved_on"] == "2026-09-28"
    assert receipt["hard_gate_passed"] is True


@pytest.mark.parametrize(
    "failure",
    ["provider", "usage", "pricing", "model", "tier", "negative", "long", "cached", "total"],
)
def test_incomplete_or_unpriced_run_cannot_claim_comparison_receipt(monkeypatch, failure) -> None:
    client = Client()
    if failure == "provider":
        client.fail = True
    elif failure == "usage":
        client.metadata["usage"] = None
    elif failure == "pricing":
        monkeypatch.setattr(live, "load_models", lambda: {})
    elif failure == "model":
        client.metadata["model"] = "gpt-5.6-terra"
    elif failure == "tier":
        client.metadata["service_tier"] = "priority"
    elif failure == "negative":
        client.metadata["usage"]["completion_tokens"] = -1
    elif failure == "long":
        client.metadata["usage"]["prompt_tokens"] = 300_000
    elif failure == "cached":
        client.metadata["usage"]["prompt_tokens_details"] = {}
    else:
        client.metadata["usage"]["total_tokens"] = 99
    receipt = live.run_live_classification(config(client))
    assert receipt["complete"] is False
    assert receipt["cost"] is None
    assert receipt["failure"]


def test_receipt_and_failures_are_secret_free(monkeypatch, capsys, caplog) -> None:
    client = Client()
    client.fail = True
    receipt = live.run_live_classification(config(client))
    assert "secret-api-key" not in json.dumps(receipt) + caplog.text
    client.fail = False
    client.metadata["model"] = "secret-api-key"
    receipt = live.run_live_classification(config(client))
    assert "secret-api-key" not in json.dumps(receipt)
    monkeypatch.setattr(
        live,
        "configure_classification_eval",
        lambda: (_ for _ in ()).throw(ValueError("secret-api-key")),
    )
    assert live.main() == 2
    assert "secret-api-key" not in capsys.readouterr().out


def test_real_api_seam_captures_usage_without_content_logging(monkeypatch) -> None:
    from app.components.llm import fabric
    from app.components.llm.router import LLMTaskIntent
    from app.services import llm

    calls = []
    client = Client()

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                **client.metadata,
                "choices": [
                    {"message": {"content": '{"intent_class":"exploratory","action_type":null}'}}
                ],
            }

    def post(url, **kwargs):
        calls.append(json.loads(kwargs["data"]))
        return Response()

    monkeypatch.setattr(llm.requests, "post", post)
    monkeypatch.setattr(llm, "log_llm_call", lambda **kw: pytest.fail("content persisted"))
    real = fabric.get_chat_client(
        LLMTaskIntent(task_kind="eval"),
        model_id="gpt-5.6-luna",
        transport_id="openai_api",
        adapter_runtime_config=fabric.AdapterRuntimeConfig(
            api_key="test-key", base_url="https://api.openai.com/v1"
        ),
    )
    receipt = live.run_live_classification(
        EvalLLMConfig(model="gpt-5.6-luna", mode="run", chat_client=real)
    )
    assert receipt["complete"]
    assert len(calls) == len(load_classification_cases())
    assert all(c["model"] == "gpt-5.6-luna" and c["service_tier"] == "default" for c in calls)
    assert all(c["reasoning_effort"] == "none" and "temperature" not in c for c in calls)


@pytest.mark.parametrize(
    "missing",
    [
        "EVAL_LLM_MODE",
        "EVAL_LLM_MODEL",
        "EVAL_LLM_TRANSPORT",
        "EVAL_LLM_API_KEY",
        "EVAL_LLM_BASE_URL",
    ],
)
def test_measured_run_refuses_incomplete_configuration_before_inference(
    monkeypatch, missing
) -> None:
    from app.services import llm

    for name, value in {
        "EVAL_LLM_MODE": "run",
        "EVAL_LLM_MODEL": "gpt-5.6-luna",
        "EVAL_LLM_TRANSPORT": "openai_api",
        "EVAL_LLM_API_KEY": "test-key",
        "EVAL_LLM_BASE_URL": "https://api.openai.com/v1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(missing, "")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **kw: pytest.fail("inference started"))
    with pytest.raises(live.LiveEvaluationError):
        live.configure_classification_eval()


def test_schema_failure_never_logs_provider_content(caplog) -> None:
    client = Client()

    def chat(name, pack, **kw):
        kw["usage_observer"](client.metadata)
        return '{"intent_class":"secret-api-key","action_type":null}'

    client.chat = chat
    receipt = live.run_live_classification(config(client))
    assert receipt["complete"]
    assert receipt["metrics"]["safe_fail"]["count"] > 0
    assert "secret-api-key" not in json.dumps(receipt) + caplog.text
