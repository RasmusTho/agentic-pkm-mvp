from __future__ import annotations

import os
from typing import Iterable

import click

from app.components.embeddings import describe_embedding

_DEFAULT_TEXTS = [
    "Hello world",
    "Det här är ett svenskt exempel",
    "Agentic PKM system",
]


def _probe(texts: Iterable[str], profile: str) -> tuple[str, int]:
    dims: set[int] = set()
    model_name = ""
    for text in texts:
        model, dim, _ = describe_embedding(text, profile=profile)
        model_name = model
        dims.add(dim)
        click.echo(f"Sample '{text}': model={model} dim={dim}")
    if len(dims) != 1:
        click.echo(f"Dimension mismatch detected: {sorted(dims)}", err=True)
        raise SystemExit(1)
    return model_name, dims.pop()


@click.command(help="Probe the embedding provider for model + dimension sanity checks.")
@click.option("--profile", default="default", show_default=True, help="Embedding profile (default or deterministic/test)")
@click.option("--model", "override_model", default=None, help="Override embedding model via env override")
def embed_probe(profile: str, override_model: str | None) -> None:
    # Default to the mock provider when no provider is set so the command works offline
    os.environ.setdefault("LLM_PROVIDER", "mock")

    if override_model:
        os.environ["EMBED_MODEL"] = override_model

    model, dim = _probe(_DEFAULT_TEXTS, profile)
    click.echo(f"Provider profile={profile} model={model} dim={dim}")


if __name__ == "__main__":  # pragma: no cover - CLI entry
    embed_probe()
