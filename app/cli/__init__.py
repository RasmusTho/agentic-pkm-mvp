import json
from typing import Optional

import click

from app.agents.normalizer.agent import run as normalize_run
from app.agents.classifier.agent import run as classify_run


@click.group(help="Agentic PKM CLI")
def cli() -> None: ...


@cli.command(
    help=(
        "Normalize file or URL and emit core object.\n\nExamples:\n"
        "  python -m app.cli normalize file.md --json\n"
        "  python -m app.cli normalize https://example.com --trace-id T123"
    )
)
@click.argument("path", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Print JSON result to stdout.")
@click.option("--trace-id", default=None, help="Attach a trace id to the run.")
def normalize(path: str, as_json: bool, trace_id: Optional[str]) -> None:
    res = normalize_run(path, trace_id=trace_id)
    print(json.dumps(res) if as_json else json.dumps(res, indent=2))


@cli.command(
    help=(
        "Classify an existing object_id using the configured agent run.\n\nExample:\n"
        "  python -m app.cli classify 00000000-0000-0000-0000-000000000000 --json"
    )
)
@click.argument("object_id")
@click.option("--json", "as_json", is_flag=True, help="Print JSON result to stdout.")
@click.option("--trace-id", default=None, help="Attach a trace id to the run.")
def classify(object_id: str, as_json: bool, trace_id: Optional[str]) -> None:
    res = classify_run(object_id, trace_id=trace_id)
    print(json.dumps(res) if as_json else json.dumps(res, indent=2))


@cli.command(
    help=(
        "Run full pipeline (normalize -> classify) for a file path.\n\nExample:\n"
        "  python -m app.cli pipe notes/foo.md --trace-id PIPE123 --json"
    )
)
@click.argument("path", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Print JSON result to stdout.")
@click.option("--trace-id", default=None, help="Attach a trace id to the run.")
def pipe(path: str, as_json: bool, trace_id: Optional[str]) -> None:
    n = normalize_run(path, trace_id=trace_id)
    c = classify_run(n["object_id"], trace_id=trace_id)
    out = {"normalize": n, "classify": c}
    print(json.dumps(out) if as_json else json.dumps(out, indent=2))


if __name__ == "__main__":
    cli()
