"""Shared helpers for the Yggdrasil invariant test skeletons.

These tests are architecture *fitness* probes, not runtime tests. Static probes load the JSON
schemas under ``schemas/`` and assert structural facts that are true today. Runtime probes call a
future-runtime entry point that does not exist yet, so they ``xfail`` until the first vertical slice
lands.

Invariant registry: docs/testing/invariant-tests.md (#2550). Skeletons: #2552.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "schemas"
DOCS_DIR = REPO_ROOT / "docs"
INVARIANT_REGISTRY = DOCS_DIR / "testing" / "invariant-tests.md"

# Placeholder namespace for the not-yet-implemented runtime vertical slice
# (Capture -> MetadataBundle -> DRI segment -> retrieval prefilter -> RCA result -> ContextEnvelope).
# Importing any of these raises ModuleNotFoundError today, which is what makes the runtime
# skeletons honestly ``xfail`` (strict) instead of faking a pass.
FUTURE_RUNTIME_PACKAGE = "yggdrasil_runtime"


def load_schema(name: str) -> dict[str, Any]:
    """Load and parse a JSON schema from ``schemas/`` (asserts it is valid JSON)."""
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def schema_text(name: str) -> str:
    return (SCHEMAS_DIR / name).read_text(encoding="utf-8")


def load_defs() -> dict[str, Any]:
    return load_schema("_defs.schema.json")


def value_family(name: str) -> list[str]:
    """Return the canonical enum for a shared value family in ``_defs.schema.json``."""
    return load_defs()["$defs"][name]["enum"]


def read_doc(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def require_future_runtime(module_suffix: str, reason: str, attr: str | None = None) -> Any:
    """Import a future-runtime entry point, or ``xfail`` *only* on its absence.

    This is deliberately narrower than wrapping a whole test in ``@pytest.mark.xfail``: it converts
    **only** the missing-runtime ``ModuleNotFoundError`` into an xfail. Once the runtime module
    exists, the import succeeds and the test's real assertions run normally — so a *wrong* first
    implementation fails the test instead of being masked as an expected failure. ``reason`` must
    name the missing runtime and the invariant the skeleton protects.
    """
    try:
        module = importlib.import_module(f"{FUTURE_RUNTIME_PACKAGE}.{module_suffix}")
    except ModuleNotFoundError:
        pytest.xfail(reason)
    return getattr(module, attr) if attr else module
