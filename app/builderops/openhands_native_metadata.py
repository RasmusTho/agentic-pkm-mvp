"""Read bounded native session metadata for one retained OpenHands conversation.

Only native metadata is emitted. Native logs remain worker-controlled evidence, not attestation.
"""
from __future__ import annotations

import glob
import json
import os
import re
import stat
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

MAX_FILE = 64 * 1024 * 1024
MAX_LINE = 4 * 1024 * 1024
# Claude Code writes this zero-usage, non-inference record when same-conversation steering asks
# for no reply. Only this exact shape is skipped; any other synthetic record refuses.
_CONTROL_CONTENT = [{"type": "text", "text": "No response requested."}]
_CONTROL_COUNTERS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
_CONTROL_NULLS = {"output_tokens_details", "service_tier", "inference_geo", "iterations", "speed", "fallback_credit"}
_CONTROL_NESTED = {"server_tool_use": {"web_search_requests", "web_fetch_requests"},
                   "cache_creation": {"ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens"}}


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
            raise ValueError("native metadata file is invalid or too large")
        total = 0
        while True:
            line = stream.readline(MAX_LINE + 1)
            if not line:
                break
            total += len(line)
            if len(line) > MAX_LINE or total > MAX_FILE or not line.endswith(b"\n"):
                raise ValueError("native metadata line is incomplete or too large")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("native metadata record is invalid")
            yield row


def _codex(path: Path, session: str) -> dict[str, Any]:
    found = False
    context: tuple[str, str, str] | None = None
    executed: list[tuple[str, str, str]] = []
    for row in _rows(path):
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if row.get("type") == "session_meta":
            if found or payload.get("id") != session:
                raise ValueError("native session mismatch")
            found = True
        elif row.get("type") == "turn_context":
            model, effort, timestamp = payload.get("model"), payload.get("effort"), row.get("timestamp")
            if (not isinstance(model, str) or not model or not isinstance(effort, str) or not effort
                    or not isinstance(timestamp, str) or not timestamp):
                raise ValueError("native turn metadata missing")
            context = (model, effort, timestamp)
        elif row.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "assistant":
            if context is None:
                raise ValueError("native assistant lacks turn context")
            executed.append(context)
    if not found or not executed or len({(m, e) for m, e, _ in executed}) != 1:
        raise ValueError("native execution is missing or mixed")
    model, effort, timestamp = executed[-1]
    return {"session_id": session, "model": model, "effort": effort, "timestamp": timestamp}


def _zero(value: Any) -> bool:
    return type(value) is int and value == 0


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").tzinfo is not None
    except ValueError:
        return False


def _claude_control(row: dict[str, Any], message: dict[str, Any], session: str) -> bool:
    usage = message.get("usage")
    if (row.get("isApiErrorMessage") is not False or row.get("sessionId") != session
            or not _timestamp(row.get("timestamp")) or message.get("content") != _CONTROL_CONTENT
            or message.get("stop_reason") != "stop_sequence" or message.get("role", "assistant") != "assistant"
            or message.get("type", "message") != "message" or not isinstance(usage, dict)
            or not all(_zero(usage.get(key)) for key in _CONTROL_COUNTERS)):
        return False
    for key, value in usage.items():
        if key in _CONTROL_NULLS and value is not None:
            return False
        if key in _CONTROL_NESTED and value is not None and not (
                isinstance(value, dict) and set(value) <= _CONTROL_NESTED[key]
                and all(item is None or _zero(item) for item in value.values())):
            return False
        if key not in _CONTROL_NULLS and key not in _CONTROL_NESTED and key not in _CONTROL_COUNTERS:
            return False
    return True


def _claude(path: Path, session: str) -> dict[str, Any]:
    observed: list[tuple[str, str]] = []
    for row in _rows(path):
        if row.get("type") != "assistant":
            continue
        message = row.get("message")
        model, timestamp = message.get("model") if isinstance(message, dict) else None, row.get("timestamp")
        if row.get("isApiErrorMessage") is True and model == "<synthetic>":
            continue
        if model == "<synthetic>":
            if not isinstance(message, dict) or not _claude_control(row, message, session):
                raise ValueError("native synthetic record is not a recognized control")
            continue
        if row.get("sessionId") != session or not isinstance(model, str) or not model or not isinstance(timestamp, str):
            raise ValueError("native assistant identity missing")
        observed.append((model, timestamp))
    if not observed or len({model for model, _ in observed}) != 1:
        raise ValueError("native execution is missing or mixed")
    return {"session_id": session, "model": observed[-1][0], "effort": None, "timestamp": observed[-1][1]}


def observe(home: Path, codex_home: Path, engine: str, conversation: str) -> dict[str, Any]:
    cid = uuid.UUID(conversation)
    if str(cid) != conversation:
        raise ValueError("conversation identity is invalid")
    state_path = home / "openhands" / "conversations" / cid.hex / "base_state.json"
    # base state is a single JSON object; bound it separately from JSONL.
    if state_path.is_symlink() or state_path.stat().st_size > MAX_LINE:
        raise ValueError("conversation state is invalid")
    state = json.loads(state_path.read_bytes())
    agent = state.get("agent_state") if isinstance(state, dict) else None
    session = agent.get("acp_session_id") if isinstance(agent, dict) else None
    if (uuid.UUID(str(state.get("id"))) != cid or state.get("execution_status") not in ("finished", "FINISHED")
            or state.get("workspace", {}).get("working_dir") != "/workspace"
            or not isinstance(agent, dict) or agent.get("acp_session_cwd") != "/workspace"
            or not isinstance(session, str) or str(uuid.UUID(session)) != session):
        raise ValueError("conversation and native session do not agree")
    if engine == "codex":
        pattern = str(codex_home / "sessions" / "*" / "*" / "*" / f"rollout-*-{session}.jsonl")
        matches = glob.glob(pattern)
        if len(matches) != 1:
            raise ValueError("native session log is missing or ambiguous")
        result = _codex(Path(matches[0]), session)
    elif engine == "claude-code":
        result = _claude(home / ".claude" / "projects" / "-workspace" / f"{session}.jsonl", session)
    else:
        raise ValueError("unsupported engine")
    return {"engine": engine, "conversation_id": conversation, **result}


def main() -> None:
    try:
        if len(sys.argv) != 5:
            raise ValueError("invalid arguments")
        result = observe(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4])
        if not re.fullmatch(r"[A-Za-z0-9_.:+-]{1,100}", result["model"]):
            raise ValueError("invalid native model")
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        print("native metadata unavailable", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
