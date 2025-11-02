from app.agents.normalizer.graph import invoke

def test_normalizer_graph_core6(tmp_path):
    src = tmp_path / "g.md"
    src.write_text("Hej\n\nBody")
    res = invoke(str(src), trace_id="t-norm-graph-1")
    out = res.get("output") or {}
    assert out.get("event") == "ingest.normalize.done"
    assert out.get("object_id")
    c6 = out.get("core6") or {}
    for k in ["id", "title", "review_state", "created_at"]:
        assert k in c6
