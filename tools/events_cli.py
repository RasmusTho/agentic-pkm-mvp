import json, sys, collections, datetime, pathlib, argparse

def load(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def summarize(recs):
    by_day = collections.defaultdict(lambda: collections.Counter())
    for r in recs:
        ts = r.get("ts","")[:10]
        t = r.get("topic","")
        by_day[ts][t] += 1
    lines = []
    for day in sorted(by_day):
        cnt = by_day[day]
        lines.append(f"{day}: " + ", ".join(f"{k}={v}" for k,v in sorted(cnt.items())))
    return "\n".join(lines)

def tail(recs, n):
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in recs[-n:])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="events.jsonl")
    ap.add_argument("--mode", choices=["summary","tail"], default="summary")
    ap.add_argument("-n", type=int, default=20)
    args = ap.parse_args()
    recs = load(args.file)
    if args.mode == "summary":
        print(summarize(recs))
    else:
        print(tail(recs, args.n))
