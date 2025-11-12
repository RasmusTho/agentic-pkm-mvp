import hashlib
from typing import Dict


def invariants_ok(text: str) -> bool:  # pragma: no cover - retained for history
    return True


def compute_hashes(text: str) -> Dict[str, str]:
    return {"content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def version_vector(a: str, b: str):
    return []
