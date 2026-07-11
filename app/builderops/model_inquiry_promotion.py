"""Issue-ready inquiry evaluation and explicit REST-only GitHub promotion."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.model_inquiry_contract import (
    canonical_hash,
    github_issue_url_matches,
    parse_issue_proposal,
    parse_model_turn_response,
)
from app.builderops.models import BuilderOpsValidationError
from scripts.validate_issue_readiness import classify_issue_body
from scripts.validate_source_anchors import validate_issue_body as validate_source_anchors

MARKER_SCHEMA = "builderops.model-inquiry-promotion-marker.v1"
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
DEFAULT_LABELS = ("type:task", "prio:med", "agent:ready")
REPO_ROOT = Path(__file__).resolve().parents[2]


class ModelInquiryPromotionError(BuilderOpsValidationError):
    """The inquiry cannot safely cross into GitHub Issue authority."""


class GitHubIssueRestClient(Protocol):
    def find_issue_by_marker(self, marker: str) -> Mapping[str, Any] | None: ...

    def create_issue(
        self,
        *,
        title: str,
        body: str,
        labels: Sequence[str],
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ValidatedIssueProposal:
    title: str
    body: str


class GhApiIssueClient:
    """Small `gh api` REST client; never uses GraphQL or `gh issue`."""

    def __init__(
        self,
        repository: str,
        *,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
    ) -> None:
        self.repository = _repository_slug(repository)
        if timeout_seconds <= 0 or max_pages < 1:
            raise ModelInquiryPromotionError("GitHub REST client bounds must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages

    def find_issue_by_marker(self, marker: str) -> Mapping[str, Any] | None:
        matches: list[dict[str, Any]] = []
        for page in range(1, self.max_pages + 1):
            payload = self._run(
                [
                    "--method",
                    "GET",
                    f"repos/{self.repository}/issues",
                    "-f",
                    "state=all",
                    "-f",
                    "per_page=100",
                    "-f",
                    f"page={page}",
                ]
            )
            if not isinstance(payload, list):
                raise ModelInquiryPromotionError("GitHub REST issue listing was not a list")
            for item in payload:
                if (
                    isinstance(item, dict)
                    and "pull_request" not in item
                    and marker in str(item.get("body") or "")
                ):
                    matches.append(item)
            if len(payload) < 100:
                break
        else:
            raise ModelInquiryPromotionError("GitHub REST issue scan was truncated")
        if len(matches) > 1:
            raise ModelInquiryPromotionError("multiple GitHub Issues contain the promotion marker")
        return matches[0] if matches else None

    def create_issue(
        self,
        *,
        title: str,
        body: str,
        labels: Sequence[str],
    ) -> Mapping[str, Any]:
        return self._run(
            ["--method", "POST", f"repos/{self.repository}/issues", "--input", "-"],
            input_payload={"title": title, "body": body, "labels": list(labels)},
        )

    def _run(
        self,
        arguments: Sequence[str],
        *,
        input_payload: Mapping[str, Any] | None = None,
    ) -> Any:
        try:
            result = subprocess.run(
                ["gh", "api", "--hostname", "github.com", *arguments],
                input=json.dumps(input_payload) if input_payload is not None else None,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ModelInquiryPromotionError("GitHub REST command unavailable or timed out") from exc
        if result.returncode != 0:
            raise ModelInquiryPromotionError(
                f"GitHub REST command failed with exit {result.returncode}"
            )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ModelInquiryPromotionError("GitHub REST response was not JSON") from exc


class ModelInquiryPromotionGateway:
    def __init__(
        self,
        service: ModelInquiryService,
        *,
        repository: str | None = None,
        client: GitHubIssueRestClient | None = None,
    ) -> None:
        self.service = service
        self.repository = _repository_slug(repository) if repository is not None else None
        self.client = client

    def evaluate(
        self,
        inquiry_id: str,
        *,
        actor: Mapping[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        trace = self.service.trace(inquiry_id)
        terminal = next(
            (
                receipt
                for receipt in trace.get("receipts", [])
                if receipt.get("event_type") == "inquiry_run_terminal"
            ),
            None,
        )
        if terminal is None:
            raise ModelInquiryPromotionError(
                "readiness evaluation requires a terminal inquiry run"
            )
        try:
            proposal = _validated_issue_proposal(trace)
        except ModelInquiryPromotionError as exc:
            outcome = "not_ready" if "consensus terminal" in str(exc) else "needs_input"
            input_refs = (
                ["synthesis"]
                if isinstance(trace.get("synthesis"), dict)
                else [turn["turn_id"] for turn in trace.get("turns", [])[-2:]] or ["question"]
            )
            readiness = self.service.commit_readiness(
                inquiry_id,
                outcome=outcome,
                rationale=str(exc),
                input_artifact_refs=input_refs,
                source_refs=list(trace["source_refs"]),
            )
            receipt = self.service.commit_readiness_receipt(
                inquiry_id,
                source_refs=list(trace["source_refs"]),
                actor=actor,
            )
            return {
                "inquiry_id": inquiry_id,
                "proposal": None,
                "readiness": readiness,
                "receipt": receipt,
            }
        readiness = self.service.commit_readiness(
            inquiry_id,
            outcome="issue_ready",
            rationale="Consensus proposal satisfies the canonical Issue contract.",
            input_artifact_refs=["synthesis"],
            source_refs=list(trace["source_refs"]),
        )
        receipt = self.service.commit_readiness_receipt(
            inquiry_id,
            source_refs=list(trace["source_refs"]),
            actor=actor,
        )
        return {
            "inquiry_id": inquiry_id,
            "proposal": {"title": proposal.title, "body": proposal.body},
            "readiness": readiness,
            "receipt": receipt,
        }

    def promote(
        self,
        inquiry_id: str,
        *,
        labels: Sequence[str] = DEFAULT_LABELS,
        actor: Mapping[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        if self.repository is None or self.client is None:
            raise ModelInquiryPromotionError(
                "issue promotion requires an explicit repository and REST client"
            )
        with self.service.inquiry_promotion_lock(inquiry_id):
            trace = self.service.trace(inquiry_id, include_delivery=True)
            proposal = _validated_issue_proposal(trace)
            readiness = _require_readiness_evidence(trace)
            marker = _promotion_marker(
                repository=self.repository,
                inquiry_id=inquiry_id,
                readiness_hash=str(readiness["artifact_hash"]),
                synthesis_hash=str(trace["synthesis"]["artifact_hash"]),
                title=proposal.title,
                body=proposal.body,
            )
            issue_body = f"{proposal.body.rstrip()}\n\n{marker}\n"
            existing_receipt = next(
                (
                    receipt
                    for receipt in trace["receipts"]
                    if receipt.get("event_type") == "inquiry_promotion_terminal"
                ),
                None,
            )
            if existing_receipt is not None:
                existing_intent = trace.get("promotion_intent")
                if not isinstance(existing_intent, Mapping):
                    raise ModelInquiryPromotionError(
                        "terminal promotion receipt has no promotion intent"
                    )
                return _promotion_result(existing_intent, existing_receipt, reconciled=True)

            intent = self.service.commit_promotion_intent(
                inquiry_id,
                repository=self.repository,
                marker=marker,
                title=proposal.title,
                issue_body=issue_body,
                source_refs=list(trace["source_refs"]),
                actor=actor,
            )

            issue = self.client.find_issue_by_marker(marker)
            reconciled = issue is not None
            if issue is None:
                issue = self.client.create_issue(
                    title=proposal.title,
                    body=issue_body,
                    labels=tuple(labels),
                )
            normalized_issue = _validated_issue_response(
                issue,
                marker=marker,
                expected_title=proposal.title,
                expected_body=issue_body,
                expected_repository=self.repository,
            )
            receipt = self.service.commit_promotion_receipt(
                inquiry_id,
                intent=intent,
                issue_number=normalized_issue["number"],
                issue_url=normalized_issue["html_url"],
                issue_created_at=normalized_issue["created_at"],
                source_refs=list(trace["source_refs"]),
                actor=actor,
            )
            return _promotion_result(intent, receipt, reconciled=reconciled)


def _validated_issue_proposal(trace: Mapping[str, Any]) -> ValidatedIssueProposal:
    terminal = next(
        (
            receipt
            for receipt in trace.get("receipts", [])
            if receipt.get("event_type") == "inquiry_run_terminal"
        ),
        None,
    )
    if terminal is None or terminal.get("outcome") != "consensus":
        raise ModelInquiryPromotionError("issue promotion requires a consensus terminal receipt")
    synthesis = trace.get("synthesis")
    if not isinstance(synthesis, dict):
        raise ModelInquiryPromotionError("issue promotion requires a synthesis artifact")
    try:
        response = parse_model_turn_response(str(synthesis.get("content", "")))
    except BuilderOpsValidationError as exc:
        raise ModelInquiryPromotionError("accepted model response contract is invalid") from exc
    if response.blocking_questions:
        raise ModelInquiryPromotionError("issue proposal contains unresolved blocking questions")
    try:
        proposal = parse_issue_proposal(response.content)
    except BuilderOpsValidationError as exc:
        raise ModelInquiryPromotionError("embedded issue proposal contract is invalid") from exc
    report = classify_issue_body(proposal.body)
    if report.readiness_classification != "ready_candidate":
        raise ModelInquiryPromotionError(
            f"issue proposal is not ready: {report.readiness_classification}"
        )
    anchors_ok, anchor_errors = validate_source_anchors(proposal.body, REPO_ROOT)
    if not anchors_ok:
        raise ModelInquiryPromotionError(
            f"issue proposal has unresolved source anchors: {anchor_errors[0]}"
        )
    return ValidatedIssueProposal(title=proposal.title, body=proposal.body)


def _require_readiness_evidence(trace: Mapping[str, Any]) -> Mapping[str, Any]:
    readiness = trace.get("readiness")
    if not isinstance(readiness, dict) or readiness.get("outcome") != "issue_ready":
        raise ModelInquiryPromotionError("issue promotion requires issue_ready evidence")
    receipt = next(
        (
            item
            for item in trace.get("receipts", [])
            if item.get("event_type") == "inquiry_readiness_terminal"
        ),
        None,
    )
    if receipt is None:
        raise ModelInquiryPromotionError("issue promotion requires a readiness terminal receipt")
    return readiness


def _promotion_marker(
    *,
    repository: str,
    inquiry_id: str,
    readiness_hash: str,
    synthesis_hash: str,
    title: str,
    body: str,
) -> str:
    digest = canonical_hash(
        {
            "schema": MARKER_SCHEMA,
            "repository": repository,
            "inquiry_id": inquiry_id,
            "readiness_artifact_hash": readiness_hash,
            "synthesis_artifact_hash": synthesis_hash,
            "title": title,
            "body": body,
        }
    )
    return f"<!-- builderops-inquiry-promotion:{inquiry_id}:{digest} -->"


def _validated_issue_response(
    issue: Mapping[str, Any],
    *,
    marker: str,
    expected_title: str,
    expected_body: str,
    expected_repository: str,
) -> dict[str, Any]:
    number = issue.get("number")
    url = issue.get("html_url")
    created_at = issue.get("created_at")
    body = issue.get("body")
    title = issue.get("title")
    if (
        isinstance(number, bool)
        or not isinstance(number, int)
        or number < 1
        or not isinstance(url, str)
        or not github_issue_url_matches(url, expected_repository, number)
        or not isinstance(created_at, str)
        or not created_at
        or not isinstance(body, str)
        or body != expected_body
        or title != expected_title
        or marker not in expected_body
    ):
        raise ModelInquiryPromotionError("GitHub REST issue response is incomplete or mismatched")
    return {"number": number, "html_url": url, "created_at": created_at}


def _promotion_result(
    intent: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    reconciled: bool,
) -> dict[str, Any]:
    return {
        "inquiry_id": intent["inquiry_id"],
        "promotion_intent_artifact_hash": intent["artifact_hash"],
        "issue_number": receipt["github_issue_number"],
        "issue_url": receipt["github_issue_url"],
        "receipt_id": receipt["id"],
        "reconciled": reconciled,
    }


def _repository_slug(value: str) -> str:
    normalized = value.strip()
    if not REPOSITORY_RE.fullmatch(normalized):
        raise ModelInquiryPromotionError("repository must be owner/name")
    return normalized.casefold()


__all__ = [
    "DEFAULT_LABELS",
    "GhApiIssueClient",
    "GitHubIssueRestClient",
    "ModelInquiryPromotionError",
    "ModelInquiryPromotionGateway",
]
