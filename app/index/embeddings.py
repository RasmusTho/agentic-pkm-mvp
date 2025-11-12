from __future__ import annotations

from typing import Iterable, Iterator, List, Sequence

from app.llm import embeddings as _emb


def _prepend_speaker(text: str, speaker: str | None = None) -> str:
    if speaker:
        prefix = f"[speaker={speaker}] "
        return f"{prefix}{text}".strip()
    return text


def embed_text(text: str, *, speaker: str | None = None) -> List[float]:
    enriched = _prepend_speaker(text, speaker)
    return _emb.embed_text(enriched)


def embed_texts(texts: Sequence[str], *, speakers: Sequence[str | None] | None = None) -> List[List[float]]:
    if speakers:
        if len(texts) != len(speakers):
            raise ValueError("texts and speakers must be the same length")
        enriched = [_prepend_speaker(text, spk) for text, spk in zip(texts, speakers)]
        return _emb.embed_texts(enriched)
    return _emb.embed_texts(list(texts))


def embed_batches(
    texts: Iterable[str],
    *,
    speakers: Iterable[str | None] | None = None,
    batch_size: int = 64,
) -> Iterator[List[List[float]]]:
    batch: List[str] = []
    batch_speakers: List[str | None] = []
    speaker_iter = iter(speakers) if speakers is not None else None
    for text in texts:
        batch.append(text)
        if speaker_iter is not None:
            batch_speakers.append(next(speaker_iter, None))
        if len(batch) >= batch_size:
            if batch_speakers:
                yield embed_texts(batch, speakers=batch_speakers)
            else:
                yield embed_texts(batch)
            batch = []
            batch_speakers = []
    if batch:
        if batch_speakers:
            yield embed_texts(batch, speakers=batch_speakers)
        else:
            yield embed_texts(batch)


__all__ = ["embed_text", "embed_texts", "embed_batches"]
