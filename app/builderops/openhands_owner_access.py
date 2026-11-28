"""Model-free owner conversation; existing work is read-only, controls own one sandbox."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, cast

from app.builderops import epic_workspace

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
        capture_output=True, text=True, timeout=300, check=False,
    )
    if result.returncode:
        # Controller diagnostics can include paths; never echo subprocess stderr or keys.
        if "already mounted" in result.stderr:
            raise OwnerAccessError("The shared native slot is busy. Existing work was preserved; request status and retry later.")
        if args[0] == "openhands-start" and "--claude-env-file" in args:
            raise OwnerAccessError("Sandbox could not bind its provisioned Claude subscription configuration. Request sandbox status.")
        if args[0] == "conversation-start" and ("catalog" in result.stderr or "subscription" in result.stderr):
            raise OwnerAccessError("Sandbox could not verify the chosen engine's subscription or refreshed ACP model catalog. Request sandbox status.")
        if args[0] == "conversation-start" and ("qualification" in result.stderr or "selection" in result.stderr):
            raise OwnerAccessError("Sandbox could not verify the selected model or effort in its native session. Request sandbox status.")
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
            f"OpenHands conversation: `{conversation.get('id', 'unavailable')}`; selected engine/model/effort: "
            f"{conversation.get('engine', 'unknown')} / {conversation.get('model', 'unknown')} / "
            f"{conversation.get('effort', 'unspecified')}.",
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


def _sandbox_profile(config: dict[str, Any], engine: str, model: str, effort: str | None) -> None:
    """Select the existing upstream ACP profile surface so Canvas enables its composer."""
    code = """import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from app.builderops import epic_workspace as e
e.OPENHANDS_PORT_RANGE=range(18840,18848)
l=e.Layout(Path(sys.argv[2]),int(sys.argv[3]))
m=e._load_state(l)['issue_mappings'][sys.argv[3]]
engine,model=e.resolve_engine(sys.argv[4],sys.argv[5])
effort=e.resolve_effort(engine,model,sys.argv[6] or None)
c=m.get('conversation',{})
if (c.get('status'),c.get('engine'),c.get('model'),c.get('effort'))!=('created',engine,model,effort): raise ValueError('selection changed')
selector=e.conversation_acp_selector(c)
expected={'agent_kind':'acp','acp_server':engine,'acp_model':selector,'mcp_server_refs':[],'secret_refs':[],'integration_refs':[]}
if effort is not None: expected['acp_effort']=effort
profile='owner-sandbox' if effort is None and model=='gpt-6.1-terra' else 'owner-sandbox-'+model+('-'+effort if effort else '')
if selector!=model: profile+='-acp-'+selector
with e._endpoint_session(l,'owner-sandbox',int(sys.argv[3]),m,e.subprocess.run) as (port,key):
 if c.get('selection_policy')=='catalog' or 'acp_selector' in c:
  if e._load_state(l)['issue_mappings'][sys.argv[3]].get('conversation')!=c: raise ValueError('conversation changed')
  code,info=e._http('GET',port,key,'/conversations/'+c['id'],None,10)
  if code!=200 or not e._conversation_bound(info,l,int(sys.argv[3]),'owner-sandbox',c['id']) or not e.selection_proof_matches(c,info):
   raise ValueError('native selection proof mismatch')
 code,data=e._http('GET',port,key,'/agent-profiles/'+profile,None,10)
 if code==404:
  code,_=e._http('POST',port,key,'/agent-profiles/'+profile,expected,10)
  if code not in (200,201): raise ValueError('profile creation uncertain')
  code,data=e._http('GET',port,key,'/agent-profiles/'+profile,None,10)
 p=data.get('profile',{})
 if code!=200 or any(p.get(k)!=v for k,v in expected.items()): raise ValueError('profile mismatch')
 code,_=e._http('POST',port,key,'/agent-profiles/'+p['id']+'/activate',None,10)
 if code!=200:raise ValueError('profile activation unavailable')
"""
    result = subprocess.run(["python3", "-c", code, config["runner"], config["root"], str(config["sandbox_epic"]), engine, model, effort or ""],
                            capture_output=True, text=True, timeout=60, check=False)
    if result.returncode:
        raise OwnerAccessError("Sandbox ACP profile is not verified; no UI readiness is claimed.")


def _sandbox_auth(config: dict[str, Any], engine: str = "codex") -> None:
    code = """import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from app.builderops import epic_workspace as e
e.OPENHANDS_PORT_RANGE=range(18840,18848)
l=e.Layout(Path(sys.argv[2]),int(sys.argv[3]))
m=e._load_state(l)['issue_mappings'][sys.argv[3]]
with e._endpoint_session(l,'owner-sandbox',int(sys.argv[3]),m,e.subprocess.run):
 if m.get('conversation',{}).get('engine')!=sys.argv[4]: raise ValueError('engine changed')
 verify={'codex':e.verify_codex_subscription,'claude-code':e.verify_claude_subscription}[sys.argv[4]]
 verify(m,e.subprocess.run)
