from __future__ import annotations
import hashlib, json, os, sys, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

import yaml

from app.vault.paths import get_vault_inbox_dir_rel

ROOT = Path(__file__).resolve().parents[2]
VAULT = ROOT / "vault"
INBOX_BASE = VAULT / get_vault_inbox_dir_rel(VAULT) / "Samples"
EVENT_LOG = VAULT / "_system" / "events" / "ingest.log.jsonl"
SETTINGS = ROOT / "vault" / "_system" / "settings" / "system-settings.yaml"

@dataclass
class IngestResult:
    src: Path
    dst: Path
    status: str
    note: str
    uuid: str


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_frontmatter(text: str) -> Tuple[Dict, str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end_idx = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end_idx is None:
        return {}, text
    fm = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    try:
        meta = yaml.safe_load(fm) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}
    return meta, body


def _write_md(path: Path, meta: Dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    text = f"---\n{fm}\n---\n{body.strip()}\n"
    path.write_text(text, encoding="utf-8")


def _ensure_uuid(meta: Dict) -> Tuple[Dict, str]:
    u = meta.get("uuid") or uuid.uuid4().hex.upper()
    meta["uuid"] = u
    return meta, u


def _log_event(ev: Dict) -> None:
    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def ingest_md(src: Path, rel: Path) -> IngestResult:
    text = src.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)
    meta.setdefault("title", src.stem)
    meta.setdefault("origin", "imported")
    meta.setdefault("trust", "external")
    meta["review_state"] = "inbox"
    meta, u = _ensure_uuid(meta)
    meta.setdefault("source_ref", f"file://{src}")

    dst = INBOX_BASE / rel
    _write_md(dst, meta, body)
    return IngestResult(src, dst, "imported", "markdown", u)


def ingest_binary(src: Path, rel: Path) -> IngestResult:
    data = src.read_bytes()
    h = _sha256_bytes(data)
    attach = INBOX_BASE / "_attachments" / rel
    attach.parent.mkdir(parents=True, exist_ok=True)
    attach.write_bytes(data)

    meta: Dict = {
        "title": src.name,
        "origin": "imported",
        "trust": "external",
        "review_state": "inbox",
        "source_ref": f"file://{src}",
        "attachment_sha256": h,
        "attachment_path": str(Path("_attachments") / rel),
    }
    meta, u = _ensure_uuid(meta)
    note_body = f"Attachment imported from samples.\n\nSHA256: `{h}`\n"
    md_rel = rel.with_suffix(".md")
    dst = INBOX_BASE / md_rel
    _write_md(dst, meta, note_body)
    return IngestResult(src, dst, "imported", "attachment", u)


def main():
    samples_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples"
    if not samples_root.exists():
        print(f"Samples path not found: {samples_root}", file=sys.stderr)
        sys.exit(2)

    settings = yaml.safe_load(SETTINGS.read_text(encoding="utf-8"))
    trace_id = uuid.uuid4().hex
    count = 0
    for src in samples_root.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(samples_root)
        try:
            if src.suffix.lower() == ".md":
                res = ingest_md(src, rel)
            else:
                res = ingest_binary(src, rel)
        except Exception as exc:
            print(f"Error ingesting {src}: {exc}", file=sys.stderr)
            continue
        count += 1
        _log_event(
            {
                "event": "ingest.sample",
                "timestamp": _now_iso(),
                "trace_id": trace_id,
                "payload": {
                    "src": str(res.src),
                    "dst": str(res.dst),
                    "status": res.status,
                    "note": res.note,
                    "uuid": res.uuid,
                },
            }
        )

    print(f"Ingested {count} files into {INBOX_BASE}")


if __name__ == "__main__":
    main()
