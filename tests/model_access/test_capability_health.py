from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.api.routes import health as health_route
from app.model_access.codex_remote_transport import RemotePreflightError
from app.model_access.capability_health import (
    aggregate_capability_health,
    aggregate_transport_health,
)

health_module = importlib.import_module("app.cli.health")


NOW = datetime.now(timezone.utc)


def _observation(
    capability_id: str,
    status: str,
    *,
    observed_at: datetime = NOW,
    reason_code: str = "adapter_ready",
) -> dict[str, object]:
    return {
        "capability_id": capability_id,
        "status": status,
        "observed_at": observed_at.isoformat(),
        "reason_code": reason_code,
    }


def test_health_uses_provider_neutral_capability_contract() -> None:
    result = aggregate_capability_health(
        ["text_generation", "structured_output"],
        [
            _observation("text_generation", "available"),
            _observation("structured_output", "available"),
        ],
        now=NOW,
    )

    assert result["ok"] is True
    assert set(result["capabilities"]) == {"text_generation", "structured_output"}
    assert all(
        item["status"] == "available" and item["freshness"] == "fresh"
        for item in result["capabilities"].values()
    )
    assert not {"provider", "model", "transport_id", "endpoint"}.intersection(result)


def test_unselected_provider_absence_does_not_fail_health(monkeypatch) -> None:
    probed: list[str] = []

    def _probe_selected_route(task_kind, effective, intent, *, ollama_probe=None):
        probed.append(task_kind)
        return {
            "status": "available",
            "reason_code": "adapter_ready",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "capabilities": {"structured_output": True},
            "transport_observation": {
                "status": "degraded",
                "reason_code": "transport_fallback_used",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    monkeypatch.setattr(health_module, "_probe_selected_route", _probe_selected_route)
    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "openai",
                        "model": "gpt-6-luna",
                        "transport_id": "codex_cli_tailscale",
                    },
                    "intent": {"json_schema_required": True},
                },
                "embed": {
                    "effective": {
                        "provider": "ollama",
                        "model": "nomic-embed-text",
                        "transport_id": "ollama_http",
                    },
                    "intent": {},
                },
            }
        }
    )

    assert result["ok"] is True
    assert probed == ["qa"]
    assert set(result["capabilities"]) == {"text_generation", "structured_output"}
    assert result["transport_observation"]["status"] == "degraded"
    assert result["transport_observation"]["reason_code"] == "transport_fallback_used"
    assert "ollama" not in repr(result)


