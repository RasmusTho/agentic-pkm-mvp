from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from app.services.capture_indexer import index_capture_bundle


INBOX_DIR = Path("vault/@Inbox")
INBOX_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class CaptureBundle:
    bundle_id: str
    summary: str
    tasks: List[Dict[str, str]]
    decisions: List[str]
    entities: List[Dict[str, str]]
    raw: str


def naive_parse(raw: str) -> CaptureBundle:
    """
    Rule-based capture triage.
    """
    lines = [l.rstrip() for l in raw.strip().splitlines()]
    summary_lines: list[str] = []
    tasks: list[dict[str, str]] = []
    decisions: list[str] = []

    for line in lines:
        if line.strip().startswith("- [ ]"):
            body = line.strip()[5:].strip()
            owner = "Rasmus"
            tasks.append({"text": body, "owner": owner})
        elif line.lower().startswith("beslut:"):
            decisions.append(line.split(":", 1)[1].strip())
        else:
            summary_lines.append(line)

    entities: list[dict[str, str]] = []
    for word in "Demerzel OPNsense Jaeger Tracing VLAN IoT NVR".split():
        if word in raw:
            entities.append({"name": word, "type": "entity"})

    summary = " ".join(summary_lines).strip()

    cap_id = f"cap-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    return CaptureBundle(
        bundle_id=cap_id,
        summary=summary,
        tasks=tasks,
        decisions=decisions,
        entities=entities,
        raw=raw,
    )


def write_capture_file(bundle: CaptureBundle) -> Path:
    note_path = INBOX_DIR / f"{bundle.bundle_id}.md"
    with note_path.open("w", encoding="utf-8") as f:
        f.write(f"---\n")
        f.write(f"uuid: {bundle.bundle_id}\n")
        f.write("kind: capture\n")
        f.write("review_state: inbox\n")
        f.write("---\n\n")

        f.write("## Summary\n")
        f.write(bundle.summary.strip() + "\n\n")

        f.write("## Tasks\n")
        for t in bundle.tasks:
            f.write(f"- [ ] {t['text']} @{t['owner']}\n")
        f.write("\n")

        f.write("## Decisions\n")
        for d in bundle.decisions:
            f.write(f"- {d}\n")
        f.write("\n")

        f.write("## Entities\n")
        for e in bundle.entities:
            f.write(f"- [[{e['name']}]] ({e['type']})\n")
        f.write("\n")

        f.write("## Raw capture\n")
        f.write("```text\n")
        f.write(bundle.raw.strip() + "\n")
        f.write("```\n")

    return note_path


def main(argv: list[str]) -> int:
    raw_input = sys.stdin.read()
    bundle = naive_parse(raw_input)

    # 1. skriv fil till vault
    note_path = write_capture_file(bundle)

    # 2. indexera i DB
    index_capture_bundle(asdict(bundle))

    print(note_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
