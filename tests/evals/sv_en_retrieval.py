"""SV/EN retrieval eval harness (G3-2, #2985).

Scores the LIVE app retrieval path (``app.retrieval.hybrid.scoped_hybrid_search``, the same
entrypoint ``hybrid_search`` and the ASK path bind to) over the synthetic SV/EN fixture corpus under
``tests/evals/fixtures/sv_en_retrieval/``.

Two sections, per the issue contract:

* **Retrieval quality** — recall@k + MRR over a hand-labelled SV-only / EN-only / cross-lingual query
  set, run against both embedding identities (``nomic-embed-text``@768 and ``bge-m3``@1024) with the
  fusion strategy held fixed, so the identity is the only moving part.
* **Expansion quality** — connect precision over a hand-labelled SV/EN related-pair set, using E3's
  real finding shape (``app.expansion.connect.run_connect_pass``: pairs among retrieval hits above
  ``ConnectPassConfig.relatedness_floor``), not a relatedness proxy.

This module holds no numbers. It computes them. The recorded scorecard lives in
``fixtures/sv_en_retrieval/scorecard.json`` and is produced by
``scripts/eval_sv_en_retrieval.py``; the eval note that reads it is
``tests/evals/SV_EN_RETRIEVAL_EVAL_G3_2.md``.

Nothing here changes retrieval behaviour — it measures it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable, Sequence

from tests.evals._helpers import parse_frontmatter

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sv_en_retrieval"
CORPUS_DIR = FIXTURES_DIR / "corpus"
QUERIES_PATH = FIXTURES_DIR / "queries.json"
CONNECT_PAIRS_PATH = FIXTURES_DIR / "connect_pairs.json"
SCORECARD_PATH = FIXTURES_DIR / "scorecard.json"

# The eval's own scope. Every fixture doc carries it, so the production scope prefilter admits the
# whole corpus and the ranking — not the prefilter — is what is being measured.
EVAL_SCOPE = "scope:general/retrieval-eval"

RECALL_KS: tuple[int, ...] = (1, 3, 5)
QUERY_CLASSES: tuple[str, ...] = ("sv_only", "en_only", "cross_lingual")

#: The two identities the issue compares. ``dim`` is asserted against the live vector width.
IDENTITIES: dict[str, dict[str, object]] = {
    "nomic": {"model": "nomic-embed-text:latest", "dim": 768},
    "bge_m3": {"model": "bge-m3:latest", "dim": 1024},
}

FUSIONS: tuple[str, ...] = ("linear", "rrf")


@dataclass(frozen=True)
class CorpusDoc:
    doc_id: str
    lang: str
    topic: str
    text: str
    meta: dict[str, str]


def load_corpus() -> list[CorpusDoc]:
    """Load the SV/EN fixture corpus, ordered by ``doc_id`` so runs are reproducible."""
    docs: list[CorpusDoc] = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        docs.append(
            CorpusDoc(
                doc_id=path.stem,
                lang=meta.get("lang", ""),
                topic=meta.get("topic", ""),
                text=body.strip(),
                meta=meta,
            )
        )
    return docs


def load_query_set() -> dict:
    return json.loads(QUERIES_PATH.read_text(encoding="utf-8"))


def load_connect_pairs() -> dict:
    return json.loads(CONNECT_PAIRS_PATH.read_text(encoding="utf-8"))


def load_scorecard() -> dict:
    return json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# Metrics — pure functions over ranked doc-id lists, independent of the retrieval backend.
# --------------------------------------------------------------------------------------


def recall_at_k(ranked: Sequence[str], gold: Iterable[str], k: int) -> float:
    """Fraction of gold documents present in the top ``k``."""
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    return len(gold_set & set(ranked[:k])) / len(gold_set)


def reciprocal_rank(ranked: Sequence[str], gold: Iterable[str]) -> float:
    """1/rank of the first gold document, 0.0 when no gold document is retrieved at all."""
    gold_set = set(gold)
    for position, doc_id in enumerate(ranked, start=1):
        if doc_id in gold_set:
            return 1.0 / position
    return 0.0


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


# --------------------------------------------------------------------------------------
# Live retrieval backend
# --------------------------------------------------------------------------------------


DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


def ollama_base_url() -> str:
    """The Ollama base URL the availability probe and the pinned run must both use.

    These have to agree. ``ollama`` itself defaults to localhost, but the app's embedding client
    requires an explicit ``OLLAMA_HOST``/``OLLAMA_BASE_URL`` and substitutes a ZERO VECTOR when none
    is set. If the probe defaulted to localhost while the run did not, the live tests would run
    against an all-zero index and report meaningless scores instead of skipping.
    """
    return (os.getenv("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST).rstrip("/")


def ollama_models_available() -> set[str]:
    """Return the Ollama model tags reachable from this host, or an empty set.

    Used to skip — never to silently pass — when the runner machine has no embedding host. The
    owner's laptop deliberately carries no ML deps; the eval runs on the test-channel host or any
    other host with an Ollama runtime.
    """
    import httpx

    base = ollama_base_url()
    try:
        response = httpx.get(f"{base}/api/tags", timeout=3.0)
        response.raise_for_status()
    except Exception:
        return set()
    payload = response.json()
    return {str(entry.get("name", "")) for entry in payload.get("models", [])}


def identities_available() -> bool:
    tags = ollama_models_available()
    return all(str(spec["model"]) in tags for spec in IDENTITIES.values())


def _load_corpus_into_store(docs: Sequence[CorpusDoc], vectors: Sequence[Sequence[float]]) -> None:
    """Load the corpus into the live retrieval store with pre-computed vectors.

    Vectors are passed in rather than embedded lazily so that a run pins exactly one identity: the
    store never mixes a doc embedded under one model with a query embedded under another.
    """
    from app.retrieval.hybrid import get_store

    store = get_store()
    store.set_documents(
        [
            {
                "doc_id": doc.doc_id,
                "text": doc.text,
                "language": doc.lang,
                "source_ref": f"{doc.doc_id}.md",
                "payload": {
                    "domain": EVAL_SCOPE,
                    "scope_id": EVAL_SCOPE,
                    "evidence_role": doc.meta.get("evidence_role"),
                    "sphere": doc.meta.get("sphere"),
                    "source_role": doc.meta.get("source_role"),
                    "sensitivity": doc.meta.get("sensitivity"),
                    "lang": doc.lang,
                    "topic": doc.topic,
                },
                "embedding": list(vector),
            }
            for doc, vector in zip(docs, vectors)
        ]
    )


class IdentityRun:
    """One pinned (identity, fusion) retrieval configuration over the fixture corpus.

    Entering the context sets the embedding identity and fusion strategy for the process, embeds the
    corpus once under that identity, and loads it into the live store. Leaving restores the prior
    environment and clears the cached tuning, so runs cannot leak into one another.
    """

    def __init__(self, identity_key: str, fusion: str) -> None:
        if identity_key not in IDENTITIES:
            raise ValueError(f"unknown identity {identity_key!r}")
        if fusion not in FUSIONS:
            raise ValueError(f"unknown fusion {fusion!r}")
        self.identity_key = identity_key
        self.fusion = fusion
        self.spec = IDENTITIES[identity_key]
        self._prior: dict[str, str | None] = {}
        self._prior_docs: list = []
        self.resolved_identity: object | None = None

    def _set_env(self, **values: str) -> None:
        for key, value in values.items():
            self._prior[key] = os.environ.get(key)
            os.environ[key] = value

    def __enter__(self) -> "IdentityRun":
        self._set_env(
            EMBED_PRIMARY_PROVIDER="ollama",
            EMBED_MODEL=str(self.spec["model"]),
            OLLAMA_EMBED_MODEL=str(self.spec["model"]),
            EMBED_DIM=str(self.spec["dim"]),
            RETRIEVAL_FUSION=self.fusion,
            # Pin the same host the availability probe resolved, so a run can never silently fall
            # back to zero vectors (see ollama_base_url).
            OLLAMA_HOST=ollama_base_url(),
            # The corpus is the whole eligible set; the prefilter must admit it so the ranking is
            # what gets measured.
            ASK_DOMAIN_SCOPE=EVAL_SCOPE,
        )
        from app.retrieval.hybrid import get_store

        # The retrieval store is process-global and tests/conftest.py does not reset it, so a run
        # must hand it back exactly as it found it.
        self._prior_docs = get_store().all()
        from app.components.retrieval import embed_docs
        from app.retrieval.tuning import get_retrieval_tuning, reset_retrieval_tuning_cache

        reset_retrieval_tuning_cache()
        tuning = get_retrieval_tuning()
        if tuning.fusion != self.fusion:
            raise RuntimeError(
                f"fusion pin failed: asked for {self.fusion!r}, runtime resolved {tuning.fusion!r}"
            )

        self.docs = load_corpus()
        vectors, identity = embed_docs([doc.text for doc in self.docs])
        if identity.provider != "ollama" or identity.model != str(self.spec["model"]):
            raise RuntimeError(f"identity pin failed: resolved {identity}")
        if len(vectors[0]) != int(self.spec["dim"]):
            raise RuntimeError(
                f"dim mismatch for {self.spec['model']}: expected {self.spec['dim']}, got {len(vectors[0])}"
            )
        self.resolved_identity = identity
        _load_corpus_into_store(self.docs, vectors)
        return self

    def __exit__(self, *exc: object) -> None:
        from app.retrieval.hybrid import get_store
        from app.retrieval.tuning import reset_retrieval_tuning_cache

        get_store().set_documents(
            [
                {
                    "doc_id": doc.doc_id,
                    "text": doc.text,
                    "language": doc.language,
                    "source_ref": doc.source_ref,
                    "payload": dict(doc.payload or {}),
                    "embedding": doc.embedding,
                }
                for doc in self._prior_docs
            ]
        )
        for key, value in self._prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_retrieval_tuning_cache()

    def ranked(self, query: str, k: int) -> list[str]:
        """Ranked doc ids from the production scoped entrypoint."""
        from app.components.retrieval import embed_query
        from app.retrieval.hybrid import scoped_hybrid_search

        vector, _ = embed_query(query)
        scoped = scoped_hybrid_search(query, k=k, query_vector=vector)
        return [str(hit.get("doc_id") or hit.get("id")) for hit in scoped.results]

    def scored(self, query: str, k: int) -> list[tuple[str, float]]:
        from app.components.retrieval import embed_query
        from app.retrieval.hybrid import scoped_hybrid_search

        vector, _ = embed_query(query)
        scoped = scoped_hybrid_search(query, k=k, query_vector=vector)
        return [
            (str(hit.get("doc_id") or hit.get("id")), float(hit.get("score") or 0.0))
            for hit in scoped.results
        ]


# --------------------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------------------


def score_retrieval(run: IdentityRun) -> dict:
    """recall@k + MRR over the labelled query set, overall and per query class."""
    query_set = load_query_set()
    top_k = max(RECALL_KS)
    per_query: list[dict] = []
    for entry in query_set["queries"]:
        ranked = run.ranked(entry["query"], k=top_k)
        per_query.append(
            {
                "id": entry["id"],
                "class": entry["class"],
                "topic": entry["topic"],
                "gold": entry["gold"],
                "ranked": ranked,
                "recall": {f"@{k}": round(recall_at_k(ranked, entry["gold"], k), 4) for k in RECALL_KS},
                "rr": round(reciprocal_rank(ranked, entry["gold"]), 4),
            }
        )

    def aggregate(rows: Sequence[dict]) -> dict:
        return {
            "n": len(rows),
            "recall": {f"@{k}": _mean([row["recall"][f"@{k}"] for row in rows]) for k in RECALL_KS},
            "mrr": _mean([row["rr"] for row in rows]),
        }

    return {
        "overall": aggregate(per_query),
        "by_class": {
            cls: aggregate([row for row in per_query if row["class"] == cls])
            for cls in QUERY_CLASSES
        },
        "per_query": per_query,
    }


def _proposed_connect_pairs(run: IdentityRun, seed_queries: Sequence[str], *, k: int, floor: float) -> set[frozenset[str]]:
    """The pair set ``run_connect_pass`` would propose, reproduced from its documented shape.

    ``run_connect_pass`` retrieves ``k`` hits per seed query, drops anything below
    ``relatedness_floor``, and emits every unordered pair among the survivors as a
    ``connect.related_unlinked`` finding. Reproducing that here keeps the eval free of a vault root,
    outbox and WriteGuard while scoring exactly the pairs the real pass would surface.
    """
    pairs: set[frozenset[str]] = set()
    for query in seed_queries:
        survivors = [doc_id for doc_id, score in run.scored(query, k=k) if score >= floor]
        for a, b in combinations(sorted(set(survivors)), 2):
            pairs.add(frozenset((a, b)))
    return pairs


def score_connect_precision(run: IdentityRun) -> dict:
    """Connect precision against the hand-labelled SV/EN related-pair set."""
    spec = load_connect_pairs()
    shape = spec["finding_shape"]
    related = {frozenset(pair) for pair in spec["related_pairs"]}
    hard_negatives = {frozenset(pair) for pair in spec["hard_negative_pairs"]}

    proposed = _proposed_connect_pairs(
        run,
        spec["seed_queries"],
        k=int(shape["retrieval_k"]),
        floor=float(shape["relatedness_floor"]),
    )

    true_positives = proposed & related
    hard_negative_hits = proposed & hard_negatives
    precision = len(true_positives) / len(proposed) if proposed else 0.0
    recall = len(true_positives) / len(related) if related else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "proposed_pairs": len(proposed),
        "labelled_related_pairs": len(related),
        "true_positives": len(true_positives),
        "hard_negatives_surfaced": len(hard_negative_hits),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "missed_related_pairs": sorted(sorted(pair) for pair in (related - proposed)),
        "hard_negative_pairs_surfaced": sorted(sorted(pair) for pair in hard_negative_hits),
    }


__all__ = [
    "CORPUS_DIR",
    "EVAL_SCOPE",
    "FIXTURES_DIR",
    "FUSIONS",
    "IDENTITIES",
    "IdentityRun",
    "QUERY_CLASSES",
    "RECALL_KS",
    "SCORECARD_PATH",
    "CorpusDoc",
    "identities_available",
    "load_connect_pairs",
    "load_corpus",
    "load_query_set",
    "load_scorecard",
    "ollama_base_url",
    "ollama_models_available",
    "recall_at_k",
    "reciprocal_rank",
    "score_connect_precision",
    "score_retrieval",
]
