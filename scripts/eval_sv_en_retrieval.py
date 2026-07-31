#!/usr/bin/env python3
"""Reproducible scorecard runner for the SV/EN retrieval eval (G3-2, #2985).

Runs the hand-labelled SV/EN query set and the connect-precision pair set against the live app
retrieval path under both embedding identities, and writes the scorecard the eval note cites.

Two axes, deliberately not crossed into a full matrix:

* **identity comparison** — ``nomic-embed-text``@768 vs ``bge-m3``@1024 with fusion held fixed at the
  shipped default (``linear``), so the embedding identity is the only moving part. This is the
  comparison owner ruling R2 asked for: the eval validates the migration after the fact.
* **fusion comparison** — ``linear`` vs ``rrf`` on the shipped identity (``bge-m3``), which is the
  evidence the G5 default-fusion recommendation needs.

Requires an Ollama host with both models pulled:

    ollama pull nomic-embed-text
    ollama pull bge-m3
    python3 scripts/eval_sv_en_retrieval.py

Writes ``tests/evals/fixtures/sv_en_retrieval/scorecard.json``. It measures retrieval; it never
changes it, touches a vault, or writes outside that one file.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.evals.sv_en_retrieval import (  # noqa: E402
    IDENTITIES,
    SCORECARD_PATH,
    IdentityRun,
    load_connect_pairs,
    load_corpus,
    load_query_set,
    ollama_models_available,
    score_connect_precision,
    score_retrieval,
)

#: (identity, fusion) configurations the scorecard records, and why each one is in the set.
RUNS: tuple[tuple[str, str, str], ...] = (
    ("nomic", "linear", "identity comparison baseline (pre-migration snapshot)"),
    ("bge_m3", "linear", "identity comparison candidate + shipped default configuration"),
    ("bge_m3", "rrf", "fusion comparison arm for the G5 default recommendation"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=SCORECARD_PATH,
        help="scorecard destination (default: the committed fixture scorecard)",
    )
    parser.add_argument(
        "--stamp",
        default=None,
        help="ISO date recorded as run_date; omit to leave it unset rather than invent one",
    )
    args = parser.parse_args()

    available = ollama_models_available()
    missing = [str(spec["model"]) for spec in IDENTITIES.values() if str(spec["model"]) not in available]
    if missing:
        print(f"ERROR: Ollama host is missing required models: {', '.join(missing)}", file=sys.stderr)
        print("Pull them first: ollama pull nomic-embed-text && ollama pull bge-m3", file=sys.stderr)
        return 2

    corpus = load_corpus()
    query_set = load_query_set()
    pair_set = load_connect_pairs()

    results: dict[str, dict] = {}
    for identity_key, fusion, rationale in RUNS:
        label = f"{identity_key}/{fusion}"
        print(f"running {label} ...", file=sys.stderr)
        with IdentityRun(identity_key, fusion) as run:
            results[label] = {
                "identity": {
                    "key": identity_key,
                    "model": str(IDENTITIES[identity_key]["model"]),
                    "dim": int(IDENTITIES[identity_key]["dim"]),
                },
                "fusion": fusion,
                "rationale": rationale,
                "retrieval": score_retrieval(run),
                "connect_precision": score_connect_precision(run),
            }

    scorecard = {
        "schema": "sv_en_retrieval_scorecard.v1",
        "issue": 2985,
        "slice": "G3-2",
        "run_date": args.stamp,
        "runner": "scripts/eval_sv_en_retrieval.py",
        "host": {"python": platform.python_version(), "platform": platform.platform()},
        "corpus": {
            "docs": len(corpus),
            "sv_docs": sum(1 for doc in corpus if doc.lang == "sv"),
            "en_docs": sum(1 for doc in corpus if doc.lang == "en"),
            "topics": sorted({doc.topic for doc in corpus}),
        },
        "query_set": {
            "queries": len(query_set["queries"]),
            "by_class": {
                cls: sum(1 for q in query_set["queries"] if q["class"] == cls)
                for cls in sorted({q["class"] for q in query_set["queries"]})
            },
        },
        "connect_pair_set": {
            "related_pairs": len(pair_set["related_pairs"]),
            "hard_negative_pairs": len(pair_set["hard_negative_pairs"]),
            "seed_queries": len(pair_set["seed_queries"]),
        },
        "runs": results,
    }

    args.output.write_text(json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