def test_required_capability_status_controls_aggregate_health(monkeypatch) -> None:
    observations_by_status = {
        "available": [_observation("text_generation", "available")],
        "degraded": [_observation("text_generation", "degraded", reason_code="readiness_degraded")],
        "unavailable": [_observation("text_generation", "unavailable", reason_code="adapter_unavailable")],
        "unknown": [_observation("text_generation", "unknown", reason_code="readiness_unknown")],
        "missing": [],
        "malformed": [
            {"capability_id": "text_generation", "status": "available", "observed_at": "not-a-time"}
        ],
        "malformed_status": [
            {"capability_id": "text_generation", "status": {"ready": True}, "observed_at": NOW.isoformat()}
        ],
        "stale": [
            _observation(
                "text_generation",
                "available",
                observed_at=NOW - timedelta(minutes=5),
            )
        ],
        "future": [
            _observation(
                "text_generation",
                "available",
                observed_at=NOW + timedelta(seconds=1),
            )
        ],
    }

    for case, observations in observations_by_status.items():
        result = aggregate_capability_health(
            ["text_generation"], observations, now=NOW, max_age_seconds=30
        )
        expected = case == "available"
        assert result["ok"] is expected, case
        if not expected:
            assert result["capabilities"]["text_generation"]["status"] != "available", case

    selected = {"qa": {"effective": {"provider": "openai", "model": "gpt-6-luna", "transport_id": "codex_cli_tailscale"}, "intent": {}}}

    def _probe_selected_route(_task_kind, _effective, _intent, *, ollama_probe=None):
        return {
            "status": "unavailable",
            "reason_code": "adapter_unavailable",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "capabilities": {},
            "transport_observation": {
                "status": "unavailable",
                "reason_code": "transport_unavailable",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    for name in (
        "_check_ffmpeg",
        "_check_yt_dlp",
        "_check_outbox_path",
        "_check_dead_letters",
        "_check_panel_actions",
        "_check_obsidian_dependencies",
        "_check_embedding_index",
        "_check_companion_diagnostics",
        "_check_llm_providers",
        "_watcher_runtime_status",
        "_worker_runtime_status",
        "_db_runtime_status",
        "_settings_ingestion_status",
    ):
        monkeypatch.setattr(health_module, name, lambda *_args, **_kwargs: {"ok": True, "detail": "healthy"})
    monkeypatch.setattr(health_module, "_check_llm_router", lambda: {"ok": True, "route_policies": selected})
    monkeypatch.setattr(health_module, "_probe_selected_route", _probe_selected_route)
    monkeypatch.setattr(health_module, "check_v6_seams", lambda: {})
    monkeypatch.setattr(health_module, "get_runtime_version", lambda: {"git_sha": "test"})
    monkeypatch.setattr(health_module, "_check_authority_spine", lambda: {})

    payload = health_module.run_health()
    monkeypatch.setattr(health_route, "run_health", lambda: payload)
    public_payload = asyncio.run(health_route.health())

    assert payload["checks"]["llm_access"]["ok"] is False
    assert payload["required_ok"] is False
    assert payload["ok"] is False
    assert public_payload["required_ok"] is False
    assert public_payload["ok"] is False
    assert "provider" not in repr(public_payload["checks"]["llm_access"])


def test_provider_substitution_preserves_health_schema(monkeypatch) -> None:
    def _probe_selected_route(_task_kind, _effective, _intent, *, ollama_probe=None):
        return {
            "status": "available",
            "reason_code": "adapter_ready",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "capabilities": {"structured_output": True},
            "transport_observation": {
                "status": "available",
                "reason_code": "transport_reachable",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    monkeypatch.setattr(health_module, "_probe_selected_route", _probe_selected_route)

    def _health_for(provider: str, model: str, transport_id: str):
        return health_module._check_llm_access(
            {
                "route_policies": {
                    "qa": {
                        "effective": {
                            "provider": provider,
                            "model": model,
                            "transport_id": transport_id,
                        },
                        "intent": {"json_schema_required": True},
                    }
                }
            }
        )

    first = _health_for("openai", "gpt-6-luna", "codex_cli_tailscale")
    replacement = _health_for("deepseek", "deepseek-chat", "deepseek_api")

    assert first == replacement
    assert set(first["capabilities"]) == {"text_generation", "structured_output"}
    assert "provider" not in repr(first)
    assert "deepseek" not in repr(replacement)


def test_health_is_no_inference_and_preserves_readiness_boundaries(monkeypatch) -> None:
    seen: list[str] = []

    class _Client:
        preflight_transport_observation = {
            "status": "available",
            "reason_code": "transport_reachable",
        }
        model_access_route = SimpleNamespace(
            preflight_status="passed",
            capabilities=SimpleNamespace(
                structured_output=True,
                native_tools=False,
                system_prompt_channel=True,
                deterministic_execution=False,
            ),
        )

        def chat(self, *_args, **_kwargs):
            raise AssertionError("health must never dispatch inference")

    def _get_chat_client_for_route(
        intent,
        *,
        selected_route,
        allow_fallback,
        allow_catalog_promotion,
    ):
        seen.append(intent.task_kind)
        assert intent.task_kind == "health"
        assert selected_route.model == "gpt-6-luna"
        assert allow_fallback is False
        assert allow_catalog_promotion is False
        return _Client()

    monkeypatch.setattr(health_module, "get_chat_client_for_route", _get_chat_client_for_route)
    monkeypatch.setattr(health_module, "_check_ollama", lambda **_kwargs: pytest.fail("embedding route was probed"))

    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "openai",
                        "model": "gpt-6-luna",
                        "transport_id": "codex_cli_tailscale",
                        "reasoning_effort": "low",
                    },
                    "intent": {"json_schema_required": True},
                },
                "embed": {
                    "effective": {
                        "provider": "ollama",
                        "model": "nomic-embed-text",
                        "transport_id": "ollama_http",
                    },
                    "intent": {},
                },
            }
        }
    )

    assert result["ok"] is True
    assert seen == ["health"]
    assert set(result["capabilities"]) == {"text_generation", "structured_output"}
    assert result["transport_observation"]["status"] == "available"
    assert "embedding_index" not in result["capabilities"]


