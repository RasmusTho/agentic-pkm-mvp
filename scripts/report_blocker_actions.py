#!/usr/bin/env python3
"""Read-only REST intake for the canonical blocked-action queues."""
from __future__ import annotations

import argparse
import json
import subprocess

from app.builderops.blocker_actions import intake


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be 1..100")
    owner, name = args.repo.split("/", 1)
    command = ["gh", "api", f"repos/{owner}/{name}/issues", "--method", "GET", "-f", "state=open", "-F", f"per_page={args.limit}"]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    print(json.dumps(intake(json.loads(result.stdout)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
