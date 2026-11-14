"""Model-free owner conversation; existing work is read-only, controls own one sandbox."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, cast

REPO = "https://github.com/RasmusTho/agentic-pkm-mvp"
WORKER = "owner-sandbox"


class OwnerAccessError(RuntimeError):
    """A fixed, credential-free diagnostic suitable for the owner conversation."""


def _controller(config: dict[str, Any], *args: str) -> dict[str, Any]:
    # Use the frozen controller, including its lifecycle/port/auth-home locks.
    bootstrap = (
        "import sys;sys.path.insert(0,sys.argv.pop(1));"
        "from app.builderops import epic_workspace as e;"
        "from functools import partial;"
        "e.start_openhands_worker=partial(e.start_openhands_worker,"
        "image='epic-worker@sha256:3c3c2472b35ea3ccb0df57df7cc9d2303f582dcb2987b259124c9df946d56644',"
        "network='epicws-6615-egress-20261114');"
        "e.OPENHANDS_PORT_RANGE=range(18840,18848);raise SystemExit(e.main())"
    )
    result = subprocess.run(
        ["python3", "-c", bootstrap, config["runner"], "--root", config["root"],
         "--epic", str(config["sandbox_epic"]), *args],
        capture_output=True, text=True, timeout=180, check=False,
    )
    if result.returncode:
        # Controller diagnostics can include paths; never echo subprocess stderr or keys.
        if "already mounted" in result.stderr or "codex-home" in result.stderr:
            raise OwnerAccessError("The shared native slot is busy. Existing work was preserved; request status and retry later.")
        raise OwnerAccessError("Sandbox operation refused or incomplete. Request status; no automatic retry.")
    return json.loads(result.stdout)


def render_status(state: dict[str, Any], observations: dict[str, Any] | None = None) -> str:
    lines = [f"## Epic #6615 — observation, not delivery acceptance\n\n[GitHub epic]({REPO}/issues/6615)",
             "GitHub issues, PRs and their current checks are delivery truth. This snapshot may lag the active owner's latest comment."]
    for issue, mapping in state.get("issue_mappings", {}).items():
        if not str(issue).isdigit() or not isinstance(mapping, dict):
            continue
        conversation = mapping.get("conversation") or {}
        live = (observations or {}).get(str(issue), {})
        lines.extend([
            f"\n### [Issue #{issue}]({REPO}/issues/{issue}) — {mapping.get('worker', 'unknown')}",
            f"Recorded workspace state: {mapping.get('state', 'unknown')}; branch: `{mapping.get('branch', 'unknown')}`.",
            f"OpenHands conversation: `{conversation.get('id', 'unavailable')}`; selected engine/model: "
            f"{conversation.get('engine', 'unknown')} / {conversation.get('model', 'unknown')}.",
            f"Live conversation: {live.get('execution_status') or 'unavailable (stopped, busy or not verified reachable)'}. "
            f"Latest observed activity: {live.get('latest_event') or 'unavailable'}.",
            f"Recorded next action: {str(mapping.get('next_action', 'unknown'))[:1600]}",
        ])
    lines.extend([
        f"\n[PR #6628 — current CI/review/delivery evidence]({REPO}/pull/6628)",
        f"[Active #6618 owner and blockers]({REPO}/issues/6618#issuecomment-6876526692)",
        "Responsible delivery owner: the existing Epic #6615 execution session and its issue owners. "
        "Native subagents/process descendants are opaque: unknown is not zero or verified stopped. "
        "Conversation completion/activity does not establish merge or issue completion.",
        "\n`status` refreshes this read-only snapshot. `sandbox start`, `sandbox status`, `sandbox stop` "
        "control only the separate owner sandbox. Existing epic workers cannot be controlled here.",
    ])
    return "\n\n".join(lines)


def _sandbox_profile(config: dict[str, Any]) -> None:
    """Select the existing upstream ACP profile surface so Canvas enables its composer."""
    code = """import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from app.builderops import epic_workspace as e
e.OPENHANDS_PORT_RANGE=range(18840,18848)
l=e.Layout(Path(sys.argv[2]),int(sys.argv[3]))
m=e._load_state(l)['issue_mappings'][sys.argv[3]]
expected={'agent_kind':'acp','acp_server':'codex','acp_model':'gpt-6.1-terra','mcp_server_refs':[],'secret_refs':[],'integration_refs':[]}
with e._endpoint_session(l,'owner-sandbox',int(sys.argv[3]),m,e.subprocess.run) as (port,key):
 code,data=e._http('GET',port,key,'/agent-profiles/owner-sandbox',None,10)
 if code==404:
  code,_=e._http('POST',port,key,'/agent-profiles/owner-sandbox',expected,10)
  if code not in (200,201): raise ValueError('profile creation uncertain')
  code,data=e._http('GET',port,key,'/agent-profiles/owner-sandbox',None,10)
 p=data.get('profile',{})
 if code!=200 or any(p.get(k)!=v for k,v in expected.items()): raise ValueError('profile mismatch')
 code,_=e._http('POST',port,key,'/agent-profiles/'+p['id']+'/activate',None,10)
 if code!=200:raise ValueError('profile activation unavailable')
"""
    result = subprocess.run(["python3", "-c", code, config["runner"], config["root"], str(config["sandbox_epic"])],
                            capture_output=True, text=True, timeout=60, check=False)
    if result.returncode:
        raise OwnerAccessError("Sandbox ACP profile is not verified; no UI readiness is claimed.")


def status(config: dict[str, Any]) -> str:
    # Import the reviewed controller in a child process, so neither source nor active runner changes.
    code = """import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from app.builderops import epic_workspace as e
