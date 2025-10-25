from fastapi import APIRouter, Query
import os
import psycopg
from app.services.embedding import deterministic_embedding
from app.search.cosine import cosine

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:15432/app")

def _conn():
    return psycopg.connect(DATABASE_URL)

@router.get("/search")
async def search(q: str = Query(...)):
    q_vector = deterministic_embedding(q)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("select uuid, title, vector from objects_embeddings join objects using(uuid) limit 50")
            rows = cur.fetchall()
    results = []
    for uuid, title, vector in rows:
        score = cosine(q_vector, vector)
        results.append({"uuid": uuid, "title": title, "score": float(score)})
    results.sort(key=lambda item: item["score"], reverse=True)
    return {"results": results[:10]}
