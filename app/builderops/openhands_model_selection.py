"""Select from the installed OpenHands worker's native model control surfaces."""

from __future__ import annotations

import json
import os
import re
import signal
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOL_ID = re.compile(r"gpt-([1-9][0-9]{0,2})(?:\.([0-9]{1,3}))?-sol")
_CLAUDE_VERSION = r"([1-9][0-9]{0,2})(?:[-.]([0-9]{1,3}))?(?:-([0-9]{8}))?"
CLAUDE_ID = re.compile(r"claude-(sonnet|haiku|opus)-" + _CLAUDE_VERSION)
_CLAUDE_FABLE_ID = re.compile(r"claude-fable-" + _CLAUDE_VERSION)
_CLAUDE_ALIASES = frozenset({"default", "sonnet", "opus", "haiku", "fable"})
_CLAUDE_FAMILY_PREFERENCE = {"opus": 0, "haiku": 1, "sonnet": 2}
CODEX_CACHE_MAX_AGE_SECONDS = 300


class ModelSelectionError(ValueError):
    """The chosen engine's current selection could not be established."""


def model_generation(engine: str, model: str) -> tuple[int, int]:
    if engine == "codex":
        match = SOL_ID.fullmatch(model)
        return (int(match[1]), int(match[2] or 0)) if match else (0, 0)
    match = CLAUDE_ID.fullmatch(model)
    return (int(match[2]), int(match[3] or 0)) if match else (0, 0)


def claude_alias_matches(selector: str, model: str) -> bool:
    """Check a standard selectable alias against an exact wire ID."""
    match = CLAUDE_ID.fullmatch(model)
    if match:
        return selector in ("default", match[1])
    return selector in ("default", "fable") and _CLAUDE_FABLE_ID.fullmatch(model) is not None


def _claude_choices(visible: Mapping[str, None], read_sdk_models: Callable[[], Any] | None) -> dict[str, str]:
    aliases = _CLAUDE_ALIASES.intersection(visible)
    exact = {name: name for name in visible if CLAUDE_ID.fullmatch(name) or _CLAUDE_FABLE_ID.fullmatch(name)}
    if len(aliases) + len(exact) != len(visible):
        raise ModelSelectionError("Claude ACP catalog contains unsupported selectors")
    if not aliases:
        return exact
    rows = read_sdk_models() if read_sdk_models is not None else None
    if not isinstance(rows, list) or not 0 < len(rows) <= 512:
        raise ModelSelectionError("Claude SDK catalog readback is missing or invalid")

    resolved: dict[str, str] = {}
    seen: set[str] = set()
    for row in rows:
        if (not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str)
                or not 0 < len(row[0]) <= 100 or row[0] in seen):
            raise ModelSelectionError("Claude SDK catalog contains invalid or duplicate selectors")
        selector, wire = row
        seen.add(selector)
        if selector in exact and wire not in (None, selector):
            raise ModelSelectionError("Claude SDK catalog conflicts with an exact ACP selector")
        if selector in aliases:
            if not isinstance(wire, str) or not claude_alias_matches(selector, wire):
                raise ModelSelectionError("Claude SDK catalog contains unresolved or conflicting alias metadata")
            resolved[selector] = wire
    if resolved.keys() != aliases:
        raise ModelSelectionError("Claude SDK catalog is missing metadata for selectable ACP aliases")
    return {**exact, **resolved}


def _select_claude_model(visible: Mapping[str, None], model: str | None,
                         read_sdk_models: Callable[[], Any] | None) -> tuple[str, str]:
    if model is not None and model in visible:
        return model, model
    candidates = []
    for selector, wire in _claude_choices(visible, read_sdk_models).items():
        if (match := CLAUDE_ID.fullmatch(wire)) and (model is None or model == wire):
            # Default and the family alias can legitimately resolve to the same model.
            # Prefer its exact selector, then its named family alias, then default.
            candidates.append((model_generation("claude-code", wire), _CLAUDE_FAMILY_PREFERENCE[match[1]],
                               int(match[4] or 0), wire, selector == wire, selector != "default", selector))
    if not candidates:
        raise ModelSelectionError("Claude ACP catalog contains no eligible selectable exact model")
    _, _, _, wire, _, _, selector = max(candidates)
    return wire, selector


