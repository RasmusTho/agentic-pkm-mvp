"""One read-only native Codex review through the existing guarded app-server."""

from __future__ import annotations

import json
import copy
import os
import re
import selectors
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from app.builderops import openhands_policy as policy


class ReviewError(RuntimeError):
    """The reviewer did not produce an unambiguous, guarded result."""

    def __init__(self, message: str, response: str | None = None) -> None:
        super().__init__(message)
        self.response = response


_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "head_sha": {"type": "string"},
        "verdict": {"type": "string", "enum": ["pass", "findings", "unresolved"]},
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"severity": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                           "description": {"type": "string"}, "file": {"type": "string"},
                           "line": {"type": "integer"}},
            "required": ["severity", "description", "file", "line"],
        }},
    },
    "required": ["head_sha", "verdict", "summary", "findings"],
}

_TRUSTED_BOOTSTRAP = (
    "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); "
    "runpy.run_module('app.builderops.openhands_proxy',run_name='__main__')"
)


def _startup_diagnostic(data: bytes) -> str:
    """Return only fixed, non-secret diagnoses; never echo process output."""
    text = data.decode("utf-8", errors="replace").casefold()
    if "invalid transport in mcp_servers" in text:
        return "Codex rejected an inherited MCP transport; inspect the disabled MCP configuration"
    if "no module named" in text and ("openhands_proxy" in text or "app.builderops" in text or "'app'" in text):
        return "The guarded proxy module could not be imported; inspect the factory source and Python path"
    if "sandbox_apply" in text or "sandbox-exec" in text:
        return "The operating-system sandbox could not be applied; inspect host sandbox availability"
    if "permission denied" in text or "operation not permitted" in text:
        return "Host permissions prevented reviewer startup; inspect the executable, configuration and temporary paths"
    if ("permissions.builder_factory.filesystem" in text or ":workspace_roots" in text) and any(
        term in text for term in ("invalid", "unknown", "parse", "failed", "error")
    ):
        return "Codex rejected the read-only workspace permission; inspect the reviewer filesystem profile"
    if ("config" in text or "permissions" in text) and any(
        term in text for term in ("invalid", "unknown", "parse", "failed", "error")
    ):
        return "Codex rejected or could not load the reviewer configuration; inspect the read-only profile"
    if any(term in text for term in ("not logged in", "authentication failed", "login required", "token refresh")):
        return "Codex subscription authentication was unavailable; inspect the existing login"
    return "No recognized non-secret startup diagnostic was available"


_POLICY_DIAGNOSTICS = {
    "subscription_auth_not_verified": "ChatGPT subscription authentication was not verified",
    "effective_model_or_provider_mismatch": "the effective model or provider did not match the approved profile",
    "model_not_permitted": "the requested model was not the approved Terra model",
    "provider_not_permitted": "the requested provider was not approved",
    "provider_route_not_verified": "the approved subscription provider route was not verified",
    "effective_permissions_mismatch": "the effective read-only sandbox profile did not match",
    "uncontrolled_external_tools": "inherited external tools were not disabled",
    "uncontrolled_execution_features": "inherited execution features were not disabled",
    "preflight_request_failed": "the guarded authentication or configuration preflight failed",
    "preflight_unavailable": "the guarded authentication or configuration preflight was unavailable",
    "model_rerouted": "the approved model was rerouted",
}


def _read_only_args(settings: dict[str, Any]) -> list[str]:
    args = list(settings["codex_config_args"])
    matches = [i for i, value in enumerate(args)
               if value.startswith("permissions.builder_factory.filesystem=")]
    if len(matches) != 1:
        raise ReviewError("Retained sandbox configuration is unavailable")
    entries = ['":minimal"="read"', '":workspace_roots"="read"']
    entries.extend(f"{json.dumps(root)}=\"read\"" for root in settings["sandbox_read_roots"])
    args[matches[0]] = "permissions.builder_factory.filesystem={" + ",".join(entries) + "}"
    return args


