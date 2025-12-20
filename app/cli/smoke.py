from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import click

from app.agents.ask.graph import run_ask_graph
from app.agents.panel_agent import execute_panel_intent, run_panel_intent_for_note
from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep, new_plan_id
from app.planner.tools import MCP_TOOL_DESCRIPTORS
from app.retrieval.hybrid import get_store, hybrid_search
from app.settings.validate import validate_settings
from app.store.object_store import DomainObject, ObjectStore
from app.stores.plan_store import get_plan_store, reset_plan_store

_DEFAULT_VAULT = Path("tmp/vault_smoke")
_DEFAULT_OUTBOX = Path("tmp/index-outbox.smoke.jsonl")
_CURSOR_MARKER = "<!-- reality_smoke_processed -->"
_ASK_NOTE_TITLE = "Smoke - ASK"


def _default_env(outbox: Path) -> None:
    os.environ.setdefault("STORE_BACKEND", "memory")
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    os.environ.setdefault("POLICY_ENFORCE", "1")
    os.environ.setdefault("PANEL_AGENT_PIPELINE", "planner")
    os.environ.setdefault("LLM_PROVIDER", "mock")
    os.environ.setdefault("EMBED_DIM", "1536")
    os.environ["INDEX_OUTBOX_PATH"] = str(outbox)


def _validate_settings() -> None:
    issues = validate_settings()
    if issues:
        raise SystemExit(f"settings validate failed: {len(issues)} issue(s)")


def _hash_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_state(path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "exists": exists,
        "mtime": path.stat().st_mtime if exists else None,
        "hash": _hash_file(path),
    }


def _outbox_count(outbox: Path) -> int:
    if not outbox.exists():
        return 0
    return sum(1 for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip())


def _list_created_notes(vault: Path) -> list[Path]:
    return sorted((vault / "_mcp").glob("*.md"))


def _has_cursor(note_path: Path) -> bool:
    if not note_path.exists():
        return False
    return _CURSOR_MARKER in note_path.read_text(encoding="utf-8")


def _mark_cursor(note_path: Path) -> None:
    content = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
    if _CURSOR_MARKER in content:
        return
    appended = content.rstrip() + "\n\n" + _CURSOR_MARKER + "\n"
    note_path.write_text(appended, encoding="utf-8")


def _sync_store(note_uuid: str, note_path: Path) -> None:
    try:
        obj = ObjectStore().get_object(note_uuid)
    except Exception:
        obj = None
    if not obj:
        return
    payload = obj.payload or {}
    if note_path.exists():
        payload["raw_text"] = note_path.read_text(encoding="utf-8")
    obj.payload = payload
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="smoke-reality")


def _seed_note(vault: Path) -> tuple[str, Path]:
    vault.mkdir(parents=True, exist_ok=True)
    note_uuid = uuid4().hex
    note_path = vault / "PanelSmoke.md"
    panel_block = (
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Make this note evergreen\n"
        "## AI-åtgärder\n"
        "- [x] Make this note evergreen\n"
        "%% AI:End %%\n"
    )
    note_path.write_text(panel_block, encoding="utf-8")
    payload = {"raw_text": panel_block, "origin": "vault"}
    domain_obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload=payload,
        source_ref=str(note_path),
        created_at=datetime.now(UTC),
    )
    ObjectStore().save_object(domain_obj, emit_outbox=False, trace_id="smoke-reality")
    return note_uuid, note_path


