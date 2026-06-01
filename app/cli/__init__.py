from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
import time

import click
import httpx
from watchfiles import watch

from app.config.environment import active_environment
from app.observability.status_service import get_system_status
from app.promotion.consumer import consume_promotion_intents
from app.ingest.config import DEFAULT_VAULT_ROOT
from app.cli.alpha_human_flows import run_alpha_human_flows
from app.ingest.vault_root import ingest_vault_root
from app.ingest.vault_alpha import run_vault_alpha_ingest, run_vault_alpha_ingest_paths, run_vault_alpha_ingest_locked_only
from app.ingest.external import ingest_external_folder
from app.planner.schema import Plan, PlanMetadata, PlanStep, new_plan_id
from app.cli.panel import panel as panel_cli
from app.cli.health_contract import emit_health_contract_status
from app.cli.watcher import vault_watcher_run, vault_watcher_daemon, watcher_group
from app.cli.index_rebuild import index as index_cli
from app.cli.llm_doctor import llm as llm_cli
from app.cli import index_doctor  # noqa: F401 -- register index doctor command
from app.cli.events_doctor import events_doctor
from app.cli.smoke import smoke as smoke_cli
from app.cli.settings_validate import run_settings_validate
from app.cli.settings_explain import build_settings_explain_payload, emit_settings_explain
from app.cli.builderops import builderops as builderops_cli


from app.config.paths import resolve_system_settings_path, resolve_vault_root
from app.services import settings as settings_service
from app.watcher.vault_watcher import OutboxPathError as WatcherOutboxPathError, run_watcher_tick
from app.runtime.runtime_loop import OutboxPathError, RuntimeLoopConfig, resolve_outbox_path, run_forever, run_once
from app.cli.uat import (
    DEFAULT_FOLDER_NAME,
    DEFAULT_TARGET_SUBDIR,
    DEFAULT_MAX_NOTES,
    UATAssertionError,
    run_vault_test_flow,
    seed_vault_test_notes,
)
from app.cli.latency_harness import LatencyHarnessTimeoutError, run_latency_harness
from app.stores import get_object_store, get_vector_index, resolve_store_backend
from app.agents.classifier.agent import run as classify_run
from app.agents.panel.integration import handle_panel_update
from app.services.note_update import NoteUpdateResult, process_note_update
from app.services.note_watcher import NoteWatcherService
from app.events.models import new_event
from app.events.types import ASK_QUERY_RECEIVED, INGEST_OBJECT_CREATED
from app.agents.normalizer.agent import run as normalize_run
from app.index.outbox import append_jsonl
from app.services.outbox import write_outbox_event
from app.orchestrator.handler import OrchestratorContext, handle_event
from app.orchestrator.runtime import Orchestrator
from app.orchestrator.executor import MockPlanExecutor
from app.a2a.schema import AgentRequest, new_response
from app.media.transcribe import transcribe_source
from app.obs.log import with_trace_id
from app.cli.health import run_health
from app.stores.plan_store import get_plan_store
from app.settings.compiler import compile_all
from app.settings.tiering import require_lab_profile
from app.knowledge.write_ops import default_vault_root_for_path, write_note_from_absolute
from app.llm.trace_inspect import (
    build_sequence_for_trace,
    group_by_trace_id,
    LLMSequence,
    list_agents_in_sequence,
    load_trace,
)
from app.settings.runtime import get_settings_bundle
from app.settings.yggdrasil_scaffolder import YggdrasilScaffolder

_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
_DOWNLOAD_DIR = Path("tmp/normalize")


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _materialize_source(source: str) -> Path:
    path = Path(source)
    if path.exists():
        return path
    if _looks_like_url(source):
        _DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = _DOWNLOAD_DIR / f"download-{uuid.uuid4().hex}.md"
        resp = httpx.get(source, timeout=30)
        resp.raise_for_status()
        tmp_path.write_text(resp.text, encoding="utf-8")
        return tmp_path
    raise FileNotFoundError(f"Source not found: {source}")


def _dump(data: dict, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False))
    else:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))

def _should_transcribe(source: str) -> bool:
    path = Path(source)
    if path.exists() and path.suffix.lower() in _AUDIO_EXTS:
        return True
    return _looks_like_url(source)


TRUE_STRINGS = {"1", "true", "yes", "on"}


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in TRUE_STRINGS
    return bool(value)


def _write_note_via_knowledge_port(note_path: Path, content: str) -> None:
    resolved = note_path.resolve()
    root = default_vault_root_for_path(resolved)
    write_note_from_absolute(resolved, content, vault_root=root)


def _resolve_vault_root_path(
    value: Path | None, *, allow_env: bool = True, fallback_to_default: bool = False
) -> Path | None:
    """Resolve vault root, defaulting to the alpha vault path when requested."""
    if value is not None:
        return value
    if allow_env:
        env_root = os.getenv("VAULT_ROOT")
        if env_root:
            return Path(env_root)
    if fallback_to_default:
        return DEFAULT_VAULT_ROOT
    return None


def _resolve_yggdrasil_root(path_override: Path | None) -> Path:
    if path_override is not None:
        return path_override
    try:
        settings_bundle = get_settings_bundle()
        settings_root = getattr(settings_bundle, "yggdrasil_paths", None)
        if settings_root and getattr(settings_root, "yggdrasil_root", None):
            return Path(settings_root.yggdrasil_root)
    except Exception:
        # Settings are optional for scaffolding; fall back to default root.
        pass
    return Path.home() / "Yggdrasil"


def _truncate_preview(text: Any, limit: int) -> str:
    try:
        value = "" if text is None else str(text)
    except Exception:
        value = ""
    value = value.replace("\n", "\\n")
    return value[:limit] + ("..." if len(value) > limit else "")


def _response_text(rec) -> str:
    candidates = (rec.response_preview, getattr(rec, "response_text_preview", ""), getattr(rec, "raw_response_preview", ""))
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            text = str(candidate)
        except Exception:
            text = ""
        if text.strip() not in {"", "{}"}:
            return text
    return ""