def test_duplicate_capability_observations_are_order_independent() -> None:
    observations = [
        _observation("text_generation", "available", reason_code="adapter_ready"),
        _observation("text_generation", "degraded", reason_code="readiness_degraded"),
        _observation("text_generation", "unavailable", reason_code="capability_unsupported"),
    ]

    forward = aggregate_capability_health(["text_generation"], observations, now=NOW)
    reverse = aggregate_capability_health(
        ["text_generation"], list(reversed(observations)), now=NOW
    )

    assert forward == reverse
    assert forward["capabilities"]["text_generation"]["status"] == "unavailable"


def test_configured_path_fallback_preserves_capability_health(monkeypatch) -> None:
    def _probe_selected_route(_task_kind, _effective, _intent, *, ollama_probe=None):
        observed_at = datetime.now(timezone.utc).isoformat()
        return {
            "status": "available",
            "reason_code": "adapter_ready",
            "observed_at": observed_at,
            "capabilities": {},
            "transport_observation": {
                "status": "degraded",
                "reason_code": "transport_fallback_used",
                "observed_at": observed_at,
            },
        }

    monkeypatch.setattr(health_module, "_probe_selected_route", _probe_selected_route)
    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "openai",
                        "model": "gpt-6-luna",
                        "transport_id": "codex_cli_tailscale",
                    },
                    "intent": {},
                }
            }
        }
    )

    assert result["ok"] is True
    assert result["capabilities"]["text_generation"]["status"] == "available"
    assert result["transport_observation"]["status"] == "degraded"
    assert "selected_path_profile" not in repr(result)


def test_unknown_output_limit_capability_fails_closed(monkeypatch) -> None:
    def _probe_selected_route(_task_kind, _effective, _intent, *, ollama_probe=None):
        return {
            "status": "available",
            "reason_code": "adapter_ready",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "capabilities": {},
            "transport_observation": {
                "status": "not_applicable",
                "reason_code": "transport_not_required",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    monkeypatch.setattr(health_module, "_probe_selected_route", _probe_selected_route)
    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {"provider": "openai", "model": "gpt-6-luna"},
                    "intent": {"max_output_tokens_required": True},
                }
            }
        }
    )

    assert result["ok"] is False
    assert result["capabilities"]["max_output_tokens"] == {
        "status": "unknown",
        "freshness": "fresh",
        "reason_code": "capability_not_observable",
    }


def test_transport_observation_reports_fallback_without_path_identity() -> None:
    result = aggregate_transport_health(
        [
            {
                "status": "degraded",
                "reason_code": "transport_fallback_used",
                "observed_at": NOW.isoformat(),
            }
        ],
        now=NOW,
    )

    assert result == {
        "status": "degraded",
        "freshness": "fresh",
        "reason_code": "transport_fallback_used",
    }
    assert not {"path_id", "selected_path", "endpoint"}.intersection(result)


def test_transport_failure_is_separate_from_route_capability_failure() -> None:
    observed_at = datetime.now(timezone.utc).isoformat()

    path_unavailable = health_module._transport_observation_for_failure(
        "codex_cli_tailscale",
        RemotePreflightError("PATH_UNAVAILABLE"),
        observed_at,
    )
    route_unavailable = health_module._transport_observation_for_failure(
        "codex_cli_tailscale",
        RemotePreflightError("model_unavailable"),
        observed_at,
    )

    assert path_unavailable["status"] == "unavailable"
    assert path_unavailable["reason_code"] == "transport_unavailable"
    assert route_unavailable["status"] == "available"
    assert route_unavailable["reason_code"] == "transport_reachable"
