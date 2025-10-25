import os
from pathlib import Path

from app.memory.store import recall

os.environ.setdefault("MEMORY_ENABLED", "true")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:15432/app")


def test_normalizer_writes_memory(tmp_path: Path) -> None:
    from app.agents.normalizer.agent import run as normalize_run

    src = tmp_path / "n.md"
    src.write_text("Hello\n\nWorld.")
    res = normalize_run(str(src), trace_id="t-mem-n-1")
    oid = res["object_id"]
    rows = recall("normalizer", "normalized", object_id=None, limit=5)
    assert any(r.get("core6") and r["core6"].get("id") == oid for r in rows)


def test_classifier_writes_memory(tmp_path: Path) -> None:
    from app.agents.normalizer.agent import run as normalize_run
    from app.agents.classifier.agent import run as classify_run

    src = tmp_path / "c.md"
    src.write_text("# Title\n\nSome text about embeddings.")
    nres = normalize_run(str(src), trace_id="t-mem-c-1")
    oid = nres["object_id"]
    classify_run(oid, trace_id="t-mem-c-1")
    rows = recall("classifier", "classified", object_id=None, limit=10)
    assert any(
        isinstance(r.get("labels"), (list, tuple, set))
        or isinstance(r.get("labels"), dict)
        or r.get("labels") is not None
        for r in rows
    )


def test_chunker_writes_memory(tmp_path: Path) -> None:
    from app.agents.normalizer.agent import run as normalize_run
    from app.agents.chunker.agent import run as chunk_run

    src = tmp_path / "h.md"
    src.write_text("# A\nBody sentence.\n\n## B\nMore body.")
    nres = normalize_run(str(src), trace_id="t-mem-h-1")
    oid = nres["object_id"]
    chunk_run(oid, max_tokens=120, overlap=20, strategy="heading_first", trace_id="t-mem-h-1")
    rows = recall("chunker", "chunked", object_id=None, limit=10)
    assert any((r.get("chunks") or 0) >= 1 for r in rows)
