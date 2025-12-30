#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -z "${VAULT_ROOT:-}" ]; then
  echo "VAULT_ROOT is required to export runtime env" >&2
  exit 2
fi

mkdir -p tmp
printf "%s\n" "VAULT_ROOT=$VAULT_ROOT" > tmp/runtime.env
if [ -n "${LLM_PROVIDER:-}" ]; then
  printf "%s\n" "LLM_PROVIDER=$LLM_PROVIDER" >> tmp/runtime.env
fi

if [ "${LLM_PROVIDER:-}" = "ollama" ]; then
  python - <<'PY' >> tmp/runtime.env
from __future__ import annotations

import os
from pathlib import Path

try:
    from app.settings.compiler import compile_file, merge
    from app.settings.models import Providers
except Exception:
    compile_file = None
    merge = None
    Providers = None


def _strip_v1(url: str) -> str:
    clean = url.rstrip("/")
    if clean.endswith("/v1"):
        return clean[:-3]
    return clean


def _load_providers(vault_root: Path) -> object | None:
    if compile_file is None or merge is None or Providers is None:
        return None
    path = vault_root / "@Settings" / "providers.md"
    if not path.exists():
        return None
    try:
        sections = compile_file(path)
        payload: dict[str, object] = {}
        for value in sections.values():
            if isinstance(value, dict):
                merge(payload, value)
        return Providers(**payload)
    except Exception:
        return None


vault_root = Path(os.environ.get("VAULT_ROOT", "vault"))
providers = _load_providers(vault_root)
llm_ref = providers.llm.get("default_chat") if providers else None
embed_ref = providers.embedding.get("default") if providers else None

base_url = os.getenv("OLLAMA_BASE_URL") or os.getenv("OPENAI_BASE_URL")
if not base_url:
    base_url = getattr(llm_ref, "base_url", None) if llm_ref else None

model = os.getenv("OLLAMA_MODEL") or os.getenv("LLM_MODEL")
if not model:
    model = getattr(llm_ref, "model", None) if llm_ref else None

embed_model = os.getenv("OLLAMA_EMBED_MODEL") or os.getenv("EMBED_MODEL")
if not embed_model:
    embed_model = getattr(embed_ref, "model", None) if embed_ref else None

default_base = "http://host.docker.internal:11434/v1"
if not base_url:
    base_url = default_base
elif "127.0.0.1" in base_url or "localhost" in base_url:
    base_url = default_base

base_url = base_url.rstrip("/")
ollama_host = _strip_v1(base_url)

if ollama_host:
    print(f"OLLAMA_HOST={ollama_host}")
    print(f"OLLAMA_URL={ollama_host}")
if model:
    print(f"OLLAMA_MODEL={model}")
    print(f"LLM_MODEL={model}")
if embed_model:
    print(f"OLLAMA_EMBED_MODEL={embed_model}")
    print(f"EMBED_MODEL={embed_model}")
PY
fi