def _append_plan(note_uuid: str, vault: Path) -> Plan:
    return Plan(
        id=new_plan_id(),
        meta=PlanMetadata(
            goal="Reality smoke append",
            source_object_uuid=note_uuid,
            created_by="cli.smoke",
        ),
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


def _summarize_results(label: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    status = "ok"
    for entry in results:
        if entry.get("status") != "ok":
            status = "error"
            break
    return {"label": label, "status": status, "results": results}


def _run_once(
    run_idx: int,
    *,
    note_uuid: str,
    note_path: Path,
    vault: Path,
    outbox: Path,
    orchestrator: Orchestrator,
) -> dict[str, Any]:
    pre_state = _file_state(note_path)
    created_before = _list_created_notes(vault)
    outbox_before = _outbox_count(outbox)

    summary: dict[str, Any] = {
        "run": run_idx,
        "mutations": False,
        "events_emitted": 0,
        "note_appended": False,
        "outbox_before": outbox_before,
        "note_hash_before": pre_state["hash"],
        "note_mtime_before": pre_state["mtime"],
    }

    if _has_cursor(note_path):
        post_state = _file_state(note_path)
        summary.update(
            {
                "outbox_after": outbox_before,
                "note_hash_after": post_state["hash"],
                "note_mtime_after": post_state["mtime"],
            }
        )
        return summary

    panel_events = run_panel_intent_for_note(note_uuid=note_uuid, trace_id=uuid4().hex)
    panel_runtime = [execute_panel_intent(event, outbox_path=outbox) for event in panel_events]
    plans = get_plan_store().list_by_object(note_uuid)

    panel_plan_results: list[dict[str, Any]] = []
    if plans:
        panel_plan_results = orchestrator.run_plan(plans[-1])

    append_plan = _append_plan(note_uuid, vault)
    append_results = orchestrator.run_plan(append_plan)

    _mark_cursor(note_path)
    _sync_store(note_uuid, note_path)

    post_state = _file_state(note_path)
    outbox_after = _outbox_count(outbox)
    created_after = _list_created_notes(vault)

    summary.update(
        {
            "mutations": True,
            "events_emitted": max(0, outbox_after - outbox_before),
            "note_appended": len(created_after) > len(created_before),
            "outbox_after": outbox_after,
            "note_hash_after": post_state["hash"],
            "note_mtime_after": post_state["mtime"],
            "panel_events": len(panel_events),
            "panel_runtime_results": len(panel_runtime),
            "panel_plan": (
                _summarize_results("panel", panel_plan_results)
                if panel_plan_results
                else None
            ),
            "append_plan": _summarize_results("append", append_results),
        }
    )
    return summary


def _seed_ask_corpus() -> list[dict[str, str]]:
    corpus = [
        {
            "uuid": uuid4().hex,
            "title": "Sweden Basics",
            "text": "Sweden is in Scandinavia. The capital of Sweden is Stockholm.",
        },
        {
            "uuid": uuid4().hex,
            "title": "Norway Basics",
            "text": "Norway is west of Sweden with capital Oslo.",
        },
    ]
    store = ObjectStore()
    for entry in corpus:
        payload = {"raw_text": entry["text"], "title": entry["title"], "origin": "seed"}
        obj = DomainObject(
            uuid=entry["uuid"],
            kind="note",
            payload=payload,
            source_ref=entry["title"],
            created_at=datetime.now(UTC),
        )
        store.save_object(obj, emit_outbox=False, trace_id="smoke-ask")

    get_store().set_documents(
        [
            {
                "doc_id": entry["uuid"],
                "text": entry["text"],
                "payload": {"title": entry["title"], "uuid": entry["uuid"]},
            }
            for entry in corpus
        ]
    )
    return corpus


def _run_ask(query: str) -> tuple[str, list[str]]:
    state = run_ask_graph(query, trace_id=uuid4().hex)
    hits = state.hits or []
    citations = [h.object_id for h in hits if getattr(h, "object_id", "")]
    answer = state.answer or ""
    if not answer:
        results = hybrid_search(query, k=1)
        if results:
            answer = results[0].get("snippet") or results[0].get("text") or "No answer found."
    return answer, citations


def _append_ask_body(answer: str, citations: list[str]) -> str:
    lines = ["## ASK Answer", answer.strip(), "", "### Provenance"]
    if citations:
        for cid in citations:
            lines.append(f"- object_id: {cid}")
    else:
        lines.append("- object_id: none")
    return "\n".join(lines).strip() + "\n"


def _append_ask_plan(body: str, vault: Path) -> Plan:
    return Plan(
        id=new_plan_id(),
        meta=PlanMetadata(
            goal="ASK smoke append",
            source_object_uuid="ask-smoke",
            created_by="cli.smoke.ask",
        ),
        steps=[
            PlanStep(
                id="append-answer",
                kind="tool_call",
                description="Append ASK answer",
                tool="mcp.vault.append_note",
                tool_args={"title": _ASK_NOTE_TITLE, "body": body, "tags": ["smoke", "ask"]},
                agent_id="panel_agent.v5",
            )
        ],
        context={"tool_settings": {"vault_root": str(vault), "mcp_vault_enable": True}},
        goal="ASK smoke append",
    )


@click.group(help="Smoke test utilities.")
def smoke() -> None:
    ...


@smoke.command(
    name="reality",
    help="Run deterministic end-to-end smoke (panel intent + tool write with policy on).",
)
@click.option(
    "--vault",
    type=click.Path(path_type=Path),
    default=_DEFAULT_VAULT,
    show_default=True,
    help="Vault root for smoke files.",
)
@click.option(
    "--outbox",
    type=click.Path(path_type=Path),
    default=_DEFAULT_OUTBOX,
    show_default=True,
    help="Outbox path for smoke events.",
)
@click.option(
    "--runs",
    type=int,
    default=2,
    show_default=True,
    help="Number of runs (second run should be no-op).",
)
@click.option("--json", "as_json", is_flag=True, help="Return JSON summary instead of text output.")
def smoke_reality(vault: Path, outbox: Path, runs: int, as_json: bool) -> None:
    if runs < 1:
        raise SystemExit("runs must be >= 1")

    _default_env(outbox)
    outbox.parent.mkdir(parents=True, exist_ok=True)
    outbox.write_text("", encoding="utf-8")
    reset_plan_store()

    _validate_settings()

    note_uuid, note_path = _seed_note(vault)
    orchestrator = Orchestrator(tool_settings={"vault_root": str(vault), "mcp_vault_enable": True})

    run_summaries: list[dict[str, Any]] = []
    for idx in range(1, runs + 1):
        run_summaries.append(
            _run_once(
                idx,
                note_uuid=note_uuid,
                note_path=note_path,
                vault=vault,
                outbox=outbox,
                orchestrator=orchestrator,
            )
        )

    created_notes = [str(p) for p in _list_created_notes(vault)]
    summary: dict[str, Any] = {
        "note_uuid": note_uuid,
        "note_path": str(note_path),
        "runs": run_summaries,
        "outbox_path": str(outbox),
        "created_notes": created_notes,
    }

    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False))
    else:
        click.echo(f"Reality smoke summary (runs={runs}):")
        for run_entry in run_summaries:
            label = "mutated" if run_entry.get("mutations") else "no-op"
            click.echo(
                f"  run {run_entry['run']}: {label} events={run_entry.get('events_emitted', 0)} "
                f"outbox={run_entry.get('outbox_after', run_entry.get('outbox_before'))}"
            )
        click.echo(f"  created notes: {created_notes or '-'}")

    if not run_summaries or not run_summaries[0].get("mutations"):
        raise SystemExit(1)
    if runs >= 2:
        later_mutations = any(entry.get("mutations") for entry in run_summaries[1:])
        if later_mutations:
            raise SystemExit(1)