def _render_text_sequence(seq: LLMSequence) -> str:
    lines = [f"Trace: {seq.trace_id}", ""]
    for step in seq.steps:
        mode = f" mode={step.mode}" if getattr(step, "mode", "") else ""
        status = f" status={step.status}" if getattr(step, "status", "") else ""
        lines.append(f"Step {step.index}: agent={step.agent}{mode}{status} kind={step.kind}")
        lines.append(f"  input:  {_truncate_preview(step.prompt_preview, 160)}")
        lines.append(f"  output: {_truncate_preview(step.response_preview, 160)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_mermaid_sequence(seq: LLMSequence) -> str:
    agents = list_agents_in_sequence(seq)
    lines = [f"# LLM Trace {seq.trace_id}", "", "```mermaid", "sequenceDiagram"]
    for agent in agents:
        lines.append(f"    participant {agent}")
    lines.append("    participant LLM")
    lines.append("")
    for step in seq.steps:
        prompt = _truncate_preview(step.prompt_preview, 110)
        response = _truncate_preview(step.response_preview, 110)
        lines.append(f"    {step.agent}->>LLM: {step.kind}\\ninput: {prompt}")
        lines.append(f"    LLM-->>{step.agent}: output: {response}")
        lines.append("")
    lines.append("```")
    return "\n".join(lines).rstrip()


class _RecordingOrchestrator(Orchestrator):
    def __init__(self, *args, **kwargs) -> None:
        executor = MockPlanExecutor()
        executor.register_handler("ingest-agent", self._mock_ingest_agent)
        kwargs.setdefault("executor", executor)
        super().__init__(*args, **kwargs)
        self.last_results: list[dict[str, Any]] | None = None

    def run_plan(self, plan):
        results = super().run_plan(plan)
        self.last_results = results
        return results

    @staticmethod
    def _mock_ingest_agent(request):
        return new_response(
            sender="ingest-agent",
            recipient=request.sender,
            payload={
                "summary": "Summaries from ingest-agent",
                "status": "ok",
            },
            correlation_id=str(request.id),
            trace_id=request.trace_id,
        )


def _ingest_agent_stub(request: AgentRequest):
    return new_response(
        sender="ingest-agent",
        recipient="orchestrator.runtime",
        payload={"summary": "Summaries from ingest-agent", "request_id": str(request.id)},
        correlation_id=str(request.id),
        trace_id=request.trace_id,
    )


def _ingest_agent_stub(request: AgentRequest):
    return new_response(
        sender="ingest-agent",
        recipient="orchestrator.runtime",
        payload={"summary": "Summaries from ingest-agent", "request_id": str(request.id)},
        correlation_id=str(request.id),
        trace_id=request.trace_id,
    )


def _extract_note_path(results: list[dict[str, Any]]) -> str | None:
    for entry in results:
        result_payload = entry.get("result")
        if not isinstance(result_payload, dict):
            continue
        tool_name = result_payload.get("tool")
        if tool_name != "mcp.vault.append_note":
            continue
        inner = result_payload.get("result")
        if isinstance(inner, dict) and inner.get("note_path"):
            return inner.get("note_path")
    return None


@click.group(help="Agentic PKM CLI")
def cli() -> None:
    ...

cli.add_command(index_cli, name="index")
cli.add_command(llm_cli)
cli.add_command(events_doctor)
cli.add_command(smoke_cli, name="smoke")
cli.add_command(builderops_cli, name="builderops")

# ---------------------------------------------------------------------------
# Canvas CLI group
# ---------------------------------------------------------------------------

# In-memory session registry for tests (process lifetime).
_canvas_sessions: dict[str, object] = {}


@cli.group(name="canvas", help="Canvas Chat session commands.")
def canvas_cli() -> None:
    ...


@canvas_cli.command(name="open", help="Open a canvas session on a note.")
@click.argument("note_path")
@click.option("--label", default="canvas-session", help="Human label for the session.")
@click.option("--vault-root", "vault_root", default=None, help="Vault root (defaults to VAULT_ROOT).")
def canvas_open(note_path: str, label: str, vault_root: str | None) -> None:
    from app.chat.session_log import SessionLogWriter
    from app.chat.session_store import SessionStore

    root = Path(vault_root).expanduser().resolve() if vault_root else resolve_vault_root().expanduser().resolve()
    note = Path(note_path).expanduser()
    if not note.is_absolute():
        note = root / note
    note = note.resolve()
    lw = SessionLogWriter(vault_root=root)
    session = lw.open_session(note, label)
    store = SessionStore(vault_root=root)
    store.save(session)
    _canvas_sessions[session.session_id] = session
    click.echo(f"session_id {session.session_id}")
    click.echo(f"log_path {session.log_path}")


@canvas_cli.command(name="edit", help="Apply a body edit to an open canvas session.")
@click.argument("session_id")
@click.option("--body", required=True, help="New note body content.")
@click.option("--summary", required=True, help="Change summary for the session log.")
@click.option("--vault-root", "vault_root", default=None, help="Vault root.")
def canvas_edit(session_id: str, body: str, summary: str, vault_root: str | None) -> None:
    from app.chat.canvas_writer import CanvasWriter, GovernanceBearingMutationError
    from app.chat.session_log import SessionLogWriter
    from app.chat.session_store import SessionStore

    root = Path(vault_root).expanduser().resolve() if vault_root else resolve_vault_root().expanduser().resolve()
    store = SessionStore(vault_root=root)
    session = store.load(session_id)
    if session is None:
        session = _canvas_sessions.get(session_id)
    if session is None:
        raise click.ClickException(f"Session {session_id!r} not found — run 'canvas open' first")
    lw = SessionLogWriter(vault_root=root)
    cw = CanvasWriter(vault_root=root, log_writer=lw)
    try:
        cw.apply_edit(session, body, summary)
    except GovernanceBearingMutationError as exc:
        raise click.ClickException(str(exc)) from exc
    store.save(session)
    click.echo(f"edit applied to session {session_id}")


@canvas_cli.command(name="close", help="Close a canvas session and write the session log.")
@click.argument("session_id")
@click.option("--summary", default="session closed", help="Total session summary.")
@click.option("--vault-root", "vault_root", default=None, help="Vault root.")
def canvas_close(session_id: str, summary: str, vault_root: str | None) -> None:
    from app.chat.session_log import SessionLogWriter
    from app.chat.session_store import SessionStore

    root = Path(vault_root).expanduser().resolve() if vault_root else resolve_vault_root().expanduser().resolve()
    store = SessionStore(vault_root=root)
    session = store.load(session_id)
    if session is None:
        session = _canvas_sessions.pop(session_id, None)
    if session is None:
        raise click.ClickException(f"Session {session_id!r} not found")
    lw = SessionLogWriter(vault_root=root)
    lw.close_session(session, summary)
    store.delete(session_id)
    click.echo(f"session {session_id} closed")


def _store_stats_payload() -> dict:
    backend = resolve_store_backend()
    store = get_object_store()
    vector_idx = get_vector_index()
    result = {
        "backend": backend,
        "objects": store.count_objects(),
    }
    vector_counter = getattr(vector_idx, "count_vectors", None)
    if callable(vector_counter):
        result["vectors"] = vector_counter()
    return result


@cli.group(name="store", help="Store utilities.")
def store_cli() -> None:
    ...


@store_cli.command(name="stats", help="Report store and vector index counts for diagnostics.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Print the result as JSON.")
def store_stats(as_json: bool) -> None:
    _dump(_store_stats_payload(), as_json)


@cli.command(name="store-stats", help="Report store and vector index counts for diagnostics (deprecated; use 'store stats').")
@click.option("--json", "as_json", is_flag=True, default=False, help="Print the result as JSON.")
def store_stats_legacy(as_json: bool) -> None:
    _dump(_store_stats_payload(), as_json)


@cli.command(name="llm-trace-sequence", help="Render a single trace flow as text or Mermaid sequence diagram.")
@click.option("--trace-id", "trace_id", default="", help="Trace ID to visualize.")
@click.option("--latest", is_flag=True, default=False, help="Use the most recent trace_id when none is provided.")
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(["mermaid", "text"], case_sensitive=False),
    default="mermaid",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--out-file",
    "-o",
    "out_file",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional path to write Markdown output (for Obsidian).",
)
def llm_trace_sequence(trace_id: str, latest: bool, fmt: str, out_file: Path | None) -> None:
    path = Path(os.getenv("LLM_TRACE_PATH", "tmp/llm-trace.jsonl"))
    records = load_trace(path)
    if not records:
        click.echo("No trace records found.")
        return
    target_trace_id = trace_id.strip()
    if not target_trace_id:
        if latest:
            target_trace_id = max(records, key=lambda r: r.timestamp).trace_id
        else:
            click.echo("Please provide --trace-id or use --latest to select the most recent trace.")
            raise SystemExit(1)
    try:
        seq = build_sequence_for_trace(records, target_trace_id)
    except ValueError as exc:
        click.echo(str(exc))
        raise SystemExit(1)

    fmt_normalized = fmt.strip().lower()
    output = _render_mermaid_sequence(seq) if fmt_normalized == "mermaid" else _render_text_sequence(seq)

    if out_file:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        content = output if output.endswith("\n") else output + "\n"
        out_file.write_text(content, encoding="utf-8")
        click.echo(f"Wrote sequence to {out_file}")
    else:
        click.echo(output)


@cli.command(
    help="Normalize file or URL and emit core object.\n\nExamples:\n"
    "  python -m app.cli normalize file.md --json\n"
    "  python -m app.cli normalize https://example.com --trace-id T123"
)
@click.argument("source")
@click.option("--json", "as_json", is_flag=True, help="Print JSON result to stdout.")
@click.option("--trace-id", default=None, help="Attach a trace id to the run.")
def normalize(source: str, as_json: bool, trace_id: Optional[str]) -> None:
    trace_id = with_trace_id(trace_id)
    path = _materialize_source(source)
    res = normalize_run(str(path), trace_id=trace_id)
    _dump(res, as_json)


@cli.command(
    help="Classify an existing object_id using the configured agent run.\n\nExample:\n"
    "  python -m app.cli classify 00000000-0000-0000-0000-000000000000 --json"
)
@click.argument("object_id")
@click.option("--json", "as_json", is_flag=True, help="Print JSON result to stdout.")
@click.option("--trace-id", default=None, help="Attach a trace id to the run.")
def classify(object_id: str, as_json: bool, trace_id: Optional[str]) -> None:
    trace_id = with_trace_id(trace_id)
    res = classify_run(object_id, trace_id=trace_id)
    _dump(res, as_json)


