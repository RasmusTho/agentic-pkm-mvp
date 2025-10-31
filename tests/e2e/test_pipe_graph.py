from __future__ import annotations

import os
from pathlib import Path

from app.agents.normalizer.graph import invoke as normalize_invoke
from app.agents.classifier.graph import invoke as classify_invoke
from app.agents.chunker.graph import invoke as chunk_invoke
from app.agents.deduper.graph import invoke as dedupe_invoke
from app.agents.indexer.graph import invoke as index_invoke
from app.agents.reviewer.graph import invoke as review_invoke
from app.agents.set_evaluator.graph import invoke as evaluate_invoke
from app.agents.projector.graph import invoke as project_invoke

# offline cache of "published membership"
PROJECTED_CACHE: set[tuple[str, str]] = set()


def test_e2e_pipe(tmp_path: Path):
    trace_id = "t-e2e-graph-1"
    os.environ.setdefault("LLM_PROVIDER", "mock")
    os.environ.setdefault(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )

    # --- create sample files -------------------------------------------------
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    c = tmp_path / "c.md"
    a.write_text(
        "# Title\n\nAccording to the 2023 report, vector search adoption grew 25% last year.\nIt references pgvector and BM25 without citing sources.\n"
    )
    b.write_text(
        "Title\n\nAccording to the 2023 report, vector search adoption grew 25% last year.\nIt references pgvector and bm25!\nSee https://example.org/report.\n"
    )
    c.write_text(
        "# Different\n\nA totally different topic about LangGraph and PER loops.\n"
    )

    # --- normalizer ----------------------------------------------------------
    r1 = normalize_invoke(str(a), trace_id=trace_id)
    r2 = normalize_invoke(str(b), trace_id=trace_id)
    r3 = normalize_invoke(str(c), trace_id=trace_id)

    oids = [
        r1["output"]["object_id"],
        r2["output"]["object_id"],
        r3["output"]["object_id"],
    ]
    assert all(oids)
    assert all(r["output"]["core6"].get("id") for r in [r1, r2, r3])

    # --- classifier ----------------------------------------------------------
    for oid in oids:
        cr = classify_invoke(oid, trace_id=trace_id)
        assert cr["output"]["event"] == "curation.classify.done"

    # --- chunker -------------------------------------------------------------
    total_chunks = 0
    for oid in oids:
        ch = chunk_invoke(
            oid,
            trace_id=trace_id,
            max_tokens=800,
            overlap=120,
            strategy="heading_first",
        )
        assert ch["output"]["event"] == "ingest.chunk.done"
        assert ch["output"]["chunks"] >= 1
        total_chunks += ch["output"]["chunks"]

    # --- deduper -------------------------------------------------------------
    dres = dedupe_invoke(oids[:2], trace_id=trace_id, threshold=0.85)
    assert dres["output"]["event"] == "curation.dedupe.done"
    assert isinstance(dres["output"]["pairs"], list)

    # --- downstream: index / review / evaluate / project --------------------
    reviews = []
    evaluations = []
    projections = []

    for oid in oids:
        # index (embeddings etc.)
        ix = index_invoke(oid, trace_id=trace_id)
        assert ix["output"]["event"] == "ingest.index.done"
        assert ix["output"]["embeddings"] >= 1

        # reviewer (quality gate)
        rv = review_invoke(oid, trace_id=trace_id, threshold=0.75)
        assert rv["output"]["event"] == "curation.review.done"
        reviews.append(rv["output"])

        # set_evaluator (decides if it's promotable)
        ev = evaluate_invoke(oid, trace_id=trace_id, threshold=0.7)
        assert ev["output"]["event"] == "promotion.evaluate.done"
        evaluations.append(ev["output"])

        # projector (adds to published set if promotable)
        pj = project_invoke(oid, trace_id=trace_id, set_name="published")
        assert pj["output"]["event"] in {
            "promotion.project.done",
            "promotion.project.skip",
        }
        projections.append(pj["output"])

        if pj["output"].get("promote"):
            PROJECTED_CACHE.add((oid, pj["output"].get("set_name", "published")))

    # --- offline assertions (no DB required) --------------------------------

    assert len(oids) == 3
    assert total_chunks >= 3

    for review in reviews:
        assert review["event"] == "curation.review.done"
        assert isinstance(review.get("allow"), bool)
        assert "reasons" in review
        assert "agent" in review

    for evaluation in evaluations:
        assert evaluation["event"] == "promotion.evaluate.done"
        assert isinstance(evaluation.get("promote"), bool)
        assert isinstance(evaluation.get("score"), float)
        assert "allow" in evaluation

    for proj in projections:
        assert proj["event"] in {"promotion.project.done", "promotion.project.skip"}
        assert "promote" in proj
