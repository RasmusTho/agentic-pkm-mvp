from pathlib import Path
def test_chunker_heading_and_fallback(tmp_path):
    from app.agents.normalizer.agent import run as normalize_run
    from app.agents.chunker.agent import run as chunk_run

    text = """# Titel
Det här är en inledning. Den har några meningar som bör hållas ihop för semantik.

## Del 1
Detta är ett längre avsnitt som ska chunkas. Här kommer flera meningar i rad för att forcera fallback vid max_tokens. Vi vill undvika att bryta mitt i meningar när det går. Detta är ytterligare en mening. Och en till. Slutligen ännu en mening för att överskrida gränsen lite grand.

## Del 2
Kort stycke.
"""
    src = tmp_path / "note.md"
    src.write_text(text)

    norm = normalize_run(str(src), trace_id="t-chunk-1")
    oid = norm["object_id"]

    res1 = chunk_run(
        oid,
        max_tokens=50,
        overlap=10,
        strategy="heading_first",
        trace_id="t-chunk-1",
    )
    assert res1["chunks"] >= 1