@cli.command(
    help="Transcribe YouTube URL eller ljudfil till text och skriv index-outbox.\n\n"
    "Exempel:\n  python -m app.cli transcribe https://youtu.be/ID --json"
)
@click.argument("source")
@click.option("--json", "as_json", is_flag=True, help="Print JSON result to stdout.")
@click.option("--trace-id", default=None, help="Attach a trace id to the run.")
def transcribe(source: str, as_json: bool, trace_id: Optional[str]) -> None:
    trace_id = with_trace_id(trace_id)
    res = transcribe_source(source, trace_id=trace_id)
    _dump(res, as_json)


@cli.command(
    help="Run full pipeline (normalize -> classify -> optional transcribe). Accepts file, URL, or audio/YouTube."
)
@click.argument("source")
@click.option("--json", "as_json", is_flag=True, help="Print JSON result to stdout.")
@click.option("--trace-id", default=None, help="Attach a trace id to the run.")
def pipe(source: str, as_json: bool, trace_id: Optional[str]) -> None:
    trace_id = with_trace_id(trace_id)
    path = _materialize_source(source)
    normalize_res = normalize_run(str(path), trace_id=trace_id)
    classify_res = classify_run(normalize_res["object_id"], trace_id=trace_id)
    output = {"normalize": normalize_res, "classify": classify_res}

    if _should_transcribe(source):
        output["transcribe"] = transcribe_source(source, trace_id=trace_id)

    append_jsonl(
        {
            "object_id": normalize_res["object_id"],
            "kind": "pipeline",
            "source_ref": source,
            "payload": output,
        }
    )
    emit_db_outbox = _truthy_flag(os.getenv("PIPE_EMIT_DB_OUTBOX", "1"))
    if emit_db_outbox:
        db_payload = {
            "object_id": normalize_res["object_id"],
            "source_ref": str(path),
            "trace_id": trace_id,
        }
        db_event = new_event(
            event_type=INGEST_OBJECT_CREATED,
            payload=db_payload,
            trace_id=trace_id,
            source=str(path),
        )
        try:
            write_outbox_event(db_event)
        except Exception as exc:
            click.echo(f"WARNING: pipe DB outbox emit failed: {exc}", err=True)

    _dump(output, as_json)


@cli.command(
    name="ingest-vault-root",
    help="Ingest markdown files from vault root (root-only, non-recursive ingest; defaults to PKM - Alpha vault).",
)
@click.option(
    "--root",
    "root_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override vault root (default is PKM - Alpha vault).",
)
@click.option("--limit", type=int, default=None, help="Maximum number of markdown files to ingest from the vault root.")
def ingest_vault_root_cmd(root_dir: Path | None, limit: int | None) -> None:
    resolved = _resolve_vault_root_path(root_dir, allow_env=False, fallback_to_default=True)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    resolved = resolved.expanduser()
    if not resolved.exists() or not resolved.is_dir():
        raise click.BadParameter(f"Vault root not found or not a directory: {resolved}")

    click.echo(
        f"Ingesting up to {limit if limit is not None else 'all'} markdown files from vault root (non-recursive): {resolved}"
    )
    count = ingest_vault_root(resolved, limit=limit)
    click.echo(f"Successfully ingested {count} files.")


@cli.command(
    name="pkm-alpha-ingest",
    help="Convenience wrapper for ingesting markdown files from the PKM - Alpha vault root.",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    show_default=True,
    help="Maximum number of markdown files to ingest from the PKM - Alpha vault root.",
)
def pkm_alpha_ingest(limit: int | None) -> None:
    resolved = DEFAULT_VAULT_ROOT.expanduser()
    if not resolved.exists() or not resolved.is_dir():
        raise click.BadParameter(f"DEFAULT_VAULT_ROOT not found or not a directory: {resolved}")

    click.echo(
        f"PKM - Alpha ingest (DEFAULT_VAULT_ROOT): {resolved} | limit={limit if limit is not None else 'all'}"
    )
    count = ingest_vault_root(resolved, limit=limit)
    click.echo(f"Successfully ingested {count} files.")


@cli.command(
    name="vault-alpha-ingest",
    help="Ingest Concept notes from the PKM - Alpha vault with panel stripping and mirror handling.",
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional vault root (defaults to DEFAULT_VAULT_ROOT or VAULT_ROOT).",
)
@click.option(
    "--max-notes",
    type=int,
    default=200,
    show_default=True,
    help="Maximum number of notes to ingest.",
)
@click.option("--include-test-note", is_flag=True, help="Include Test/Alpha-HumanFlows.md in this run.")
@click.option("--force", is_flag=True, help="Re-ingest notes even if they appear already ingested or mirrored.")
@click.option("--locked-only", is_flag=True, help="Retry only files previously skipped due to locked errors (errno=35).")
@click.option("--json", "as_json", is_flag=True, help="Output JSON summary.")
def vault_alpha_ingest(
    vault_root: Path | None, max_notes: int, include_test_note: bool, force: bool, locked_only: bool, as_json: bool
) -> None:
    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=True)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    if locked_only:
        summary = run_vault_alpha_ingest_locked_only(resolved, force=force)
    else:
        summary = run_vault_alpha_ingest(resolved, max_notes=max_notes, include_test_note=include_test_note, force=force)
    if as_json:
        payload = {
            "scanned": summary.scanned,
            "ingested": summary.ingested,
            "included_folders": summary.included_folders,
            "force": summary.force,
            "malformed": summary.malformed,
            "errors": summary.errors,
            "skipped_locked": summary.skipped_locked,
            "locked_examples": summary.locked_examples,
            "skipped_invalid": summary.skipped_invalid,
            "invalid_examples": summary.invalid_examples,
            "invalid_report_path": summary.invalid_report_path,
        }
        _dump(payload, True)
        return
    if summary.ingested == 0 and not summary.force:
        click.echo(
            f"Scanned {summary.scanned} files; ingested {summary.ingested} notes (already up to date; run with --force to resync if the store is empty)"
        )
    else:
        suffix = f" (force={summary.force})" if summary.force else ""
        click.echo(f"Scanned {summary.scanned} files; ingested {summary.ingested} notes{suffix}")
    click.echo(f"Included folders: {', '.join(summary.included_folders) if summary.included_folders else '-'}")

@cli.command(
    name="vault-layout-ensure",
    help="Ensure vault layout folders and default vault.layout.md note exist.",
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional vault root (defaults to VAULT_ROOT or DEFAULT_VAULT_ROOT).",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON summary.")
def vault_layout_ensure(vault_root: Path | None, as_json: bool) -> None:
    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=True)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    if not resolved.exists() or not resolved.is_dir():
        raise click.BadParameter(f"Vault root not found or not a directory: {resolved}")
    from app.vault.layout import ensure_vault_layout_report

    layout, migrated, warnings = ensure_vault_layout_report(resolved)
    if as_json:
        payload = {
            "system_folder": layout.system_folder,
            "inbox_folder": layout.inbox_folder,
            "desk_folder": layout.desk_folder,
            "layout_note": str(layout.note_path),
            "migrated_legacy_system": migrated,
            "warnings": warnings,
        }
        _dump(payload, True)
        return
    click.echo(
        "Vault layout ensured: "
        f"inbox={layout.inbox_folder} desk={layout.desk_folder} system={layout.system_folder}"
    )
    if warnings:
        click.echo(f"Warnings: {', '.join(warnings)}", err=True)


@cli.command(
    name="ingest-vault-paths",
    help="Ingest specific vault markdown files by path (relative or absolute, resolved within the vault root).",
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional vault root (defaults to DEFAULT_VAULT_ROOT or VAULT_ROOT).",
)
@click.argument("paths", nargs=-1, type=click.Path(path_type=Path))
def ingest_vault_paths_cmd(vault_root: Path | None, paths: tuple[Path, ...]) -> None:
    if not paths:
        raise click.BadParameter("At least one path must be provided.")
    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=True)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    summary = run_vault_alpha_ingest_paths(resolved, paths, force=False)
    click.echo(
        f"Scanned {summary.scanned} paths; ingested {summary.ingested} notes (malformed={summary.malformed}, errors={summary.errors})"
    )
    if summary.error_notes:
        click.echo(f"Error ingesting: {', '.join(summary.error_notes)}", err=True)