"""
    result = subprocess.run(["python3", "-c", code, config["runner"], config["root"], str(config["sandbox_epic"]), engine],
                            capture_output=True, text=True, timeout=120, check=False)
    if result.returncode:
        raise OwnerAccessError("Sandbox subscription authentication is not verified; no readiness is claimed.")


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
    parts = command.split()
    if parts[:2] == ["sandbox", "start"]:
        request = parts[2:]
        explicit = bool(request)
        engine = request.pop(0) if request and request[0] in epic_workspace.NATIVE_ENGINES else "codex"
        if len(request) > 2:
            return "Use `sandbox start [codex|claude-code] [MODEL [EFFORT]]`."
        model = request[0] if request else None
        effort = request[1] if len(request) == 2 else None
        try:
            _, _, qualified_effort = epic_workspace.model_request(engine, model, effort, qualify_selection=True)
        except epic_workspace.LaunchRefused as exc:
            return f"Sandbox model selection refused. {exc}"
        current = _controller(config, "status")
        worker = next((w for w in current.get("workers", []) if w.get("worker") == WORKER), None)
        if not worker:
            raise OwnerAccessError("Sandbox has not been provisioned; no worker was created.")
        if worker.get("container") != "running":
            flag, field = (("--claude-env-file", "claude_env_file") if engine == "claude-code"
                           else ("--codex-home", "codex_home"))
            auth_path = config.get(field)
            if not isinstance(auth_path, str) or not Path(auth_path).is_absolute():
                return f"Sandbox has no provisioned {engine} subscription configuration."
            if worker.get("recorded_state") == "stopped_verified":
                _controller(config, "takeover", "--worker", WORKER, "--reason", "owner requested sandbox restart")
            _controller(config, "openhands-start", "--worker", WORKER, "--cpus", "0.7", "--memory", "1500m",
                        "--pids", "256", flag, auth_path)
        observation = _controller(config, "conversation-status", "--worker", WORKER)
        record = observation.get("conversation") or {}
        start_needed = not record or record.get("status") == "ended_with_container"
        if model is not None and (start_needed or record.get("selection_policy") == "catalog"):
            effort = qualified_effort
        if start_needed:
            args = ["conversation-start", "--worker", WORKER, "--engine", engine, "--qualify-selection"]
            if model is not None:
                args.extend(["--model", model])
            if effort is not None:
                args.extend(["--effort", effort])
            _controller(config, *args, "--prompt-file", config["readiness_prompt"])
        elif explicit and (record.get("engine") != engine or (model is not None and (
                record.get("model"), record.get("effort")) != (model, effort))):
            return "Existing sandbox selection differs. Use sandbox stop before requesting a new selection."
        elif record.get("status") in {"creating", "unknown"}:
            _controller(config, "conversation-reconcile", "--worker", WORKER)
        observed = _controller(config, "conversation-status", "--worker", WORKER)
        if not observed.get("reachable") or (observed.get("conversation") or {}).get("status") != "created":
            return "Sandbox conversation is not verified reachable. Request `sandbox status`; no readiness or task execution is claimed."
        selected = observed.get("conversation") or {}
        settings = observed.get("agent_settings") or {}
        if (explicit and selected.get("engine") != engine) or (model is not None and (
                selected.get("model") != model or selected.get("effort") != effort)):
            return "Existing sandbox selection differs. Use sandbox stop before requesting a new selection."
        selected_engine, model, effort = selected.get("engine"), selected.get("model"), selected.get("effort")
        if (not isinstance(selected_engine, str) or selected_engine not in epic_workspace.NATIVE_ENGINES
                or not isinstance(model, str) or not model):
            return "Sandbox model is unavailable. Request `sandbox status`."
        engine = selected_engine
        selector = epic_workspace.conversation_acp_selector(selected)
        if ((selected.get("selection_policy") == "catalog" or "acp_selector" in selected)
                and observed.get("selection_verified") is not True):
            return "Sandbox native model selection is not verified. Request `sandbox status`."
        if (engine == "claude-code" or effort is not None) and (
                settings.get("agent_kind") != "acp" or settings.get("acp_server") != engine
                or settings.get("acp_model") != selector or settings.get("current_model_id") != selector
                or (effort is not None and (settings.get("acp_effort") != effort or settings.get("current_effort") != effort))):
            return "Sandbox model or effort is not verified; no readiness is claimed."
        if observed.get("execution_status") == "error":
            return "Sandbox conversation reports an engine error; task submission is not ready. Request `sandbox status`. No engine switch or automatic replay was attempted."
        _sandbox_auth(config, engine)
        if start_needed or selected.get("selection_policy") == "catalog":
            _sandbox_profile(config, engine, model, effort)
        conversation = observed.get("conversation") or {}
        url = config['sandbox_url'] + '/conversations/' + str(conversation.get('id', ''))
        selector_text = f" (ACP selector `{selector}`)" if selector != model else ""
        return (f"Owner sandbox is running. [Open sandbox Canvas]({url}). "
                "Open the existing owner-sandbox conversation and send a bounded scratch/read-only task. "
                f"One admitted conversation protects the shared checkout. Native {engine} {model}{selector_text} / {effort or 'provider effort'}, "
                "using the provisioned subscription. Return here and use "
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
            "Enter `sandbox start` for the latest available Sol at high effort or `sandbox start claude-code` for Claude Code. Add an exact model ID after the engine to pin it. Open the returned Canvas link and the existing conversation for your next bounded "
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
