from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Event
import time
from types import SimpleNamespace

from app.config import llm as llm_config
from app.model_access.codex_remote_transport import RemotePreflightError
from app.model_access.health_observer import ProductHealthObserver
from app.settings.models import LLMRoutingSettings, SettingsBundle

health_module = importlib.import_module("app.cli.health")


def test_health_preflight_is_single_flight_per_exact_route_intent(
    monkeypatch, tmp_path
) -> None:
    settings_state = SimpleNamespace(
        state="ok",
        source="vault",
        loaded_at="generation-one",
    )
    monkeypatch.setattr(
        health_module, "get_settings_ingestion_state", lambda: settings_state
    )
    route = {
        "provider": "openai",
        "model": "gpt-6-luna",
        "transport_id": "codex_cli_tailscale",
        "reasoning_effort": "low",
    }
    intent = {"task_kind": "qa", "json_schema_required": True}
    policy_path = tmp_path / "executor_network_paths.yaml"
    policy_text = health_module.DEFAULT_EXECUTOR_NETWORK_POLICY_PATH.read_text(
        encoding="utf-8"
    )
    policy_text = policy_text.replace(
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT", "CUSTOM_EXECUTOR_ENDPOINT"
    )
    policy_text = policy_text.replace(
        "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE", "CUSTOM_EXECUTOR_TRUST"
    )
    policy_text = policy_text.replace(
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT", "CUSTOM_EXECUTOR_CERTIFICATE"
    )
    policy_text = policy_text.replace(
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY", "CUSTOM_EXECUTOR_PRIVATE_KEY"
    )
    policy_path.write_text(policy_text, encoding="utf-8")
    monkeypatch.setattr(
        health_module, "DEFAULT_EXECUTOR_NETWORK_POLICY_PATH", policy_path
    )
    trust_files = {
        "CUSTOM_EXECUTOR_TRUST": tmp_path / "trust-bundle",
        "CUSTOM_EXECUTOR_CERTIFICATE": tmp_path / "client-certificate",
        "CUSTOM_EXECUTOR_PRIVATE_KEY": tmp_path / "client-key",
    }
    for path in trust_files.values():
        path.write_text("initial material", encoding="utf-8")
    extra_certificate = tmp_path / "extra-client-certificate"
    extra_certificate.write_text("initial extra certificate", encoding="utf-8")
    monkeypatch.setenv("CUSTOM_EXECUTOR_ENDPOINT", "https://first.invalid")
    for variable, path in trust_files.items():
        value = f" {path} " if variable == "CUSTOM_EXECUTOR_CERTIFICATE" else str(path)
        monkeypatch.setenv(variable, value)
    monkeypatch.setenv("MODEL_ACCESS_EXTRA_CLIENT_CERT", f" {extra_certificate} ")
    key = health_module._route_health_observation_key(route, intent)
    assert health_module._route_health_observation_key(
        route, {**intent, "task_kind": "plan"}
    ) == key
    assert health_module._route_health_observation_key(
        {**route, "reason": "per-task explanation"}, intent
    ) == key
    assert health_module._route_health_observation_key(
        {**route, "reasoning_effort": "high"}, intent
    ) != key
    assert health_module._route_health_observation_key(
        route, {"json_schema_required": False}
    ) != key
    settings_state.loaded_at = "generation-two"
    assert health_module._route_health_observation_key(route, intent) != key
    settings_state.loaded_at = "generation-one"
    policy_path.write_text("paths: generation-two\n", encoding="utf-8")
    assert health_module._route_health_observation_key(route, intent) != key
    policy_path.write_text(policy_text, encoding="utf-8")
    key = health_module._route_health_observation_key(route, intent)
    monkeypatch.setenv("CUSTOM_EXECUTOR_ENDPOINT", "https://second.invalid")
    assert health_module._route_health_observation_key(route, intent) != key
    monkeypatch.setenv("CUSTOM_EXECUTOR_ENDPOINT", "https://first.invalid")
    key = health_module._route_health_observation_key(route, intent)
    for path in trust_files.values():
        previous_key = key
        path.write_text("updated authentication material", encoding="utf-8")
        key = health_module._route_health_observation_key(route, intent)
        assert key != previous_key
    previous_key = key
    extra_certificate.write_text("updated extra certificate", encoding="utf-8")
    key = health_module._route_health_observation_key(route, intent)
    assert key != previous_key
    monkeypatch.setenv("MODEL_ACCESS_CODEX_VLAN_ENDPOINT", "https://changed.invalid")
    assert health_module._route_health_observation_key(route, intent) != key

    now = datetime.now(timezone.utc)
    observer = ProductHealthObserver(
        max_workers=1,
        max_in_flight=1,
        refresh_after_seconds=15,
        clock=lambda: now,
    )
    started = Event()
    release = Event()
    distinct_started = Event()
    calls = 0

    def slow_sampler():
        nonlocal calls
        calls += 1
        started.set()
        release.wait(2)
        return {"status": "available", "reason_code": "adapter_ready"}

    def distinct_sampler():
        distinct_started.set()
        return {"status": "available", "reason_code": "adapter_ready"}

    try:
        assert observer.observe(key, slow_sampler) is None
        assert started.wait(1)
        callers_ready = Barrier(8)

        def observe_same_key():
            callers_ready.wait()
            return observer.observe(key, slow_sampler)

        with ThreadPoolExecutor(max_workers=8) as callers:
            results = list(callers.map(lambda _index: observe_same_key(), range(8)))
        assert results == [None] * 8
        assert calls == 1
        distinct_key = health_module._route_health_observation_key(
            {**route, "model": "gpt-6-luna-next"}, intent
        )
        assert observer.observe(distinct_key, distinct_sampler) is None
        assert not distinct_started.is_set()

        release.set()
        deadline = time.monotonic() + 2
        sample = None
        while sample is None and time.monotonic() < deadline:
            sample = observer.observe(key, slow_sampler)
            if sample is None:
                Event().wait(0.01)
        assert sample is not None
        assert sample["status"] == "available"

        assert observer.observe(distinct_key, distinct_sampler) is None
        assert distinct_started.wait(1)
    finally:
        release.set()


