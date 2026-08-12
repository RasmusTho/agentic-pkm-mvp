"""Non-writing compatibility contract types for relation consumers."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class RelationEdge:
    src_uuid: str
    dst_uuid: str
    relation_type: str
    weight: float
    provenance: dict[str, Any]
    created_at: datetime


@dataclass
class GraphSlice:
    center: str
    edges: list[RelationEdge]