def select_from_catalog(engine: str, model: str | None, effort: str | None,
                        catalog: Any, *, read_claude_models: Callable[[], Any] | None = None
                        ) -> tuple[str, str | None, str]:
    """Select from one fresh native catalog and reject uncertain capabilities."""
    if not isinstance(catalog, Mapping) or "error" not in catalog or catalog["error"] is not None:
        raise ModelSelectionError(f"{engine} catalog refresh failed or is unavailable")
    if engine == "claude-code" and (catalog.get("agent_name") != "@agentclientprotocol/claude-agent-acp"
                                     or catalog.get("supports_runtime_model_switch") is not True):
        raise ModelSelectionError("Claude ACP catalog cannot establish native model selection")
    rows = catalog.get("available_models")
    if not isinstance(rows, list) or not rows or len(rows) > 512:
        raise ModelSelectionError(f"{engine} catalog is missing or invalid")
    visible: dict[str, None] = {}
    seen: set[str] = set()
    for row in rows:
        model_id = row.get("model_id") if isinstance(row, Mapping) else None
        hidden = row.get("hidden", False) if isinstance(row, Mapping) else None
        if not isinstance(model_id, str) or not model_id or model_id in seen or type(hidden) is not bool:
            raise ModelSelectionError(f"{engine} catalog contains invalid or ambiguous model entries")
        seen.add(model_id)
        if not hidden:
            visible[model_id] = None

    default = model is None
    if engine == "claude-code":
        model, selector = _select_claude_model(visible, model, read_claude_models)
    else:
        if default:
            candidates = [(version, name) for name in visible if (version := model_generation(engine, name)) >= (6, 2)]
            if not candidates:
                raise ModelSelectionError("Codex catalog contains no visible Sol newer than the explicit 6.1 compatibility choice")
            model = max(candidates)[1]
        if not isinstance(model, str) or model not in visible:
            raise ModelSelectionError(f"Exact {engine} model is absent from the visible native catalog")
        selector = model
    if effort is not None:
        efforts = catalog.get("efforts_by_model")
        options = efforts.get(model) if isinstance(efforts, Mapping) else None
        if not isinstance(options, list) or not any(
                isinstance(option, Mapping) and option.get("value") == effort for option in options):
            raise ModelSelectionError(f"{engine} catalog does not confirm {effort} effort for the selected model")
    if engine == "codex":
        cache = catalog.get("cache_models")
        cached_efforts = cache.get(model) if isinstance(cache, Mapping) else None
        if not isinstance(cached_efforts, list) or (effort is not None and effort not in cached_efforts):
            raise ModelSelectionError("Codex catalog selection lacks matching fresh native cache evidence")
        if default and isinstance(cache, Mapping) and any(
                isinstance(name, str) and model_generation(engine, name) > model_generation(engine, model) for name in cache):
            raise ModelSelectionError("Codex App Server catalog omits a newer visible Sol from its fresh native cache")
    return model, effort, selector


def read_codex_catalog(command: list[str]) -> dict[str, Any]:
    """Use stdio App Server initialization and model/list only, under the same native login."""
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as server:
        assert server.stdin is not None and server.stdout is not None
        stdin, stdout = server.stdin, server.stdout

        def send(method: str, params: dict[str, Any] | None = None, request_id: int | None = None) -> None:
            request: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                request["params"] = params
            if request_id is not None:
                request["id"] = request_id
            stdin.write(json.dumps(request).encode() + b"\n")
            stdin.flush()

        def receive(request_id: int) -> dict[str, Any]:
            for _ in range(64):
                line = stdout.readline(1_048_577)
                if not line.endswith(b"\n") or len(line) > 1_048_576:
                    break
                response = json.loads(line)
                if not isinstance(response, dict):
                    break
                if "id" not in response and isinstance(response.get("method"), str):
                    continue
                if response.get("id") == request_id and "error" not in response and isinstance(response.get("result"), dict):
                    return response["result"]
                break
            raise ModelSelectionError("Codex App Server model catalog request failed")

        try:
            send("initialize", {"clientInfo": {"name": "epic-workspace-catalog", "version": "1"}}, 1)
            receive(1)
            send("initialized")
            rows: list[dict[str, Any]] = []
            cursor, seen = None, set()
            for request_id in range(2, 10):
                send("model/list", {"includeHidden": False, "limit": 100, "cursor": cursor}, request_id)
                page = receive(request_id)
                if not isinstance(page.get("data"), list) or len(page["data"]) > 100:
                    raise ModelSelectionError("Codex App Server model catalog page is invalid")
                rows.extend(page["data"])
                cursor = page.get("nextCursor")
                if cursor is None:
                    break
                if not isinstance(cursor, str) or not cursor or len(cursor) > 512 or cursor in seen:
                    raise ModelSelectionError("Codex App Server model catalog is incomplete")
                seen.add(cursor)
            else:
                raise ModelSelectionError("Codex App Server model catalog pagination limit reached")
        finally:
            server.kill()

    models, efforts = [], {}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]
                or type(row.get("hidden", False)) is not bool or not isinstance(row.get("supportedReasoningEfforts"), list)
                or len(row["supportedReasoningEfforts"]) > 32):
            raise ModelSelectionError("Codex App Server returned an invalid catalog entry")
        name = row["id"]
        models.append({"model_id": name, "hidden": row.get("hidden", False)})
        efforts[name] = [{"value": option["reasoningEffort"]} for option in row["supportedReasoningEfforts"]]
    return {"available_models": models, "efforts_by_model": efforts, "error": None}