@cli.command(
    name="ingest-external",
    help="Ingest external files (txt/md) from a drop folder into the external plane (external_raw).",
)
@click.option(
    "--root",
    "root_dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Path to the external drop folder.",
)
@click.option("--limit", type=int, default=None, help="Maximum number of files to ingest.")
def ingest_external_cmd(root_dir: Path, limit: int | None) -> None:
    summary = ingest_external_folder(root_dir, limit=limit)
    click.echo(f"External ingest: scanned={summary.scanned} ingested={summary.ingested} errors={summary.errors}")
    if summary.error_files:
        click.echo(f"Error files: {', '.join(summary.error_files)}", err=True)


@cli.command(
    name="orchestrate-external",
    help="Run the external ingest pipeline via the orchestrator runtime (plan + executor).",
)
@click.option(
    "--root",
    "root_dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Path to the external drop folder.",
)
@click.option("--limit", type=int, default=None, help="Maximum number of files to ingest.")
def orchestrate_external(root_dir: Path, limit: int | None) -> None:
    plan = Plan(
        id=new_plan_id(),
        meta=PlanMetadata(goal="External ingest", source_object_uuid=str(uuid.uuid4()), created_by="cli.orchestrator"),
        steps=[
            PlanStep(
                id="ingest-external",
                kind="tool_call",
                description="Ingest external drop folder",
                tool="internal.ingest_external",
                tool_args={"root_dir": str(root_dir), **({"limit": limit} if limit is not None else {})},
            )
        ],
        goal="External ingest",
    )
    orchestrator = Orchestrator()
    results = orchestrator.run_plan(plan)
    click.echo(f"Plan {plan.id} results:")
    for entry in results:
        status = entry.get("status")
        detail = entry.get("error") or entry.get("result")
        click.echo(f"  - step={entry.get('step_id')} status={status} detail={detail}")


@cli.command(
    name="panel-orchestrate-plan",
    help="Execute a panel-originated plan via the orchestrator runtime.",
)
@click.option("--plan-id", "plan_id", type=str, default=None, help="Identifier of the plan to execute.")
@click.option(
    "--note-uuid",
    "note_uuid",
    type=str,
    default=None,
    help="Optional note UUID; executes the latest panel plan for that note when plan-id is omitted.",
)
def panel_orchestrate_plan(plan_id: str | None, note_uuid: str | None) -> None:
    store = get_plan_store()
    plan = store.get(plan_id) if plan_id else None
    if plan is None and note_uuid:
        candidates = store.list_by_object(note_uuid)
        plan = candidates[-1] if candidates else None
    if plan is None:
        click.echo("No matching plan found for execution.", err=True)
        raise SystemExit(1)

    orchestrator = Orchestrator()
    results = orchestrator.run_plan(plan)
    click.echo(f"Executed plan {plan.id} with {len(plan.steps)} step(s)")
    for entry in results:
        status = entry.get("status")
        detail = entry.get("error") or entry.get("result")
        click.echo(f"  - step={entry.get('step_id')} status={status} detail={detail}")
    if not results:
        click.echo("No steps executed.")


@cli.command(
    name="alpha-human-flows",
    help=(
        "Dev-only: run alpha human flows end-to-end (sample ingest, test note, panel, promotion, ASK) "
        "against a vault root for testing."
    ),
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional vault root (defaults to DEFAULT_VAULT_ROOT).",
)
@click.option("--dry-run", is_flag=True, help="Print actions without writing to disk.")
@click.option(
    "--sample-size",
    type=int,
    default=6,
    show_default=True,
    help="Maximum sample notes to ingest in Flow A.",
)
@click.option(
    "--explain-only",
    is_flag=True,
    help="Print checklist of flows without running any steps.",
)
@click.option(
    "--reset-outbox",
    is_flag=True,
    help="Development/diagnostic only: truncates the index outbox file before running (no effect in dry-run or explain-only).",
)
def alpha_human_flows(
    vault_root: Path | None, dry_run: bool, sample_size: int, explain_only: bool, reset_outbox: bool
) -> None:
    """
    Flows: A) ingest sample notes; B) ensure Test/Alpha-HumanFlows.md exists;
    C) ingest + report mirror path; D) insert AI panel and reingest;
    E) set reviewed/evergreen frontmatter and reingest; F) run ASK queries.
    """
    resolved = _resolve_vault_root_path(vault_root, allow_env=False, fallback_to_default=True)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    run_alpha_human_flows(
        resolved,
        dry_run=dry_run,
        sample_size=sample_size,
        explain_only=explain_only,
        reset_outbox=reset_outbox,
    )


@cli.command(name="yggdrasil-init", help="Initialize a Yggdrasil root with module folders and the Mimer vault layout.")
@click.option(
    "--root",
    "root_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional Yggdrasil root path (defaults to settings.yggdrasil_paths.yggdrasil_root or ~/Yggdrasil).",
)
def yggdrasil_init(root_dir: Path | None) -> None:
    yggdrasil_root = _resolve_yggdrasil_root(root_dir).expanduser()
    result = YggdrasilScaffolder(root=yggdrasil_root).scaffold()
    created = result.get("created", [])
    existed = result.get("existed", [])

    click.echo(f"Yggdrasil root: {yggdrasil_root}")
    if created:
        click.echo("Created:")
        for path in sorted(created):
            click.echo(f"  - {path}")
    if existed:
        click.echo("Already existed:")
        for path in sorted(set(existed)):
            click.echo(f"  - {path}")


@cli.command(help="Ask a question through the planner/orchestrator pipeline.")
@click.argument("question")
@click.option("--vault-root", type=click.Path(path_type=Path), default=None, help="Path to vault root for MCP writes.")
@click.option("--enable-mcp-vault", is_flag=True, default=False, help="Enable real MCP vault writes.")
def ask(question: str, vault_root: Path | None, enable_mcp_vault: bool) -> None:
    # ASK call chain:
    # CLI -> new ask.query.received event -> planner.plan_for_event -> Orchestrator.run_plan
    # -> PlanExecutor executes agent/tool/decision steps. QA answers come from app.agents.qa.answer
    # (hybrid_search over retrieval store -> LLM provider mock/ollama) when a plan step targets QA.
    question_text = question.strip()
    if not question_text:
        raise click.BadParameter("Question must not be empty.")

    event = new_event(event_type=ASK_QUERY_RECEIVED, payload={"question": question_text}, source="cli")
    resolved_root = _resolve_vault_root_path(vault_root)
    env_flag = os.getenv("MCP_VAULT_ENABLE")
    writes_enabled = enable_mcp_vault or _truthy_flag(env_flag)
    tool_settings: Dict[str, Any] = {}
    if resolved_root is not None:
        tool_settings["vault_root"] = str(resolved_root)
    elif writes_enabled:
        tool_settings["vault_root"] = str(Path("vault"))
    if writes_enabled:
        tool_settings["mcp_vault_enable"] = True
    else:
        tool_settings["mcp_vault_enable"] = False

    executor = MockPlanExecutor(handlers={"ingest-agent": _ingest_agent_stub})
    orchestrator = _RecordingOrchestrator(executor=executor, tool_settings=tool_settings)
    settings: Dict[str, Any] = {"event_orchestrator_enable": True, "origin": "cli.ask"}
    planner_profiles_env = os.getenv("PLANNER_PROFILES_ENABLE")
    if planner_profiles_env is not None:
        settings["planner_profiles_enable"] = planner_profiles_env
    plan = handle_event(event, OrchestratorContext(settings=settings, orchestrator=orchestrator))
    results = orchestrator.last_results or []

    click.echo(f"Question: {question_text}")
    selection = None
    if plan.context:
        selection = plan.context.get("profile_selection")
    if selection:
        flow_id = selection.get("flow_id") or "-"
        pattern = (selection.get("pattern") or {}).get("name") or "-"
        prompt = (selection.get("prompt_profile") or {}).get("id") or "-"
        click.echo(f"Flow: {flow_id} pattern: {pattern} prompt: {prompt}")
    else:
        flow_ids = (plan.context or {}).get("flow_ids") or []
        if flow_ids:
            click.echo(f"Flow: {flow_ids[0]}")
    click.echo(f"Plan steps: {len(plan.steps)}")
    if writes_enabled:
        click.echo("Vault writes enabled.")
    else:
        click.echo("Vault writes disabled (mock mode).")

    step_lookup = {step.id: step for step in plan.steps}
    exit_code = 0
    for entry in results:
        step = step_lookup.get(entry.get("step_id"))
        label = step.description if step else entry.get("step_id")
        click.echo(f"- {label}: {entry.get('status')}")
        if entry.get("status") == "error":
            exit_code = 1
            if entry.get("error_type"):
                click.echo(f"  error_type: {entry['error_type']}")
            if entry.get("error"):
                click.echo(f"  error: {entry['error']}")

    note_path = _extract_note_path(results)
    if note_path:
        click.echo(f"note_path: {note_path}")
    elif not writes_enabled:
        click.echo("No files were written.")

    if exit_code != 0:
        raise SystemExit(exit_code)


