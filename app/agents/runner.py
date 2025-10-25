from __future__ import annotations
import argparse, json
from app.agents.normalizer.graph import invoke as normalize_invoke

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--agent", required=True)
    p.add_argument("--path")
    p.add_argument("--trace-id", required=True)
    args = p.parse_args()
    if args.agent == "normalizer":
        out = normalize_invoke(args.path, trace_id=args.trace_id)
    else:
        raise SystemExit(f"unknown agent {args.agent}")
    print(json.dumps(out))

if __name__ == "__main__":
    main()