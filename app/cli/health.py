from __future__ import annotations

import importlib
import os
import shutil
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlsplit

from app.api.v6_seams import check_v6_seams
from app.components.llm.fabric import (
    describe_default_route_policies,
    describe_default_routes,
    get_chat_client_for_route,
)
from app.components.llm.router import LLMRoute, LLMTaskIntent
from app.services.companion_diagnostics import companion_diagnostics_summary
from app.events.outbox import default_outbox_path
from app.config.environment import active_environment
from app.eval.llm_client import DEFAULT_MODE as DEFAULT_EVAL_MODE
from app.knowledge.errors import KnowledgeConfigError
from app.knowledge.health import obsidian_dependency_status
from app.knowledge.settings import KnowledgeAdapter, load_knowledge_settings
from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.capability_health import (
    aggregate_capability_health,
    aggregate_transport_health,
)
from app.model_access.codex_remote_transport import RemotePreflightError
from app.cli.settings_explain import mask_dsn
from app.observability.log import span, with_trace_id
from app.version import get_runtime_version
from app.runtime.health_probe import _watcher_runtime_status, _worker_runtime_status
from app.settings.ingestion import get_settings_ingestion_state
from app.settings.panel_actions import get_panel_actions_diagnostics
from app.stores.db_health import ping_postgres, resolve_dsn

_TRUE_VALUES = {"1", "true", "yes", "on"}

def _result(ok: bool, detail: str, *, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": ok, "detail": detail}
    if data:
        out["data"] = data
    return out


def _exception_kind(exc: Exception) -> str:
    return type(exc).__name__


def _safe_endpoint_origin(value: str) -> str:
    """Keep health output useful without exposing URL credentials or paths."""
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host:
            return "[configured]"
        rendered_host = f"[{host}]" if ":" in host else host
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme}://{rendered_host}{port}"
    except ValueError:
        return "[configured]"


def _health_probe_timeout() -> float:
    """Return the short health-only timeout without coupling to generation."""
    try:
        return float(os.environ.get("HEALTH_PROBE_TIMEOUT", "2"))
    except (TypeError, ValueError):
        return 2.0


def _annotate_required(payload: Dict[str, Any], *, required: bool, severity: str | None = None) -> Dict[str, Any]:
    payload["required"] = required
    payload["severity"] = severity or ("required" if required else "optional")
    return payload


def _watcher_required() -> bool:
    raw = os.getenv("WATCHER_HEARTBEAT_REQUIRED")
    if not raw:
        return False
    return raw.strip().lower() in _TRUE_VALUES


def _check_ffmpeg() -> Dict[str, Any]:
    ok = shutil.which("ffmpeg") is not None
    detail = "ffmpeg hittades i PATH" if ok else "ffmpeg saknas i PATH"
    return _result(ok, detail)


def _check_yt_dlp() -> Dict[str, Any]:
    try:
        importlib.import_module("yt_dlp")
        return _result(True, "yt-dlp kan importeras")
    except Exception as exc:  # pragma: no cover - import side-effects differ per env
        return _result(False, f"yt-dlp import misslyckades ({_exception_kind(exc)})")


def _check_panel_actions() -> Dict[str, Any]:
    diag = get_panel_actions_diagnostics()
    count = diag.get("panel_actions_mappings_count") or 0
    resolved = diag.get("resolved_panel_actions_root")
    error = diag.get("last_panel_mapping_load_error")
    if count > 0:
        detail = f"panel actions loaded ({count})"
    elif resolved is None:
        detail = "panel actions root not resolved"
    elif error:
        detail = f"panel actions load error: {error}"
    else:
        detail = "panel actions root missing or empty"
    return _result(True, detail, data={"resolved_root": resolved, "count": count})


def _check_dead_letters() -> Dict[str, Any]:
    """Read-only dead-letter signal reflecting the health-contract fields (KERNEL-12 / #2774).

    Mirrors `dead_lettered_count` / `oldest_undelivered_age_seconds` from
    `HealthContract.evaluate()` via the shared `dead_letter_snapshot()` helper,
    so the CLI check and the `/healthz`-`/readyz` contract snapshot can never
    disagree on the computation. Detection only — no auto-repair.
    """
    try:
        from app.health_contract import dead_letter_snapshot

        snap = dead_letter_snapshot()
    except Exception as exc:
        return _result(
            True,
            f"dead-letter signal unavailable ({_exception_kind(exc)})",
            data={"skipped": True},
        )
    status = snap["dead_letter_status"]
    ok = status == "pass"
    if status == "pass":
        detail = "no dead-lettered outbox events above threshold"
    elif status == "unknown":
        detail = "dead-letter signal unavailable; outbox tail could not be read safely"
    else:
        detail = (
            f"dead-letter breach: {snap['dead_lettered_count']} dead-lettered event(s), "
            f"oldest undelivered {snap['oldest_undelivered_age_seconds']:.1f}s"
        )
    return _result(ok, detail, data=dict(snap))


