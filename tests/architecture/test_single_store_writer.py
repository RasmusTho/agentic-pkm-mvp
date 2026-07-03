"""Single store generation guards (KERNEL-03, issue #2765).

Audit invariants (docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md):

- **I-S1** — one writer per durable store table: only the ``app.stores``
  protocol implementations may issue INSERT/UPDATE against the store tables.
- **CW-1** — the legacy ``app.store.object_store`` / ``app.store.vector_store``
  write generation is removed; no production code may import it.

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/SINGLE_STORE_GENERATION.md
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "app"

# Legacy store-writer modules removed by KERNEL-03. Importing them (they no
# longer exist) or re-adding them is a regression to the two-generation world.
LEGACY_MODULES = (
    "app.store.object_store",
    "app.store.vector_store",
)
LEGACY_FILES = (
    "app/store/object_store.py",
    "app/store/vector_store.py",
)

# Durable store tables and the only modules allowed to write (INSERT/UPDATE)
# them. Allowlist is the app.stores protocol implementations — nothing else.
# ``embeddings`` is the superseded legacy vector table: zero writers allowed
# (table removal itself belongs to KERNEL-04).
STORE_TABLE_WRITERS: dict[str, frozenset[str]] = {
    "store_objects": frozenset({"app/stores/pg.py", "app/stores/postgres.py"}),
    "store_vector_index": frozenset({"app/stores/pg.py"}),
    "store_relations": frozenset({"app/stores/pg.py"}),
    "store_relation_memberships": frozenset({"app/stores/pg.py"}),
    "vector_index_meta": frozenset({"app/stores/pg.py"}),
    "embeddings": frozenset(),
}

_WRITE_SQL_RE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE)\s+(?:ONLY\s+)?\"?(?P<table>[A-Za-z_][A-Za-z0-9_]*)\"?",
    re.IGNORECASE,
)


def _all_app_py_files() -> list[Path]:
    return sorted(APP_ROOT.rglob("*.py"))


def _imports_legacy_store_module(path: Path) -> list[str]:
    """Return the legacy store modules imported by ``path`` (absolute imports)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []

    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in LEGACY_MODULES:
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            if module in LEGACY_MODULES:
                hits.append(module)
            elif module == "app.store":
                for alias in node.names:
                    candidate = f"app.store.{alias.name}"
                    if candidate in LEGACY_MODULES:
                        hits.append(candidate)
    return hits


def test_no_legacy_store_imports() -> None:
    """No production code imports the removed legacy store writer modules.

    Verify target for issue #2765 AC1. The legacy modules themselves must not
    exist, and no app/**/*.py file may import them (which would crash at
    import time — but the guard keeps the failure at review time instead).
    """
    still_present = [rel for rel in LEGACY_FILES if (REPO_ROOT / rel).exists()]
    assert not still_present, (
        "Legacy store writer modules must stay deleted (KERNEL-03):\n"
        + "\n".join(f"  {rel}" for rel in still_present)
    )

    violations: list[str] = []
    for py_file in _all_app_py_files():
        hits = _imports_legacy_store_module(py_file)
        if hits:
            rel = str(py_file.relative_to(REPO_ROOT))
            violations.append(f"{rel}: imports {', '.join(sorted(set(hits)))}")

    assert not violations, (
        "Production code must not import the removed legacy store modules.\n"
        "Use app.objects (DomainObject/ObjectStore) or the app.stores providers\n"
        "(get_object_store()/get_vector_index()) instead.\n" + "\n".join(f"  {v}" for v in sorted(violations))
    )


def test_one_writer_per_table() -> None:
    """Exactly one write generation per durable store table (I-S1).

    Verify target for issue #2765 AC2. Enumerates every app module issuing
    INSERT/UPDATE SQL against a store table and asserts the writer set equals
    the allowlist (app.stores protocol implementations only).
    """
    found: dict[str, set[str]] = {table: set() for table in STORE_TABLE_WRITERS}

    for py_file in _all_app_py_files():
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(py_file.relative_to(REPO_ROOT))
        for match in _WRITE_SQL_RE.finditer(source):
            table = match.group("table").lower()
            if table in found:
                found[table].add(rel)

    unexpected: list[str] = []
    stale: list[str] = []
    for table, allowed in STORE_TABLE_WRITERS.items():
        extra = found[table] - allowed
        missing = allowed - found[table]
        if extra:
            unexpected.append(f"{table}: unexpected writer(s) {sorted(extra)}")
        if missing:
            stale.append(f"{table}: allowlisted writer(s) no longer write it {sorted(missing)}")

    assert not unexpected, (
        "Store tables must be written only through the app.stores protocols (I-S1).\n"
        + "\n".join(f"  {v}" for v in unexpected)
    )
    assert not stale, (
        "Writer allowlist is stale — update STORE_TABLE_WRITERS to keep the guard honest.\n"
        + "\n".join(f"  {v}" for v in stale)
    )
