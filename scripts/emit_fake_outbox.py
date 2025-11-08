from __future__ import annotations

from uuid import uuid4

from app.outbox.events import emit_index_object_embedded


def _make_embedding(axis: int, dim: int = 1536) -> list[float]:
    vec = [0.0] * dim
    vec[axis % dim] = 1.0
    return vec


def main() -> None:
    for idx in range(2):
        object_id = uuid4()
        text = f"Synthetic note {idx}"
        emit_index_object_embedded(
            {
                "object_id": object_id,
                "kind": "note",
                "source_ref": f"fake:{idx}",
                "payload": {
                    "text": text,
                    "content": text,
                    "object_type": "note",
                    "system_intent": "learn",
                    "emergent_tags": [],
                },
                "embedding": _make_embedding(idx),
                "model": "openai/text-embedding-3-large",
            }
        )
    print("Emitted 2 synthetic index.object.embedded events")


if __name__ == "__main__":
    main()
