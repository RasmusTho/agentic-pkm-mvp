from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import yaml


@dataclass(slots=True)
class FrontmatterData:
    title: str
    origin: str
    created: date
    tags: List[str] = field(default_factory=list)
    trust: str = "provisional"
    source_ref: Optional[str] = None
    nodes: List[str] = field(default_factory=list)
    edges: List[str] = field(default_factory=list)
    chunk_algo: str = "recursive"
    chunk_size: int = 800
    chunk_overlap: int = 120


def render_frontmatter(meta: FrontmatterData) -> str:
    """
    Render YAML frontmatter according to the v0.1 spec captured in docs/ALIGNMENT.md.
    """

    payload = {
        "title": meta.title,
        "origin": meta.origin,
        "created": meta.created.isoformat(),
        "tags": meta.tags,
        "trust": meta.trust,
        "source_ref": meta.source_ref,
        "amg": {
            "nodes": meta.nodes,
            "edges": meta.edges,
        },
        "chunks": {
            "algo": meta.chunk_algo,
            "size": meta.chunk_size,
            "overlap": meta.chunk_overlap,
        },
    }
    serialized = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{serialized}\n---\n"