def _check_outbox_path() -> Dict[str, Any]:
    path = default_outbox_path()
    if not path.exists():
        return _result(
            False,
            f"Index-outbox path saknas: {path}",
            data={"path": str(path), "status": "missing"},
        )
    if not path.is_file() or not os.access(path, os.R_OK | os.W_OK):
        return _result(
            False,
            f"Index-outbox path är inte läs-/skrivbar: {path}",
            data={"path": str(path), "status": "unavailable"},
        )
    return _result(
        True,
        f"Index-outbox path är läs-/skrivbar: {path}",
        data={"path": str(path), "status": "ready"},
    )


def _check_llm_router() -> Dict[str, Any]:
    forced_provider = os.getenv("LLM_FORCE_PROVIDER")
    forced_model = os.getenv("LLM_FORCE_MODEL")
    return {
        "ok": True,
        "detail": "router ready",
        "selected_defaults": describe_default_routes(),
        "route_policies": describe_default_route_policies(),
        "forced_overrides": {
            "provider": forced_provider or "",
            "model": forced_model or "",
        },
    }


def _provider_env_check(
    provider: str,
    model: str,
    *,
    transport_id: str | None = None,
    reasoning_effort: str | None = None,
    structured_output_required: bool = False,
    native_tools_required: bool = False,
    literal_system_role_required: bool = False,
    determinism_required: bool = False,
) -> Dict[str, Any]:
    normalized = (provider or "").strip().lower()
    resolved_model = (model or "").strip()
    if not resolved_model:
        return {"ok": False, "detail": "route model is missing", "status": "fail"}
    if transport_id in _PRODUCT_UNSUPPORTED_TRANSPORTS:
        return {
            "ok": False,
            "detail": "Product route transport is unsupported",
            "status": "fail",
        }
    if normalized in {"", "mock", "deterministic"}:
        return {"ok": True, "detail": f"deterministic/local route ({resolved_model})", "status": "ok"}
    try:
        intent = LLMTaskIntent(
            task_kind="health",
            json_schema_required=structured_output_required,
            native_tools_required=native_tools_required,
            literal_system_role_required=literal_system_role_required,
            determinism_required=determinism_required,
        )
        client = get_chat_client_for_route(
            intent,
            selected_route=LLMRoute(
                provider=normalized,
                model=resolved_model,
                mode="chat",
                reason="health-preflight",
                timeout_seconds=_health_probe_timeout(),
                transport_id=transport_id,
                reasoning_effort=reasoning_effort,
            ),
            allow_fallback=False,
            allow_catalog_promotion=False,
        )
        bound_route = client.model_access_route
        if bound_route is None:
            return {
                "ok": False,
                "detail": "shared route facade returned no bound model route",
                "status": "fail",
            }
        ready = bound_route.preflight_status == "passed"
        return {
            "ok": ready,
            "detail": (
                "Product model-access preflight passed"
                if ready
                else f"Product model-access preflight {bound_route.preflight_status}"
            ),
            "status": "ok" if ready else "fail",
            "provider": bound_route.provider,
            "model": bound_route.model,
            "transport_id": bound_route.transport_id,
            "preflight_status": bound_route.preflight_status,
        }
    except Exception as exc:
        return {
            "ok": False,
            "detail": f"Product model-access preflight failed ({_exception_kind(exc)})",
            "status": "fail",
        }


def _check_llm_task_routes(
    router_check: Dict[str, Any],
) -> Dict[str, Any]:
    policies = router_check.get("route_policies") or {}
    route_statuses: Dict[str, Any] = {}
    overall = True

    for task_kind, item in policies.items():
        effective = item.get("effective") or {}
        provider = str(effective.get("provider") or "").strip().lower()
        model = str(effective.get("model") or "").strip()
        transport_id = str(effective.get("transport_id") or "").strip() or None
        reasoning_effort = str(effective.get("reasoning_effort") or "").strip() or None
        intent = item.get("intent") or {}
        eval_mode = (os.getenv("EVAL_LLM_MODE") or DEFAULT_EVAL_MODE).strip().lower() or DEFAULT_EVAL_MODE
        if task_kind == "eval" and eval_mode == "skip":
            route_statuses[task_kind] = {
                "ok": True,
                "detail": "eval skipped",
                "status": "skipped",
                "provider": provider,
                "model": model,
            }
            continue
        probe = _provider_env_check(
            provider,
            model,
            transport_id=transport_id,
            reasoning_effort=reasoning_effort,
            structured_output_required=bool(intent.get("json_schema_required")),
            native_tools_required=bool(intent.get("native_tools_required")),
            literal_system_role_required=bool(
                intent.get("literal_system_role_required")
            ),
            determinism_required=bool(intent.get("determinism_required")),
        )
        route_statuses[task_kind] = {
            "ok": bool(probe.get("ok")),
            "detail": probe.get("detail", ""),
            "status": probe.get("status", "fail"),
            "provider": probe.get("provider", provider),
            "model": probe.get("model", model),
            "transport_id": probe.get("transport_id", transport_id),
            "preflight_status": probe.get("preflight_status"),
            "base_url": probe.get("base_url"),
        }
        if probe.get("ok") is False:
            overall = False

    detail = "task routes ready" if overall else "one or more task routes are not ready"
    return {"ok": overall, "detail": detail, "routes": route_statuses}


