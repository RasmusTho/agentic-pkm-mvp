#!/usr/bin/env python3
"""Run one headless Model Inquiry role turn through a declared provider API.

This is the installed headless role entrypoint. It requires no interactive
subscription session: provider, model, and endpoint are resolved from the
declared provider census, and the credential is resolved through the host secret
contract. A declared credential that is absent or unusable fails the process
closed while naming only its logical identifier.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.builderops.model_inquiry_adapters import (  # noqa: E402
    ROLE_NAMES,
    AdapterExecutionError,
    AdapterUnavailableError,
    CredentialUnavailableError,
    load_adapters,
)
from app.builderops.models import BuilderOpsValidationError  # noqa: E402

CREDENTIAL_UNAVAILABLE_EXIT_CODE = 1
CONFIGURATION_EXIT_CODE = 2
EXECUTION_EXIT_CODE = 3


def run_role(role: str, request: object) -> str:
    """Execute one turn for *role* and return the provider response text."""
    if role not in ROLE_NAMES:
        raise BuilderOpsValidationError("--role must name a declared inquiry role")
    if not isinstance(request, dict):
        raise BuilderOpsValidationError("role adapter request must be a JSON object")
    adapters = load_adapters()
    return adapters[role].execute(request).response_text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=ROLE_NAMES)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("ERROR: role adapter stdin is not valid JSON", file=sys.stderr)
        return CONFIGURATION_EXIT_CODE
    try:
        print(run_role(args.role, request), flush=True)
    except CredentialUnavailableError as exc:
        print(
            "ERROR: declared credential unavailable: "
            f"{exc.credential_identity_ref}",
            file=sys.stderr,
        )
        return CREDENTIAL_UNAVAILABLE_EXIT_CODE
    except (AdapterUnavailableError, BuilderOpsValidationError) as exc:
        print(f"ERROR: role adapter is unavailable: {exc}", file=sys.stderr)
        return CONFIGURATION_EXIT_CODE
    except AdapterExecutionError as exc:
        print(f"ERROR: role adapter execution failed: {exc}", file=sys.stderr)
        return EXECUTION_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
