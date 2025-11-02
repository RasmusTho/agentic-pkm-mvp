import os, json, pathlib, argparse, textwrap, hashlib
OUTDIR = pathlib.Path("MergePrompts")

def load_events(path="events.jsonl"):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try:
                yield json.loads(line)
            except Exception:
                continue

def render_prompt(i, rec):
    payload = rec.get("payload",{})
    reason = payload.get("reason","")
    parents = payload.get("parents",[])
    h = payload.get("hash",{})
    meta = f"reason: {reason}\nparents: {parents}\ncontent_hash: {h.get('content_hash','')}"
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
    fname = OUTDIR / f"merge_prompt_{rec.get('ts','')[:10]}_{digest}.md"
    body = f"""---
trace_id: {rec.get('trace_id')}
topic: merge.prompt
ts: {rec.get('ts')}
{meta}
---

# Merge prompt

System recommends manual choice (A/B/HYBRID). See details in payload above.

## Option A (current)
<insert local snippet during real integration>

## Option B (other)
<insert remote snippet during real integration>

## Suggested action
- [ ] Accept A
- [ ] Accept B
- [ ] Hybrid (edit below)

### Hybrid draft
"""
    fname.write_text(body, encoding="utf-8")
    return fname

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="events.jsonl")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    created = []
    for i, rec in enumerate(load_events(ap.parse_args().file)):
        if rec.get("topic") == "merge.prompt":
            created.append(render_prompt(i, rec))
    print("\n".join(str(p) for p in created) if created else "no merge.prompt events")
