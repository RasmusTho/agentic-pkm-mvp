from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from fastapi.testclient import TestClient

from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.codex_executor_service import create_codex_executor_app


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


def test_configured_mtls_vlan_path_is_the_only_executor_path() -> None:
    root = Path(__file__).resolve().parents[2]
    policy = yaml.safe_load(
        (root / "config/model_access/executor_network_paths.yaml").read_text(
            encoding="utf-8"
        )
    )
    path_profiles = policy["path_profiles"]
    vlan_policy = path_profiles["ygg_vlan_primary"]["caller_policy_ref"]
    configured_order = policy["executor_path_policies"][
        "profile.codex_remote_host"
    ]["order"]
    authentication = policy["authentication_profiles"]["ygg_vlan_mutual_tls"]
    assert vlan_policy == "policy.vlan_mtls_authenticated_caller"
    assert configured_order == ["ygg_vlan_primary"]
    assert set(path_profiles) == {"ygg_vlan_primary"}
    assert authentication["mode"] == "mutual_tls"

    payload = _preflight_payload()
    with TestClient(_executor_app(), client=("127.0.0.1", 12345)) as client:
        # The external VLAN ingress authenticates the client certificate; the
        # loopback-only backend does not depend on Tailscale-injected claims.
        local_backend = client.post("/v1/preflight", json=payload)

    assert local_backend.status_code == 200