_EMBEDDING_TASK_KINDS = {"embed", "embedding", "embeddings"}
_REMOTE_EXECUTOR_TRANSPORTS = {"codex_cli_tailscale", "ollama_http_tailscale"}
_PRODUCT_UNSUPPORTED_TRANSPORTS = {"codex_cli"}
_NETWORK_PATH_FAILURE_CODES = {
    "PATH_UNAVAILABLE",
    "CONNECT_TIMEOUT",
    "PREFLIGHT_TIMEOUT",
    "PATH_AUTHENTICATION_FAILED",
}
_LOCAL_PREFLIGHT_FAILURE_CODES = {
    "preflight_request_invalid",
    "preflight_request_too_large",
}
_CAPABILITY_INTENT_FIELDS = {
    "structured_output": "json_schema_required",
    "native_tools": "native_tools_required",
    "system_prompt_channel": "literal_system_role_required",
    "deterministic_execution": "determinism_required",
    "max_output_tokens": "max_output_tokens_required",
}
_REMOTE_PREFLIGHT_CAPABILITY_FAILURES = {
    "structured_output_unavailable": "structured_output",
    "native_tools_unavailable": "native_tools",
    "literal_system_role_unavailable": "system_prompt_channel",
    "output_token_limit_unavailable": "max_output_tokens",
}


def _transport_observation(
    status: str, reason_code: str, observed_at: str
) -> Dict[str, str]:
    return {
        "status": status,
        "reason_code": reason_code,
        "observed_at": observed_at,
    }


def _transport_observation_for_failure(
    transport_id: str | None,
    exc: Exception,
    observed_at: str,
    *,
    remote_executor: bool | None = None,
) -> Dict[str, str]:
    if remote_executor is None:
        remote_executor = transport_id in _REMOTE_EXECUTOR_TRANSPORTS
    if not remote_executor:
        return _transport_observation(
            "not_applicable", "transport_not_required", observed_at
        )
    if not isinstance(exc, RemotePreflightError):
        return _transport_observation("unknown", "transport_unknown", observed_at)
    if exc.code in _NETWORK_PATH_FAILURE_CODES:
        return _transport_observation(
            "unavailable", "transport_unavailable", observed_at
        )
    if (
        exc.code in _LOCAL_PREFLIGHT_FAILURE_CODES
        or exc.code == "path_preflight_unclassified"
    ):
        return _transport_observation("unknown", "transport_unknown", observed_at)
    # A sanitized preflight response means a network path reached the executor,
    # even when that executor reports an unavailable route or capability.
    return _transport_observation("available", "transport_reachable", observed_at)


def _client_transport_observation(
    transport_id: str | None,
    client: Any,
    observed_at: str,
    *,
    remote_executor: bool | None = None,
) -> Dict[str, str]:
    if remote_executor is None:
        remote_executor = transport_id in _REMOTE_EXECUTOR_TRANSPORTS
    if not remote_executor:
        return _transport_observation(
            "not_applicable", "transport_not_required", observed_at
        )
    observation = getattr(client, "preflight_transport_observation", None)
    if not isinstance(observation, dict):
        return _transport_observation("unknown", "transport_unknown", observed_at)
    status = observation.get("status")
    reason_code = observation.get("reason_code")
    if not isinstance(status, str) or status not in {
        "available",
        "degraded",
        "unavailable",
        "unknown",
    }:
        return _transport_observation("unknown", "transport_unknown", observed_at)
    if not isinstance(reason_code, str):
        reason_code = "transport_unknown"
    return _transport_observation(status, reason_code, observed_at)


@lru_cache(maxsize=1)
def _health_adapter_factory() -> ModelAccessAdapterFactory:
    return ModelAccessAdapterFactory.from_declared_sources()


