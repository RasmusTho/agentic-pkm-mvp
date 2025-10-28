from pathlib import Path
from textwrap import dedent
from app.index.ingest_md import parse_markdown

def write(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")

def test_no_frontmatter_parses_as_body(tmp_path: Path):
    p = tmp_path / "note.md"
    write(p, "Hello body only")
    meta, body = parse_markdown(p)
    assert meta == {}
    assert body == "Hello body only"

def test_well_formed_frontmatter(tmp_path: Path):
    p = tmp_path / "note.md"
    write(p, dedent("""\
    ---
    title: T
    review_state: promoted
    ---
    Body text
    """))
    meta, body = parse_markdown(p)
    assert meta.get("title") == "T"
    assert body == "Body text"

def test_malformed_missing_closing_delimiter(tmp_path: Path):
    p = tmp_path / "bad.md"
    write(p, dedent("""\
    ---
    title: Broken
    review_state: inbox
    Body never closed
    """))
    meta, body = parse_markdown(p)
    assert meta == {}
    assert "Body never closed" in body

def test_frontmatter_non_mapping_defaults_to_empty(tmp_path: Path):
    p = tmp_path / "odd.md"
    write(p, dedent("""\
    ---
    - not: a mapping
    ---
    Body
    """))
    meta, body = parse_markdown(p)
    assert meta == {}
    assert body == "Body"

def test_frontmatter_then_triple_dash_in_body_is_ok(tmp_path: Path):
    p = tmp_path / "split.md"
    write(p, dedent("""\
    ---
    title: Has dashes
    ---
    Body line 1
    ---
    Body line 2
    """))
    meta, body = parse_markdown(p)
    assert meta.get("title") == "Has dashes"
    assert "Body line 1" in body and "Body line 2" in body
