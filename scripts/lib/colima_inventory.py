#!/usr/bin/env python3
"""Read Docker identities without modifying metadata; refuse ambiguous residue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ID = re.compile(r"[0-9a-f]{64}")


def scan(root: Path) -> dict[str, list[str]]:
    required, terminal = [], []
    for entry in sorted(root.iterdir()):
        if entry.is_symlink() or not entry.is_dir() or not ID.fullmatch(entry.name):
            raise ValueError("invalid container directory")
        if any((entry / name).is_symlink() for name in ("config.v2.json", "hostconfig.json")):
            raise ValueError("symlinked container metadata")
        config = json.loads((entry / "config.v2.json").read_text())
        host = json.loads((entry / "hostconfig.json").read_text())
        if config["ID"] != entry.name:
            raise ValueError("container identity mismatch")
        state = config["State"]
        for value in (
            state["Dead"],
            state["Running"],
            config["HasBeenStartedBefore"],
            host["AutoRemove"],
        ):
            if type(value) is not bool:
                raise ValueError("ambiguous container state")
        restart = host["RestartPolicy"]["Name"]
        if restart not in ("", "no", "always", "unless-stopped", "on-failure"):
            raise ValueError("unknown restart policy")
        residue = (
            host["AutoRemove"]
            and state["Dead"]
            and not state["Running"]
            and not config["HasBeenStartedBefore"]
            and restart in ("", "no")
        )
        if residue:
            mounts = config["MountPoints"]
            if not isinstance(mounts, dict):
                raise ValueError("ambiguous mount associations")
            for mount in mounts.values():
                kind = mount["Type"]
                if kind == "volume":
                    if not isinstance(mount["Spec"]["Source"], str) or not mount["Spec"]["Source"]:
                        raise ValueError("terminal residue has anonymous volume")
                elif kind not in ("bind", "tmpfs"):
                    raise ValueError("unknown terminal mount type")
            terminal.append(entry.name)
        else:
            required.append(entry.name)
    return {"required": required, "terminal": terminal}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()
    try:
        if args.compare:
            payload = json.loads(sys.stdin.readline())
            actual = sys.stdin.read().splitlines()
            if any(not ID.fullmatch(item) for item in actual) or len(set(actual)) != len(actual):
                raise ValueError("invalid API inventory")
            required, terminal = set(payload["required"]), set(payload["terminal"])
            # Docker may already have removed terminal AutoRemove residue, or may
            # still expose it. Required identities must all exist; no others may.
            if not required <= set(actual) <= required | terminal:
                raise ValueError("required inventory identity mismatch")
        else:
            if args.root is None:
                raise ValueError("missing root")
            print(json.dumps(scan(args.root), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError):
        print("inventory refused: unreadable, ambiguous, or mismatched identities", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
