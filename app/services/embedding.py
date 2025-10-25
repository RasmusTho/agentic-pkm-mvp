import hashlib
import math

DIM = 1536

def _hash_bytes(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()

def deterministic_embedding(text: str, dim: int = DIM) -> list[float]:
    digest = _hash_bytes(text)
    values = []
    for i in range(dim):
        b = digest[i % len(digest)]
        x = ((b / 255.0) - 0.5) * 2.0
        values.append(x)
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]