@cli.command(name="llm-trace-flows", help="Inspect LLM trace flows grouped by trace_id.")
@click.option("--agent", default=None, help="Filter by agent name.")
@click.option("--limit", default=1, show_default=True, help="Number of trace groups to display.")
def llm_trace_flows(agent: Optional[str], limit: int) -> None:
    path = Path(os.getenv("LLM_TRACE_PATH", "tmp/llm-trace.jsonl"))
    records = load_trace(path)
    if agent:
        records = [r for r in records if r.agent == agent]
    if not records:
        click.echo("No trace records found.")
        return
    grouped = group_by_trace_id(records)
    count = 0
    for trace_id, recs in grouped.items():
        click.echo(f"=== trace_id: {trace_id} ===")
        for idx, rec in enumerate(recs, start=1):
            mode = f" mode={rec.mode}" if getattr(rec, "mode", "") else ""
            status = f" status={rec.status}" if getattr(rec, "status", "") else ""
            click.echo(f"[{idx}] agent={rec.agent}{mode}{status} kind={rec.kind}")
            click.echo(f"    prompt:   {rec.prompt_preview}")
            click.echo(f"    response: {_response_text(rec)}")
            click.echo()
        count += 1
        if count >= max(1, limit):
            break


@cli.command(name="llm-trace-planner-flows", help="Show planner-centric LLM traces (planner → reasoning → answer).")
@click.option("--limit", default=1, show_default=True, help="Number of trace groups to display.")
def llm_trace_planner_flows(limit: int) -> None:
    allowed_agents = {"planner", "reasoning", "set_evaluator", "reviewer", "orchestrator", "qa"}
    path = Path(os.getenv("LLM_TRACE_PATH", "tmp/llm-trace.jsonl"))
    records = [rec for rec in load_trace(path) if rec.agent in allowed_agents]
    if not records:
        click.echo("No planner-centric trace records found.")
        return
    grouped = group_by_trace_id(records)
    count = 0
    for trace_id, recs in grouped.items():
        has_planner = any(rec.agent == "planner" or rec.kind.startswith("planner.") for rec in recs)
        has_other = any(rec.agent != "planner" for rec in recs)
        if not (has_planner and has_other):
            continue
        click.echo(f"=== trace_id: {trace_id} ===")
        for idx, rec in enumerate(recs, start=1):
            mode = f" mode={rec.mode}" if getattr(rec, "mode", "") else ""
            status = f" status={rec.status}" if getattr(rec, "status", "") else ""
            click.echo(f"[{idx}] agent={rec.agent}{mode}{status} kind={rec.kind}")
            click.echo(f"    prompt:   {rec.prompt_preview}")
            click.echo(f"    response: {_response_text(rec)}")
            click.echo()
        count += 1
        if count >= max(1, limit):
            break


@cli.command(help="Run the AI panel pipeline on a note and optionally dispatch events.")
@click.argument("note_path", type=click.Path(path_type=Path))
@click.option("--old-path", type=click.Path(path_type=Path), default=None, help="Path to old note content for diffing.")
def panel_update(note_path: Path, old_path: Path | None) -> None:
    note_path = note_path.resolve()
    old_path = old_path.resolve() if old_path else None
    new_markdown = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
    old_markdown = new_markdown
    if old_path is not None and old_path.exists():
        old_markdown = old_path.read_text(encoding="utf-8")

    ctx = OrchestratorContext(settings={"origin": "cli.panel"})
    result = handle_panel_update(
        note_id=str(note_path),
        old_markdown=old_markdown,
        new_markdown=new_markdown,
        ctx=ctx,
    )

    if result.panel.updated_markdown != new_markdown:
        _write_note_via_knowledge_port(note_path, result.panel.updated_markdown)

    click.echo(f"Note: {note_path}")
    click.echo(f"Panel intents: {len(result.panel.intents)}")
    click.echo(f"Panel events: {len(result.events)} created, {result.dispatch_count} dispatched")
    if result.plans:
        click.echo(f"Plans executed: {len(result.plans)}")
    else:
        click.echo("Plans executed: 0")


def _format_note_update_status(result: NoteUpdateResult) -> str:
    if result.stale:
        status = "stale (skipped)"
    elif result.changed:
        status = f"updated (events={result.events_count}, dispatched={result.dispatch_count})"
    else:
        status = "no changes"
    if getattr(result, "uuid_added", False):
        status = f"{status} (added uuid={result.uuid})"
    return status


@cli.command(help="Run NoteUpdateService on one or more notes.")
@click.argument("target", type=click.Path(path_type=Path))
@click.option("--glob", "pattern", default="*.md", help="Glob pattern when target is a directory.")
def note_update(target: Path, pattern: str) -> None:
    resolved_target = target.resolve()
    if resolved_target.is_dir():
        files = sorted(p for p in resolved_target.rglob(pattern) if p.is_file())
    elif resolved_target.is_file():
        files = [resolved_target]
    else:
        raise click.BadParameter(f"Path not found: {target}")
    if not files:
        click.echo("No notes matched.")
        return
    ctx = OrchestratorContext(settings={"origin": "cli.note_update"})
    processed = changed = dispatched = errors = 0
    for file_path in files:
        try:
            result = process_note_update(file_path, ctx)
        except Exception as exc:
            click.echo(f"{file_path}: error: {exc}")
            errors += 1
            continue
        processed += 1
        if result.stale:
            click.echo(f"{file_path}: {_format_note_update_status(result)}")
            continue
        dispatched += result.dispatch_count
        if result.changed:
            changed += 1
        click.echo(f"{file_path}: {_format_note_update_status(result)}")
    click.echo(f"Processed {processed} notes (changed: {changed}, dispatched: {dispatched})")
    if errors:
        raise SystemExit(1)


@cli.command(help="Scan vault for changed notes and run NoteUpdateService on detected edits.")
@click.argument("target", type=click.Path(path_type=Path))
@click.option("--glob", "pattern", default="*.md", help="Glob pattern when target is a directory.")
def note_scan(target: Path, pattern: str) -> None:
    resolved_target = target.resolve()
    if not resolved_target.exists():
        raise click.BadParameter(f"Path not found: {target}")

    service = NoteWatcherService(vault_root=resolved_target, glob_pattern=pattern)
    ctx = OrchestratorContext(settings={"origin": "cli.note_scan"})
    results = service.scan_vault_once(ctx)

    dispatched = sum(result.dispatch_count for result in results)
    changed = sum(1 for result in results if result.changed)
    processed = service.last_scan.get("processed", len(results))
    skipped = service.last_scan.get("skipped", 0)
    total = service.last_scan.get("checked", processed + skipped)
    errors = service.last_scan.get("errors", 0)

    for result in results:
        click.echo(f"{result.current_path}: {_format_note_update_status(result)}")
    for path in service.last_skipped:
        click.echo(f"{path}: skipped")

    click.echo(
        f"Scanned {total} notes (processed: {processed}, changed: {changed}, skipped: {skipped}, dispatched: {dispatched})"
    )

    if errors:
        raise SystemExit(1)


