from __future__ import annotations
from typing import Dict, Any, List
from app.ingest.chunk_policy import split_into_chunks
from app.ingest.deduper import Deduper

_deduper = Deduper()

def ingest_and_chunk(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    text = obj.get("text","")
    chunks = split_into_chunks(text)
    out=[]
    for i,ch in enumerate(chunks):
        if _deduper.is_dup(ch, obj.get("uuid","")):
            out.append({"kind":"duplicate","index":i})
        else:
            out.append({"kind":"chunk","index":i,"text":ch})
    return out
