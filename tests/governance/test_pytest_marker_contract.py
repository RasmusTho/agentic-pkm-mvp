"""Governance regression test for the ``pg`` pytest marker contract on the
PostgreSQL store-contract suite (issue #3879).

``tests/stores/test_store_contract_pg.py`` parametrizes several store-contract
tests over a memory backend and a real PostgreSQL backend, plus three
standalone PostgreSQL-only regression tests. The required validation gate is
``pytest -q -m "not pg"``: every PostgreSQL-backed case must be *deselected*
by that marker expression regardless of whether a PostgreSQL socket happens
to be reachable on the host running the suite.

Regression context: while validating #3162, a locally reachable but
unmigrated PostgreSQL server let unmarked ``backend="pg"`` parameters and
standalone PostgreSQL tests run under the nominal ``not pg`` gate instead of
being deselected, failing with ``StoreSchemaMissingError``. On CI (no
PostgreSQL reachable) the same unmarked cases merely skipped, hiding the
marker gap entirely.

This test proves the deselection contract statically via ``--collect-only``,
so it never touches a database itself: marker-based deselection is decided
entirely at collection time, before any fixture or test body executes, so
the result cannot depend on host DB reachability.
"""

from __future__ import annotations

import subprocess
import sys
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = "tests/stores/test_store_contract_pg.py"


@lru_cache(maxsize=None)
def _collect_node_ids(marker_expr: str | None) -> frozenset[str]:
    """Return the set of test node ids pytest collects for ``TARGET``.

    Uses ``--collect-only -q`` so no test body, fixture, or database
    connection ever executes for the collected file -- this only exercises
    pytest's marker-expression evaluation at collection time, which is
    independent of whether a PostgreSQL socket happens to be reachable.
    """
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    if marker_expr is not None:
        cmd += ["-m", marker_expr]
    cmd.append(TARGET)
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"pytest --collect-only failed (exit {result.returncode}) for "
        f"marker={marker_expr!r}:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return frozenset(
        line.strip() for line in result.stdout.splitlines() if "::" in line
    )


def test_store_contract_postgres_cases_are_marked_pg() -> None:
    """``-m "not pg"`` deselects every PostgreSQL-backed case in the file.

    A case is treated as PostgreSQL-backed when its node id does not carry
    the ``[memory]`` parametrization id -- in this file that is exactly the
    ``backend="pg"`` parametrizations plus the standalone PostgreSQL-only
    regression tests. Every such case must both (a) be absent from the
    ``not pg`` collection and (b) be present in the ``pg`` collection, so a
    case can't silently lose its marker without also disappearing from the
    intentional ``pg`` selection.
    """
    full = _collect_node_ids(None)
    not_pg = _collect_node_ids("not pg")
    pg_only = _collect_node_ids("pg")

    postgres_backed = {node_id for node_id in full if not node_id.endswith("[memory]")}
    assert postgres_backed, "expected at least one PostgreSQL-backed case in the file"

    leaked = postgres_backed & not_pg
    assert not leaked, (
        "PostgreSQL-backed case(s) were collected under -m 'not pg' (missing "
        f"the pg marker): {sorted(leaked)}"
    )

    unmarked = postgres_backed - pg_only
    assert not unmarked, (
        f"PostgreSQL-backed case(s) missing from -m 'pg': {sorted(unmarked)}"
    )

    # Known from the issue context: 5 parametrized backend="pg" cases + 3
    # standalone PostgreSQL-only tests. Pinning the count also guards
    # against silent coverage shrinkage, not just missing markers.
    assert len(postgres_backed) == 8, sorted(postgres_backed)


def test_store_contract_memory_cases_remain_not_pg() -> None:
    """Memory-backed store contract coverage remains in the non-PG suite."""
    full = _collect_node_ids(None)
    not_pg = _collect_node_ids("not pg")

    memory_backed = {node_id for node_id in full if node_id.endswith("[memory]")}
    assert memory_backed, "expected at least one memory-backed case in the file"

    missing = memory_backed - not_pg
    assert not missing, (
        f"memory-backed case(s) missing from -m 'not pg': {sorted(missing)}"
    )

    # Known from the issue context: 5 parametrized store-contract functions
    # cover the memory backend.
    assert len(memory_backed) == 5, sorted(memory_backed)