@cli.group(
    help="Kör funktionskontroller för lokala beroenden (ffmpeg, yt-dlp, index-outbox, Ollama).",
    invoke_without_command=True,
)
@click.option("--json", "as_json", is_flag=True, help="Print JSON result to stdout.")
@click.option("--trace-id", default=None, help="Attach a trace id to the run.")
@click.pass_context
def health(ctx, as_json: bool, trace_id: Optional[str]) -> None:
    if ctx.invoked_subcommand is not None:
        return
    trace_id = with_trace_id(trace_id)
    result = run_health(trace_id=trace_id)
    _dump(result, as_json)
    if not result.get("ok"):
        raise SystemExit(1)


@health.command("status", help="Emit the health contract snapshot (JSON or text).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON payload.")
def health_status(as_json: bool) -> None:
    emit_health_contract_status(as_json)


@cli.command(help="Print a system status snapshot (Reality-MVP observability).")
def status() -> None:
    status = get_system_status()
    baseline = getattr(status, "sot_baseline_version", status.sot_version)
    forward_line = getattr(status, "feature_line_version", None) or getattr(status, "sot_forward_line_version", None)
    label = getattr(status, "sot_label", "")
    features = getattr(status, "active_features", []) or []
    intents = getattr(status, "intents", None)
    events = getattr(status, "events", None)

    click.echo(f"Environment: {status.environment}")
    click.echo(f"SoT baseline: {baseline} (Reality-MVP, locked)")
    if forward_line:
        click.echo(f"SoT forward line: {forward_line} (PanelAgent + Watchers)")
    if label:
        click.echo(f"SoT label: {label}")
    if features:
        click.echo("Active features:")
        for feat in features:
            click.echo(f"  - {feat}")
    click.echo(f"Timestamp: {status.timestamp.isoformat()}Z")
    click.echo("Stores:")
    for store in status.stores:
        last_ingest = store.last_ingest_at.isoformat() if store.last_ingest_at else "-"
        last_error = store.last_error_at.isoformat() if store.last_error_at else "-"
        click.echo(
            f"  - {store.name}: {store.object_count} objects (last_ingest: {last_ingest}, last_error: {last_error})"
        )
    click.echo("Ingestion:")
    click.echo(f"  last_run: {status.ingestion.last_run_at.isoformat() if status.ingestion.last_run_at else '-'}")
    if status.ingestion.last_run_ok is None:
        click.echo("  status: unknown")
    else:
        click.echo(f"  status: {'OK' if status.ingestion.last_run_ok else 'FAILED'}")
    click.echo(
        "  totals: "
        f"scanned={status.ingestion.total_scanned} "
        f"ingested={status.ingestion.total_ingested} "
        f"errors={status.ingestion.total_errors} "
        f"malformed={status.ingestion.total_malformed}"
    )
    if status.ingestion.planes:
        click.echo("  per-plane:")
        for plane in status.ingestion.planes:
            last_run = plane.last_run_at.isoformat() if plane.last_run_at else "-"
            click.echo(
                "    - "
                f"{plane.plane}: scanned={plane.scanned or 0} ingested={plane.ingested or 0} "
                f"errors={plane.errors or 0} malformed={plane.malformed or 0} last_run={last_run}"
            )
    click.echo(f"  last_error: {status.ingestion.last_error_message or '-'}")
    if events:
        click.echo("Events:")
        click.echo(f"  watcher runs: total={events.watcher_runs_total} (24h={events.watcher_runs_24h})")
        click.echo(f"  panel runs: total={events.panel_runs_total} (24h={events.panel_runs_24h})")
        click.echo("  promotion intents:")
        click.echo(f"    total={events.promote_created_total} (24h={events.promote_created_24h})")
        click.echo("  promotion executed:")
        click.echo(f"    total={events.promotion_executed_total} (24h={events.promotion_executed_24h})")
        if events.ingest_runs_by_plane:
            click.echo("  ingest runs by plane:")
            for plane, count in events.ingest_runs_by_plane.items():
                click.echo(f"    - {plane}: {count}")
        if getattr(events, 'source_path', None):
            click.echo(f"  source: {events.source_path}")
    watcher_automation = getattr(status, "watcher_automation", None)
    if watcher_automation:
        click.echo("Watcher automation:")
        click.echo(
            "  gate: "
            f"{watcher_automation.mode} "
            f"(enabled={watcher_automation.auto_exec_enabled}, "
            f"source={watcher_automation.source}, env={watcher_automation.env_key}, "
            f"raw={watcher_automation.raw_value or '-'}, default={watcher_automation.default_enabled})"
        )
        click.echo(
            "  allowlist: "
            f"{', '.join(watcher_automation.allowed_actions) if watcher_automation.allowed_actions else '-'}"
        )
        click.echo(
            "  invalid_actions: "
            f"{', '.join(watcher_automation.invalid_allowed_actions) if watcher_automation.invalid_allowed_actions else '-'}"
        )
        click.echo(
            "  write_guard: "
            f"writes_allowed={watcher_automation.writes_allowed} mode={watcher_automation.write_guard_mode or '-'}"
        )
        click.echo(
            "  paths: "
            f"settings={watcher_automation.source_path or '-'} "
            f"tick_log={watcher_automation.tick_log_path or '-'} "
            f"panel_event_log={watcher_automation.panel_event_log_path or '-'}"
        )
        if watcher_automation.last_tick_timestamp:
            click.echo(
                "  last_tick: "
                f"ts={watcher_automation.last_tick_timestamp} "
                f"candidates={watcher_automation.last_tick_panel_candidates or 0} "
                f"skipped_policy={watcher_automation.last_tick_panel_skipped_policy or 0} "
                f"skipped_auto_exec={watcher_automation.last_tick_panel_skipped_auto_exec or 0}"
            )
        if (
            watcher_automation.last_run_skipped_dedup is not None
            or watcher_automation.last_run_skipped_idempotent is not None
            or watcher_automation.last_run_skipped_writes_blocked is not None
            or watcher_automation.last_run_skipped_allowed_actions is not None
        ):
            click.echo(
                "  last_run_skips: "
                f"dedup={watcher_automation.last_run_skipped_dedup or 0} "
                f"idempotent={watcher_automation.last_run_skipped_idempotent or 0} "
                f"writes_blocked={watcher_automation.last_run_skipped_writes_blocked or 0} "
                f"allowed_actions={watcher_automation.last_run_skipped_allowed_actions or 0}"
            )
    watcher_lifecycle = getattr(status, "watcher_lifecycle", None)
    if watcher_lifecycle:
        click.echo("Watcher lifecycle:")
        panel_changed = watcher_lifecycle.panel_changed_total
        panel_emitted = watcher_lifecycle.panel_emitted_total
        panel_rate_limited = watcher_lifecycle.panel_rate_limited_total
        if any(v is not None for v in (panel_changed, panel_emitted, panel_rate_limited)):
            click.echo(
                "  panel watcher: "
                f"changed={panel_changed if panel_changed is not None else '-'} "
                f"emitted={panel_emitted if panel_emitted is not None else '-'} "
                f"rate_limited={panel_rate_limited if panel_rate_limited is not None else '-'}"
            )
            if watcher_lifecycle.panel_last_emitted_event_at:
                click.echo(f"  panel last_emitted_at: {watcher_lifecycle.panel_last_emitted_event_at}")
        ingest_changed = watcher_lifecycle.ingest_changed_total
        ingest_emitted = watcher_lifecycle.ingest_emitted_total
        ingest_rate_limited = watcher_lifecycle.ingest_rate_limited_total
        if any(v is not None for v in (ingest_changed, ingest_emitted, ingest_rate_limited)):
            click.echo(
                "  ingest watcher: "
                f"changed={ingest_changed if ingest_changed is not None else '-'} "
                f"emitted={ingest_emitted if ingest_emitted is not None else '-'} "
                f"rate_limited={ingest_rate_limited if ingest_rate_limited is not None else '-'}"
            )
        if watcher_lifecycle.last_panel_run_at is not None:
            actions_count = watcher_lifecycle.last_panel_run_actions_count
            executed_count = watcher_lifecycle.last_panel_run_executed_count
            click.echo(
                f"  last_panel_run: at={watcher_lifecycle.last_panel_run_at} "
                f"actions={actions_count if actions_count is not None else '-'} "
                f"executed={executed_count if executed_count is not None else '-'}"
            )
            if watcher_lifecycle.last_panel_run_summary:
                click.echo(f"  last_panel_run_summary: {watcher_lifecycle.last_panel_run_summary}")
        else:
            click.echo("  last_panel_run: none")
    click.echo("ASK:")
    avg_latency = (
        f"{status.ask.avg_latency_ms_24h:.0f} ms" if status.ask.avg_latency_ms_24h is not None else "-"
    )
    click.echo(f"  queries (24h): {status.ask.total_queries_24h}")
    click.echo(f"  errors (24h): {getattr(status.ask, 'error_count_24h', 0)}")
    click.echo(f"  avg latency: {avg_latency}")
    if intents and not events:
        click.echo("Intents:")
        click.echo(f"  promote.intent.created total: {intents.promote_created_total}")
        click.echo(f"  promote.intent.created (24h): {intents.promote_created_24h}")
        if getattr(intents, 'source_path', None):
            click.echo(f"  source: {intents.source_path}")