def test_health_llm_router_reports_route_policies(monkeypatch) -> None:
    monkeypatch.setattr("app.config.llm._ACTIVE_PROVIDER", None)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    result = health_module._check_llm_router()

    assert result["ok"] is True
    assert "selected_defaults" in result
    assert "route_policies" in result
    assert result["route_policies"]["embed"]["effective"]["provider"] == "ollama"
    assert result["route_policies"]["embed"]["policy"]["require_compatible_identity"] is True


def test_health_llm_router_includes_configured_task_routes(monkeypatch) -> None:
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            tasks={
                "qa": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(provider="openai", model="gpt-5.4-mini")
                )
            }
        )
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    result = health_module._check_llm_router()

    assert "qa" in result["route_policies"]
    assert result["route_policies"]["qa"]["effective"]["provider"] == "openai"


def test_health_route_inventory_uses_caller_capability_contracts(monkeypatch) -> None:
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            tasks={
                "extract.summary": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(
                        provider="openai", model="gpt-5.6-luna"
                    )
                ),
                "tool": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(
                        provider="openai", model="gpt-5.6-luna"
                    )
                ),
                "custom_text": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(
                        provider="openai", model="gpt-5.6-luna"
                    )
                ),
            }
        )
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    policies = health_module._check_llm_router()["route_policies"]

    assert policies["decide"]["intent"]["json_schema_required"] is True
    assert policies["plan"]["intent"]["json_schema_required"] is True
    assert policies["extract.summary"]["intent"]["json_schema_required"] is True
    assert policies["tool"]["intent"]["json_schema_required"] is True
    assert policies["custom_text"]["intent"]["json_schema_required"] is False


def test_health_policy_projects_product_model_to_declared_portal_transport(monkeypatch) -> None:
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            tasks={
                "qa": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(
                        provider="openai", model="gpt-6-luna"
                    )
                )
            }
        )
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    route = health_module._check_llm_router()["route_policies"]["qa"]["effective"]

    assert route["provider"] == "openai"
    assert route["model"] == "gpt-6-luna"
    assert route["transport_id"] == "codex_cli_tailscale"


