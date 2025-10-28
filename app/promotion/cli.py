from __future__ import annotations

import argparse
from pathlib import Path

from .queue import enqueue, run_once


def main() -> None:
    parser = argparse.ArgumentParser(prog="promotion")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    queue_parser = subparsers.add_parser("queue")
    queue_parser.add_argument("path")
    queue_parser.add_argument("uuid")
    queue_parser.add_argument("--state", default="promoted")

    subparsers.add_parser("run")

    args = parser.parse_args()
    if args.cmd == "queue":
        enqueue(Path(args.path), uuid=args.uuid, desired_state=args.state)
    elif args.cmd == "run":
        run_once()


if __name__ == "__main__":
    main()