@cli.command("promote-consume", help="Consume promotion intents from outbox and apply promotion effects.")
@click.option("--limit", type=int, default=None, help="Maximum number of intents to consume.")
def promote_consume(limit: int | None) -> None:
    summary = consume_promotion_intents(limit=limit)
    click.echo("Promotion consume summary:")
    click.echo(f"  intents_seen={summary['intents_seen']}")
    click.echo(f"  applied={summary['applied']}")
    click.echo(f"  errors={summary['errors']}")
    click.echo(f"  emitted={summary['emitted']}")
    if summary.get('errors'):
        raise SystemExit(1)

@cli.group(help="Settings commands (Vault-as-GUI).")
def settings() -> None:
    ...

@cli.command("settings-validate", help="Validate settings registries and cross-references.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON output.")
def settings_validate_alias(as_json: bool) -> None:
    exit_code = run_settings_validate(as_json=as_json)
    raise SystemExit(exit_code)


@cli.command("settings-explain", help="Explain settings provenance / resolution (JSON).")
@click.option("--json", "as_json", is_flag=True, help="(Deprecated) Always emits JSON; kept for compatibility.")
@click.option("--compact", is_flag=True, help="Emit compact JSON (no indentation).")
def settings_explain_alias(as_json: bool, compact: bool) -> None:
    del as_json
    payload = build_settings_explain_payload()
    emit_settings_explain(payload, pretty=not compact)


@settings.command("compile", help="Compile vault/@Settings into runtime/settings.")
@click.option("--auto-heal/--no-auto-heal", default=False, help="Rewrite YAML blocks when invalid values are healed.")
def settings_compile(auto_heal: bool) -> None:
    bundle = compile_all(auto_heal=auto_heal)
    click.echo(f"compiled {len(bundle.agents)} agents")


@settings.command("validate", help="Validate settings registries and cross-references.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON output.")
def settings_validate(as_json: bool) -> None:
    exit_code = run_settings_validate(as_json=as_json)
    raise SystemExit(exit_code)


@settings.command("watch", help="Watch vault settings markdown and recompile deterministically.")
@click.option("--path", "watch_path", default="vault/@Settings", type=click.Path(path_type=Path))
@click.option("--auto-heal/--no-auto-heal", default=False, help="Rewrite YAML blocks when invalid values are healed.")
def settings_watch(watch_path: Path, auto_heal: bool) -> None:
    compile_all(auto_heal=auto_heal)
    click.echo(f"watching {watch_path}")
    last = 0.0
    try:
        for changes in watch(str(watch_path), recursive=True):
            now = time.time()
            if now - last < 0.5:
                continue
            compile_all(auto_heal=auto_heal)
            changed = ", ".join(str(Path(path).name) for _, path in changes)
            click.echo(f"settings updated: {changed}")
            last = now
    except KeyboardInterrupt:
        click.echo("stopped watching settings")



@cli.command(
    name="uat-seed-vault-test",
    help="Seed curated watcher/panel UAT notes into a vault Test folder for manual runs.",
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path),
    required=True,
    help="Vault root path (will place notes under <vault_root>/<target-subdir>/<folder>).",
)
@click.option(
    "--target-subdir",
    type=str,
    default=DEFAULT_TARGET_SUBDIR,
    show_default=True,
    help="Subdirectory under the vault root to place seeds (default Test).",
)
@click.option(
    "--folder",
    type=str,
    default=DEFAULT_FOLDER_NAME,
    show_default=True,
    help="Folder name created inside target subdir for UAT seeds.",
)
@click.option("--overwrite/--no-overwrite", default=False, show_default=True)
def uat_seed_vault_test(vault_root: Path, target_subdir: str, folder: str, overwrite: bool) -> None:
    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=False)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    summary = seed_vault_test_notes(vault_root=resolved, target_subdir=target_subdir, folder=folder, overwrite=overwrite)
    click.echo(
        f"Seeded UAT notes to {summary.destination} (written={summary.written} skipped={summary.skipped}, overwrite={overwrite})"
    )


@cli.command(
    name="uat-run-vault-test",
    help="Run watcher + panel + promotion consumer against seeded Test notes.",
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path),
    required=True,
    help="Vault root path; watcher scope will be <vault_root>/<target-subdir>.",
)
@click.option(
    "--target-subdir",
    type=str,
    default=DEFAULT_TARGET_SUBDIR,
    show_default=True,
    help="Subdirectory under vault root to watch (default Test).",
)
@click.option(
    "--folder",
    type=str,
    default=DEFAULT_FOLDER_NAME,
    show_default=True,
    help="Seed folder name that holds UAT notes.",
)
@click.option(
    "--max-notes",
    type=int,
    default=DEFAULT_MAX_NOTES,
    show_default=True,
    help="Maximum changed notes allowed before aborting unless --force.",
)
@click.option("--force", is_flag=True, help="Override max-notes guard.")
@click.option("--dry-run", is_flag=True, help="Perform watcher scan without ingest/panel/promotion.")
@click.option("--run-panels/--no-run-panels", default=True, show_default=True)
@click.option("--consume-promotions/--no-consume-promotions", default=True, show_default=True)
@click.option("--assert", "assert_expectations", is_flag=True, help="Fail if expected intents/effects are missing.")
@click.option(
    "--assert-mode",
    type=click.Choice(["bootstrap", "converged"], case_sensitive=False),
    default="bootstrap",
    show_default=True,
    help="Assertion profile for scripted UAT: first successful run vs stable rerun.",
)
def uat_run_vault_test(
    vault_root: Path,
    target_subdir: str,
    folder: str,
    max_notes: int,
    force: bool,
    dry_run: bool,
    run_panels: bool,
    consume_promotions: bool,
    assert_expectations: bool,
    assert_mode: str,
) -> None:
    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=False)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    try:
        summary = run_vault_test_flow(
            vault_root=resolved,
            target_subdir=target_subdir,
            folder=folder,
            max_notes=max_notes,
            force=force,
            dry_run=dry_run,
            run_panels=run_panels,
            consume_promotions=consume_promotions,
            assert_expectations=assert_expectations,
            assert_mode=assert_mode.lower(),
        )
    except FileNotFoundError as exc:
        raise click.BadParameter(str(exc))
    except UATAssertionError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    for line in summary.to_lines():
        click.echo(line)

    if summary.watcher.get("limit_exceeded"):
        raise SystemExit(1)
    if summary.watcher.get("errors", 0) or summary.promotion.get("errors", 0):
        raise SystemExit(1)


