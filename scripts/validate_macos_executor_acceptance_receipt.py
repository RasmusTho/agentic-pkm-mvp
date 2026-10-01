#!/usr/bin/env python3
"""Validate a sanitized MARR v3 receipt against an independently supplied route."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import NoReturn, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.model_access.macos_acceptance import (  # noqa: E402
    ReceiptValidationError,
    validate_acceptance_receipt,
)

_MAX_RECEIPT_BYTES = 128_000
_MAX_EXPECTED_ROUTE_BYTES = 16_000


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        print("arguments_invalid", file=sys.stderr)
        raise SystemExit(2)


def _read_bounded(path: Path, limit: int) -> bytes | None:
    try:
        with path.open("rb") as source:
            payload = source.read(limit + 1)
    except OSError:
        return None
    return None if len(payload) > limit else payload


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="sanitized receipt JSON")
    parser.add_argument(
        "--expected-route",
        required=True,
        type=Path,
        help="local JSON with exact route, catalog hash, executor profile, and path profiles",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt_payload = _read_bounded(args.input, _MAX_RECEIPT_BYTES)
    if receipt_payload is None:
        print("receipt_invalid")
        return 2

    expected_payload = _read_bounded(args.expected_route, _MAX_EXPECTED_ROUTE_BYTES)
    if expected_payload is None:
        print("expected_route_invalid")
        return 2

    try:
        result = validate_acceptance_receipt(receipt_payload, expected_payload)
    except ReceiptValidationError as exc:
        print(exc.code)
        return 2

    if result.status == "incomplete":
        missing = ",".join(result.missing_prerequisites)
        print(f"incomplete missing={missing}")
        return 1

    print("passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
