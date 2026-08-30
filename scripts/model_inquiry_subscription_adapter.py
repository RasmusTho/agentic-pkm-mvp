#!/usr/bin/env python3
"""Run one configured subscription-authenticated Model Inquiry perspective."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping

# xhigh subscription turns can spend several minutes in provider-side reasoning
# before producing their structured response. Keep this inner deadline aligned
# with the host wrapper's larger 1500-second bound.
COMMAND_TIMEOUT_SECONDS = 1200
TIMEOUT_EXIT_CODE = 124
# An expired interactive session is not a generic command failure. The parent
# LocalCommandAdapter maps this conventional code to the session_expired
# diagnostic class so the two never collapse into command_exit_nonzero.
SESSION_EXPIRED_EXIT_CODE = 125
SESSION_EXPIRED_MARKERS = (
    "please run /login",
    "please log in",
    "not logged in",
    "session expired",
    "session has expired",
    "authentication required",
    "unauthorized",
    "invalid credentials",
)
PERSPECTIVES = ("synthesis", "verification")


def build_argv(model: str) -> list[str]:
    return [
        _command_path("codex"),
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "-c",
        'model_reasoning_effort="xhigh"',
        "--model",
        model,
        "--sandbox",
        "read-only",
        "-",
    ]


def _command_path(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"configured {name} command is unavailable")
    return path


def run_perspective(
    request: Mapping[str, Any],
    perspective: str,
    model: str,
) -> dict[str, Any]:
    strict_prompt = (
        str(request["system_prompt"])
        + " Return exactly these top-level keys and no others: schema_version, stance, content, "
        "claims, risks, blocking_questions, reviewed_artifact_refs, accepted_artifact_hash. Use "
        "schema_version=builderops.model-turn-response.v1. reviewed_artifact_refs must equal "
        "request.reviewed_artifact_refs exactly (an independent draft therefore uses []). For a "
        "draft use stance=draft and accepted_artifact_hash=null. For a review use stance=accept "
        "or revise; if accepting, accepted_artifact_hash must equal the artifact_hash of one of "
        "the reviewed input artifacts. content must be a plain string, never a nested JSON issue "
        "proposal."
    )
    prompt = (
        strict_prompt
        + f"\nInquiry perspective: {perspective}."
        + "\nCanonical request JSON:\n"
        + json.dumps(request, ensure_ascii=False, sort_keys=True)
    )
    try:
        result = subprocess.run(
            build_argv(model),
            input=prompt,
            text=True,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # The parent LocalCommandAdapter maps this conventional timeout exit
        # code to its closed, receipt-safe command_timeout diagnostic class.
        raise SystemExit(TIMEOUT_EXIT_CODE) from exc
    if result.returncode:
        if _is_expired_session(result.stderr) or _is_expired_session(result.stdout):
            raise SystemExit(SESSION_EXPIRED_EXIT_CODE)
        raise SystemExit(result.returncode)
    return _response_from_text(result.stdout)


def _is_expired_session(text: str) -> bool:
    """Classify an interactive session failure without echoing provider output."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in SESSION_EXPIRED_MARKERS)


def _response_from_text(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    found: dict[str, Any] | None = None
    for match in re.finditer(r"\{", text.strip()):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("schema_version") == "builderops.model-turn-response.v1":
            found = value
    if found is None:
        raise SystemExit("model did not return a schema-valid response")
    # Preserve the provider payload exactly. The runner owns all contract,
    # phase, refusal, and reviewed-artifact validation; coercion here could
    # make invalid output look valid and therefore persistable.
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--perspective", required=True, choices=PERSPECTIVES)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    request = json.load(sys.stdin)
    print(
        json.dumps(
            run_perspective(request, args.perspective, args.model),
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