def _probe_selected_route(
    task_kind: str,
    effective: Dict[str, Any],
    intent: Dict[str, Any],
) -> Dict[str, Any]:
    """Ask the selected adapter for no-inference readiness and declared capabilities."""
    provider = str(effective.get("provider") or "").strip().lower()
    model = str(effective.get("model") or "").strip()
    transport_id = str(effective.get("transport_id") or "").strip() or None
    reasoning_effort = str(effective.get("reasoning_effort") or "").strip() or None
    policy_degraded = effective.get("degraded") is True or str(
        effective.get("degraded") or ""
    ).strip().lower() == "true"
    observed_at = datetime.now(timezone.utc).isoformat()
    if not provider or not model:
        return {
            "status": "unavailable",
            "reason_code": "route_not_configured",
            "observed_at": observed_at,
            "capabilities": {},
            "transport_observation": _transport_observation(
                "unknown" if transport_id in _REMOTE_EXECUTOR_TRANSPORTS else "not_applicable",
                "transport_unknown" if transport_id in _REMOTE_EXECUTOR_TRANSPORTS else "transport_not_required",
                observed_at,
            ),
        }
    if transport_id in _PRODUCT_UNSUPPORTED_TRANSPORTS:
        # The local Codex CLI adapter is registered for Model Inquiry/Builder
        # callers, but the Product completion facade explicitly refuses it.
        # Do not let an OpenAI API environment check stand in for this route.
        return {
            "status": "unavailable",
            "reason_code": "route_transport_unsupported",
            "observed_at": observed_at,
            "capabilities": {},
            "transport_observation": _transport_observation(
                "not_applicable", "transport_not_required", observed_at
            ),
        }

    structured_output = intent.get("json_schema_required") is True
    native_tools = intent.get("native_tools_required") is True
    literal_system_role = intent.get("literal_system_role_required") is True
    determinism = intent.get("determinism_required") is True
    uses_product_portal = provider not in {"", "mock", "deterministic"}
    transport_observation = _transport_observation(
        "unknown" if uses_product_portal else "not_applicable",
        "transport_unknown" if uses_product_portal else "transport_not_required",
        observed_at,
    )
    try:
        if uses_product_portal:
            client = get_chat_client_for_route(
                LLMTaskIntent(
                    task_kind="health",
                    json_schema_required=structured_output,
                    native_tools_required=native_tools,
                    literal_system_role_required=literal_system_role,
                    determinism_required=determinism,
                ),
                selected_route=LLMRoute(
                    provider=provider,
                    model=model,
                    mode="chat",
                    reason="health-preflight",
                    degraded=policy_degraded,
                    timeout_seconds=_health_probe_timeout(),
                    transport_id=transport_id,
                    reasoning_effort=reasoning_effort,
                ),
                allow_fallback=False,
                allow_catalog_promotion=False,
            )
            transport_observation = _client_transport_observation(
                transport_id,
                client,
                observed_at,
                remote_executor=True,
            )
            bound_route = getattr(client, "model_access_route", None)
            if bound_route is None:
                return {
                    "status": "unknown",
                    "reason_code": "readiness_unknown",
                    "observed_at": observed_at,
                    "capabilities": {},
                    "transport_observation": transport_observation,
                }
            preflight_status = getattr(bound_route, "preflight_status", None)
            if preflight_status == "passed":
                ready = True
            elif preflight_status in {"failed", "unavailable"}:
                ready = False
            else:
                return {
                    "status": "unknown",
                    "reason_code": "readiness_unknown",
                    "observed_at": observed_at,
                    "capabilities": {},
                    "transport_observation": transport_observation,
                }
            declared = getattr(bound_route, "capabilities", None)
            route_degraded = bool(getattr(bound_route, "degraded", False))
        else:
            factory = _health_adapter_factory()
            adapter_id = transport_id or factory.default_adapter_id(provider)
            descriptor = factory.describe(adapter_id, provider=provider, model=model)
            # Legacy in-process adapters expose no shared preflight operation yet.
            # Their adapter-specific checker is contained here; aggregation below
            # consumes only a neutral status and declared adapter capabilities.
            adapter_probe = _provider_env_check(
                provider,
                model,
                transport_id=transport_id,
                reasoning_effort=reasoning_effort,
                structured_output_required=structured_output,
                native_tools_required=native_tools,
                literal_system_role_required=literal_system_role,
                determinism_required=determinism,
            )
            ready = adapter_probe.get("ok") is True
            declared = descriptor.supported_capabilities
            route_degraded = policy_degraded
    except Exception as exc:
        transport_observation = _transport_observation_for_failure(
            transport_id,
            exc,
            observed_at,
            remote_executor=uses_product_portal,
        )
        capability_status = "unavailable"
        capability_reason = "adapter_unavailable"
        capability_overrides: dict[str, dict[str, str]] = {}
        if (
            isinstance(exc, RemotePreflightError)
            and exc.code in _REMOTE_PREFLIGHT_CAPABILITY_FAILURES
        ):
            # The executor rejected one requested capability before checking
            # runtime readiness. Name that capability, and leave the rest
            # unknown instead of marking the entire route unavailable.
            capability_status = "unknown"
            capability_reason = "readiness_unknown"
            failed_capability = _REMOTE_PREFLIGHT_CAPABILITY_FAILURES[exc.code]
            capability_overrides[failed_capability] = {
                "status": "unavailable",
                "reason_code": "capability_unsupported",
            }
        if uses_product_portal and (
            not isinstance(exc, RemotePreflightError)
            or exc.code in _LOCAL_PREFLIGHT_FAILURE_CODES
            or exc.code == "path_preflight_unclassified"
        ):
            # No adapter capability result exists when the executor path fails
            # before classification. Preserve that uncertainty in capability
            # health instead of claiming that the configured route rejected it.
            capability_status = "unknown"
            capability_reason = "readiness_unknown"
        return {
            "status": capability_status,
            "reason_code": capability_reason,
            "observed_at": observed_at,
            "capabilities": {},
            "capability_overrides": capability_overrides,
            "transport_observation": transport_observation,
        }

    if not ready:
        status, reason_code = "unavailable", "adapter_unavailable"
    elif route_degraded:
        status, reason_code = "degraded", "readiness_degraded"
    else:
        status, reason_code = "available", "adapter_ready"

    capabilities = {
        capability_id: getattr(declared, capability_id, None)
        for capability_id in _CAPABILITY_INTENT_FIELDS
        if capability_id != "max_output_tokens"
    }
    return {
        "status": status,
        "reason_code": reason_code,
        "observed_at": observed_at,
        "capabilities": capabilities,
        "transport_observation": transport_observation,
    }


