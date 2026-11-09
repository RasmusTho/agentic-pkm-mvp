"""A deterministic Canvas conversation for the existing OpenHands owner CLI.

This ACP endpoint makes no model requests. A user submits one explicit Issue
number; the existing factory owns admission, execution, verification and PRs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import socket
import subprocess
import uuid
from pathlib import Path
from typing import Any, cast

import acp
from acp.schema import AgentCapabilities, InitializeResponse, LoadSessionResponse, NewSessionResponse, PromptResponse

COMMAND = re.compile(r"/?(start|status|cancel|resume|stop|watch)\s+#?([1-9][0-9]{0,8})\s*", re.IGNORECASE)
HELP = ("Enter `start #123`, `status #123`, `cancel #123`, `resume #123`, `stop #123`, or `watch #123`. "
        "Start authorizes only that Issue; the factory checks its contract and ownership.")


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _summary(action: str, issue: int, result: dict[str, Any]) -> str:
    raw_state, raw_watcher = result.get("state"), result.get("watcher")
    state: dict[str, Any] = raw_state if isinstance(raw_state, dict) else {}
    watcher: dict[str, Any] = raw_watcher if isinstance(raw_watcher, dict) else {}
    raw_publication = state.get("full_publication")
    publication: dict[str, Any] = raw_publication if isinstance(raw_publication, dict) else {}
    pr = watcher.get("pr_number") or publication.get("pr_number")
    delivery_status = watcher.get("status")
    if delivery_status == "not_started" and type(pr) is int and pr > 0:
        delivery_status = "draft published"
    fields = [f"Issue #{issue}: {action} request completed."]
    for label, value in (("Conversation", result.get("conversation_status")),
                         ("Service", result.get("service_status")),
                         ("Run phase", state.get("phase")), ("Delivery", delivery_status),
                         ("Watcher phase", watcher.get("phase")),
                         ("Cancellation", result.get("cancel_status"))):
        if isinstance(value, str):
            fields.append(f"{label}: {value}.")
    reason = watcher.get("reason")
    if isinstance(reason, str) and len(reason) <= 240 and re.fullmatch(r"[A-Za-z0-9 .,;:_#()/-]+", reason):
        fields.append(f"Detail: {reason}.")
    if type(pr) is int and pr > 0:
        fields.append(f"Draft PR: https://github.com/RasmusTho/agentic-pkm-mvp/pull/{pr}")
    ci = watcher.get("ci")
    if isinstance(ci, dict) and isinstance(ci.get("status"), str):
        head = ci.get("head")
        revision = head if isinstance(head, str) and re.fullmatch(r"[0-9a-f]{40,64}", head) else "unknown"
        fields.append(f"Recorded CI: {ci['status']} (head {revision}); request a fresh check for current status.")
    recovery = result.get("recovery")
    if isinstance(recovery, dict) and recovery.get("continuation") == "blocked":
        fields.append("Continuation is blocked: previous execution and delegated work are not verified stopped.")
        execution = recovery.get("execution")
        if isinstance(execution, dict) and isinstance(execution.get("observed_descendants"), list):
            fields.append(f"Visible descendant processes: {len(execution['observed_descendants'])}; visibility is incomplete.")
        else:
            fields.append("Process readback is unavailable; execution status is unknown.")
        worktree = recovery.get("worktree")
        if isinstance(worktree, dict) and worktree.get("status") == "observed" and type(worktree.get("dirty")) is bool:
            fields.append("Worktree snapshot: " + ("changed." if worktree["dirty"] else "clean."))
        else:
            fields.append("Worktree readback is unavailable.")
        delegated = recovery.get("delegated_work")
        conversations = delegated.get("openhands_conversations") if isinstance(delegated, dict) else None
        known_statuses = {"running", "idle", "paused", "finished", "error", "stuck", "waiting_for_confirmation"}
        if isinstance(conversations, list) and all(
            isinstance(item, dict) and isinstance(item.get("status"), str) and item["status"] in known_statuses
            for item in conversations
        ):
            active = sum(item["status"] == "running" for item in conversations)
            fields.append(f"OpenHands child conversations: {len(conversations)} observed, {active} running; native child processes remain unverified.")
        else:
            fields.append("OpenHands child conversation readback is unavailable.")
        pr_readback = recovery.get("publication")
        if isinstance(pr_readback, dict) and pr_readback.get("status") == "ambiguous":
            fields.append("Publication readback is ambiguous; no new PR may be created.")
        elif isinstance(pr_readback, dict) and pr_readback.get("status") == "observed":
            matches = pr_readback.get("matching_prs")
            if isinstance(matches, list) and not matches:
                fields.append("No matching PR was found in GitHub readback.")
            elif isinstance(matches, list) and len(matches) == 1 and isinstance(matches[0], dict):
                pr_item = matches[0]
                if type(pr_item.get("number")) is int and pr_item["number"] > 0 and type(pr_item.get("draft")) is bool:
                    label = "Draft PR" if pr_item["draft"] else "Non-draft PR"
                    fields.append(f"{label}: https://github.com/RasmusTho/agentic-pkm-mvp/pull/{pr_item['number']}")
        else:
            fields.append("GitHub PR readback is unavailable; do not assume a PR was not created.")
    if action == "cancel":
        fields.append("Delegated-process cancellation has not been verified.")
    if result.get("conversation_readback_error") or result.get("service_status_error"):
        fields.append("Live readback is unavailable; inspect the recorded run.")
    if result.get("snapshot_notice"):
        fields.append("Run state changed during readback; request status again.")
    return "\n".join(fields)


def _invoke(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(args, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=240)
    except subprocess.TimeoutExpired:
        # Signal before reaping the group leader, so its PID cannot be reused
        # while a descendant in the same group is still running.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass  # Outcome remains uncertain; no retry is performed.
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        raise
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def run_command(entry: Path, message: str) -> str:
    if message.strip().lower() in {"help", "/help"}:
        return HELP
    match = COMMAND.fullmatch(message.strip())
    if match is None:
        return "Please use one explicit Issue command. " + HELP
    action, issue_text = match.groups()
    action, issue = action.lower(), int(issue_text)
    args = [str(entry), action, "--issue", str(issue)]
    if action == "start":
        try:
            args.extend(["--port", str(_port())])
        except OSError:
            return "No local worker port is available; no Issue was started."
    env = {k: os.environ[k] for k in ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR",
           "DISPATCHER_STATE_DIR", "DISPATCHER_DB_PATH", "DISPATCHER_EVENTS_PATH") if k in os.environ}
    try:
        result = _invoke(args, env)
    except (OSError, subprocess.TimeoutExpired):
        return f"Issue #{issue}: outcome is uncertain. Use `status #{issue}` before retrying."
    if result.returncode:
        diagnostics = {
            "No valid delivery state in this directory": "No run is recorded for this Issue.",
            "Issue does not have exactly agent:ready as its agent state":
                "The Issue is not ready for factory pickup.",
            "Issue is not open": "The Issue is not open.",
            "Continuation unavailable: previous execution and delegated work have not been independently reconciled; the recorded task and workspace are preserved":
                "Continuation is blocked until previous execution and delegated work are reconciled. The task and workspace are preserved.",
            "Existing branch, worktree or PR requires reconciliation":
                "Existing work needs reconciliation before starting.",
            "Another delivery is active or unresolved; inspect it before starting":
                "Another delivery is active or unresolved; inspect its status first.",
            "Another delivery has uncertain state; inspect it before starting":
                "Another delivery has uncertain state; inspect it first.",
        }
        diagnostic = result.stderr.strip().removeprefix("OpenHands factory: ")
        if diagnostic in diagnostics:
            return f"Issue #{issue}: {diagnostics[diagnostic]}"
        return f"Issue #{issue}: {action} did not complete. Use `status #{issue}` to inspect the recorded state."
    try:
        payload = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        return f"Issue #{issue}: outcome is uncertain. Use `status #{issue}` before retrying."
    if not isinstance(payload, dict):
        return f"Issue #{issue}: outcome is uncertain. Use `status #{issue}` before retrying."
    return _summary(action, issue, payload)


class OwnerAgent:
    def __init__(self, entry: Path) -> None:
        self.entry = entry
        self.client: Any = None
        self.session_id: str | None = None
        self.lock = asyncio.Lock()

    def on_connect(self, client: Any) -> None:
        self.client = client

    async def initialize(self, protocol_version: int, **kwargs: Any) -> InitializeResponse:
        return InitializeResponse(protocol_version=acp.PROTOCOL_VERSION,
                                  agent_capabilities=AgentCapabilities(load_session=True))

    async def new_session(self, cwd: str, **kwargs: Any) -> NewSessionResponse:
        if self.session_id is not None:
            raise ValueError("Only one owner control session is supported")
        self.session_id = str(uuid.uuid4())
        return NewSessionResponse(session_id=self.session_id)

    async def load_session(self, cwd: str, session_id: str, **kwargs: Any) -> LoadSessionResponse:
        if self.session_id is not None or str(uuid.UUID(session_id)) != session_id:
            raise ValueError("Owner control session is invalid")
        self.session_id = session_id
        return LoadSessionResponse()

    async def prompt(self, session_id: str, prompt: list[Any], **kwargs: Any) -> PromptResponse:
        if session_id != self.session_id or self.client is None:
            raise ValueError("Owner control session is unknown")
        if len(prompt) != 1 or getattr(prompt[0], "type", None) != "text":
            response = HELP
        else:
            async with self.lock:
                task = asyncio.create_task(asyncio.to_thread(run_command, self.entry, str(prompt[0].text)))
                try:
                    response = await asyncio.shield(task)
                except asyncio.CancelledError:
                    # The CLI may already have claimed or published. Keep the
                    # turn serialized until its exact outcome is recorded.
                    await task
                    raise
        await self.client.session_update(session_id, acp.update_agent_message_text(response))
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        # A start may already have external effects. Its recorded state must be
        # reconciled by `status`, never restarted implicitly on interruption.
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", type=Path, required=True)
    args = parser.parse_args()
    if not args.entry.is_absolute() or not args.entry.is_file() or not os.access(args.entry, os.X_OK):
        raise SystemExit("An absolute executable factory entry is required")
    # The SDK's Protocol includes optional methods this agent does not advertise.
    asyncio.run(acp.run_agent(cast(acp.Agent, OwnerAgent(args.entry))))


if __name__ == "__main__":
    main()
