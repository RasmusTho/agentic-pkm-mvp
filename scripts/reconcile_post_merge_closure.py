#!/usr/bin/env python3
"""Classify and recover bounded post-merge closure evidence.

This entrypoint is deliberately a pure artifact producer.  It never writes
GitHub state and it never treats incomplete evidence as terminal.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.build_closure_dispatch_request import build_request


MAX_LOOKBACK_DAYS = 31
MAX_PAGES = 3
MAX_REQUESTS = 30
MAX_ITEMS_PER_PAGE = 100
MAX_BACKOFF_ATTEMPTS = 3
MAX_BACKOFF_SECONDS = 300
CURSOR_VERSION = "closure-reconcile-cursor.v1"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _items(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [_dict(item) for item in value if isinstance(item, Mapping)]


def _merged(pr: Mapping[str, object]) -> bool:
    return pr.get("merged") is True or (
        pr.get("state") == "closed" and isinstance(pr.get("merged_at"), str) and bool(pr.get("merged_at"))
    )


def _merge_sha(pr: Mapping[str, object]) -> str:
    value = pr.get("merge_commit_sha")
    if isinstance(value, str):
        return value
    merge = pr.get("merge_commit")
    return _dict(merge).get("sha", "") if isinstance(_dict(merge).get("sha"), str) else ""


def _receipt_matches(receipt: object, *, repository: str, pr_number: int, merge_sha: str) -> bool:
    data = _dict(receipt)
    return (
        data.get("contract") in {"closure_delivery_receipt.v1", "autonomous_pr_closure_receipt.v1"}
        and data.get("repository") == repository
        and data.get("pr_number") == pr_number
        and data.get("merge_sha") == merge_sha
        and data.get("status") in {"complete", "terminal", "reconciled"}
    )


def classify_pending(
    *,
    pr: Mapping[str, object],
    issue_evidence: Sequence[Mapping[str, object]] = (),
    authoritative_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Classify one merged PR from explicit evidence.

    A complete receipt is terminal only when its identity matches the merged
    PR. Missing, unavailable, malformed, or conflicting evidence is pending.
    """

    repository_value = pr.get("repository")
    repository = repository_value if isinstance(repository_value, str) else ""
    if isinstance(repository_value, Mapping):
        repository = str(repository_value.get("full_name") or repository_value.get("name_with_owner") or "")
    if not repository:
        repository = str(_dict(pr.get("base")).get("repository") or "")
    if not repository:
        repository = str(_dict(pr.get("base")).get("repo") or "")
    number = pr.get("number")
    merge_sha = _merge_sha(pr)
    evidence = _dict(authoritative_evidence)
    receipts = evidence.get("receipts", pr.get("receipts", []))
    if "closure_receipt" in evidence and receipts in (None, []):
        receipts = [evidence.get("closure_receipt")]
    if "closure_receipt" in pr and receipts in (None, []):
        receipts = [pr.get("closure_receipt")]
    if not (_merged(pr) and isinstance(number, int) and number > 0 and _SHA.fullmatch(merge_sha)):
        return {"status": "unknown", "reason": "merged PR identity is missing or malformed"}
    if not isinstance(repository, str) or not repository:
        return {"status": "unknown", "reason": "repository identity is missing"}
    if evidence.get("conflict") is True or pr.get("evidence_conflict") is True:
        return {"status": "merged_closure_pending", "reason": "conflicting authority evidence"}
    if evidence.get("unavailable") is True or pr.get("evidence_unavailable") is True:
        return {"status": "merged_closure_pending", "reason": "authoritative evidence unavailable"}
    if isinstance(receipts, list) and any(
        _receipt_matches(item, repository=repository, pr_number=number, merge_sha=merge_sha)
        for item in receipts
    ):
        return {"status": "complete", "reason": "matching terminal closure receipt"}
    if receipts not in ([], None) and not isinstance(receipts, list):
        return {"status": "merged_closure_pending", "reason": "receipt evidence unavailable"}
    issues = list(issue_evidence)
    if any(item.get("repository") not in (None, repository) for item in issues):
        return {"status": "merged_closure_pending", "reason": "foreign issue evidence"}
    # Direct-repair and Issue deliveries need a PR-specific receipt. Closed
    # Issues alone are intentionally insufficient proof of terminal delivery.
    if any(item.get("state") == "closed" and item.get("terminal_receipt") for item in issues):
        return {"status": "merged_closure_pending", "reason": "issue closure lacks matching PR receipt"}
    return {"status": "merged_closure_pending", "reason": "terminal closure evidence is incomplete"}


def encode_cursor(*, page: int, window_end: str) -> str:
    payload = {"version": CURSOR_VERSION, "page": page, "window_end": window_end}
    return base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None, *, window_end: str) -> tuple[int, str | None]:
    if cursor is None:
        return 1, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeError, binascii.Error, json.JSONDecodeError):
        return 0, "invalid cursor"
    if (
        not isinstance(data, dict)
        or data.get("version") != CURSOR_VERSION
        or not isinstance(data.get("page"), int)
        or data["page"] < 1
        or data.get("window_end") != window_end
    ):
        return 0, "cursor does not match the declared recovery window"
    return data["page"], None


