#!/usr/bin/env python3
"""Prove a candidate PR body restores exactly the authenticated pre-merge body.

Read-only. Consume the restoration payload written by
``scripts/resolve_neutralized_body_restoration.py --output-json`` and a candidate
body file, and exit ``0`` only when the candidate reproduces the durable
receipt's original-body digest and its governing and closing identities.

This exists so restoring a stranded neutralization is an executable proof rather
than a hand-edit. A hand-edited body is exactly what strands a neutralization in
the first place.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.dispatcher.verified_merge import restored_body_matches_authority


def _restoration(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    # Accept either the resolver payload or the bare restoration it wraps.
    nested = value.get("restoration")
    if isinstance(nested, dict):
        return nested
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restoration-json", type=Path, required=True)
    parser.add_argument("--restored-body-file", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    restoration = _restoration(args.restoration_json)
    body = args.restored_body_file.read_text(encoding="utf-8")
    matches = restored_body_matches_authority(body, restoration=restoration)
    print(
        json.dumps(
            {
                "restore_body_sha256": restoration.get("restore_body_sha256"),
                "restored_body_matches_authority": matches,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
