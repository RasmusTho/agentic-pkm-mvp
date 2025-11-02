from __future__ import annotations
import json, time, shutil, hashlib
from pathlib import Path
from typing import Dict, Any
import yaml
from .policy import pick_target as _pick_target
from app.observability.tracing import current_trace_id, span

ROOT = Path().resolve()
VAULT = ROOT / "vault"
EVENTS = VAULT / "_system" / "events"
QUEUE = EVENTS / "promote.queue.jsonl"
LOG   = EVENTS / "promote.log.jsonl"
SETTINGS = ROOT / "vault" / "_system" / "settings" / "system-settings.yaml"

def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def enqueue(path: Path, uuid: str, desired_state: str = "promoted") -> None:
    _append_jsonl(QUEUE, {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trace_id": current_trace_id() or hashlib.sha1(f"{uuid}{path}".encode()).hexdigest()[:12],
        "uuid": uuid,
        "path": str(path),
        "desired_state": desired_state,
        "retries": 0
    })

def _load_settings() -> Dict[str, Any]:
    if not SETTINGS.exists():
        return {}
    return yaml.safe_load(SETTINGS.read_text(encoding="utf-8")) or {}

def _read_frontmatter(p: Path) -> tuple[Dict[str, Any], str]:
    text = p.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    fm = "\n".join(lines[1:end])
    body = "\n".join(lines[end+1:])
    try:
        meta = yaml.safe_load(fm) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}
    return meta, body

def _write_frontmatter(p: Path, meta: Dict[str, Any], body: str) -> None:
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(f"---\n{fm}\n---\n{body.strip()}\n", encoding="utf-8")
    tmp.replace(p)

def _safe_move(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():
        stem, suff = dst.stem, dst.suffix
        i = 1
        while (dst_dir / f"{stem}-{i}{suff}").exists():
            i += 1
        dst = dst_dir / f"{stem}-{i}{suff}"
    shutil.move(str(src), str(dst))
    return dst

def run_once() -> int:
    if not QUEUE.exists():
        return 0
    settings = _load_settings()
    promo = (settings.get("promotion") or {})
    cooldown = int(promo.get("cooldown_seconds", 90))
    idle_req = int(promo.get("require_idle_seconds", 30))
    max_retries = int(promo.get("max_retries", 3))
    move_policy = promo.get("move_policy") or {"enabled": False, "default_target": "2_Cards/Concepts"}

    lines = QUEUE.read_text(encoding="utf-8").splitlines()
    QUEUE.unlink(missing_ok=True)
    processed = 0

    for ln in lines:
        ev: Dict[str, Any] | None = None
        try:
            with span("worker.process_event"):
                ev = json.loads(ln)
                p = Path(ev["path"])
                if not p.exists():
                    _append_jsonl(LOG, {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "level": "warn", "event": "promote.skip.missing", "path": str(p),
                                        "uuid": ev.get("uuid"), "trace_id": current_trace_id()})
                    continue

                st = p.stat()
                age = time.time() - st.st_mtime
                if age < cooldown or age < idle_req:
                    _append_jsonl(QUEUE, ev)
                    continue

                with span("worker.read_frontmatter"):
                    meta, body = _read_frontmatter(p)
                meta = dict(meta)
                meta["review_state"] = ev.get("desired_state", "promoted")

                with span("worker.update_frontmatter"):
                    cleaned_lines = [ln for ln in body.splitlines() if "Promote" not in ln]
                    new_body = "\n".join(cleaned_lines).strip() + ("\n" if cleaned_lines else "")
                    _write_frontmatter(p, meta, new_body)

                new_p = p
                if move_policy.get("enabled", False):
                    with span("worker.move_file"):
                        target_rel = _pick_target(meta, move_policy)
                        target_dir = VAULT / target_rel
                        new_p = _safe_move(p, target_dir)

                with span("worker.log_done"):
                    _append_jsonl(LOG, {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "level": "info", "event": "promote.done",
                                        "uuid": ev.get("uuid"), "from": str(p), "to": str(new_p),
                                        "trace_id": current_trace_id()})
                processed += 1

        except json.JSONDecodeError as e:
            _append_jsonl(LOG, {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "level": "error", "event": "promote.skip.decode",
                                "raw": ln, "err": repr(e), "trace_id": current_trace_id()})
            continue
        except Exception as e:
            payload = ev if isinstance(ev, dict) else {"raw": ln}
            payload["retries"] = int(payload.get("retries", 0)) + 1
            if payload["retries"] <= max_retries:
                _append_jsonl(QUEUE, payload)
            _append_jsonl(LOG, {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "level": "error", "event": "promote.error",
                                "path": payload.get("path"), "uuid": payload.get("uuid"),
                                "err": repr(e), "retries": payload["retries"],
                                "trace_id": current_trace_id()})
    return processed
