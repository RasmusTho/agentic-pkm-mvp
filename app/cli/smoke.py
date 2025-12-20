from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import click

from app.agents.panel_agent import execute_panel_intent, run_panel_intent_for_note
from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep, new_plan_id
from app.settings.validate import validate_settings
from app.store.object_store import DomainObject, ObjectStore
from app.stores.plan_store import get_plan_store, reset_plan_store

_DEFAULT_VAULT = Path("tmp/vault_smoke")
_DEFAULT_OUTBOX = Path("tmp/index-outbox.smoke.jsonl")


def _default_env(outbox: Path) -> None:
    os.environ.setdefault("STORE_BACKEND", "memory")
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    os.environ.setdefault("POLICY_ENFORCE", "1")
    os.environ.setdefault("PANEL_AGENT_PIPELINE", "planner")
    os.environ["INDEX_OUTBOX_PATH"] = str(outbox)


def _validate_settings() -> None:
    issues = validate_settings()
    if issues:
        raise SystemExit(f"settings validate failed: {len(issues)} issue(s)")


def _seed_note(vault: Path) -> tuple[str, Path]:
    vault.mkdir(parents=True, exist_ok=True)
    note_uuid = uuid4().hex
    note_path = vault / "PanelSmoke.md"
    panel_block = """%% AI:Start %%\n## AI-instruktion\nMake this note evergreen\n## AI-åtgärder\n- [x] Make this note evergreen\n%% AI:End %%\n"""
    note_path.write_text(panel_block, encoding="utf-8")
    payload = {"raw_text": panel_block, "origin": "vault"}
    domain_obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload=payload,
        source_ref=str(note_path),
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(domain_obj, emit_outbox=False, trace_id="smoke-reality")
    return note_uuid, note_path


def _append_plan(note_uuid: str, vault: Path) -> Plan:
    return Plan(
        id=new_plan_id(),
        meta=PlanMetadata(goal="Reality smoke append", source_object_uuid=note_uuid, created_by="cli.smoke"),
        steps=[
            PlanStep(
                id="append-note",
                kind="tool_call",
                description="Append smoke note",
                tool="mcp.vault.append_note",
                tool_args={
                    "title": "Reality Smoke",
                    "body": f"Smoke write for {note_uuid}",
                    "tags": ["smoke", "reality"],
                },
                agent_id="panel_agent.v5",
            )
        ],
        context={"tool_settings": {"vault_root": str(vault), "mcp_vault_enable": True}},
        goal="Reality smoke append",
    )


def _summarize_results(label: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    status = "ok"
    for entry in results:
        if entry.get("status") != "ok":
            status = "error"
            break
    return {"label": label, "status": status, "results": results}


@click.group(help="Smoke test utilities.")
def smoke() -> None:
    ...


@smoke.command(name="reality", help="Run deterministic end-to-end smoke (panel intent + tool write with policy on).")
@click.option("--vault", type=click.Path(path_type=Path), default=_DEFAULT_VAULT, show_default=True, help="Vault root for smoke files.")
@click.option(
    "--outbox",
    type=click.Path(path_type=Path),
    default=_DEFAULT_OUTBOX,
    show_default=True,
    help="Outbox path for smoke events.",
)
@click.option("--json", "as_json", is_flag=True, help="Return JSON summary instead of text output.")
def smoke_reality(vault: Path, outbox: Path, as_json: bool) -> None:
    _default_env(outbox)
    outbox.parent.mkdir(parents=True, exist_ok=True)
    outbox.write_text("", encoding="utf-8")
    reset_plan_store()

    _validate_settings()

    note_uuid, note_path = _seed_note(vault)
    trace_id = uuid4().hex

    panel_events = run_panel_intent_for_note(note_uuid=note_uuid, trace_id=trace_id)
    panel_runtime = [execute_panel_intent(event, outbox_path=outbox) for event in panel_events]
    plans = get_plan_store().list_by_object(note_uuid)

    orchestrator = Orchestrator(tool_settings={"vault_root": str(vault), "mcp_vault_enable": True})
    panel_plan_results: list[dict[str, Any]] = []
    if plans:
        panel_plan_results = orchestrator.run_plan(plans[-1])

    append_plan = _append_plan(note_uuid, vault)
    append_results = orchestrator.run_plan(append_plan)

    created_notes = sorted((vault / "_mcp").glob("*.md"))
    outbox_lines = outbox.read_text(encoding="utf-8").splitlines() if outbox.exists() else []

    summary: Dict[str, Any] = {
        "note_uuid": note_uuid,
        "note_path": str(note_path),
        "panel_events": len(panel_events),
        "panel_runtime_results": len(panel_runtime),
        "panel_plan": _summarize_results("panel", panel_plan_results) if plans else None,
        "append_plan": _summarize_results("append", append_results),
        "outbox_path": str(outbox),
        "outbox_events": len(outbox_lines),
        "created_notes": [str(p) for p in created_notes],
    }

    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False))
    else:
        click.echo("Reality smoke summary:")
        click.echo(f"  note_uuid: {note_uuid}")
        click.echo(f"  panel events: {len(panel_events)} plan_steps={len(plans[-1].steps) if plans else 0}")
        click.echo(f"  append status: {summary['append_plan']['status']}")
        click.echo(f"  outbox: {len(outbox_lines)} events -> {outbox}")
        click.echo(f"  created notes: {summary['created_notes'] or '-'}")

    statuses = [summary["append_plan"]["status"]]
    if summary["panel_plan"]:
        statuses.append(summary["panel_plan"]["status"])
    if any(status != "ok" for status in statuses):
        raise SystemExit(1)