def read_fresh_codex_cache(path: Path, client_version: str, now: datetime) -> dict[str, list[str]]:
    """Confirm freshness and visible exact IDs in the native CLI's own model cache."""
    # This fixed catalog file is the only native file read by discovery. Auth stays inside the CLI.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ModelSelectionError("Codex native model cache is not a regular file")
        data = stream.read(4_194_305)
        if len(data) > 4_194_304:
            raise ModelSelectionError("Codex native model cache exceeds the read limit")
    cache = json.loads(data)
    if (not isinstance(cache, dict) or cache.get("client_version") != client_version
            or not isinstance(cache.get("fetched_at"), str) or not isinstance(cache.get("models"), list)):
        raise ModelSelectionError("Codex native model cache is invalid or from a different CLI version")
    fetched = datetime.fromisoformat(cache["fetched_at"].replace("Z", "+00:00"))
    if fetched.tzinfo is None or not 0 <= (now - fetched).total_seconds() <= CODEX_CACHE_MAX_AGE_SECONDS:
        raise ModelSelectionError("Codex native model cache timestamp is outside the freshness window")
    visible: dict[str, list[str]] = {}
    for row in cache["models"]:
        if not isinstance(row, dict) or not isinstance(row.get("slug"), str):
            raise ModelSelectionError("Codex native model cache contains invalid rows")
        slug = row["slug"]
        if row.get("visibility") != "list" or (slug != "gpt-6.1-terra" and not SOL_ID.fullmatch(slug)):
            continue
        options = row.get("supported_reasoning_levels")
        if slug in visible or not isinstance(options, list) or not all(
                isinstance(option, dict) and isinstance(option.get("effort"), str) for option in options):
            raise ModelSelectionError("Codex native model cache contains ambiguous model capabilities")
        visible[slug] = [option["effort"] for option in options]
    return visible


def main() -> None:
    def timed_out(signum: int, frame: Any) -> None:
        raise TimeoutError("Codex App Server model catalog deadline")

    signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(25)
    try:
        cache_path = Path(sys.argv[1])
        if os.environ.get("CODEX_HOME") != str(cache_path.parent):
            raise ModelSelectionError("Codex native model cache is outside the installed CLI's configured home")
        command = sys.argv[2:]
        cli = subprocess.run([*command[:-3], "--version"], capture_output=True, text=True, check=True, timeout=5)
        version = re.fullmatch(r"codex-cli (\d+\.\d+\.\d+(?:[-.][a-zA-Z0-9.]+)?)", cli.stdout.strip())
        if version is None:
            raise ModelSelectionError("Codex CLI version readback unavailable")
        catalog = read_codex_catalog(command)
        catalog["cache_models"] = read_fresh_codex_cache(cache_path, version[1], datetime.now(timezone.utc))
        print(json.dumps(catalog))
    except (OSError, RuntimeError, ValueError, KeyError, IndexError, TypeError, subprocess.SubprocessError):
        print("Codex App Server model catalog unavailable", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