def test_schema_backed_caller_cannot_report_text_only_health_as_green(monkeypatch) -> None:
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            tasks={
                "decide": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(
                        provider="openai",
                        model="gpt-6-luna",
                        transport_id="codex_cli_tailscale",
                    )
                )
            }
        )
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    def _raise_structured_output_failure(*_args, **_kwargs):
        raise RemotePreflightError("structured_output_unavailable")

    monkeypatch.setattr(
        health_module,
        "get_chat_client_for_route",
        _raise_structured_output_failure,
    )
    policy = health_module._check_llm_router()["route_policies"]["decide"]

    result = health_module._check_llm_access({"route_policies": {"decide": policy}})

    assert policy["intent"]["json_schema_required"] is True
    assert result["ok"] is False
    assert result["capabilities"]["structured_output"] == {
        "status": "unavailable",
        "freshness": "fresh",
        "reason_code": "capability_unsupported",
    }


def test_health_route_projection_preserves_reasoning_effort(monkeypatch) -> None:
    bundle = SettingsBundle(
        llm_routing=LLMRoutingSettings(
            tasks={
                "qa": LLMRoutingSettings.TaskPolicy(
                    primary=LLMRoutingSettings.RouteTarget(
                        provider="openai",
                        model="gpt-6-luna",
                        transport_id="codex_cli_tailscale",
                        reasoning_effort="high",
                    )
                )
            }
        )
    )
    seen: dict[str, str | None] = {}

    def _provider_env_check(provider, model, **kwargs):
        if model == "gpt-6-luna":
            seen["provider"] = provider
            seen["reasoning_effort"] = kwargs.get("reasoning_effort")
        return {"ok": True, "detail": "preflight passed", "status": "ok"}

    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)
    monkeypatch.setattr(health_module, "_provider_env_check", _provider_env_check)

    route_check = health_module._check_llm_router()
    qa_route = route_check["route_policies"]["qa"]["effective"]
    assert qa_route["reasoning_effort"] == "high"

    result = health_module._check_llm_task_routes(route_check)

    assert result["routes"]["qa"]["status"] == "ok"
    assert seen == {"provider": "openai", "reasoning_effort": "high"}


def test_provider_env_check_uses_portal_without_local_credentials(monkeypatch) -> None:
    class _Client:
        model_access_route = SimpleNamespace(
            provider="openai",
            model="gpt-6-luna",
            transport_id="codex_cli_tailscale",
            preflight_status="passed",
        )

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(
        "OPENAI_BASE_URL",
        "https://operator:password@api.example.invalid/private?token=secret",
    )
    monkeypatch.setattr(
        health_module,
        "get_chat_client_for_route",
        lambda *_args, **_kwargs: _Client(),
    )

    result = health_module._provider_env_check("openai", "gpt-6-luna")

    assert result["ok"] is True
    assert result["preflight_status"] == "passed"
    assert "base_url" not in result
    assert all(
        secret not in repr(result)
        for secret in ("operator", "password", "private", "token", "secret")
    )


def test_health_task_routes_fail_when_effective_model_missing(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE", "https://api.example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    result = health_module._check_llm_task_routes(
        {
            "route_policies": {
                "qa": {
                    "effective": {"provider": "openai", "model": ""},
                }
            }
        }
    )

    assert result["ok"] is False
    assert result["routes"]["qa"]["status"] == "fail"
    assert result["routes"]["qa"]["detail"] == "route model is missing"


def test_health_codex_transport_uses_remote_preflight_not_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen = {}

    class _Client:
        model_access_route = SimpleNamespace(
            provider="openai",
            model="gpt-6-luna",
            transport_id="codex_cli_tailscale",
            preflight_status="passed",
        )

        def chat(self, *_args, **_kwargs):
            raise AssertionError("health must never dispatch a completion")

    def _get_chat_client_for_route(
        intent, *, selected_route, allow_fallback, allow_catalog_promotion
    ):
        seen["intent"] = intent
        seen["route"] = selected_route
        seen["allow_fallback"] = allow_fallback
        seen["allow_catalog_promotion"] = allow_catalog_promotion
        return _Client()

    monkeypatch.setattr(
        health_module, "get_chat_client_for_route", _get_chat_client_for_route
    )

    result = health_module._check_llm_task_routes(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "openai",
                        "model": "gpt-6-luna",
                        "transport_id": "codex_cli_tailscale",
                        "reasoning_effort": "low",
                    },
                    "intent": {"json_schema_required": False},
                }
            }
        }
    )

    assert result["ok"] is True
    route = result["routes"]["qa"]
    assert route["transport_id"] == "codex_cli_tailscale"
    assert route["status"] == "ok"
    assert route["preflight_status"] == "passed"
    assert seen["intent"].task_kind == "health"
    assert seen["route"].transport_id == "codex_cli_tailscale"
    assert seen["route"].model == "gpt-6-luna"
    assert seen["route"].timeout_seconds == health_module._health_probe_timeout()
    assert seen["allow_fallback"] is False
    assert seen["allow_catalog_promotion"] is False
    assert "endpoint" not in route