def bounded_rest_backoff(*, attempt: int, retry_after_seconds: float | None = None) -> dict[str, object]:
    """Describe one bounded retry without sleeping or widening the scan."""

    if attempt < 0 or attempt >= MAX_BACKOFF_ATTEMPTS:
        return {"retry": False, "attempt": attempt, "sleep_seconds": 0, "reason": "backoff cap reached"}
    delay = retry_after_seconds if retry_after_seconds is not None else float(2**attempt)
    if delay < 0:
        delay = 0
    return {
        "retry": True,
        "attempt": attempt,
        "sleep_seconds": min(MAX_BACKOFF_SECONDS, int(delay)),
        "max_attempts": MAX_BACKOFF_ATTEMPTS,
        "max_seconds": MAX_BACKOFF_SECONDS,
    }


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def recover(
    *,
    repository: str,
    pages: Sequence[Sequence[Mapping[str, object]]],
    classifications: Mapping[str, Mapping[str, object]] | None = None,
    cursor: str | None = None,
    window_end: str,
    window_start: str | None = None,
    max_pages: int = MAX_PAGES,
    max_requests: int = MAX_REQUESTS,
    rest_attempt: int = 0,
    retry_after_seconds: float | None = None,
) -> dict[str, object]:
    """Recover orphaned merges from already-collected bounded pages."""

    if max_pages < 1 or max_pages > MAX_PAGES or max_requests < 1 or max_requests > MAX_REQUESTS:
        raise ValueError("recovery bounds exceed the producer contract")
    end = _parse_timestamp(window_end)
    start = _parse_timestamp(window_start) if window_start else (end - timedelta(days=MAX_LOOKBACK_DAYS) if end else None)
    if end is None or start is None or start > end or end - start > timedelta(days=MAX_LOOKBACK_DAYS):
        return {"requests": [], "pending": [], "overflow": True, "continuation_cursor": None, "error": "invalid or overlong recovery window"}
    backoff = bounded_rest_backoff(attempt=rest_attempt, retry_after_seconds=retry_after_seconds)
    if rest_attempt < 0 or rest_attempt >= MAX_BACKOFF_ATTEMPTS:
        return {"requests": [], "pending": [], "overflow": True, "continuation_cursor": None, "backoff": backoff, "error": "REST backoff cap reached"}
    page_start, cursor_error = decode_cursor(cursor, window_end=window_end)
    if cursor_error:
        return {"requests": [], "pending": [], "overflow": True, "continuation_cursor": None, "error": cursor_error}
    requests: list[dict[str, object]] = []
    pending: list[dict[str, object]] = []
    scanned_pages = 0
    scanned_requests = 0
    labels = classifications or {}
    for offset, page in enumerate(pages[page_start - 1 : page_start - 1 + max_pages], start=page_start):
        scanned_pages += 1
        if len(page) > MAX_ITEMS_PER_PAGE:
            return {"requests": requests, "pending": pending, "overflow": True, "continuation_cursor": encode_cursor(page=offset, window_end=window_end), "error": "page exceeds item cap"}
        for pr in page:
            scanned_requests += 1
            if scanned_requests > max_requests:
                return {"requests": requests, "pending": pending, "overflow": True, "continuation_cursor": encode_cursor(page=offset, window_end=window_end), "error": "request cap reached"}
            if not _merged(pr):
                continue
            merged_at = _parse_timestamp(pr.get("merged_at"))
            if merged_at is None or merged_at < start or merged_at > end:
                continue
            number = pr.get("number")
            classification = labels.get(str(number), {}) if isinstance(number, int) else {}
            request = build_request(
                event={"repository": {"full_name": repository}, "generated_at": pr.get("merged_at", window_end)},
                pr={**dict(pr), "repository": {"full_name": repository}},
                classification=classification,
                source="bounded_recovery",
            )
            if request is not None:
                requests.append(request)
            else:
                pending.append({"pr_number": number, "reason": "missing or mismatched classification/merge evidence"})
    more = page_start - 1 + scanned_pages < len(pages)
    return {
        "requests": requests,
        "pending": pending,
        "overflow": more,
        "continuation_cursor": encode_cursor(page=page_start + scanned_pages, window_end=window_end) if more else None,
        "scanned_pages": scanned_pages,
        "scanned_requests": scanned_requests,
        "window_end": window_end,
        "window_start": start.isoformat().replace("+00:00", "Z"),
        "backoff": backoff,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--cursor")
    args = parser.parse_args(argv)
    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("recovery input must be an object")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    window_end = payload.get("window_end") if isinstance(payload.get("window_end"), str) else now.isoformat().replace("+00:00", "Z")
    window_start = payload.get("window_start") if isinstance(payload.get("window_start"), str) else None
    pages = payload.get("pages", [])
    result = recover(
        repository=str(payload.get("repository", "")),
        pages=[_items(page) for page in pages] if isinstance(pages, list) else [],
        classifications={str(k): _dict(v) for k, v in _dict(payload.get("classifications")).items()},
        cursor=args.cursor or (payload.get("cursor") if isinstance(payload.get("cursor"), str) else None),
        window_end=window_end,
        window_start=window_start,
        rest_attempt=int(payload.get("rest_attempt", 0)) if isinstance(payload.get("rest_attempt", 0), int) else 0,
        retry_after_seconds=float(payload["retry_after_seconds"]) if isinstance(payload.get("retry_after_seconds"), (int, float)) else None,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
