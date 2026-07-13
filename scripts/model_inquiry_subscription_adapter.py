#!/usr/bin/env python3
"""Run one subscription-authenticated Model Inquiry role with a bounded high-effort profile."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping

COMMAND_TIMEOUT_SECONDS = 540
TIMEOUT_EXIT_CODE = 124
FABLE_MODEL = "claude-fable-5"
CODEX_MODEL = "gpt-5.6-sol"
RESPONSE_FIELDS = (
    "schema_version",
    "stance",
    "content",
    "claims",
    "risks",
    "blocking_questions",
    "reviewed_artifact_refs",
    "accepted_artifact_hash",
)


def build_argv(role: str, strict_prompt: str) -> list[str]:
    if role == "fable":
        return [
            _command_path("claude"),
            "-p",
            "--no-session-persistence",
            "--model",
            FABLE_MODEL,
            "--effort",
            "xhigh",
            "--output-format",
            "text",
            "--permission-mode",
            "bypassPermissions",
            "--system-prompt",
            strict_prompt,
            "--tools",
            "",
        ]
    if role == "gpt_codex":
        return [
            _command_path("codex"),
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "-c",
            'model_reasoning_effort="xhigh"',
            "--model",
            CODEX_MODEL,
            "--sandbox",
            "read-only",
            "-",
        ]
    raise ValueError("INQUIRY_ROLE must be fable or gpt_codex")


def _command_path(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"configured {name} command is unavailable")
    return path


def run_role(request: Mapping[str, Any], role: str) -> dict[str, Any]:
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
    prompt = json.dumps(request, ensure_ascii=False, sort_keys=True)
    if role == "gpt_codex":
        prompt = strict_prompt + "\nCanonical request JSON:\n" + prompt
    try:
        result = subprocess.run(
            build_argv(role, strict_prompt),
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
        raise SystemExit(result.returncode)
    return _response_from_text(result.stdout, request)


def _response_from_text(text: str, request: Mapping[str, Any]) -> dict[str, Any]:
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
    response = {key: found.get(key) for key in RESPONSE_FIELDS}
    for field in ("claims", "risks", "blocking_questions", "reviewed_artifact_refs"):
        values = response.get(field)
        if isinstance(values, list):
            response[field] = [
                item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)
                for item in values
            ]
        elif isinstance(values, str) and values.strip():
            response[field] = [values]
        else:
            response[field] = []
    response["reviewed_artifact_refs"] = request["reviewed_artifact_refs"]
    if request["phase"] == "draft":
        response["stance"] = "draft"
        response["accepted_artifact_hash"] = None
    return response


def main() -> int:
    request = json.load(sys.stdin)
    role = os.environ.get("INQUIRY_ROLE", "")
    print(json.dumps(run_role(request, role), ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
