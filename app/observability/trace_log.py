import json, os, time
LOG_PATH = os.getenv("TRACE_LOG_PATH", "/tmp/trace.jsonl")
def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def log_span(name: str, trace_id: str, attrs: dict | None = None):
    rec = {"ts": _now_iso(), "span": name, "trace_id": trace_id, "attrs": attrs or {}}
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(rec) + "\n")