def _required_capabilities(intent: Dict[str, Any]) -> set[str]:
    required = {"text_generation"}
    required.update(
        capability_id
        for capability_id, intent_field in _CAPABILITY_INTENT_FIELDS.items()
        if intent.get(intent_field) is True
    )
    return required


def _route_capability_observations(
    required: set[str], probe: Dict[str, Any]
) -> list[dict[str, Any]]:
    route_status = probe.get("status")
    route_reason = probe.get("reason_code")
    observed_at = probe.get("observed_at")
    declared = probe.get("capabilities")
    overrides = probe.get("capability_overrides")
    observations: list[dict[str, Any]] = []
    for capability_id in sorted(required):
        override = overrides.get(capability_id) if isinstance(overrides, dict) else None
        if isinstance(override, dict):
            override_status = override.get("status")
            status = (
                override_status
                if isinstance(override_status, str)
                and override_status in {"available", "degraded", "unavailable", "unknown"}
                else "unknown"
            )
            reason_code = (
                override.get("reason_code")
                if isinstance(override.get("reason_code"), str)
                else "readiness_unknown"
            )
        elif route_status != "available":
            status = route_status if route_status in {"degraded", "unavailable", "unknown"} else "unknown"
            reason_code = route_reason if isinstance(route_reason, str) else "readiness_unknown"
        elif capability_id == "text_generation":
            status, reason_code = "available", "adapter_ready"
        elif capability_id == "max_output_tokens":
            status, reason_code = "unknown", "capability_not_observable"
        else:
            intent_field = _CAPABILITY_INTENT_FIELDS.get(capability_id)
            capability_value = declared.get(capability_id) if isinstance(declared, dict) else None
            if intent_field is None or not isinstance(capability_value, bool):
                status, reason_code = "unknown", "capability_not_observable"
            elif capability_value:
                status, reason_code = "available", "adapter_ready"
            else:
                status, reason_code = "unavailable", "capability_unsupported"
        observations.append(
            {
                "capability_id": capability_id,
                "status": status,
                "observed_at": observed_at,
                "reason_code": reason_code,
            }
        )
    return observations


