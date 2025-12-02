
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
from app.cli.alpha_human_flows import run_alpha_human_flows
from app.ingest.vault_root import ingest_vault_root
from app.ingest.vault_alpha import run_vault_alpha_ingest
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
from app.llm.trace_inspect import (
    build_sequence_for_trace,
    group_by_trace_id,
    LLMSequence,
    list_agents_in_sequence,
    load_trace,
)
from app.settings.runtime import get_settings_bundle

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


def _truncate_preview(text: str, limit: int) -> str:
    text = text or ""
    text = text.replace("\n", "\\n")
    return text[:limit] + ("..." if len(text) > limit else "")


def _response_text(rec) -> str:
    for candidate in (rec.response_preview, getattr(rec, "response_text_preview", ""), getattr(rec, "raw_response_preview", "")):
        if candidate and candidate.strip() not in {"", "{}"}:
            return candidate
    return rec.response_preview or getattr(rec, "raw_response_preview", "") or ""


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


@cli.command(name="llm-trace-sequence", help="Render a single trace flow as text or Mermaid sequence diagram.")
@click.option("--trace-id", "trace_id", default="", help="Trace ID to visualize.")
@click.option("--latest", is_flag=True, default=False, help="Use the most recent trace_id when none is provided.")
@click.option(
    "--format",
    "-f",
    type=click.Choice(["text", "mermaid"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option("--out-file", type=click.Path(path_type=Path), default=None, help="Optional output file path.")
def llm_trace_sequence(trace_id: str, latest: bool, format: str, out_file: Path | None) -> None:
    seq = None
    if latest:
        seq = LLMSequence.latest()
        if seq is None:
            raise click.BadParameter("No traces available")
    elif trace_id:
        seq = build_sequence_for_trace(trace_id)
    if seq is None:
        raise click.BadParameter("Trace ID not found")

    output = _render_mermaid_sequence(seq) if format.lower() == "mermaid" else _render_text_sequence(seq)
    if out_file:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(output, encoding="utf-8")
    else:
        click.echo(output)


@cli.command(help="Ask a question via hybrid retrieval (API parity)")
@click.argument("question")
@click.option("--as-json", is_flag=True, help="Print JSON response instead of text")
def ask(question: str, as_json: bool) -> None:
    question = question.strip()
    if not question:
        raise click.BadParameter("Question cannot be empty")
    event = new_event(
        event_type=ASK_QUERY_RECEIVED,
        payload={"question": question},
        trace_id=with_trace_id(None),
    )
    append_jsonl(event.model_dump())
    from app.search.service import ask_question

    answer = ask_question(question)
    if as_json:
        _dump(answer, as_json=True)
    else:
        click.echo(answer.get("answer") or "")
        if answer.get("sources"):
            click.echo("Sources:")
            for src in answer["sources"]:
                click.echo(f"- {src['title']} ({src.get('path') or src.get('source_ref') or src.get('id')})")


@cli.command(name="watch-notes", help="Watch a folder for markdown changes and run note-update on changes.")
@click.option("--root", "root_dir", type=click.Path(path_type=Path), default=None, help="Vault root to watch.")
@click.option("--glob", "glob_pattern", default="*.md", show_default=True, help="Glob pattern for files to watch.")
@click.option("--debounce-ms", default=500, show_default=True, help="Debounce time in milliseconds.")
@click.option("--snapshot-dir", type=click.Path(path_type=Path), default=Path("tmp/note_update_snapshots"))
@click.option("--outbox-path", type=click.Path(path_type=Path), default=None, help="Optional outbox path to write events.")
@click.option(
    "--dry-run", is_flag=True, help="Print actions without writing files or dispatching events.")
def watch_notes(root_dir: Path | None, glob_pattern: str, debounce_ms: int, snapshot_dir: Path, outbox_path: Path | None, dry_run: bool) -> None:
    resolved = _resolve_vault_root_path(root_dir, allow_env=True, fallback_to_default=True)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    if not resolved.exists() or not resolved.is_dir():
        raise click.BadParameter(f"Vault root not found or not a directory: {resolved}")

    watcher = NoteWatcherService(
        root_dir=resolved,
        glob_pattern=glob_pattern,
        debounce_ms=debounce_ms,
        snapshot_dir=snapshot_dir,
        outbox_path=outbox_path,
        dry_run=dry_run,
    )

    click.echo(f"Watching {resolved} for changes (pattern={glob_pattern}, debounce={debounce_ms}ms, dry_run={dry_run})")

    for changes in watch(resolved, debounce=debounce_ms / 1000.0):
        events = watcher.handle_changes(changes)
        if events:
            click.echo(f"Dispatched {len(events)} events from {len(changes)} change batches.")


@cli.command(name="note-update", help="Process one or more markdown files with panel handling and optional event dispatch.")
@click.argument("paths", nargs=-1, type=click.Path(path_type=Path))
@click.option("--glob", "glob_pattern", default="*.md", show_default=True, help="Glob pattern when a directory path is provided.")
@click.option("--snapshot-dir", type=click.Path(path_type=Path), default=Path("tmp/note_update_snapshots"))
@click.option("--outbox-path", type=click.Path(path_type=Path), default=None, help="Optional outbox path to write events.")
@click.option(
    "--expect-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional expected path to guard against rename/move races.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print actions without writing files or dispatching events.",
)
@click.option(
    "--dispatch-events",
    is_flag=True,
    help="Dispatch panel events to the Orchestrator if PANEL_EVENTS_ENABLE and EVENT_ORCHESTRATOR_ENABLE are set.",
)
def note_update(paths: tuple[Path, ...], glob_pattern: str, snapshot_dir: Path, outbox_path: Path | None, expect_path: Path | None, dry_run: bool, dispatch_events: bool) -> None:
    if not paths:
        raise click.BadParameter("At least one path is required")

    resolved_paths: list[Path] = []
    for raw in paths:
        path = raw.expanduser()
        if path.is_dir():
            resolved_paths.extend(path.rglob(glob_pattern))
        else:
            resolved_paths.append(path)

    settings = None
    try:
        settings = get_settings_bundle()
    except Exception:
        settings = None

    results: list[NoteUpdateResult] = []
    for path in resolved_paths:
        result = process_note_update(
            path,
            snapshot_dir=snapshot_dir,
            outbox_path=outbox_path,
            expect_path=expect_path,
            dry_run=dry_run,
            dispatch_events=dispatch_events,
            settings=settings,
        )
        results.append(result)
        click.echo(f"Processed {path} -> changed={result.changed} dispatched={result.dispatched_events}")

    changed = sum(1 for r in results if r.changed)
    dispatched = sum(r.dispatched_events for r in results)
    click.echo(f"Summary: processed={len(results)}, changed={changed}, dispatched_events={dispatched}")


@cli.command(name="panel-update", help="Process a single markdown file for AI panel updates and optional event dispatch.")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--old-path", type=click.Path(path_type=Path), default=None, help="Optional path to previous version for diffing panels.")
@click.option(
    "--dispatch-events",
    is_flag=True,
    help="Dispatch panel events to the Orchestrator if PANEL_EVENTS_ENABLE and EVENT_ORCHESTRATOR_ENABLE are set.",
)
@click.option("--outbox-path", type=click.Path(path_type=Path), default=None, help="Optional outbox path to write events.")
@click.option("--dry-run", is_flag=True, help="Print actions without writing back the note.")
def panel_update(path: Path, old_path: Path | None, dispatch_events: bool, outbox_path: Path | None, dry_run: bool) -> None:
    if not path.exists():
        raise click.BadParameter(f"File not found: {path}")
    settings = None
    try:
        settings = get_settings_bundle()
    except Exception:
        settings = None

    if old_path is not None and old_path.exists():
        old_text = old_path.read_text(encoding="utf-8")
    else:
        old_text = None

    result = handle_panel_update(
        path=path,
        old_text=old_text,
        dispatch_events=dispatch_events,
        outbox_path=outbox_path,
        dry_run=dry_run,
        settings=settings,
    )

    if result.updated_text and not dry_run:
        path.write_text(result.updated_text, encoding="utf-8")
        click.echo(f"Updated {path}")

    click.echo(f"Events created: {len(result.events)} dispatched: {result.dispatched_events}")


@cli.command(
    name="ingest",
    help="Normalize and chunk a file or directory of files (non-recursive) into the default ObjectStore with outbox entries.",
)
@click.option("--input", "input_path", type=click.Path(path_type=Path), required=True, help="Path to file or directory to ingest.")
@click.option("--limit", type=int, default=None, help="Optional limit on number of files to ingest when a directory is provided.")
@click.option("--kind", type=str, default="note", show_default=True, help="Override kind for ingested objects.")
@click.option("--as-json", is_flag=True, help="Output results as JSON")
@click.option("--emit-outbox", is_flag=True, help="Emit outbox events for ingested items")
@click.option(
    "--trace-id",
    type=str,
    default=None,
    help="Optional trace_id to attach to all events; generated if absent.",
)
def ingest(input_path: Path, limit: int | None, kind: str, as_json: bool, emit_outbox: bool, trace_id: str | None) -> None:
    resolved = Path(input_path).expanduser()
    if not resolved.exists():
        raise click.BadParameter(f"Input path not found: {resolved}")

    if resolved.is_dir():
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
def vault_alpha_ingest(vault_root: Path | None, max_notes: int, include_test_note: bool, force: bool) -> None:
    resolved = _resolve_vault_root_path(vault_root, allow_env=True, fallback_to_default=True)
    if resolved is None:
        raise click.BadParameter("Vault root could not be resolved.")
    summary = run_vault_alpha_ingest(
        resolved,
        max_notes=max_notes,
        include_test_note=include_test_note,
        force=force,
    )
    if summary.ingested == 0 and not summary.force:
        click.echo(
            f"Scanned {summary.scanned} files; ingested {summary.ingested} notes (already up to date; run with --force to resync if the store is empty)"
        )
    else:
        suffix = f" (force={summary.force})" if summary.force else ""
        click.echo(f"Scanned {summary.scanned} files; ingested {summary.ingested} notes{suffix}")
    click.echo(f"Included folders: {', '.join(summary.included_folders) if summary.included_folders else '-'}")


@cli.command(
    name="alpha-human-flows",
    help=(
        "Run alpha human flows end-to-end (sample ingest, test note, panel, promotion, ASK) "
        "against a vault root."
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
    help="Truncate the index outbox file before running (no effect in dry-run or explain-only).",
)
def alpha_human_flows(
    vault_root: Path | None, dry_run: bool, sample_size: int, explain_only: bool, reset_outbox: bool
) -> None:
    """
    Flows: A) ingest sample notes; B) ensure Test/Alpha-HumanFlows.md exists;
    C) ingest + report mirror path; D) insert AI panel and reingest;
    E) set promoted/evergreen frontmatter and reingest; F) run ASK queries.
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
    root = _resolve_yggdrasil_root(root_dir)
    scaffolder = YggdrasilScaffolder(root)
    scaffolder.scaffold()
    click.echo(f"Yggdrasil root initialized at {root}")


@cli.command(help="Compile runtime settings from vault markdown into runtime/settings/**/*.yaml")
def settings_compile() -> None:
    bundle = compile_all()
    click.echo(json.dumps(bundle.model_dump(mode="json"), indent=2, ensure_ascii=False))


@cli.command(help="Normalize a note then classify it with the classifier agent")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--trace-id", default=None, help="Optional trace_id")
def classify(path: Path, trace_id: str | None) -> None:
    res = normalize_run(str(path), trace_id=trace_id)
    res = classify_run(res["object_id"], trace_id=trace_id)
    click.echo(json.dumps(res, indent=2))


@cli.command(help="Normalize + classify a note, then append an AI panel suggestion")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--trace-id", default=None, help="Optional trace_id")
def classify_panel(path: Path, trace_id: str | None) -> None:
    res = normalize_run(str(path), trace_id=trace_id)
    res = classify_run(res["object_id"], trace_id=trace_id)
    suggest_panel(path, res)


@cli.command(help="Parse AI panels and print what the panel agent would do")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--old-path", type=click.Path(path_type=Path), default=None, help="Optional previous revision for diffing panels")
@click.option("--markdown", "md_out", is_flag=True, help="Print markdown log output")
@click.option("--json", "json_out", is_flag=True, help="Print JSON output")
def panel_parse(path: Path, old_path: Path | None, md_out: bool, json_out: bool) -> None:
    from app.agents.panel.agent import parse_panel

    old_text = None
    if old_path is not None and old_path.exists():
        old_text = old_path.read_text(encoding="utf-8")
    new_text = path.read_text(encoding="utf-8")
    res = parse_panel(new_text, old_text=old_text)
    if md_out:
        click.echo(res.markdown_log or "<no markdown log>")
    if json_out or not md_out:
        click.echo(json.dumps(res.model_dump(mode="json"), indent=2, ensure_ascii=False))


@cli.command(help="Run a quick health check against the API")
@click.option("--url", default="http://127.0.0.1:18000/agent/health", show_default=True)
def health(url: str) -> None:
    run_health(url)


@cli.command(help="Transcribe an audio file or URL; saves to tmp/normalize by default.")
@click.option("--source", required=True, help="Path or URL to the audio source.")
@click.option("--trace-id", default=None, help="Optional trace_id")
def transcribe(source: str, trace_id: str | None) -> None:
    resolved = str(_materialize_source(source))
    if _should_transcribe(resolved):
        res = transcribe_source(resolved, trace_id=trace_id)
        click.echo(json.dumps(res, indent=2))
    else:
        raise click.BadParameter(f"Unsupported source format for {source}")


@cli.command(help="Render a trace file as a Mermaid sequence diagram")
@click.option("--trace-file", type=click.Path(path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path), required=True)
def trace_mermaid(trace_file: Path, out: Path) -> None:
    seqs = load_trace(trace_file)
    if not seqs:
        raise click.BadParameter("Trace file is empty or invalid")
    grouped = group_by_trace_id(seqs)
    for trace_id, seq in grouped.items():
        mermaid = _render_mermaid_sequence(seq)
        dest = out if out.suffix else out / f"{trace_id}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(mermaid, encoding="utf-8")
        click.echo(f"Wrote {dest}")


@cli.command(help="Run orchestrator for an event (feature-gated)")
@click.option("--event-type", required=True)
@click.option("--payload", default="{}", help="JSON payload for the event")
@click.option("--trace-id", default=None)
@click.option("--enable", is_flag=True, help="Set EVENT_ORCHESTRATOR_ENABLE=1 and PANEL_EVENTS_ENABLE=1")
def orchestrate(event_type: str, payload: str, trace_id: str | None, enable: bool) -> None:
    if enable:
        os.environ["EVENT_ORCHESTRATOR_ENABLE"] = "1"
        os.environ.setdefault("PANEL_EVENTS_ENABLE", "1")
    ctx = OrchestratorContext(settings={"event_orchestrator_enable": True})
    event = new_event(event_type=event_type, payload=json.loads(payload), trace_id=trace_id)
    plan = handle_event(event, ctx)
    click.echo(json.dumps(plan.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    cli()
