from app.ingest.chunker import ChunkConfig, chunk_text


def test_chunk_text_handles_empty_input():
    assert chunk_text("") == []


def test_chunk_text_respects_size_and_overlap():
    text = " ".join(f"word{i}" for i in range(1, 21))
    config = ChunkConfig(size=5, overlap=2)
    chunks = chunk_text(text, config)
    assert chunks[0].split()[0] == "word1"
    assert chunks[0].split()[-1] == "word5"
    assert chunks[1].split()[0] == "word4"
    assert chunks[-1].split()[-1] == "word20"
    expected_chunk_count = 1 + (20 - 5) // (5 - 2) + (1 if (20 - 5) % (5 - 2) else 0)
    assert len(chunks) == expected_chunk_count
