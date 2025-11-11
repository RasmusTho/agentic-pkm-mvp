import pytest

pytestmark = pytest.mark.not_pg


def test_chunks_with_size():
    from app.ingest.chunk_policy import split_into_chunks

    s = "A" * 3500 + "\n" + "B" * 1200
    parts = split_into_chunks(s, max_chars=3000)
    assert len(parts) == 2
    assert parts[0].count("A") == 3500


def test_dedup_detects_identical_chunks():
    from app.agents.pipeline import ingest_and_chunk

    obj = {"uuid": "u1", "text": "hello\nworld\nhello\nworld"}
    first = ingest_and_chunk(obj)
    assert any(x["kind"] == "chunk" for x in first)
    obj2 = {"uuid": "u2", "text": "hello\nworld\nhello\nworld"}
    second = ingest_and_chunk(obj2)
    assert any(x["kind"] == "duplicate" for x in second)


def test_build_chunks_with_segments(monkeypatch):
    from app.ingest.chunk_policy import build_chunks

    monkeypatch.setenv("DIARIZE_ENABLE", "1")
    records = build_chunks(
        "",
        segments=[
            {"speaker": "spk_a", "text": "alpha statement"},
            {"speaker": "spk_b", "text": "beta reply"},
        ],
    )
    assert records[0]["speaker"] == "spk_a"
    assert records[1]["speaker"] == "spk_b"
