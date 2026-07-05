"""KERNEL-05: retrieval reads the durable index; no volatile-only truth.

Covers docs/RUNTIME_CORRECTNESS_KERNEL/RETRIEVAL_READS_DURABLE_INDEX.md and audit
invariant I-D3 (CW-1): the in-memory hybrid retrieval store must be a cache of
``store_vector_index``, never an independently written truth.

- test_results_survive_restart: kill-and-restart equivalence.
- test_no_fanin_writers: the only production caller of add_document/set_documents
  is the durable-index rebuild path itself (plus explicitly allowlisted test/eval
  harnesses that snapshot-and-restore around a synthetic corpus).
- test_rebuild_wired_at_init: the rebuild is invoked from a production
  process/store init call site, not only from a test.
"""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.retrieval import hybrid
from app.stores import get_vector_index, reset_store_backends

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "app"


@pytest.fixture(autouse=True)
def _isolate_stores(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()
    yield
    reset_store_backends()
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()


def _seed_durable_index() -> list[UUID]:
    identity = EmbeddingIdentity(provider="mock", model="embed-test", dim=8, normalize=False)
    idx = get_vector_index()
    ids: list[UUID] = []
    seeds = [
        ("Alpha note", "alpha retrieval content about mountains"),
        ("Beta note", "beta retrieval content about oceans"),
    ]
    for title, text in seeds:
        oid = uuid4()
        idx.upsert(
            object_id=oid,
            kind="note",
            source_ref=f"unit-test://{title}",
            payload={"title": title, "text": text, "content": text},
            embedding=[0.1] * 8,
            model=identity.model,
            identity=identity,
        )
        ids.append(oid)
    return ids


def test_results_survive_restart() -> None:
    """Kill-and-restart equivalence: rebuilding from the durable index reproduces
    identical retrieval results after the in-process cache is discarded."""
    _seed_durable_index()

    hybrid.rebuild_from_durable_index()
    before = hybrid.hybrid_search("alpha retrieval mountains", k=5)
    assert before, "expected at least one hit from the seeded durable index"

    # Simulate a process restart: discard the in-process cache, keep the
    # durable index untouched, and rebuild.
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()
    hybrid.rebuild_from_durable_index()
    after = hybrid.hybrid_search("alpha retrieval mountains", k=5)

    assert [hit["doc_id"] for hit in after] == [hit["doc_id"] for hit in before]
    assert [hit["id"] for hit in after] == [hit["id"] for hit in before]


def test_rebuild_wired_at_init() -> None:
    """The rebuild is invoked from the production ask-route init call site
    (app/api/routes/ask.py), not only from a test."""
    _seed_durable_index()

    import app.api.routes.ask as ask_module

    ask_module._HYBRID_WARMED = False
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()

    ask_module._ensure_hybrid_store_loaded()

    assert ask_module._HYBRID_WARMED is True
    assert hybrid.get_store().all(), (
        "expected _ensure_hybrid_store_loaded (the production init call site) to "
        "populate the retrieval cache via rebuild_from_durable_index()"
    )

    # Confirm the wiring is source-level, not merely an accidental side effect:
    # the production module must call rebuild_from_durable_index directly.
    source = Path(ask_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)
    assert "rebuild_from_durable_index" in called_names, (
        "app/api/routes/ask.py must call rebuild_from_durable_index() at its "
        "production init call site (KERNEL-05 enforcement AC)"
    )


# ---------------------------------------------------------------------------
# Fan-in architecture guard
# ---------------------------------------------------------------------------

# Files allowed to call add_document/set_documents on the hybrid retrieval
# store. Only the rebuild path itself, plus test/eval/fitness harnesses that
# snapshot-and-restore around a synthetic corpus (never a production write
# path), belong here. Do NOT add a production ingest/outbox call site.
ALLOWED_CALLERS: frozenset[str] = frozenset(
    [
        # The rebuild path itself.
        "app/retrieval/hybrid.py",
        # Eval/fitness harnesses: snapshot-and-restore around a synthetic
        # corpus for latency/quality measurement, never a production write.
        "app/eval/golden.py",
        "app/fitness/metrics.py",
    ]
)

_TARGET_METHODS = {"add_document", "set_documents"}


def _calls_target_method(path: Path) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _TARGET_METHODS:
                return True
    return False


def test_no_fanin_writers() -> None:
    """No app/**/*.py file outside ALLOWED_CALLERS calls add_document/set_documents.

    Retrieval must be populated only by the durable-index rebuild
    (KERNEL-05, I-D3) — never by an ad-hoc ingest/outbox fan-in.
    """
    violations: list[str] = []
    for py_file in APP_ROOT.rglob("*.py"):
        rel = str(py_file.relative_to(REPO_ROOT))
        if rel in ALLOWED_CALLERS:
            continue
        if _calls_target_method(py_file):
            violations.append(rel)

    assert not violations, (
        "Found production callers of add_document/set_documents outside the "
        "durable-index rebuild path. Retrieval must be populated only by "
        "app.retrieval.hybrid.rebuild_from_durable_index() (KERNEL-05, I-D3). "
        "Violations:\n" + "\n".join(f"  {v}" for v in sorted(violations))
    )


def test_allowlist_entries_still_call_target_methods() -> None:
    """Keep ALLOWED_CALLERS minimal: every entry must exist and still call a
    target method, otherwise it should be removed from the allowlist."""
    stale: list[str] = []
    for rel in ALLOWED_CALLERS:
        abs_path = REPO_ROOT / rel
        if not abs_path.exists() or not _calls_target_method(abs_path):
            stale.append(rel)

    assert not stale, (
        "Stale ALLOWED_CALLERS entries (file missing or no longer calls "
        "add_document/set_documents) — remove them:\n"
        + "\n".join(f"  {s}" for s in sorted(stale))
    )


# ---------------------------------------------------------------------------
# Post-merge audit F2 (#2899 I-D3 / #2900): every production retrieval
# entrypoint must read the durable-index-backed store, not just /api/ask.
# ---------------------------------------------------------------------------


def test_context_bundles_served_from_durable_after_restart() -> None:
    """Cold-cache the context-bundles path: a /api/context-bundles-equivalent
    request must serve durable-index results even when it is the FIRST
    retrieval call in the process (no prior /api/ask warm), and results must
    be identical before and after a simulated kill-and-restart (cache
    discard + rebuild) — not just for /api/ask.
    """
    from app.retrieval.capability import RetrievalRequest
    from app.retrieval.production_bundle import retrieve_and_emit_bundle

    _seed_durable_index()

    # Cold start: no /api/ask has ever run, no explicit rebuild has been
    # triggered by the test. The production lifespan warm
    # (app/api/app.py::_warm_retrieval_cache) is what must cover this path;
    # simulate it directly here (it is a thin call to rebuild_from_durable_index).
    assert hybrid.get_store().all() == [], "test setup must start from a cold cache"

    from app.api.app import _warm_retrieval_cache

    _warm_retrieval_cache()

    assert hybrid.get_store().all(), (
        "the lifespan warm (app/api/app.py::_warm_retrieval_cache) must "
        "populate the shared retrieval store before any route runs"
    )

    result_before, _receipt_before = retrieve_and_emit_bundle(
        RetrievalRequest(query="alpha retrieval mountains", trace_id="cold-start"),
        bundle_id="cold-start-bundle",
    )
    before_ids = [item.artifact_id for item in result_before.bundle.included]
    assert before_ids, (
        "/api/context-bundles must return a non-empty bundle on a cold cache, "
        "without any prior /api/ask request warming the shared store"
    )

    # Kill-and-restart equivalence for the context-bundles path specifically:
    # discard the in-process cache, keep the durable index untouched, rebuild
    # via the same production lifespan seam, and confirm identical results.
    hybrid.get_store().set_documents([])
    hybrid.reset_durable_rebuild_state()
    _warm_retrieval_cache()

    result_after, _receipt_after = retrieve_and_emit_bundle(
        RetrievalRequest(query="alpha retrieval mountains", trace_id="post-restart"),
        bundle_id="post-restart-bundle",
    )
    after_ids = [item.artifact_id for item in result_after.bundle.included]

    assert after_ids == before_ids, (
        "context-bundles results must be identical before and after a "
        "cache-discard + rebuild (kill-and-restart equivalence), matching the "
        "guarantee /api/ask already had"
    )


# ---------------------------------------------------------------------------
# G1res-1 (#2981): generation-checked cache revalidation — a durable
# upsert/purge committed AFTER process warm becomes visible to retrieval
# within the freshness bound, without a restart and without force=True.
# ---------------------------------------------------------------------------


def _upsert_doc(oid: UUID, title: str, text: str) -> None:
    identity = EmbeddingIdentity(provider="mock", model="embed-test", dim=8, normalize=False)
    get_vector_index().upsert(
        object_id=oid,
        kind="note",
        source_ref=f"unit-test://{title}",
        payload={"title": title, "text": text, "content": text},
        embedding=[0.1] * 8,
        model=identity.model,
        identity=identity,
    )


def _force_generation_check_due() -> None:
    """Make the next serving-path access due for a generation check without
    weakening the mandatory >=1s production min-check interval."""
    hybrid._LAST_GENERATION_CHECK_MONOTONIC = 0.0


def test_post_upsert_visibility_without_restart() -> None:
    """A row upserted after the process warmed must be served by retrieval
    without a restart, reset, or explicit force=True rebuild (G1res-1 AC1)."""
    _seed_durable_index()
    hybrid.rebuild_from_durable_index()
    assert hybrid.hybrid_search("alpha retrieval mountains", k=5)

    new_id = uuid4()
    _upsert_doc(new_id, "Gamma note", "gamma retrieval content about glaciers")

    _force_generation_check_due()
    hits = hybrid.hybrid_search("gamma retrieval glaciers", k=5)
    assert str(new_id) in [hit["doc_id"] for hit in hits], (
        "a durable upsert committed after process warm must be visible to "
        "retrieval via the generation check, without a restart"
    )


def test_post_purge_visibility_without_restart() -> None:
    """A purge committed after warm disappears from retrieval without restart."""
    ids = _seed_durable_index()
    hybrid.rebuild_from_durable_index()
    before = hybrid.hybrid_search("alpha retrieval mountains", k=5)
    assert str(ids[0]) in [hit["doc_id"] for hit in before]

    get_vector_index().purge_vectors(ids[0], view="note")

    _force_generation_check_due()
    after = hybrid.hybrid_search("alpha retrieval mountains", k=5)
    assert str(ids[0]) not in [hit["doc_id"] for hit in after], (
        "a durable purge committed after process warm must drop out of "
        "retrieval without a restart"
    )


def test_generation_check_respects_min_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated queries inside the min-check interval never hit the durable
    store's generation signal; a due check does (G1res-1 AC2)."""
    monkeypatch.setenv("RETRIEVAL_GENERATION_MIN_CHECK_INTERVAL_S", "60")
    _seed_durable_index()
    hybrid.rebuild_from_durable_index()

    idx = get_vector_index()
    calls = {"n": 0}
    real_generation = idx.generation

    def counting_generation() -> str:
        calls["n"] += 1
        return real_generation()

    monkeypatch.setattr(idx, "generation", counting_generation)

    # rebuild_from_durable_index just captured a generation and stamped the
    # check clock; every query inside the 60s window must skip the check.
    for _ in range(5):
        hybrid.hybrid_search("alpha retrieval mountains", k=5)
    assert calls["n"] == 0, (
        "the generation check must not hit the durable store more often than "
        "the configured min-check interval under repeated queries"
    )

    # Once the interval has elapsed (simulated), exactly one check runs for
    # the next query, and the clock is re-stamped for the queries after it.
    _force_generation_check_due()
    for _ in range(5):
        hybrid.hybrid_search("alpha retrieval mountains", k=5)
    assert calls["n"] == 1, (
        "a due generation check must run exactly once, then be re-bounded by "
        "the min-check interval"
    )


def test_min_check_interval_floor_is_one_second(monkeypatch: pytest.MonkeyPatch) -> None:
    """The configured interval is clamped to the mandatory >=1s floor; junk
    values fall back to the default rather than disabling the bound."""
    monkeypatch.setenv("RETRIEVAL_GENERATION_MIN_CHECK_INTERVAL_S", "0")
    assert hybrid._generation_check_min_interval() >= 1.0
    monkeypatch.setenv("RETRIEVAL_GENERATION_MIN_CHECK_INTERVAL_S", "not-a-number")
    assert hybrid._generation_check_min_interval() >= 1.0


def test_force_escape_hatch_unchanged() -> None:
    """force=True still unconditionally rebuilds (G1res-1 constraint)."""
    _seed_durable_index()
    hybrid.rebuild_from_durable_index()
    n_before = len(hybrid.get_store().all())
    hybrid.get_store().set_documents([])
    assert hybrid.rebuild_from_durable_index(force=True) == n_before


def test_freshness_check_never_populates_cold_manual_cache() -> None:
    """The freshness check only applies to a cache that WAS rebuilt from the
    durable index — it never hijacks a manually seeded store (test/eval
    harness seams unchanged, per the G1res-1 constraint)."""
    _upsert_doc(uuid4(), "Durable-only", "durable-only note about comets")
    hybrid.get_store().set_documents(
        [{"doc_id": "manual-1", "text": "manually seeded note about comets"}]
    )
    _force_generation_check_due()
    hits = hybrid.hybrid_search("comets", k=5)
    assert [hit["doc_id"] for hit in hits] == ["manual-1"], (
        "freshness check must not rebuild over a manually seeded store when "
        "no durable rebuild has happened in this process"
    )
