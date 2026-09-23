#!/usr/bin/env python3
"""Run one configured subscription-authenticated Model Inquiry perspective."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

_REPOSITORY_ROOT = str(Path(__file__).resolve().parents[1])
if _REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, _REPOSITORY_ROOT)

from app.model_access.codex_cli import (
    CodexCliError,
    CodexCliExecutor,
)

# xhigh subscription turns can spend several minutes in provider-side reasoning
# before producing their structured response. Keep this inner deadline aligned
# with the host wrapper's larger 1500-second bound.
COMMAND_TIMEOUT_SECONDS = 1200
TIMEOUT_EXIT_CODE = 124
# An expired interactive session is not a generic command failure. The parent
# LocalCommandAdapter maps this conventional code to the session_expired
# diagnostic class so the two never collapse into command_exit_nonzero.
SESSION_EXPIRED_EXIT_CODE = 125
CODEX_FAILURE_EXIT_CODES = {
    "command_timeout": TIMEOUT_EXIT_CODE,
    "session_expired": SESSION_EXPIRED_EXIT_CODE,
    "cli_missing": 126,
    "authentication_unavailable": 127,
    "unsupported_profile": 128,
    "cli_version_unsupported": 129,
    "tool_surface_unknown": 130,
    "command_exit_nonzero": 131,
    "stdout_oversize": 132,
    "stdout_empty": 133,
    "schema_violation": 134,
    "input_oversize": 135,
    "model_unavailable": 136,
}
PERSPECTIVES = ("synthesis", "verification")
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
OUTPUT_SCHEMA_REF = "builderops.model-turn-response.v1"


def run_perspective(
    request: Mapping[str, Any],
    perspective: str,
    model: str,
    reasoning_effort: str,
    output_schema_ref: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if output_schema_ref != OUTPUT_SCHEMA_REF:
        raise SystemExit(CODEX_FAILURE_EXIT_CODES["schema_violation"])
    source = dict(environment if environment is not None else os.environ)
    profile_path = source.get("CODEX_CLI_SAFE_PROFILE_PATH", "").strip()
    if not profile_path:
        raise SystemExit(CODEX_FAILURE_EXIT_CODES["unsupported_profile"])

    developer_instructions = (
        str(request["system_prompt"])
        + " Return exactly one JSON object matching the declared response schema. "
        "reviewed_artifact_refs must equal request.reviewed_artifact_refs exactly "
        "(an independent draft therefore uses []). For a draft use stance=draft and "
        "accepted_artifact_hash=null. For a review use stance=accept or revise; if "
        "accepting, accepted_artifact_hash must equal the artifact_hash of one reviewed "
        "input artifact. content must be a plain string, never a nested JSON issue proposal."
        + f"\nInquiry perspective: {perspective}."
    )
    user_request = {
        key: value for key, value in request.items() if key != "system_prompt"
    }
    user_prompt = json.dumps(user_request, ensure_ascii=False, sort_keys=True)
    response_schema = {
        "type": "object",
        "properties": {
            "schema_version": {"const": OUTPUT_SCHEMA_REF},
            "stance": {"enum": ["draft", "accept", "revise", "refuse"]},
            "content": {"type": "string", "minLength": 1},
            "claims": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "blocking_questions": {"type": "array", "items": {"type": "string"}},
            "reviewed_artifact_refs": {
                "type": "array",
                "items": {"type": "string"},
            },
            "accepted_artifact_hash": {"type": ["string", "null"]},
        },
        "required": [
            "schema_version",
            "stance",
            "content",
            "claims",
            "risks",
            "blocking_questions",
            "reviewed_artifact_refs",
            "accepted_artifact_hash",
        ],
        "additionalProperties": False,
    }
    try:
        result = CodexCliExecutor(
            safe_profile_path=Path(profile_path),
            process_group_mode="inherited",
            environment=source,
            execution_timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        ).execute(
            model=model,
            reasoning_effort=reasoning_effort,
            developer_instructions=developer_instructions,
            user_prompt=user_prompt,
            output_schema_ref=output_schema_ref,
            output_schema=response_schema,
        )
    except CodexCliError as exc:
        raise SystemExit(CODEX_FAILURE_EXIT_CODES[exc.failure_code]) from exc
    return _response_from_text(result.response_text)


def _response_from_text(text: str) -> dict[str, Any]:
    try:
        found = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(CODEX_FAILURE_EXIT_CODES["schema_violation"]) from exc
    if not isinstance(found, dict):
        raise SystemExit(CODEX_FAILURE_EXIT_CODES["schema_violation"])
    # Preserve the provider payload exactly. The runner owns all contract,
    # phase, refusal, and reviewed-artifact validation; coercion here could
    # make invalid output look valid and therefore persistable.
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--perspective", required=True, choices=PERSPECTIVES)
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", required=True, choices=REASONING_EFFORTS)
    parser.add_argument("--output-schema-ref", required=True)
    args = parser.parse_args()
    if args.output_schema_ref != OUTPUT_SCHEMA_REF:
        parser.error(f"unsupported output schema reference: {args.output_schema_ref}")
    request = json.load(sys.stdin)
    print(
        json.dumps(
            run_perspective(
                request,
                args.perspective,
                args.model,
                args.reasoning_effort,
                args.output_schema_ref,
            ),
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
