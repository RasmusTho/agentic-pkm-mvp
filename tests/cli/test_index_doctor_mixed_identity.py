"""ADR-0059 step 3 (#3406) — index doctor surfaces the mixed-identity row count.

``diagnose_index`` computes ``mixed_identity_count``: the number of
``store_vector_index`` rows whose recorded ``(provider, model)`` diverges from
the active primary embedding identity — the same comparison
``rebuild_from_durable_index()`` makes. The doctor CLI report carries it in
JSON mode and prints a content-free reconcile-signal line in text mode.

Runs under ``not pg`` (issue #3406 asks for memory-backend tests where
possible): the Pg inspection seams (`inspect_pg_identity_tuples` and friends)
are patched with canned identity-tuple rows — the exact shape
``inspect_pg_identity_tuples()`` returns from a live corpus with CTI-2
fallback rows — while the count computation and the CLI report surface under
test run for real. The live-Postgres end of the same surface is covered by
``tests/cli/test_index_doctor_mixed.py`` (pg-marked).
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.components.llm.fabric import LLMTaskIntent, get_embeddings_client
from app.index import doctor as doctor_mod
from app.retrieval import hybrid
from app.stores import reset_store_backends
from app.stores.memory import MemoryVectorIndex

_MIXED_ROW_COUNT = 2


@pytest.fixture()
def mixed_identity_doctor_env(monkeypatch: pytest.MonkeyPatch):
    """Route diagnose_index's pg-only inspection seams to canned values.

    The memory backend supplies the vector index; the lazy Postgres diagnostic
    adapter is replaced with a complete in-process tuple so the pg diagnosis
    branch (where the mixed-identity computation lives) executes without a live
    database.
    """
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    hybrid.get_store().set_documents([])
    doctor_mod.reset_diagnose_cache()

    primary = get_embeddings_client(
        LLMTaskIntent(task_kind="embed", determinism_required=False)
    ).identity

    identity_tuples = [
        {
            "provider": primary.provider,
            "model": primary.model,
            "dim": primary.dim,
            "normalize": primary.normalize,
            "count": 3,
        },
        {
            "provider": "gemini",
            "model": "gemini-embedding-001",
            "dim": primary.dim,
            "normalize": True,
            "count": _MIXED_ROW_COUNT,
        },
    ]

    def inspect_pg_index_state() -> dict[str, object]:
        return {
            "rows": 5,
            "identity_present": True,
            "dims": [primary.dim],
            "rows_wrong_dim": 0,
        }
    monkeypatch.setattr(
        doctor_mod, "inspect_unembedded_pg_objects", lambda **_kwargs: (0, [])
    )
    monkeypatch.setattr(
        doctor_mod,
        "_load_pg_diagnostics",
        lambda: (
            MemoryVectorIndex,
            lambda **_kwargs: {"stale_count": 0},
            lambda: identity_tuples,
            inspect_pg_index_state,
            lambda **_kwargs: {"missing_count": 0},
        ),
    )
    yield
    reset_store_backends()
    doctor_mod.reset_diagnose_cache()


def test_doctor_reports_mixed_identity_count(mixed_identity_doctor_env) -> None:
    """AC2: the doctor report carries the mixed-identity row count for a corpus
    containing fallback-identity rows — in JSON and in the human report."""
    runner = CliRunner()

    json_result = runner.invoke(cli, ["index", "doctor", "--json"])
    assert json_result.exit_code == 0, json_result.output
    payload = json.loads(json_result.output)
    assert payload["mixed_identity_count"] == _MIXED_ROW_COUNT
    # The full-tuple mixed-identity listing (EMBEDREL-06) stays intact alongside it.
    assert payload["mixed_identities"]

    doctor_mod.reset_diagnose_cache()
    text_result = runner.invoke(cli, ["index", "doctor"])
    assert text_result.exit_code == 0, text_result.output
    assert f"Mixed-identity rows (reconcile signal, ADR-0059): {_MIXED_ROW_COUNT}" in text_result.output
