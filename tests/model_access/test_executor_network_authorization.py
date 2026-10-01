from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from fastapi.testclient import TestClient

from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.codex_executor_service import create_codex_executor_app


CAPABILITY_NAME = "model-access.example/cap/complete"


class _CodexExecutor:
    def preflight(self, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            cli_version="codex-cli-test",
            authentication_status="chatgpt_subscription",
        )

    def execute(self, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(response_text="complete")

    def list_catalog_models(self) -> list[dict[str, Any]]:
        return []


class _OllamaAdapter:
    def preflight(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(model=kwargs["model"])

    def complete(self, **_kwargs: Any) -> str:
        return "complete"


def _executor_app():
    root = Path(__file__).resolve().parents[2]
    factory = ModelAccessAdapterFactory.from_declared_sources(
        adapters_path=root / "docs/settings/models/adapters.yaml",
        provider_census_path=root / "docs/settings/models/providers.yaml",
    )
    return create_codex_executor_app(
        codex_executor=_CodexExecutor(),  # type: ignore[arg-type]
        ollama_adapter=_OllamaAdapter(),  # type: ignore[arg-type]
        adapter_factory=factory,
        serve_capability_name=CAPABILITY_NAME,
    )


def _preflight_payload() -> dict[str, Any]:
    return {
        "route": {
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "transport_id": "codex_cli",
        },
        "reasoning_effort": "low",
        "capability_intent": {
            "structured_output": False,
            "native_tools": False,
            "literal_system_role_required": False,
            "max_output_tokens_required": False,
        },
    }


def _capability_header(*, channel: str = "product", actions: list[str] | None = None):
    return {
        "Tailscale-App-Capabilities": json.dumps(
            {
                CAPABILITY_NAME: [
                    {"channel": channel, "actions": actions or ["preflight"]}
                ]
            }
        )
    }


def test_paths_require_channel_and_action_authorization() -> None:
    root = Path(__file__).resolve().parents[2]
    policy = yaml.safe_load(
        (root / "config/model_access/executor_network_paths.yaml").read_text(
            encoding="utf-8"
        )
    )
    path_profiles = policy["path_profiles"]
    vlan_policy = path_profiles["ygg_vlan_primary"]["caller_policy_ref"]
    tailnet_policy = path_profiles["tailscale_fallback"]["caller_policy_ref"]
    assert vlan_policy == tailnet_policy == "policy.product_channel_actions"

    payload = _preflight_payload()
    with TestClient(_executor_app(), client=("127.0.0.1", 12345)) as client:
        # A local/proxied socket or source-network membership alone is not authorization.
        missing_claim = client.post("/v1/preflight", json=payload)
        wrong_channel = client.post(
            "/v1/preflight",
            json=payload,
            headers=_capability_header(channel="builder"),
        )
        wrong_action = client.post(
            "/v1/preflight",
            json=payload,
            headers=_capability_header(actions=["complete"]),
        )
        valid = client.post(
            "/v1/preflight",
            json=payload,
            headers=_capability_header(actions=["preflight"]),
        )

    assert missing_claim.status_code == 403
    assert missing_claim.json()["error"]["code"] == "serve_capability_required"
    assert wrong_channel.status_code == 403
    assert wrong_channel.json()["error"]["code"] == "serve_capability_invalid"
    assert wrong_action.status_code == 403
    assert wrong_action.json()["error"]["code"] == "serve_capability_invalid"
    assert valid.status_code == 200
