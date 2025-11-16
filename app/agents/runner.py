from __future__ import annotations
import argparse, json
from app.agents.normalizer.graph import invoke as normalize_invoke
from app.agents.classifier.graph import invoke as classify_invoke
from app.agents.chunker.graph import invoke as chunk_invoke
from app.agents.deduper.graph import invoke as dedupe_invoke
from app.agents.reviewer.graph import invoke as review_invoke
from app.agents.set_evaluator.graph import invoke as evaluate_invoke
from app.agents.projector.graph import invoke as projector_invoke
from app.jobs.backfill import run_backfill

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
    p.add_argument("--set-name", default="published")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--dry-run", action="store_true")
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
    elif args.agent == "set_evaluator":
        out = evaluate_invoke(args.object_id, trace_id=args.trace_id, threshold=args.threshold)
    elif args.agent == "projector":
        out = projector_invoke(args.object_id, trace_id=args.trace_id, set_name=args.set_name)
    elif args.agent == "backfill":
        summary = run_backfill(
            trace_id=args.trace_id,
            limit=args.limit,
            set_name=args.set_name,
            dry_run=args.dry_run,
        )
        out = {
            "event": JOBS_BACKFILL_DONE,
            "summary": {
                "chunked": summary.chunked,
                "indexed": summary.indexed,
                "reviewed": summary.reviewed,
                "evaluated": summary.evaluated,
                "projected": summary.projected,
                "dry_run": args.dry_run,
            },
        }
    else:
        raise SystemExit(f"unknown agent {args.agent}")

    print(json.dumps(out))

if __name__ == "__main__":
    main()
