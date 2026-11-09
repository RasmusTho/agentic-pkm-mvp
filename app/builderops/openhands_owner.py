"""Attach one deterministic owner control conversation to an existing Canvas backend."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_service as service

BOOTSTRAP = ("import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
             "runpy.run_module('app.builderops.openhands_owner_acp',run_name='__main__')")


def attach(install: Path, directory: Path, host_issue: int) -> dict[str, Any]:
    """Create or find the same control conversation without another model request."""
    host = delivery._state(directory)
    if host.get("issue") != host_issue or not isinstance(host.get("worktree"), str):
        raise delivery.DeliveryError("Owner control requires the recorded host Issue")
    workspace = str(Path(host["worktree"]).resolve(strict=True))
    key = delivery._server_key(directory, host)
    entry = (install / "bin/openhands").resolve(strict=True)
    python = (install / "venv/bin/python").absolute()
    source = Path(__file__).resolve().parents[2]
    command = [str(python), "-I", "-c", BOOTSTRAP, str(source), "--entry", str(entry)]
    control_dir = directory / "owner-control"
    with service._locked(control_dir):
        record = service._read(control_dir)
        if record is None:
            record = {"version": 1, "kind": "openhands_owner_control.v1", "phase": "creating",
                      "conversation_id": str(uuid.uuid4()), "host_issue": host_issue,
                      "workspace": workspace, "entry": str(entry)}
            service._write(control_dir, record)
            payload = {"conversation_id": record["conversation_id"], "workspace": {"working_dir": workspace},
                       "agent_settings": {"agent_kind": "acp", "acp_server": "custom", "acp_command": command},
                       "autotitle": False,
                       "initial_message": {"role": "user", "content": [{"type": "text", "text": "help"}]}}
            code, _ = delivery._http(host["port"], key, "POST", "/conversations", payload, timeout=120)
            if code != 201:
                raise delivery.DeliveryError("Owner control creation is uncertain; inspect the recorded conversation")
        if (record.get("kind") != "openhands_owner_control.v1" or record.get("host_issue") != host_issue
                or record.get("workspace") != workspace or record.get("entry") != str(entry)
                or record.get("phase") not in {"creating", "ready"}):
            raise delivery.DeliveryError("Owner control binding changed; inspect its recorded state")
        try:
            ident = record["conversation_id"]
            if not isinstance(ident, str) or str(uuid.UUID(ident)) != ident:
                raise ValueError("invalid conversation id")
        except (KeyError, ValueError) as exc:
            raise delivery.DeliveryError("Owner control conversation identity is invalid") from exc
        code, observed = delivery._http(host["port"], key, "GET", f"/conversations/{ident}")
        agent = observed.get("agent") if isinstance(observed, dict) else None
        observed_workspace = observed.get("workspace") if isinstance(observed, dict) else None
        if (code != 200 or not isinstance(observed, dict) or str(observed.get("id")) != ident
                or not isinstance(observed_workspace, dict) or observed_workspace.get("working_dir") != workspace
                or not isinstance(agent, dict) or agent.get("kind") != "ACPAgent"
                or agent.get("acp_server") != "custom" or agent.get("acp_command") != command
                or agent.get("acp_model") is not None):
            raise delivery.DeliveryError("Owner control conversation could not be verified")
        if observed.get("title") != "Builder control":
            title_code, _ = delivery._http(host["port"], key, "PATCH", f"/conversations/{ident}",
                                           {"title": "Builder control"})
            if title_code != 200:
                raise delivery.DeliveryError("Owner control exists but its title could not be updated")
        record["phase"] = "ready"
        service._write(control_dir, record)
        return {"status": "ready", "conversation_id": ident, "host_issue": host_issue,
                "note": "Control commands are deterministic; each task starts the existing Codex/Terra factory."}
