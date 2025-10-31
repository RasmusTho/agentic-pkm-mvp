from pathlib import Path


def test_normalizer_core6_structure(tmp_path: Path) -> None:
    from app.agents.normalizer.agent import run as normalize_run

    src = tmp_path / "sample.md"
    src.write_text("Hello world\n\nSome body text.")

    res1 = normalize_run(str(src), trace_id="t-normalize-1")
    oid1 = res1["object_id"]
    assert isinstance(oid1, str) and oid1

    core6 = res1.get("core6", {})
    for key in ["id", "title", "review_state", "created_at"]:
        assert key in core6
    assert core6["id"] == oid1
    assert isinstance(core6["title"], str)
    assert core6["review_state"]
    assert core6["created_at"]

    res2 = normalize_run(str(src), trace_id="t-normalize-2")
    oid2 = res2["object_id"]
    assert isinstance(oid2, str) and oid2
