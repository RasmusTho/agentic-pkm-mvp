#!/usr/bin/env python3
"""Write the exact BuilderOps image pair proved by the main restore gate."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _digest(value: str) -> str:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("digest must be immutable sha256")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--control-plane-digest", type=_digest, required=True)
    parser.add_argument("--postgres-walg-digest", type=_digest, required=True)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.source_sha) is None:
        parser.error("source SHA must be 40 lowercase hex characters")
    payload = {
        "receipt_version": 1,
        "repository": "RasmusTho/agentic-pkm-mvp",
        "workflow": ".github/workflows/app-image-build.yml",
        "event_name": "push",
        "source_ref": "refs/heads/main",
        "source_sha": args.source_sha,
        "control_plane_image_digest": args.control_plane_digest,
        "postgres_walg_image_digest": args.postgres_walg_digest,
        "restore_gate": "encrypted-full-backup-plus-archived-wal",
        "platform": "linux/amd64",
    }
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
