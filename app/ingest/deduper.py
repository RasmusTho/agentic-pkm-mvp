from __future__ import annotations
import hashlib
from typing import Dict, Tuple

class Deduper:
    def __init__(self) -> None:
        self.seen: Dict[str, Tuple[str,int]] = {}

    def hash(self, s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def is_dup(self, text: str, obj_id: str) -> bool:
        h=self.hash(text)
        if h in self.seen:
            return True
        self.seen[h]=(obj_id, len(text))
        return False