@smoke.command(
    name="ask",
    help="Run ASK graph on seeded corpus and append answer to vault with provenance.",
)
@click.option(
    "--vault",
    type=click.Path(path_type=Path),
    default=_DEFAULT_VAULT,
    show_default=True,
    help="Vault root for smoke files.",
)
@click.option(
    "--outbox",
    type=click.Path(path_type=Path),
    default=_DEFAULT_OUTBOX,
    show_default=True,
    help="Outbox path for smoke events.",
)
@click.option(
    "--query",
    type=str,
    default="What is the capital of Sweden?",
    show_default=True,
    help="Query to run through ASK.",
)
@click.option("--json", "as_json", is_flag=True, help="Return JSON summary instead of text output.")
def smoke_ask(vault: Path, outbox: Path, query: str, as_json: bool) -> None:
    _default_env(outbox)
    outbox.parent.mkdir(parents=True, exist_ok=True)
    outbox.write_text("", encoding="utf-8")
    reset_plan_store()
    _validate_settings()

    corpus = _seed_ask_corpus()
    outbox_before = _outbox_count(outbox)

    answer, citations = _run_ask(query)
    body = _append_ask_body(answer, citations)

    search_descriptor = MCP_TOOL_DESCRIPTORS.get("mcp.search.objects")
    if search_descriptor is not None:
        search_descriptor.mock_result = {
            "status": "ok",
            "results": [
                {
                    "id": entry["uuid"],
                    "title": entry.get("title"),
                    "snippet": entry.get("text"),
                    "payload": {"uuid": entry["uuid"], "title": entry.get("title")},
                }
                for entry in corpus
            ],
        }

    plan = Plan(
        id=new_plan_id(),
        meta=PlanMetadata(
            goal="ASK smoke",
            source_object_uuid="ask-smoke",
            created_by="cli.smoke.ask",
        ),
        steps=[
            PlanStep(
                id="search",
                kind="tool_call",
                description="Search corpus",
                tool="mcp.search.objects",
                tool_args={"query": query, "k": 3},
                agent_id="ask.v1",
            ),
            PlanStep(
                id="append-answer",
                kind="tool_call",
                description="Append ASK answer",
                tool="mcp.vault.append_note",
                tool_args={"title": _ASK_NOTE_TITLE, "body": body, "tags": ["smoke", "ask"]},
                depends_on=["search"],
                agent_id="panel_agent.v5",
            ),
        ],
        context={"tool_settings": {"vault_root": str(vault), "mcp_vault_enable": True}},
        goal="ASK smoke",
    )

    orchestrator = Orchestrator(tool_settings={"vault_root": str(vault), "mcp_vault_enable": True})
    results = orchestrator.run_plan(plan)
    outbox_after = _outbox_count(outbox)
    note_path = None
    for entry in results:
        if entry.get("step_id") != "append-answer":
            continue
        result_payload = entry.get("result") if isinstance(entry.get("result"), dict) else None
        if not isinstance(result_payload, dict):
            continue
        inner = result_payload.get("result") if isinstance(result_payload, dict) else None
        if isinstance(inner, dict):
            note_path = inner.get("note_path")
            break

    summary = {
        "query": query,
        "answer_chars": len(answer),
        "citations": citations,
        "note_path": note_path,
        "outbox_before": outbox_before,
        "outbox_after": outbox_after,
        "mutations": True,
        "policy_enforce": True,
    }

    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False))
    else:
        click.echo("ASK smoke summary:")
        click.echo(f"  query: {query}")
        click.echo(f"  answer chars: {len(answer)}")
        click.echo(f"  citations: {citations or '-'}")
        click.echo(f"  note: {note_path or '-'}")
        click.echo(f"  outbox: {outbox_before} -> {outbox_after}")

    if not note_path or outbox_after < outbox_before:
        raise SystemExit(1)
