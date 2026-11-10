"""Fail-closed policy for the OpenHands-to-Codex app-server boundary.

This module does not grant access or launch an agent.  Its caller must also
establish the named Codex permissions profile and independently verify that
the operating system enforces it before accepting any task.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MODEL = "gpt-6.1-terra"
PROVIDER = "openai"
PROFILE = "builder_factory"
_READ_METHODS = frozenset({
    "initialized", "account/read", "account/rateLimits/read", "config/read",
    "model/list", "skills/list", "mcpServerStatus/list",
})
_THREAD_METHODS = frozenset({
    "thread/read", "thread/turns/list", "thread/items/list", "thread/unsubscribe",
    "thread/name/set", "turn/interrupt", "turn/steer",
})


class PolicyRefusal(ValueError):
    """A request is outside the authorized execution envelope."""


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PolicyRefusal("invalid_request")
    return value


def _requested_model(value: Any) -> None:
    if value is not None and value != MODEL:
        raise PolicyRefusal("model_not_permitted")


def prepare_request(
    message: dict[str, Any], *, workspace: Path, threads: set[str],
    resume_thread_id: str | None = None,
) -> dict[str, Any]:
    """Validate and constrain a client request without mutating the input.

    The ACP title helper uses an ephemeral thread and a different model.  It is
    refused before thread creation, so the primary session can continue.
    """
    msg = dict(_object(message))
    method = msg.get("method")
    params = dict(_object(msg.get("params") or {}))
    if method == "initialize":
        capabilities = dict(_object(params.get("capabilities") or {}))
        capabilities["experimentalApi"] = True
        params["capabilities"] = capabilities
    elif method in {"thread/start", "thread/resume"}:
        if params.get("ephemeral") is True:
            raise PolicyRefusal("ephemeral_helper_disabled")
        if method == "thread/start" and (threads or resume_thread_id):
            raise PolicyRefusal("additional_thread_not_permitted")
        if (method == "thread/resume" and params.get("threadId") not in threads
                and (resume_thread_id is None or params.get("threadId") != resume_thread_id)):
            raise PolicyRefusal("unknown_thread")
        _requested_model(params.get("model"))
        if params.get("modelProvider") not in (None, PROVIDER):
            raise PolicyRefusal("provider_not_permitted")
        cwd = params.get("cwd")
        if cwd is not None and Path(cwd).resolve() != workspace.resolve():
            raise PolicyRefusal("workspace_not_permitted")
        params.update(model=MODEL, modelProvider=PROVIDER, permissions=PROFILE,
                      approvalPolicy="never", cwd=str(workspace.resolve()))
        params.pop("sandbox", None)
        # Session-supplied configuration can otherwise change model, tools or
        # permission roots.  The host installs the fixed configuration instead.
        params["config"] = {}
    elif method == "turn/start":
        if params.get("threadId") not in threads:
            raise PolicyRefusal("unknown_thread")
        _requested_model(params.get("model"))
        # Native child agents make model requests inside the app-server, where
        # this transport cannot independently admit each child model.  Until a
        # tested child boundary exists, use a separate guarded review session.
        if params.get("collaborationMode") is not None:
            raise PolicyRefusal("collaboration_not_permitted")
        cwd = params.get("cwd")
        if cwd is not None and Path(cwd).resolve() != workspace.resolve():
            raise PolicyRefusal("workspace_not_permitted")
        params.update(model=MODEL, permissions=PROFILE, approvalPolicy="never")
        params.pop("sandboxPolicy", None)
    elif method in _THREAD_METHODS:
        if params.get("threadId") not in threads:
            raise PolicyRefusal("unknown_thread")
    elif method not in _READ_METHODS:
        raise PolicyRefusal("method_not_permitted")
    msg["params"] = params
    return msg


def verify_effective_config(
    config: dict[str, Any], account: dict[str, Any], *, allowed_read_roots: tuple[str, ...],
    workspace_writable: bool = True,
) -> None:
    """Refuse before thread creation if inherited tools or auth are unsafe."""
    config = _object(config)
    if _object(account).get("type") != "chatgpt":
        raise PolicyRefusal("subscription_auth_not_verified")
    if config.get("model") != MODEL or config.get("model_provider") != PROVIDER:
        raise PolicyRefusal("effective_model_or_provider_mismatch")
    if (
        config.get("chatgpt_base_url") != "https://chatgpt.com/backend-api/"
        or config.get("openai_base_url") is not None
        or bool(config.get("model_providers"))
    ):
        raise PolicyRefusal("provider_route_not_verified")
    features = _object(config.get("features") or {})
    if any(features.get(name) is not False for name in (
        "apps", "multi_agent", "js_repl", "hooks", "skill_mcp_dependency_install"
    )):
        raise PolicyRefusal("uncontrolled_execution_features")
    if config.get("notify") or config.get("web_search") != "disabled":
        raise PolicyRefusal("uncontrolled_execution_features")
    for key in ("mcp_servers", "plugins"):
        entries = _object(config.get(key) or {})
        if any(not isinstance(value, dict) or value.get("enabled", True) for value in entries.values()):
            raise PolicyRefusal("uncontrolled_external_tools")
    profile = _object(_object(config.get("permissions") or {}).get(PROFILE))
    if profile.get("extends") is not None or profile.get("workspace_roots"):
        raise PolicyRefusal("effective_permissions_mismatch")
    filesystem = {
        k: v for k, v in _object(profile.get("filesystem") or {}).items() if v is not None
    }
    expected = {":minimal": "read", ":workspace_roots": "write" if workspace_writable else "read"}
    expected.update({root: "read" for root in allowed_read_roots})
    network = _object(profile.get("network") or {})
    if filesystem != expected or network.get("enabled") is not False:
        raise PolicyRefusal("effective_permissions_mismatch")
    if any(value not in (None, False) for key, value in network.items() if key != "enabled"):
        raise PolicyRefusal("effective_permissions_mismatch")


def verify_thread_response(result: dict[str, Any], *, workspace: Path) -> str:
    """Require observed model, provider and named sandbox before any turn."""
    result = _object(result)
    if result.get("model") != MODEL or result.get("modelProvider") != PROVIDER:
        raise PolicyRefusal("effective_model_or_provider_mismatch")
    profile = result.get("activePermissionProfile")
    if not isinstance(profile, dict) or profile.get("id") != PROFILE:
        raise PolicyRefusal("effective_permissions_unknown")
    if result.get("approvalPolicy") != "never":
        raise PolicyRefusal("effective_approval_policy_mismatch")
    cwd = result.get("cwd")
    if not isinstance(cwd, str) or Path(cwd).resolve() != workspace.resolve():
        raise PolicyRefusal("effective_workspace_mismatch")
    thread = result.get("thread")
    thread_id = thread.get("id") if isinstance(thread, dict) else None
    if not isinstance(thread_id, str) or not thread_id:
        raise PolicyRefusal("thread_identity_unknown")
    return thread_id