class _Rpc:
    def __init__(self, process: subprocess.Popen[bytes], timeout: float) -> None:
        if process.stdin is None or process.stdout is None:
            raise ReviewError("Reviewer transport is unavailable")
        self.process = process
        self.deadline = time.monotonic() + timeout
        self.pending = bytearray()
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)

    def send(self, value: dict[str, Any]) -> None:
        try:
            assert self.process.stdin is not None
            self.process.stdin.write((json.dumps(value) + "\n").encode())
            self.process.stdin.flush()
        except (OSError, BrokenPipeError) as exc:
            raise ReviewError("Reviewer transport failed") from exc

    def receive(self) -> dict[str, Any]:
        while b"\n" not in self.pending:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise ReviewError("Reviewer timed out")
            events = self.selector.select(timeout=remaining)
            if not events:
                raise ReviewError("Reviewer timed out")
            try:
                data = os.read(events[0][0].fd, 65536)
            except OSError as exc:
                raise ReviewError("Reviewer transport failed") from exc
            if not data:
                raise ReviewError("Reviewer exited before completing")
            self.pending.extend(data)
            if len(self.pending) > 4 * 1024 * 1024:
                raise ReviewError("Reviewer response exceeded the local limit")
        line, _, rest = self.pending.partition(b"\n")
        self.pending = bytearray(rest)
        try:
            message = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise ReviewError("Reviewer returned malformed protocol data") from exc
        if not isinstance(message, dict):
            raise ReviewError("Reviewer returned malformed protocol data")
        if message.get("method") in ("model/rerouted", "error", "turn/failed"):
            raise ReviewError("Reviewer reported a model or process failure")
        return message

    def response(self, request_id: int) -> dict[str, Any]:
        while True:
            message = self.receive()
            if message.get("id") == request_id:
                if "error" in message or not isinstance(message.get("result"), dict):
                    error = message.get("error")
                    code = error.get("message") if isinstance(error, dict) else None
                    detail = _POLICY_DIAGNOSTICS.get(code) if isinstance(code, str) else None
                    raise ReviewError("Reviewer request was refused or failed" + (f": {detail}" if detail else ""))
                return message["result"]


def _parse_result(text: str, head: str, doc_targets: list[str] | None = None) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    try:
        result = json.loads(text, object_pairs_hook=unique_object)
    except ValueError as exc:
        raise ReviewError("Reviewer verdict is not valid JSON") from exc
    expected_fields = {"head_sha", "verdict", "summary", "findings"}
    if doc_targets:
        expected_fields.add("doc_writebacks")
    if (not isinstance(result, dict) or set(result) != expected_fields
            or result["head_sha"] != head or not isinstance(result["verdict"], str)
            or result["verdict"] not in {"pass", "findings", "unresolved"}
            or not isinstance(result["summary"], str) or not result["summary"].strip()
            or not isinstance(result["findings"], list)):
        raise ReviewError("Reviewer verdict is incomplete or does not match the candidate")
    if doc_targets:
        checks = result["doc_writebacks"]
        if (not isinstance(checks, list) or len(checks) != len(doc_targets)
                or any(not isinstance(item, dict) or set(item) != {"target", "result", "rationale"}
                       or not isinstance(item.get("target"), str)
                       or not isinstance(item.get("result"), str)
                       or item["result"] not in {"pass", "fail", "unresolved"}
                       or not isinstance(item.get("rationale"), str) or len(item["rationale"].strip()) < 20
                       for item in checks)
                or sorted(item["target"] for item in checks) != sorted(doc_targets)):
            raise ReviewError("Reviewer document writeback results are incomplete or mismatched")
        # This incomplete check detects explicit uncertainty; it cannot prove semantic correctness.
        uncertain = re.compile(
            r"(?i)\b(?:cannot|can't|could not|did not|unable to|un(?:able|willing) to)\s+"
            r"(?:independently\s+)?(?:review|inspect|verify|assess|confirm|determine|read|check|access)\b"
            r"|\b(?:not|never)\s+(?:been\s+)?(?:reviewed|inspected|verified|assessed|confirmed|checked|examined|available)\b"
            r"|\b(?:insufficient|missing|unavailable|inadequate)\s+(?:evidence|information|content)\b"
            r"|\b(?:uncertain|unsure|unknown|unverified|unresolved)\b"
        )
        if any(item["result"] == "pass" and uncertain.search(item["rationale"]) for item in checks):
            raise ReviewError("Reviewer document writeback pass reports uncertainty or incomplete review")
    for item in result["findings"]:
        if (not isinstance(item, dict) or set(item) != {"severity", "description", "file", "line"}
                or not isinstance(item["severity"], str) or item["severity"] not in {"P0", "P1", "P2", "P3"}
                or not isinstance(item["description"], str) or not item["description"].strip()
                or not isinstance(item["file"], str) or not item["file"].strip()
                or type(item["line"]) is not int or item["line"] < 1):
            raise ReviewError("Reviewer findings are incomplete")
    if result["verdict"] == "pass" and re.search(
        r"(?i)\b(?:cannot|can't|could not|did not|unable to)\s+(?:review|inspect|verify|assess)\b"
        r"|\binsufficient\s+(?:evidence|information)\b", result["summary"]
    ):
        raise ReviewError("Reviewer reported an incomplete review")
    if result["verdict"] == "pass" and any(item["severity"] in {"P0", "P1"} for item in result["findings"]):
        raise ReviewError("Reviewer verdict conflicts with its blocking findings")
    if result["verdict"] == "findings" and not result["findings"]:
        raise ReviewError("Reviewer reported findings without details")
    return result