l=e.Layout(Path(sys.argv[2]),6615)
s=e._load_state(l)
out={}
for issue,m in s.get('issue_mappings',{}).items():
 if m.get('state')=='running':
  try: out[issue]=e.conversation_status(l,m['worker'],limit=5,include_messages=False)
  except (OSError,ValueError,e.EpicWorkspaceError): pass
print(json.dumps({'state':s,'observations':out}))
"""
    result = subprocess.run(["python3", "-c", code, config["runner"], config["root"]],
                            capture_output=True, text=True, timeout=60, check=False)
    if result.returncode:
        return f"Live status unavailable. Read [the epic's latest comments]({REPO}/issues/6615). Nothing was started or stopped."
    data = json.loads(result.stdout)
    return render_status(data["state"], data["observations"])


def run_command(config: dict[str, Any], text: str) -> str:
    command = text.strip().lower()
    if command in {"status", "status #6615", "workers"}:
        return status(config)
    if command == "sandbox start":
        current = _controller(config, "status")
        worker = next((w for w in current.get("workers", []) if w.get("worker") == WORKER), None)
        if not worker:
            raise OwnerAccessError("Sandbox has not been provisioned; no worker was created.")
        started = worker.get("container") != "running"
        if started:
            if worker.get("recorded_state") == "stopped_verified":
                _controller(config, "takeover", "--worker", WORKER, "--reason", "owner requested sandbox restart")
            _controller(config, "openhands-start", "--worker", WORKER, "--cpus", "0.7", "--memory", "1500m",
                        "--pids", "256", "--codex-home", config["codex_home"])
        _sandbox_profile(config)
        observation = _controller(config, "conversation-status", "--worker", WORKER)
        record = observation.get("conversation") or {}
        if not record or record.get("status") == "ended_with_container":
            _controller(config, "conversation-start", "--worker", WORKER, "--engine", "codex", "--model",
                        "gpt-6.1-terra", "--prompt-file", config["readiness_prompt"])
        elif record.get("status") in {"creating", "unknown"}:
            _controller(config, "conversation-reconcile", "--worker", WORKER)
        observed = _controller(config, "conversation-status", "--worker", WORKER)
        if not observed.get("reachable") or (observed.get("conversation") or {}).get("status") != "created":
            return "Sandbox conversation is not verified reachable. Request `sandbox status`; no readiness or task execution is claimed."
        if observed.get("execution_status") == "error":
            return "Sandbox conversation reports an engine error; task submission is not ready. Request `sandbox status`. No engine switch or automatic replay was attempted."
        conversation = observed.get("conversation") or {}
        url = config['sandbox_url'] + '/conversations/' + str(conversation.get('id', ''))
        return (f"Owner sandbox is running. [Open sandbox Canvas]({url}). "
                "Open the existing owner-sandbox conversation and send a bounded scratch/read-only task. "
                "New Conversation is disabled: one admitted conversation protects the shared checkout. Native Codex gpt-6.1-terra, "
                "existing ChatGPT subscription only. No automatic publication/merge. Return here and use "
                "`sandbox stop` when finished to release the shared native slot. A busy slot refuses start; it never stops another worker.")
    if command == "sandbox stop":
        _controller(config, "worker-stop", "--worker", WORKER, "--reason", "owner stopped disposable sandbox")
        return "Owner sandbox container stopped with controller readback; workspace/history retained. Existing epic workers were untouched. Use `sandbox start` for an explicit restart; it does not replay a task."
    if command == "sandbox status":
        data = _controller(config, "status")
        workers = data.get("workers", [])
        return "\n".join(f"{w['worker']}: container {w.get('container', 'unknown')}; recorded {w.get('recorded_state', 'unknown')}. "
                         "Retained work is preserved; activity is not delivery." for w in workers)
    return ("## BOB-1 owner access\n\n"
            "Enter `status` to inspect Epic #6615, workers, blockers and delivery links.\n\n"
            "Enter `sandbox start`, then open the returned Canvas link and the existing conversation for your next bounded "
            "scratch/read-only task. The single native slot may be busy with existing work. "
            "In sandbox Canvas, Stop interrupts the conversation; sending another message continues that conversation "
            "while its server is alive. It does not prove all native descendants stopped. "
            "Return here and enter `sandbox stop` for verified container stop and preservation, or `sandbox status`.\n\n"
            f"[Epic and latest owner decisions]({REPO}/issues/6615) · [Delivery PR]({REPO}/pull/6628)\n\n"
            "This owner conversation is model-free. Messages here do not start implementation jobs. Existing epic worker "
            "stop/takeover and automatic repository-wide task delivery remain with their current owner/workflow.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    # Optional OpenHands ACP dependency exists only in the independently pinned owner environment.
    import acp
    from acp.schema import PromptResponse
    from app.builderops.openhands_owner_acp import OwnerAgent

    class AccessAgent(OwnerAgent):
        async def prompt(self, session_id: str, prompt: list[Any], **kwargs: Any) -> PromptResponse:
            if session_id != self.session_id or len(prompt) != 1 or getattr(prompt[0], "type", None) != "text":
                raise ValueError("Expected one text message in the owner conversation")
            async with self.lock:
                task = asyncio.create_task(asyncio.to_thread(run_command, config, str(prompt[0].text)))
                try:
                    response = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
                except OwnerAccessError as exc:
                    response = str(exc)
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                    response = "Operation unavailable or incomplete. Request `status` / `sandbox status` before retrying. No credentials are shown."
            await self.client.session_update(session_id, acp.update_agent_message_text(response))
            return PromptResponse(stop_reason="end_turn")

    # The ACP Protocol also lists optional methods that this agent does not advertise.
    asyncio.run(acp.run_agent(cast(acp.Agent, AccessAgent(Path(config["runner"])))))


if __name__ == "__main__":
    main()
