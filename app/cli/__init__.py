from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional
import time

import click
import httpx
from watchfiles import watch

from app.agents.classifier.agent import run as classify_run
from app.agents.normalizer.agent import run as normalize_run
from app.index.outbox import append_jsonl
from app.media.transcribe import transcribe_source
from app.obs.log import with_trace_id
from app.cli.health import run_health
from app.settings.compiler import compile_all

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
