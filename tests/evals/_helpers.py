"""Shared helpers for the Yggdrasil anti-contamination eval skeletons.

Loads the synthetic fixture corpus under ``tests/evals/fixtures/`` (#2551) and parses each
document's YAML frontmatter metadata block with a tiny stdlib parser (the metadata is flat
``key: value`` lines, so no YAML dependency is needed).

Invariant registry: docs/testing/invariant-tests.md (#2550). Skeletons: #2552.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SCHEMAS_DIR = REPO_ROOT / "schemas"

GROUPS: tuple[str, ...] = (
    "work_project_alpha",
    "work_project_beta",
    "private_programming",
    "rpg_worldbuilding",
    "general_programming",
)

# Vocabulary the corpus deliberately reuses across every group so that textual similarity alone
# cannot separate the scopes (see tests/evals/fixtures/README.md and issue #2551).
SHARED_VOCAB: tuple[str, ...] = (
    "system",
    "agent",
    "simulation",
    "rule",
    "state",
    "class",
    "event",
    "workflow",
    "authority",
    "memory",
    "capability",
    "context",
    "scope",
    "transition",
    "policy",
)

REQUIRED_META_KEYS: tuple[str, ...] = (
    "scope_id",
    "sphere",
    "source_role",
    "authority_state",
    "evidence_role",
    "sensitivity",
)

FUTURE_RUNTIME_PACKAGE = "yggdrasil_runtime"


@dataclass(frozen=True)
class FixtureDoc:
    path: Path
    group: str
    meta: dict[str, str]
    body: str

    @property
    def text(self) -> str:
        return self.body


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse a leading ``---`` YAML-ish frontmatter block of flat ``key: value`` lines."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    # lines[0] == '---'; find the closing fence.
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    body = "\n".join(lines[end + 1 :])
    return meta, body


def load_group(group: str) -> list[FixtureDoc]:
    docs: list[FixtureDoc] = []
    group_dir = FIXTURES_DIR / group
    for path in sorted(group_dir.glob("*.md")):
        if path.name.upper() == "README.MD":
            continue
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        docs.append(FixtureDoc(path=path, group=group, meta=meta, body=body))
    return docs


def load_corpus() -> list[FixtureDoc]:
    docs: list[FixtureDoc] = []
    for group in GROUPS:
        docs.extend(load_group(group))
    return docs


def value_family(name: str) -> list[str]:
    defs = json.loads((SCHEMAS_DIR / "_defs.schema.json").read_text(encoding="utf-8"))
    return defs["$defs"][name]["enum"]


def require_future_runtime(module_suffix: str, reason: str, attr: str | None = None) -> Any:
    """Import a future-runtime entry point, or ``xfail`` *only* when that exact module is absent.

    Narrower than a whole-test ``@pytest.mark.xfail``: an ``ModuleNotFoundError`` becomes an xfail
    **only when the missing module is the requested target itself (or an ancestor package)**. If the
    target exists but raises ``ModuleNotFoundError`` from one of its own imports (a broken
    implementation or missing dependency), it is re-raised so the test fails for real. ``reason``
    names the missing runtime and the invariant the skeleton protects.
    """
    target = f"{FUTURE_RUNTIME_PACKAGE}.{module_suffix}"
    try:
        module = importlib.import_module(target)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing and (missing == target or target.startswith(f"{missing}.")):
            pytest.xfail(reason)
        raise
    return getattr(module, attr) if attr else module
