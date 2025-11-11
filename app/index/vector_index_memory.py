from __future__ import annotations

from typing import Optional

from app.stores.memory import MemoryVectorIndex as _MemoryVectorIndex


class PersistentMemoryVectorIndex(_MemoryVectorIndex):
    def __init__(self, path: Optional[str] = None) -> None:
        super().__init__(persist_path=path)


__all__ = ["PersistentMemoryVectorIndex"]