def _check_llm_access(router_check: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate configured text-route readiness as logical capabilities."""
    policies = router_check.get("route_policies") or {}
    text_policies = {
        task_kind: policy
        for task_kind, policy in policies.items()
        if str(task_kind).strip().lower() not in _EMBEDDING_TASK_KINDS
    }
    if not text_policies:
        result = aggregate_capability_health(
            {"text_generation"},
            [
                {
                    "capability_id": "text_generation",
                    "status": "unknown",
                    "reason_code": "route_not_configured",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        )
        return {
            **result,
            "transport_observation": aggregate_transport_health([]),
            "detail": "no text-generation routes are configured",
        }

    eval_mode = (
        (os.getenv("EVAL_LLM_MODE") or DEFAULT_EVAL_MODE).strip().lower()
        or DEFAULT_EVAL_MODE
    )
    active_text_policies = [
        (task_kind, policy)
        for task_kind, policy in text_policies.items()
        if not (str(task_kind).strip().lower() == "eval" and eval_mode == "skip")
    ]
    if not active_text_policies:
        result = aggregate_capability_health(
            {"text_generation"},
            [
                {
                    "capability_id": "text_generation",
                    "status": "unknown",
                    "reason_code": "route_not_configured",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        )
        return {
            **result,
            "transport_observation": aggregate_transport_health([]),
            "detail": "no active text-generation routes are configured",
        }
    required: set[str] = set()
    observations: list[dict[str, Any]] = []
    transport_observations: list[dict[str, Any]] = []
    for task_kind, policy in active_text_policies:
        effective = policy.get("effective") or {}
        intent = policy.get("intent") or {}
        if not isinstance(intent, dict):
            intent = {}
        route_required = _required_capabilities(intent)
        required.update(route_required)
        probe = _probe_selected_route(
            str(task_kind), effective if isinstance(effective, dict) else {}, intent,
        )
        observations.extend(_route_capability_observations(route_required, probe))
        transport_observation = probe.get("transport_observation")
        if not isinstance(transport_observation, dict):
            provider = (
                str(effective.get("provider") or "").strip().lower()
                if isinstance(effective, dict)
                else ""
            )
            remote = provider not in {"", "mock", "deterministic"}
            transport_observation = _transport_observation(
                "unknown" if remote else "not_applicable",
                "transport_unknown" if remote else "transport_not_required",
                str(probe.get("observed_at") or ""),
            )
        transport_observations.append(transport_observation)

    result = aggregate_capability_health(required, observations)
    transport_health = aggregate_transport_health(transport_observations)
    detail = (
        "required model capabilities available"
        if result["ok"]
        else "one or more required model capabilities are not freshly available"
    )
    return {
        **result,
        "transport_observation": transport_health,
        "detail": detail,
    }


def _check_embedding_index() -> Dict[str, Any]:
    try:
        from app.index.doctor import diagnose_index

        diag = diagnose_index()
    except Exception as exc:
        return {"ok": False, "detail": f"index doctor failed ({_exception_kind(exc)})", "status": "fail"}

    rebuild_required = bool(diag.get("rebuild_required"))
    empty_index = bool(diag.get("empty_index"))
    compatible_identity = diag.get("compatible_identity")
    detail: str
    status: str
    if rebuild_required:
        detail = str(diag.get("rebuild_reason") or "embedding identity rebuild required")
        status = "rebuild_required"
    elif empty_index:
        detail = "vector index is empty; no rebuild required yet"
        status = "empty"
    elif compatible_identity is False:
        detail = "embedding identity is not compatible with stored index"
        status = "fail"
    elif compatible_identity is None:
        detail = "no stored embedding identity to compare yet"
        status = "unknown"
    else:
        detail = "embedding identity is compatible with the current index"
        status = "ok"
    return {
        "ok": not rebuild_required,
        "detail": detail,
        "status": status,
        "expected_identity": diag.get("expected_identity"),
        "stored_identity": diag.get("stored_identity"),
        "compatible_identity": compatible_identity,
        "empty_index": empty_index,
        "rebuild_required": rebuild_required,
        "rebuild_reason": diag.get("rebuild_reason"),
        "issues": diag.get("issues") or [],
        "warnings": diag.get("warnings") or [],
        # #2324: metadata/provenance completeness + coverage-gap findings. These are
        # read-only diagnostics surfaced alongside the identity-drift status above; they
        # do not affect `ok`/`rebuild_required` (no auto-repair from a health check), but
        # let an operator see completeness/coverage drift without running the CLI doctor
        # separately.
        "metadata_completeness": diag.get("metadata_completeness"),
        "vault_coverage": diag.get("vault_coverage"),
    }


def _check_llm_providers(_router_check: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Expose declared provider inventory; live readiness belongs to llm_access."""
    from app.components.settings.providers_loader import load_provider_census

    census = load_provider_census()
    declared = sorted(census.projection("app/services/llm.py::_DISPATCH_PROVIDERS"))
    return {
        "ok": True,
        "detail": "provider declarations loaded; selected-route readiness is reported by llm_access",
        "providers": [{"name": item, "declared": True} for item in declared],
    }


def _obsidian_required() -> bool:
    explicit_policy = any(
        os.getenv(name) is not None
        for name in ("KNOWLEDGE_PRIMARY_ADAPTER", "KNOWLEDGE_STRICT_STARTUP", "KNOWLEDGE_ALLOW_FALLBACK")
    )
    if not explicit_policy:
        return False
    try:
        settings = load_knowledge_settings()
    except KnowledgeConfigError:
        return True
    if settings.strict_startup:
        return True
    if settings.primary_adapter != KnowledgeAdapter.OBSIDIAN_CLI:
        return False
    return not settings.allow_fallback


def _get_obsidian_installer_version() -> str | None:
    env_version = (os.getenv("OBSIDIAN_INSTALLER_VERSION") or "").strip()
    if env_version:
        return env_version
    try:
        proc = subprocess.run(
            ["obsidian", "version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        raw = (proc.stdout or proc.stderr or "").strip()
        return raw or None
    except Exception:
        return None


def _check_obsidian_dependencies() -> Dict[str, Any]:
    try:
        settings = load_knowledge_settings()
    except KnowledgeConfigError as exc:
        return _result(False, f"knowledge settings invalid ({_exception_kind(exc)})")
    status = obsidian_dependency_status(get_installer_version=_get_obsidian_installer_version)
    data = {
        **status.details,
        "primary_adapter": settings.primary_adapter.value,
        "fallback_adapter": settings.fallback_adapter.value,
        "strict_startup": settings.strict_startup,
        "allow_fallback": settings.allow_fallback,
    }
    if status.ok:
        return _result(True, "Obsidian dependency checks passed", data=data)
    return _result(False, "Obsidian dependency checks failed", data=data)


def _db_runtime_status() -> Dict[str, Any]:
    backend = (os.getenv("STORE_BACKEND") or "memory").strip().lower()
    dsn_value = resolve_dsn()
    if backend != "pg" and not dsn_value:
        return {"ok": True, "detail": "skipped (memory mode)", "status": "skipped"}
    if not dsn_value:
        return {"ok": False, "detail": "DATABASE_URL missing for postgres backend", "status": "missing"}
    ok, detail = ping_postgres(timeout=1.0)
    return {"ok": ok, "detail": detail, "dsn": mask_dsn(dsn_value)}


def _llm_runtime_status(check_result: Dict[str, Any]) -> Dict[str, Any]:
    ok = bool(check_result.get("ok"))
    return {
        "ok": ok,
        "detail": check_result.get("detail", ""),
        "capabilities": dict(check_result.get("capabilities") or {}),
        "transport_observation": dict(
            check_result.get("transport_observation") or {}
        ),
        "status": "ok" if ok else "fail",
    }


def _runtime_ok(runtime: dict[str, dict[str, Any]]) -> bool:
    base_ok = bool(
        runtime.get("db", {}).get("ok")
        and runtime.get("llm", {}).get("ok")
        and runtime.get("worker", {}).get("ok")
    )
    if _watcher_required():
        return base_ok and bool(runtime.get("watcher", {}).get("ok"))
    return base_ok


def _checks_ok(checks: dict[str, dict[str, Any]]) -> bool:
    return all(item.get("ok") for item in checks.values() if item.get("required", True))


def _required_checks_ok(checks: dict[str, dict[str, Any]]) -> bool:
    return _checks_ok(checks)


def _suggested_actions(checks: dict[str, dict[str, Any]], runtime: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    ffmpeg = checks.get("ffmpeg", {})
    if ffmpeg.get("ok") is False:
        actions.append(
            {
                "id": "ffmpeg_missing",
                "severity": "optional",
                "message": "ffmpeg missing; media transcription features disabled",
                "command_hint": "",
            }
        )

    embedding_index = checks.get("embedding_index", {})
    if embedding_index.get("rebuild_required"):
        actions.append(
            {
                "id": "index_rebuild",
                "severity": "required",
                "message": str(embedding_index.get("detail") or "Embedding/index identity mismatch detected"),
                "command_hint": "python -m app.cli index rebuild --profile default",
            }
        )

    llm_access = checks.get("llm_access", {})
    capabilities = llm_access.get("capabilities", {})
    unavailable_capabilities = sorted(
        capability_id
        for capability_id, observation in capabilities.items()
        if isinstance(observation, dict)
        and observation.get("status") != "available"
    )
    if unavailable_capabilities:
        actions.append(
            {
                "id": "model_capabilities_unavailable",
                "severity": "required",
                "message": "One or more required model capabilities are unavailable or stale",
                "command_hint": "Inspect capability status and trace_id in the health result",
            }
        )

    watcher_runtime = runtime.get("watcher", {})
    enqueue_failures = watcher_runtime.get("enqueue_failures_total")
    if isinstance(enqueue_failures, int) and enqueue_failures > 0:
        actions.append(
            {
                "id": "watcher_outbox_enqueue_failed",
                "severity": "required",
                "message": "Watcher failed to enqueue DB outbox events",
                "command_hint": "Check DATABASE_URL and watcher logs",
            }
        )

    worker_runtime = runtime.get("worker", {})
    worker_status = str(worker_runtime.get("status") or "").lower()
    if worker_status in {"missing", "stale", "invalid", "malformed", "future"}:
        actions.append(
            {
                "id": "worker_restart",
                "severity": "required",
                "message": "Worker heartbeat unhealthy; restart the worker service",
                "command": "docker compose restart worker",
            }
        )
    elif worker_status == "blocked_pending_mvr06":
        actions.append(
            {
                "id": "worker_binding_blocked",
                "severity": "required",
                "message": "Worker has pending rows that do not match its active binding",
                "command_hint": "Keep rows pending for governed MVR-06 resolution",
            }
        )

    dead_letters = checks.get("dead_letters", {})
    if dead_letters.get("ok") is False:
        actions.append(
            {
                "id": "outbox_dead_letters",
                "severity": "required",
                "message": str(dead_letters.get("detail") or "Dead-lettered outbox events detected"),
                "command_hint": "grep outbox.event.dead_lettered $INDEX_OUTBOX_PATH",
            }
        )

    obsidian = checks.get("obsidian", {})
    if obsidian.get("ok") is False and obsidian.get("required"):
        actions.append(
            {
                "id": "obsidian_dependency_missing",
                "severity": "required",
                "message": "Obsidian CLI/installer dependency check failed",
                "command_hint": "Install/update Obsidian installer (>=1.12.4) and ensure `obsidian` is in PATH",
            }
        )

    return actions


def _check_companion_diagnostics() -> Dict[str, Any]:
    vault_root = Path(os.getenv("VAULT_ROOT") or "vault").expanduser()
    try:
        summary = companion_diagnostics_summary(vault_root)
    except Exception as exc:
        return _result(True, f"companion diagnostics skipped ({_exception_kind(exc)})", data={"skipped": True})
    count = summary["duplicate_companion_count"]
    ok = count == 0
    detail = "no duplicate companion notes" if ok else f"{count} duplicate companion note(s) detected"
    return _result(ok, detail, data=dict(summary))


def _check_authority_spine() -> Dict[str, str]:
    """Return bounded authority/provenance posture for the runtime governance spine.

    This is a diagnostic surface only. It does not grant or deny authority.
    Values are bounded status strings safe for operator inspection.
    """
    try:
        from app.health_contract import DEFAULT_CONTRACT, WRITE_BLOCKED_STATES

        state = DEFAULT_CONTRACT.state_machine.state
        write_guard_posture = "blocked" if state in WRITE_BLOCKED_STATES else "active"
    except Exception:
        write_guard_posture = "unavailable"

    return {
        "write_guard": write_guard_posture,
        "authority_non_upgrade": "enforced",
        "provenance_required_for_mutations": "yes",
        "read_projection_isolation": "active",
    }


def _settings_ingestion_status() -> Dict[str, Any]:
    """Effective-settings ingestion state (SET-1): ok / degraded_last_valid /
    invalid_sources / no_vault, so a bad vault edit is visible on the surface
    instead of silently running on code defaults."""
    return get_settings_ingestion_state().to_payload()


@span("health.check")
def run_health(*, trace_id: str | None = None, **kwargs: Any) -> Dict[str, Any]:
    trace_id = with_trace_id(trace_id)
    checks = {
        "ffmpeg": _annotate_required(_check_ffmpeg(), required=False),
        "yt_dlp": _annotate_required(_check_yt_dlp(), required=False),
        "index_outbox": _annotate_required(_check_outbox_path(), required=True),
        # Alerting signal only (KERNEL-12): loud on the surface, but not a
        # required check — a dead-letter breach must not flip the aggregate
        # probe that drives container restarts, and never blocks writes.
        "dead_letters": _annotate_required(_check_dead_letters(), required=False),
        "panel_actions": _annotate_required(_check_panel_actions(), required=False),
        "obsidian": _annotate_required(_check_obsidian_dependencies(), required=_obsidian_required()),
    }
    checks["llm_router"] = _annotate_required(_check_llm_router(), required=False)
    llm_access = _check_llm_access(checks["llm_router"])
    checks["llm_access"] = _annotate_required(llm_access, required=True)
    checks["llm_task_routes"] = _annotate_required(
        {
            **llm_access,
            "capabilities": dict(llm_access.get("capabilities") or {}),
        },
        required=True,
    )
    checks["llm_providers"] = _annotate_required(
        _check_llm_providers(checks["llm_router"]), required=False
    )
    checks["embedding_index"] = _annotate_required(_check_embedding_index(), required=True)
    checks["companion_diagnostics"] = _annotate_required(_check_companion_diagnostics(), required=False)

    runtime = {
        "watcher": _watcher_runtime_status(),
        "worker": _worker_runtime_status(),
        "db": _db_runtime_status(),
        "llm": _llm_runtime_status(checks["llm_access"]),
    }
    checks_ok = _checks_ok(checks)
    runtime_ok = _runtime_ok(runtime)
    ok = bool(checks_ok and runtime_ok)
    required_ok = bool(_required_checks_ok(checks) and runtime_ok)
    suggested_actions = _suggested_actions(checks, runtime)
    runtime_version = get_runtime_version()
    return {"environment": active_environment(), "ok": ok, "required_ok": required_ok, "checks": checks, "runtime": runtime, "settings": _settings_ingestion_status(), "trace_id": trace_id, "suggested_actions": suggested_actions, "v6_0_seams": check_v6_seams(), "authority_spine": _check_authority_spine(), "version": runtime_version.get("git_sha", "unknown")}
__all__ = ["run_health"]
