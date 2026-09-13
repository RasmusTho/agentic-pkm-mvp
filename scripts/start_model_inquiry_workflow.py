#!/usr/bin/env python3
"""Manual entrypoint to the single executable start-model-inquiry skill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Direct documented script invocation must work without a PYTHONPATH override.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.builderops.model_inquiry_workflow import SanctionedModelInquiryWorkflow  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = SanctionedModelInquiryWorkflow().manual(args.question_file)
    except Exception:
        sys.stderr.write("sanctioned Model Inquiry workflow unavailable\n")
        return 1
    print(json.dumps(result.get("terminal_receipt", result), ensure_ascii=False, sort_keys=True))
    if result.get("workflow_cleanup") == "failed" or result.get("caller_cleanup"):
        sys.stderr.write("Model Inquiry cleanup requires reconciliation\n")
    return 0 if result.get("state") == "terminal" else 1


if __name__ == "__main__":
    raise SystemExit(main())