@cli.command(
    name="sync-latency-harness",
    help="Run automated multi-device sync latency measurements on seeded test vault.",
)
@click.option(
    "--vault-root",
    type=click.Path(path_type=Path),
    required=True,
    help="Vault root path; watcher scope will be <vault_root>/<target-subdir>.",
)
@click.option(
    "--target-subdir",
    type=str,
    default=DEFAULT_TARGET_SUBDIR,
    show_default=True,
    help="Subdirectory under vault root to watch (default Test).",
)
@click.option(
    "--folder",
    type=str,
    default=DEFAULT_FOLDER_NAME,
    show_default=True,
    help="Folder name containing test notes for latency measurement.",
)
@click.option(
    "--scenario",
    type=str,
    default="changed-note-default",
    show_default=True,
    help="Name of the latency measurement scenario.",
)
@click.option(
    "--report",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional path to write machine-readable JSON report.",
)
@click.option(
    "--panel-decider",
    type=click.Choice(["rule", "llm"], case_sensitive=False),
    default="rule",
    show_default=True,
    help="Panel decider mode during the harness run; use rule mode for provider-free deterministic validation.",
)
@click.option(
    "--timeout-seconds",
    type=int,
    default=180,
    show_default=True,
    help="Bounded wall-clock timeout for watcher/panel convergence.",
)
@click.option("--dry-run", is_flag=True, help="Skip watcher/panel execution, report only.")
def sync_latency_harness(
    vault_root: Path,
    target_subdir: str,
    folder: str,
    scenario: str,
    report: Path | None,
    panel_decider: str,
    timeout_seconds: int,
    dry_run: bool,
) -> None:
    """Run automated multi-device sync latency measurements.

    The harness seeds or targets a bounded changed-note scenario, waits for
    the sync/runtime chain to converge, and collects machine-readable timing
    outputs. Suitable for repeated trials and latency analysis.
    """
    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=False)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")

    try:
        summary = run_latency_harness(
            vault_root=resolved,
            target_subdir=target_subdir,
            folder=folder,
            scenario=scenario,
            report_path=report,
            dry_run=dry_run,
            panel_decider=panel_decider.lower(),
            timeout_seconds=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise click.BadParameter(str(exc))
    except LatencyHarnessTimeoutError as exc:
        raise click.ClickException(str(exc))

    for line in summary.to_lines():
        click.echo(line)

    if report:
        click.echo(f"Report written to: {report}")

    if not summary.latency_results:
        click.echo("WARNING: No latency measurements captured. Verify notes were changed and events were emitted.")
        if not dry_run:
            raise SystemExit(1)


@cli.command(
    name="runtime-loop",
    help=(
        "Dev-only watcher→panel→promotion loop (requires PKM_ENVIRONMENT=dev or PKM_SETTINGS_PROFILE=lab). "
        "Use `watcher run` for production operation."
    ),
)
@click.option("--vault-root", type=click.Path(path_type=Path), required=True, help="Vault root path.")
@click.option("--snapshot-path", type=click.Path(path_type=Path), default=None, help="Optional snapshot path for watcher state.")
@click.option("--interval", type=int, default=0, show_default=True, help="Polling interval seconds; 0 runs only once.")
@click.option("--cooldown-seconds", type=int, default=10, show_default=True, help="Cooldown after a run with changes.")
@click.option("--max-notes", type=int, default=50, show_default=True, help="Maximum changed notes before abort unless --force.")
@click.option("--force", is_flag=True, help="Override max-notes guard.")
@click.option("--dry-run", is_flag=True, help="Skip ingest/panel/promotion side effects.")
@click.option("--run-panels/--no-run-panels", default=True, show_default=True)
@click.option("--consume-promotions/--no-consume-promotions", default=True, show_default=True)
@click.option("--outbox-path", type=click.Path(path_type=Path), default=None, help="Outbox path (defaults to INDEX_OUTBOX_PATH env).")
def runtime_loop(
    vault_root: Path,
    snapshot_path: Path | None,
    interval: int,
    cooldown_seconds: int,
    max_notes: int,
    force: bool,
    dry_run: bool,
    run_panels: bool,
    consume_promotions: bool,
    outbox_path: Path | None,
) -> None:
    try:
        require_lab_profile(command_name="runtime-loop")
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=False)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")

    try:
        resolved_outbox = resolve_outbox_path(outbox_path)
    except OutboxPathError as exc:
        raise click.ClickException(str(exc))

    cfg = RuntimeLoopConfig(
        snapshot_path=snapshot_path,
        poll_seconds=max(interval, 0) or 30,
        cooldown_seconds=cooldown_seconds,
        max_notes=max_notes,
        force=force,
        dry_run=dry_run,
        run_panels=run_panels,
        run_promotion_consumer=consume_promotions,
        outbox_path=resolved_outbox,
    )

    if interval and interval > 0:
        run_forever(resolved, cfg)
        return

    summary = run_once(resolved, cfg)
    click.echo(
        "watcher="
        + json.dumps(summary.watcher, ensure_ascii=False)
        + " promotion="
        + json.dumps(summary.promotion, ensure_ascii=False)
    )

@cli.command(name="go-live-check", help="Sanity-check go-live readiness; dry-run watcher by default.")
@click.option("--vault-root", type=click.Path(path_type=Path), default=None, help="Vault root (VAULT_ROOT or repo default).")
@click.option("--settings-path", type=click.Path(path_type=Path), default=None, help="Override system-settings.yaml path.")
@click.option("--outbox-path", type=click.Path(path_type=Path), default=None, help="Override outbox path (defaults to INDEX_OUTBOX_PATH).")
@click.option("--max-notes", type=int, default=25, show_default=True, help="Maximum notes to process before aborting.")
@click.option("--apply", "apply_changes", is_flag=True, help="Run without dry-run (applies ingest/panel actions).")
def go_live_check(
    vault_root: Path | None,
    settings_path: Path | None,
    outbox_path: Path | None,
    max_notes: int,
    apply_changes: bool,
) -> None:
    resolved_vault = resolve_vault_root(vault_root)
    resolved_vault = resolved_vault.expanduser()
    if not resolved_vault.exists() or not resolved_vault.is_dir():
        raise click.ClickException(f"Vault root not found or not a directory: {resolved_vault}")

    resolved_settings = resolve_system_settings_path(explicit=settings_path, vault_root=resolved_vault)
    click.echo(f"Vault root: {resolved_vault}")
    click.echo(f"System settings path: {resolved_settings}")
    try:
        settings_data = settings_service.load_settings(force=True, path=resolved_settings)
    except Exception as exc:
        raise click.ClickException(f"Failed to load settings from {resolved_settings}: {exc}")

    if settings_data is None:
        click.echo("Settings not found; proceeding with defaults.")
    else:
        click.echo(f"Settings loaded ({len(settings_data)} top-level keys)")

    dry_run = not apply_changes
    resolved_outbox = Path(outbox_path).expanduser() if outbox_path is not None else None
    if resolved_outbox is None:
        env_outbox = os.getenv("INDEX_OUTBOX_PATH", "").strip()
        resolved_outbox = Path(env_outbox).expanduser() if env_outbox else None

    if resolved_outbox is None and not dry_run:
        raise click.ClickException("Outbox path is required when applying changes; set INDEX_OUTBOX_PATH or pass --outbox-path.")

    click.echo(f"Outbox path: {resolved_outbox if resolved_outbox is not None else '- (not set; dry-run)'}")

    try:
        summary, messages = run_watcher_tick(
            vault_root=resolved_vault,
            snapshot_path=None,
            skip_panel=False,
            emit_only=False,
            dry_run=dry_run,
            max_notes=max_notes,
            force=False,
            outbox_path=resolved_outbox,
        )
    except WatcherOutboxPathError as exc:
        raise click.ClickException(str(exc))

    for msg in messages:
        click.echo(msg)

    click.echo(
        "Watcher summary: "
        f"changed={summary['changed']} ingest_attempted={summary['ingest_attempted']} ingested={summary['ingested']} "
        f"panel_candidates={summary['panel_candidates']} panel_runs={summary['panel_runs']} errors={summary['errors']} "
        f"dry_run={summary['dry_run']} limit_exceeded={summary['limit_exceeded']}"
    )

    if summary.get("limit_exceeded"):
        raise SystemExit(1)
    if summary.get("errors", 0) > 0:
        raise SystemExit(1)


cli.add_command(panel_cli, name="panel")
cli.add_command(watcher_group, name="watcher")
cli.add_command(vault_watcher_run)
cli.add_command(vault_watcher_daemon)

@cli.command(name="embed-probe", help="Sanity-check embeddings provider model + dimension.")
@click.option("--profile", default="default", show_default=True, help="Embedding profile (default or deterministic/test)")
@click.option("--model", "override_model", default=None, help="Override embedding model via env")
def embed_probe_cli(profile: str, override_model: str | None) -> None:
    from app.cli.embed_probe import embed_probe as _embed_probe
    args = [f"--profile={profile}"]
    if override_model:
        args.append(f"--model={override_model}")
    _embed_probe.main(args=args, prog_name="embed-probe")

if __name__ == "__main__":
    cli()