def run_review(
    python: Path, settings: dict[str, Any], workspace: Path, head: str, prompt: str,
    worker_session_id: str, *, timeout: float = 900, doc_targets: list[str] | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Return a structured result, the actual response text, and a new thread ID."""
    roots = settings["sandbox_read_roots"]
    env = {key: os.environ[key] for key in ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR") if key in os.environ}
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]), GIT_OPTIONAL_LOCKS="0",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               OPENHANDS_FACTORY_WORKSPACE=str(workspace), OPENHANDS_CODEX_BINARY=settings["codex_binary"],
               OPENHANDS_CODEX_CONFIG_ARGS=json.dumps(_read_only_args(settings)),
               OPENHANDS_FACTORY_READ_ROOTS=json.dumps(roots), OPENHANDS_FACTORY_READ_ONLY="1")
    try:
        process = subprocess.Popen([str(python), "-I", "-c", _TRUSTED_BOOTSTRAP,
                                    str(Path(__file__).resolve().parents[2]), "app-server"],
                                   cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True, bufsize=0)
    except OSError as exc:
        raise ReviewError("Cannot start guarded reviewer") from exc
    assert process.stderr is not None
    stderr_stream = process.stderr
    diagnostic_bytes = bytearray()

    def drain_stderr() -> None:
        try:
            while data := os.read(stderr_stream.fileno(), 4096):
                diagnostic_bytes.extend(data)
                if len(diagnostic_bytes) > 16384:
                    del diagnostic_bytes[:-16384]
        except (OSError, ValueError):
            pass

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()
    rpc = _Rpc(process, timeout)
    pending_error = None
    try:
        rpc.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"clientInfo": {"name": "builder-independent-review", "version": "1"}}})
        rpc.response(1)
        rpc.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        rpc.send({"jsonrpc": "2.0", "id": 2, "method": "thread/start",
                  "params": {"model": policy.MODEL, "cwd": str(workspace)}})
        thread_response = rpc.response(2)
        try:
            thread = policy.verify_thread_response(thread_response, workspace=workspace)
        except policy.PolicyRefusal as exc:
            raise ReviewError("Reviewer model or sandbox identity was not verified") from exc
        if thread == worker_session_id:
            raise ReviewError("Reviewer is not independent of the worker session")
        schema: dict[str, Any] = copy.deepcopy(_SCHEMA)
        if doc_targets:
            schema["properties"]["doc_writebacks"] = {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"target": {"type": "string"}, "result": {"type": "string", "enum": ["pass", "fail", "unresolved"]}, "rationale": {"type": "string"}},
                "required": ["target", "result", "rationale"]}}
            schema["required"].append("doc_writebacks")
        rpc.send({"jsonrpc": "2.0", "id": 3, "method": "turn/start", "params": {
            "threadId": thread, "model": policy.MODEL,
            "input": [{"type": "text", "text": prompt}], "outputSchema": schema,
        }})
        turn_id = None
        events = []
        while True:
            message = rpc.receive()
            if message.get("id") == 3:
                result = message.get("result")
                turn = result.get("turn") if isinstance(result, dict) else None
                if "error" in message or not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
                    raise ReviewError("Reviewer turn was refused or failed")
                turn_id = turn["id"]
            elif isinstance(message.get("method"), str) and message["method"] in {"item/completed", "turn/completed"}:
                events.append(message)
            if len(events) > 10000:
                raise ReviewError("Reviewer produced too many events")
            if turn_id is None:
                continue
            completed = [e["params"] for e in events if e.get("method") == "turn/completed"
                         and isinstance(e.get("params"), dict) and e["params"].get("threadId") == thread
                         and isinstance(e["params"].get("turn"), dict)
                         and e["params"]["turn"].get("id") == turn_id]
            if not completed:
                continue
            if len(completed) != 1 or completed[0]["turn"].get("status") != "completed" or completed[0]["turn"].get("error"):
                raise ReviewError("Reviewer turn did not complete successfully")
            messages = [e["params"]["item"] for e in events if e.get("method") == "item/completed"
                        and isinstance(e.get("params"), dict) and e["params"].get("threadId") == thread
                        and e["params"].get("turnId") == turn_id and isinstance(e["params"].get("item"), dict)
                        and e["params"]["item"].get("type") == "agentMessage"
                        and e["params"]["item"].get("phase") in (None, "final_answer")]
            if len(messages) != 1 or not isinstance(messages[0].get("text"), str):
                raise ReviewError("Reviewer final response is missing or ambiguous")
            text = messages[0]["text"]
            try:
                result = _parse_result(text, head, doc_targets)
            except ReviewError as exc:
                raise ReviewError(str(exc), response=text) from exc
            return result, text, thread
    except ReviewError as exc:
        pending_error = exc
    finally:
        rpc.selector.close()
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        stderr_thread.join(timeout=2)
        process.stderr.close()
    assert pending_error is not None
    failure_message = str(pending_error)
    if failure_message in {"Reviewer exited before completing", "Reviewer transport failed"}:
        failure_message += f" (exit {process.returncode}): {_startup_diagnostic(bytes(diagnostic_bytes))}"
    raise ReviewError(failure_message, response=pending_error.response) from pending_error
