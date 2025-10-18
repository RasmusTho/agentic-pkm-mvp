from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.agent.graph import invoke


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Agentic PKM LangGraph workflow from the command line."
    )
    parser.add_argument(
        "--task",
        default="summarize",
        help="Task directive for the agent (default: %(default)s).",
    )
    parser.add_argument(
        "--input",
        help="Optional input text for the task. Use '-' to read from stdin.",
    )
    parser.add_argument(
        "--profile",
        default="work",
        choices=["work", "home", "creative"],
        help="Agent profile to use (default: %(default)s).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the invocation payload without executing the agent.",
    )
    return parser.parse_args(argv)


def _resolve_input(value: str | None) -> str | None:
    if value == "-":
        data = sys.stdin.read()
        return data.strip() or None
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    user_input = _resolve_input(args.input)

    if args.dry_run:
        print("Dry run: would invoke agent with:")
        print(f"  task: {args.task}")
        if user_input:
            preview = user_input if len(user_input) <= 120 else f"{user_input[:117]}..."
            print(f"  input: {preview}")
        print(f"  profile: {args.profile}")
        return 0

    try:
        state = invoke(task=args.task, profile=args.profile, input_text=user_input)
    except Exception as exc:  # pragma: no cover - defensive guardrail
        print(f"Agent invocation failed: {exc}", file=sys.stderr)
        return 1

    if state.error:
        print(f"Agent reported error: {state.error}", file=sys.stderr)
        return 1

    print(state.result or "")
    if state.cites:
        print("Sources:", ", ".join(state.cites))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