def test_llm_access_fails_closed_on_selected_route_preflight(monkeypatch) -> None:
    class _Client:
        model_access_route = SimpleNamespace(
            provider="openai",
            model="gpt-6-luna",
            transport_id="codex_cli_tailscale",
            preflight_status="failed",
        )

        def chat(self, *_args, **_kwargs):
            raise AssertionError("health must never dispatch a completion")

    def _get_chat_client_for_route(
        intent, *, selected_route, allow_fallback, allow_catalog_promotion
    ):
        assert intent.task_kind == "health"
        assert selected_route.model == "gpt-6-luna"
        assert allow_fallback is False
        assert allow_catalog_promotion is False
        return _Client()

    monkeypatch.setattr(
        health_module, "get_chat_client_for_route", _get_chat_client_for_route
    )

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

    assert result["ok"] is False
    assert result["capabilities"]["text_generation"]["status"] == "unavailable"


def test_unclassified_remote_path_failure_reports_unknown_capability(monkeypatch) -> None:
    def _get_chat_client_for_route(*_args, **_kwargs):
        raise RemotePreflightError("path_preflight_unclassified")

    monkeypatch.setattr(
        health_module, "get_chat_client_for_route", _get_chat_client_for_route
    )

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

    assert result["ok"] is False
    assert result["capabilities"]["text_generation"] == {
        "status": "unknown",
        "freshness": "fresh",
        "reason_code": "readiness_unknown",
    }
    assert result["transport_observation"]["status"] == "unknown"
    assert result["transport_observation"]["reason_code"] == "transport_unknown"


def test_typed_remote_path_failure_keeps_capability_unavailable(monkeypatch) -> None:
    def _get_chat_client_for_route(*_args, **_kwargs):
        raise RemotePreflightError("PATH_UNAVAILABLE")

    monkeypatch.setattr(
        health_module, "get_chat_client_for_route", _get_chat_client_for_route
    )

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

    assert result["ok"] is False
    assert result["capabilities"]["text_generation"]["status"] == "unavailable"
    assert result["transport_observation"]["status"] == "unavailable"


def test_remote_capability_preflight_failure_is_scoped(monkeypatch) -> None:
    failures = (
        ("structured_output_unavailable", "structured_output", "json_schema_required"),
        ("native_tools_unavailable", "native_tools", "native_tools_required"),
        (
            "literal_system_role_unavailable",
            "system_prompt_channel",
            "literal_system_role_required",
        ),
        ("output_token_limit_unavailable", "max_output_tokens", "max_output_tokens_required"),
    )

    for error_code, capability_id, intent_field in failures:
        def _raise_capability_failure(*_args, _code=error_code, **_kwargs):
            raise RemotePreflightError(_code)

        monkeypatch.setattr(
            health_module, "get_chat_client_for_route", _raise_capability_failure
        )
        result = health_module._check_llm_access(
            {
                "route_policies": {
                    "qa": {
                        "effective": {
                            "provider": "openai",
                            "model": "gpt-6-luna",
                            "transport_id": "codex_cli_tailscale",
                        },
                        "intent": {intent_field: True},
                    }
                }
            }
        )

        assert result["ok"] is False
        assert result["capabilities"][capability_id]["status"] == "unavailable"
        assert result["capabilities"][capability_id]["reason_code"] == "capability_unsupported"
        assert result["capabilities"]["text_generation"]["status"] == "unknown"
        assert result["capabilities"]["text_generation"]["reason_code"] == "readiness_unknown"
        assert result["transport_observation"]["status"] == "available"


