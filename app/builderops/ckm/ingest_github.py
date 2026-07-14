"""REST-backed GitHub artifact ingestion for CKM-04.

This adapter only reads GitHub delivery artifacts through ``gh api`` and
writes normalized, rebuildable rows to the CKM BuilderOps store.  A missing or
temporarily unavailable CLI is an honest skip: no source watermark advances.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from app.builderops.ckm.store import CkmStore

DEFAULT_REPOSITORY = "RasmusTho/agentic-pkm-mvp"
_DOC_REF_RE = re.compile(r"\bdocs/[A-Za-z0-9_./-]+\.md\b")
_ISSUE_REF_RE = re.compile(r"(?<![\w/])#\d+\b")


@dataclass(frozen=True)
class GithubArtifact:
    natural_key: str
    artifact_kind: str
    payload_summary: str
    provenance: str
    source: str
    source_watermark: str


def _labels(payload: Mapping[str, Any]) -> list[str]:
    values = payload.get("labels", [])
    return sorted(
        item["name"] if isinstance(item, Mapping) and isinstance(item.get("name"), str) else str(item)
        for item in values if isinstance(item, (str, Mapping))
    )


def _references(payload: Mapping[str, Any]) -> list[str]:
    text = "\n".join(str(payload.get(key, "")) for key in ("body", "title"))
    refs = {*_DOC_REF_RE.findall(text), *_ISSUE_REF_RE.findall(text)}
    for key in ("closing_issues_references", "closed_by_pull_requests_references"):
        for item in payload.get(key, []) or []:
            if isinstance(item, Mapping) and isinstance(item.get("number"), int):
                refs.add(f"#{item['number']}")
    return sorted(refs)


def normalize_github_payload(payload: Mapping[str, Any], *, artifact_kind: str) -> GithubArtifact:
    """Turn one REST object into a typed, provenance-bearing CKM artifact."""
    number = payload.get("number")
    updated_at = payload.get("updated_at")
    if not isinstance(number, int) or not isinstance(updated_at, str) or not updated_at:
        raise ValueError("GitHub artifact requires integer number and updated_at")
    if artifact_kind not in {"issue", "pull_request"}:
        raise ValueError(f"unsupported GitHub artifact kind: {artifact_kind}")
    key_kind = "issue" if artifact_kind == "issue" else "pull"
    pull_request = payload.get("pull_request")
    merged_at = payload.get("merged_at")
    if merged_at is None and isinstance(pull_request, Mapping):
        merged_at = pull_request.get("merged_at")
    provenance = {
        "source_ref": f"github:{key_kind}:{number}",
        "extraction_method": "github_rest",
        "number": number,
        "title": str(payload.get("title", "")),
        "state": str(payload.get("state", "")),
        "merged_at": merged_at,
        "labels": _labels(payload),
        "references": _references(payload),
        "linked_pull_request": pull_request,
        "closing_references": payload.get("closing_issues_references", []),
        "changed_files": payload.get("changed_files", [] if artifact_kind == "pull_request" else None),
        "updated_at": updated_at,
    }
    return GithubArtifact(
        natural_key=f"github:{key_kind}:{number}",
        artifact_kind=artifact_kind,
        payload_summary=f"#{number} {provenance['title']} ({provenance['state']})",
        provenance=json.dumps(provenance, sort_keys=True),
        source="github_issues" if artifact_kind == "issue" else "github_pull_requests",
        source_watermark=updated_at,
    )


def _gh_fetch(repository: str) -> Callable[[str, str | None], list[dict[str, Any]]]:
    def request_list(endpoint: str) -> list[dict[str, Any]]:
        completed = subprocess.run(
            ["gh", "api", "--paginate", "--slurp", endpoint],
            check=True,
            capture_output=True,
            text=True,
        )
        pages = json.loads(completed.stdout)
        if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
            raise ValueError("GitHub REST endpoint returned non-list pages")
        return [item for page in pages for item in page if isinstance(item, dict)]

    def fetch(kind: str, since: str | None) -> list[dict[str, Any]]:
        endpoint = f"repos/{repository}/issues?state=all&per_page=100"
        if since:
            endpoint = f"{endpoint}&since={since}"
        decoded = request_list(endpoint)
        if kind == "issues":
            return [item for item in decoded if "pull_request" not in item]
        pulls = [item for item in decoded if "pull_request" in item]
        for item in pulls:
            number = item.get("number")
            if isinstance(number, int):
                files = request_list(f"repos/{repository}/pulls/{number}/files?per_page=100")
                item["changed_files"] = [str(file["filename"]) for file in files if "filename" in file]
        return pulls

    return fetch


def _ingest_kind(
    store: CkmStore,
    *,
    fetch: Callable[[str, str | None], Sequence[Mapping[str, Any]]],
    fetch_kind: str,
    artifact_kind: str,
) -> tuple[dict[str, int | str], str, str | None, str | None]:
    watermark_key = "github_issues" if artifact_kind == "issue" else "github_pull_requests"
    previous = store.get_watermark(watermark_key)
    records = [normalize_github_payload(item, artifact_kind=artifact_kind) for item in fetch(fetch_kind, previous)]
    changed = 0
    newest = previous
    for record in records:
        existing = store.get_artifact_by_source_ref(record.natural_key)
        if existing is None or existing.watermark != record.source_watermark:
            store.upsert_artifact(
                source_ref=record.natural_key,
                artifact_kind=record.artifact_kind,
                source=record.source,
                watermark=record.source_watermark,
                provenance=record.provenance,
            )
            changed += 1
        if newest is None or record.source_watermark > newest:
            newest = record.source_watermark
    return (
        {"artifacts": len(records), "changed": changed, "watermark": newest or "(none)"},
        watermark_key,
        previous,
        newest,
    )


def ingest_github(
    store: CkmStore,
    *,
    repository: str = DEFAULT_REPOSITORY,
    fetch: Callable[[str, str | None], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Ingest Issues and pull requests, or return an honest unavailable skip."""
    store.ensure_schema()
    try:
        fetch = fetch or _gh_fetch(repository)
        issues, issues_key, issues_previous, issues_newest = _ingest_kind(
            store, fetch=fetch, fetch_kind="issues", artifact_kind="issue"
        )
        pulls, pulls_key, pulls_previous, pulls_newest = _ingest_kind(
            store, fetch=fetch, fetch_kind="pulls", artifact_kind="pull_request"
        )
    except FileNotFoundError:
        return {"status": "skipped (gh unavailable)"}
    except subprocess.CalledProcessError as exc:
        return {"status": "skipped (gh unavailable or rate-limited)", "detail": str(exc)}
    for key, previous, newest in (
        (issues_key, issues_previous, issues_newest),
        (pulls_key, pulls_previous, pulls_newest),
    ):
        if newest is not None and newest != previous:
            store.set_watermark(key, newest)
    return {"status": "ok", "issues": issues, "pull_requests": pulls}
