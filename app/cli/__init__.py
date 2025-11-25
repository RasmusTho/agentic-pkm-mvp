
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

from app.observability.status_service import get_system_status
from app.ingest.config import DEFAULT_VAULT_ROOT
from app.ingest.vault_root import ingest_vault_root
from app.agents.classifier.agent import run as classify_run
from app.agents.panel.integration import handle_panel_update
from app.services.note_update import NoteUpdateResult, process_note_update
from app.services.note_watcher import NoteWatcherService
from app.events.models import new_event
from app.events.types import ASK_QUERY_RECEIVED
from app.agents.normalizer.agent import run as normalize_run
from app.index.outbox import append_jsonl
from app.orchestrator.handler import OrchestratorContext, handle_event
from app.orchestrator.runtime import Orchestrator
from app.media.transcribe import transcribe_source
from app.obs.log import with_trace_id
from app.cli.health import run_health
from app.settings.compiler import compile_all
from app.llm.trace_inspect import group_by_trace_id, load_trace

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


class _RecordingOrchestrator(Orchestrator):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.last_results: list[dict[str, Any]] | None = None

    def run_plan(self, plan):
        results = super().run_plan(plan)
        self.last_results = results
        return results


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


@cli.command(help="Ask a question through the planner/orchestrator pipeline.")
@click.argument("question")
@click.option("--vault-root", type=click.Path(path_type=Path), default=None, help="Path to vault root for MCP writes.")
@click.option("--enable-mcp-vault", is_flag=True, default=False, help="Enable real MCP vault writes.")
def ask(question: str, vault_root: Path | None, enable_mcp_vault: bool) -> None:
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

    orchestrator = _RecordingOrchestrator(tool_settings=tool_settings)
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
            click.echo(f"[{idx}] agent={rec.agent} kind={rec.kind}")
            click.echo(f"    prompt:   {rec.prompt_preview}")
            click.echo(f"    response: {rec.response_preview}")
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
            click.echo(f"[{idx}] agent={rec.agent} kind={rec.kind}")
            click.echo(f"    prompt:   {rec.prompt_preview}")
            click.echo(f"    response: {rec.response_preview}")
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
        note_path.write_text(result.panel.updated_markdown, encoding="utf-8")

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

@cli.command(
    help="Kör funktionskontroller för lokala beroenden (ffmpeg, yt-dlp, index-outbox, Ollama)."
)
@click.option("--json", "as_json", is_flag=True, help="Print JSON result to stdout.")
@click.option("--trace-id", default=None, help="Attach a trace id to the run.")
def health(as_json: bool, trace_id: Optional[str]) -> None:
    trace_id = with_trace_id(trace_id)
    result = run_health(trace_id=trace_id)
    _dump(result, as_json)
    if not result.get("ok"):
        raise SystemExit(1)


@cli.command(help="Print a system status snapshot (Reality-MVP observability).")
def status() -> None:
    status = get_system_status()
    click.echo(f"SoT version: {status.sot_version}")
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
    click.echo(f"  last_error: {status.ingestion.last_error_message or '-'}")
    click.echo("ASK:")
    avg_latency = (
        f"{status.ask.avg_latency_ms_24h:.0f} ms" if status.ask.avg_latency_ms_24h is not None else "-"
    )
    click.echo(f"  queries (24h): {status.ask.total_queries_24h}")
    click.echo(f"  avg latency: {avg_latency}")


@cli.group(help="Settings commands (Vault-as-GUI).")
def settings() -> None:
    ...


@settings.command("compile", help="Compile vault/@Settings into runtime/settings.")
@click.option("--auto-heal/--no-auto-heal", default=False, help="Rewrite YAML blocks when invalid values are healed.")
def settings_compile(auto_heal: bool) -> None:
    bundle = compile_all(auto_heal=auto_heal)
    click.echo(f"compiled {len(bundle.agents)} agents")


@settings.command("validate", help="Compile and print a short summary.")
@click.option("--auto-heal/--no-auto-heal", default=False, help="Rewrite YAML blocks when invalid values are healed.")
def settings_validate(auto_heal: bool) -> None:
    bundle = compile_all(auto_heal=auto_heal)
    click.echo(
        f"global enable={bundle.global_.enable} providers={len(bundle.providers.llm)} agents={len(bundle.agents)}"
    )


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


if __name__ == "__main__":
    cli()
