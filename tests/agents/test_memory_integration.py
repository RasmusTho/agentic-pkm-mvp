from pathlib import Path


def test_normalizer_returns_core6(tmp_path: Path) -> None:
    from app.agents.normalizer.agent import run as normalize_run

    src = tmp_path / "n.md"
    src.write_text("Hello\n\nWorld.")
    res = normalize_run(str(src), trace_id="t-mem-n-1")
    oid = res["object_id"]
    core6 = res.get("core6", {})
    assert core6.get("id") == oid
    assert core6.get("title") == "Hello"
    assert core6.get("review_state")
    assert core6.get("created_at")


def test_classifier_returns_classification(tmp_path: Path) -> None:
    from app.agents.normalizer.agent import run as normalize_run
    from app.agents.classifier.agent import run as classify_run

    src = tmp_path / "c.md"
    src.write_text("# Title\n\nSome text about embeddings.")
    nres = normalize_run(str(src), trace_id="t-mem-c-1")
    oid = nres["object_id"]
    cres = classify_run(oid, trace_id="t-mem-c-1")
    assert cres["object_id"] == oid
    classification = cres.get("classification", {})
    assert isinstance(classification, dict)
    assert "type" in classification
    assert "trust" in classification
    assert "confidence" in classification


def test_chunker_returns_chunk_count(tmp_path: Path) -> None:
    from app.agents.normalizer.agent import run as normalize_run
    from app.agents.chunker.agent import run as chunk_run

    src = tmp_path / "h.md"
    src.write_text("# A\nBody sentence.\n\n## B\nMore body.")
    nres = normalize_run(str(src), trace_id="t-mem-h-1")
    oid = nres["object_id"]
    cres = chunk_run(
        oid,
        max_tokens=120,
        overlap=20,
        strategy="heading_first",
        trace_id="t-mem-h-1",
    )
    assert cres["chunks"] >= 1
