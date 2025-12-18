from __future__ import annotations

import math
import os
from typing import Iterable

import click

from app.components.embeddings import get_embedding_client

_DEFAULT_TEXTS = [
    "Hello world",
    "Det här är ett svenskt exempel",
    "Agentic PKM system",
]


def _vector_norm(vector: Iterable[float]) -> float:
    return math.sqrt(sum(float(v) * float(v) for v in vector))


def _probe(texts: Iterable[str], profile: str, override_model: str | None) -> None:
    client = get_embedding_client(profile=profile, override_model=override_model)
    dims: set[int] = set()
    identity = client.identity
    for text in texts:
        vector = client.embed_text(text)
        dims.add(len(vector))
        norm = _vector_norm(vector)
        suffix = f" norm={norm:.4f}" if identity.normalize else ""
        click.echo(
            f"Sample '{text}': provider={identity.provider} model={identity.model} dim={identity.dim} normalize={identity.normalize}{suffix}"
        )
        if identity.normalize and abs(norm - 1.0) > 1e-3:
            click.echo("  warning: normalized vector deviates from unit length", err=True)
    if len(dims) != 1:
        click.echo(f"Dimension mismatch detected: {sorted(dims)}", err=True)
        raise SystemExit(1)
    click.echo(
        f"Provider profile={profile} provider={identity.provider} model={identity.model} dim={identity.dim} normalize={identity.normalize}"
    )


@click.command(help="Probe the embedding provider for model, dimension, and normalization sanity checks.")
@click.option("--profile", default="default", show_default=True, help="Embedding profile (default, deterministic, etc.)")
@click.option("--model", "override_model", default=None, help="Override embedding model for this probe run")
def embed_probe(profile: str, override_model: str | None) -> None:
    os.environ.setdefault("LLM_PROVIDER", "mock")
    _probe(_DEFAULT_TEXTS, profile, override_model)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    embed_probe()

