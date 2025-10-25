from __future__ import annotations
import argparse, json
from app.agents.normalizer.graph import invoke as normalize_invoke
from app.agents.classifier.graph import invoke as classify_invoke
from app.agents.chunker.graph import invoke as chunk_invoke
from app.agents.deduper.graph import invoke as dedupe_invoke
from app.agents.reviewer.graph import invoke as review_invoke

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--agent", required=True)
    p.add_argument("--path")
    p.add_argument("--object-id")
    p.add_argument("--trace-id", required=True)
    p.add_argument("--max-tokens", type=int, default=800)
    p.add_argument("--overlap", type=int, default=120)
    p.add_argument("--strategy", default="heading_first")
    p.add_argument("--threshold", type=float, default=0.92)
    args = p.parse_args()

    if args.agent == "normalizer":
        out = normalize_invoke(args.path, trace_id=args.trace_id)
    elif args.agent == "classifier":
        out = classify_invoke(args.object_id, trace_id=args.trace_id)
    elif args.agent == "chunker":
        out = chunk_invoke(args.object_id, trace_id=args.trace_id, max_tokens=args.max_tokens, overlap=args.overlap, strategy=args.strategy)
    elif args.agent == "deduper":
        ids = [x for x in (args.object_id or "").split(",") if x]
        out = dedupe_invoke(ids, trace_id=args.trace_id, threshold=args.threshold)
    elif args.agent == "reviewer":
        out = review_invoke(args.object_id, trace_id=args.trace_id, threshold=args.threshold)
    else:
        raise SystemExit(f"unknown agent {args.agent}")

    print(json.dumps(out))

if __name__ == "__main__":
    main()