def test_product_health_rejects_local_codex_cli_transport(monkeypatch) -> None:
    provider_env_checks: list[tuple[str, str]] = []

    def _provider_env_check(provider, model, **_kwargs):
        provider_env_checks.append((provider, model))
        return {"ok": True, "detail": "API credentials are configured"}

    monkeypatch.setattr(health_module, "_provider_env_check", _provider_env_check)

    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "openai",
                        "model": "gpt-5.6-luna",
                        "transport_id": "codex_cli",
                    },
                    "intent": {},
                }
            }
        }
    )

    assert result["ok"] is False
    assert result["capabilities"]["text_generation"] == {
        "status": "unavailable",
        "freshness": "fresh",
        "reason_code": "route_transport_unsupported",
    }
    assert result["transport_observation"]["status"] == "not_applicable"
    assert provider_env_checks == []


def test_selected_ollama_product_route_uses_portal_not_local_health(monkeypatch) -> None:
    seen: list[object] = []

    class _Client:
        model_access_route = SimpleNamespace(
            provider="ollama",
            model="llama3.1:8b",
            transport_id="ollama_http",
            preflight_status="passed",
            capabilities=SimpleNamespace(),
            degraded=False,
        )
        preflight_transport_observation = {
            "status": "available",
            "reason_code": "transport_reachable",
        }

        def chat(self, *_args, **_kwargs):
            raise AssertionError("health must never dispatch inference")

    def _get_chat_client_for_route(
        intent, *, selected_route, allow_fallback, allow_catalog_promotion
    ):
        assert intent.task_kind == "health"
        assert selected_route.provider == "ollama"
        assert selected_route.model == "llama3.1:8b"
        assert allow_fallback is False
        assert allow_catalog_promotion is False
        seen.append(selected_route)
        return _Client()

    monkeypatch.setattr(health_module, "get_chat_client_for_route", _get_chat_client_for_route)
    monkeypatch.setattr(
        health_module,
        "_provider_env_check",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("local provider env must not be checked")),
    )

    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "ollama",
                        "model": "llama3.1:8b",
                        "transport_id": "ollama_http",
                    },
                    "intent": {},
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
    assert set(result["capabilities"]) == {"text_generation"}
    assert len(seen) == 1
    assert result["transport_observation"]["status"] == "available"


def test_selected_ollama_product_route_fails_when_portal_preflight_fails(monkeypatch) -> None:
    class _Client:
        model_access_route = SimpleNamespace(
            provider="ollama",
            model="llama3.1:8b",
            transport_id="ollama_http",
            preflight_status="failed",
            capabilities=SimpleNamespace(),
            degraded=False,
        )
        preflight_transport_observation = {
            "status": "available",
            "reason_code": "transport_reachable",
        }

        def chat(self, *_args, **_kwargs):
            raise AssertionError("health must never dispatch inference")

    monkeypatch.setattr(
        health_module,
        "get_chat_client_for_route",
        lambda *_args, **_kwargs: _Client(),
    )
    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "ollama",
                        "model": "llama3.1:8b",
                        "transport_id": "ollama_http",
                    },
                    "intent": {},
                }
            }
        }
    )

    assert result["ok"] is False
    assert result["capabilities"]["text_generation"]["status"] == "unavailable"


def test_skipped_eval_ollama_route_is_not_probed(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_LLM_MODE", "skip")
    probed: list[str] = []

    def _probe_selected_route(task_kind, effective, intent, *, ollama_probe=None):
        probed.append(task_kind)
        return {
            "status": "available",
            "reason_code": "adapter_ready",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "capabilities": {"structured_output": True},
        }

    monkeypatch.setattr(health_module, "_probe_selected_route", _probe_selected_route)

    result = health_module._check_llm_access(
        {
            "route_policies": {
                "qa": {
                    "effective": {
                        "provider": "mock",
                        "model": "deterministic",
                        "transport_id": "mock",
                    },
                    "intent": {},
                },
                "eval": {
                    "effective": {
                        "provider": "ollama",
                        "model": "qwen-local",
                        "transport_id": "ollama_http",
                    },
                    "intent": {},
                },
            }
        }
    )

    assert result["ok"] is True
    assert probed == ["qa"]
    assert set(result["capabilities"]) == {"text_generation"}
