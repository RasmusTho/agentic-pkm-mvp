from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.model_inquiry_contract import (
    ISSUE_PROPOSAL_SCHEMA_VERSION,
    RESPONSE_SCHEMA_VERSION,
)
from app.builderops.model_inquiry_promotion import (
    GhApiIssueClient,
    ModelInquiryPromotionError,
    ModelInquiryPromotionGateway,
)
from app.builderops.models import BuilderOpsValidationError
from app.builderops.model_inquiry_runner import ModelInquiryRunner
from app.builderops.model_inquiry_adapters import (
    AdapterExecutionError,
    AdapterResult,
    LocalCommandAdapter,
)


def _issue_body() -> str:
    return """## Context
Bounded follow-up from a model inquiry.

## Scope
Add one deterministic contract seam.

## Source Anchors
- `docs/BUILDEROPS_MODEL_INQUIRY/PROMOTION_AND_TRACEABILITY.md`

## SBS Impact
- Primary subsystem: Builder System

## Constraints
- Preserve the authority boundary.

## Acceptance Criteria
- [ ] The seam is deterministic. Verify: `tests/builderops/test_model_inquiry_promotion.py::test_promote_creates_issue_and_receipt`

## Out of Scope
- Product runtime changes.

## Suggested Validation
- `pytest -q tests/builderops/test_model_inquiry_promotion.py::test_promote_creates_issue_and_receipt`

## Source Docs
- `docs/BUILDEROPS_MODEL_INQUIRY/PROMOTION_AND_TRACEABILITY.md`
"""


def _response(
    *,
    stance: str,
    reviewed: list[str],
    accepted_hash: str | None,
    blocking_questions: list[str] | None = None,
    issue_body: str | None = None,
    proposal_override: str | None = None,
) -> str:
    proposal = proposal_override or json.dumps(
        {
            "schema_version": ISSUE_PROPOSAL_SCHEMA_VERSION,
            "title": "Add deterministic inquiry promotion",
            "body": issue_body or _issue_body(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return json.dumps(
        {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "stance": stance,
            "content": proposal,
            "claims": ["The contract is bounded."],
            "risks": [],
            "blocking_questions": blocking_questions or [],
            "reviewed_artifact_refs": reviewed,
            "accepted_artifact_hash": accepted_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class ProposalAdapter:
    def __init__(
        self,
        role: str,
        *,
        blocking: bool = False,
        issue_body: str | None = None,
        proposal_override: str | None = None,
    ) -> None:
        self.adapter_id = f"adapter-{role}"
        self.provider = role
        self.model = f"model-{role}"
        self.role = role
        self.blocking = blocking
        self.issue_body = issue_body
        self.proposal_override = proposal_override

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        reviewed = list(request["reviewed_artifact_refs"])
        if not reviewed:
            return AdapterResult(
                _response(
                    stance="draft",
                    reviewed=[],
                    accepted_hash=None,
                    blocking_questions=["Need an answer"] if self.blocking else [],
                    issue_body=self.issue_body,
                    proposal_override=self.proposal_override,
                )
            )
        return AdapterResult(
            _response(
                stance="accept",
                reviewed=reviewed,
                accepted_hash=str(request["input_artifacts"][0]["artifact_hash"]),
                issue_body=self.issue_body,
                proposal_override=self.proposal_override,
            )
        )


class FakeIssueClient:
    def __init__(self) -> None:
        self.issues: list[dict[str, Any]] = []
        self.find_calls = 0
        self.create_calls = 0
        self.before_create = None
        self.issue_url = "https://github.com/Example/Repo/issues/501"

    def find_issue_by_marker(self, marker: str) -> Mapping[str, Any] | None:
        self.find_calls += 1
        matches = [issue for issue in self.issues if marker in issue["body"]]
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
        self.create_calls += 1
        if self.before_create is not None:
            self.before_create()
        issue = {
            "number": 501,
            "html_url": self.issue_url,
            "created_at": "2026-07-10T12:00:00Z",
            "title": title,
            "body": body,
            "labels": list(labels),
        }
        self.issues.append(issue)
        return issue


def _consensus_service(
    tmp_path: Path,
    *,
    blocking: bool = False,
    issue_body: str | None = None,
    proposal_override: str | None = None,
) -> ModelInquiryService:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    service = ModelInquiryService(vault)
    service.start(
        question="Create a bounded promotion contract",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_promotion_test",
        source_refs=[{"ref_type": "github_issue", "ref": "#3293"}],
    )
    adapters = {
        role: ProposalAdapter(
            role,
            blocking=blocking,
            issue_body=issue_body,
            proposal_override=proposal_override,
        )
        for role in ("fable", "gpt_codex")
    }
    result = ModelInquiryRunner(service, adapters).run("inq_promotion_test", max_rounds=1)
    assert result["outcome"] == "consensus"
    return service


def test_degraded_consensus_is_not_issue_ready(tmp_path: Path) -> None:
    vault = tmp_path / "degraded" / "vault"
    vault.mkdir(parents=True)
    service = ModelInquiryService(vault)
    service.start(
        question="Do not promote one-model agreement",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_degraded_promotion",
        source_refs=[{"ref_type": "github_issue", "ref": "#4713"}],
    )

    class FailedFable(ProposalAdapter):
        def execute(self, request: Mapping[str, Any]) -> AdapterResult:
            raise AdapterExecutionError(
                "provider unavailable",
                failure_class="command_exit_nonzero",
                exit_code=17,
            )

    class LocalCommandProposalAdapter(LocalCommandAdapter):
        def __init__(self, delegate: ProposalAdapter) -> None:
            super().__init__(
                adapter_id=delegate.adapter_id,
                provider=delegate.provider,
                model=delegate.model,
                argv=("fixture-local-command",),
            )
            object.__setattr__(self, "delegate", delegate)

        def execute(self, request: Mapping[str, Any]) -> AdapterResult:
            return self.delegate.execute(request)

    result = ModelInquiryRunner(
        service,
        {
            "fable": LocalCommandProposalAdapter(FailedFable("fable")),
            "gpt_codex": LocalCommandProposalAdapter(ProposalAdapter("gpt_codex")),
        },
        allow_operational_fallback=True,
    ).run("inq_degraded_promotion", max_rounds=1)
    assert result["outcome"] == "degraded_consensus"

    gateway = ModelInquiryPromotionGateway(
        service,
        repository="example/repo",
        client=FakeIssueClient(),
    )
    evaluation = gateway.evaluate("inq_degraded_promotion")
    assert evaluation["readiness"]["outcome"] == "not_ready"
    assert "consensus terminal" in evaluation["readiness"]["rationale"]
    with pytest.raises(ModelInquiryPromotionError, match="consensus terminal receipt"):
        gateway.promote("inq_degraded_promotion")


def test_issue_promotion_requires_ready_receipt(tmp_path: Path) -> None:
    service = _consensus_service(tmp_path)
    client = FakeIssueClient()
    gateway = ModelInquiryPromotionGateway(
        service,
        repository="EXAMPLE/Repo",
        client=client,
    )

    with pytest.raises(ModelInquiryPromotionError, match="issue_ready evidence"):
        gateway.promote("inq_promotion_test")

    trace = service.trace("inq_promotion_test")
    service.commit_readiness(
        "inq_promotion_test",
        outcome="issue_ready",
        rationale="Unreceipted claim",
        input_artifact_refs=["synthesis"],
        source_refs=trace["source_refs"],
    )
    with pytest.raises(ModelInquiryPromotionError, match="readiness terminal receipt"):
        gateway.promote("inq_promotion_test")
    assert client.create_calls == 0

    blocked_service = _consensus_service(tmp_path / "blocked", blocking=True)
    blocked_gateway = ModelInquiryPromotionGateway(
        blocked_service,
        repository="example/repo",
        client=FakeIssueClient(),
    )
    blocked = blocked_gateway.evaluate("inq_promotion_test")
    assert blocked["readiness"]["outcome"] == "needs_input"
    assert "blocking questions" in blocked["readiness"]["rationale"]

    missing_anchor_service = _consensus_service(
        tmp_path / "missing-anchor",
        issue_body=_issue_body().replace(
            "docs/BUILDEROPS_MODEL_INQUIRY/PROMOTION_AND_TRACEABILITY.md",
            "docs/DOES_NOT_EXIST.md",
        ),
    )
    missing_anchor_gateway = ModelInquiryPromotionGateway(
        missing_anchor_service,
        repository="example/repo",
        client=FakeIssueClient(),
    )
    missing_anchor = missing_anchor_gateway.evaluate("inq_promotion_test")
    assert missing_anchor["readiness"]["outcome"] == "needs_input"
    assert "unresolved source anchors" in missing_anchor["readiness"]["rationale"]

    absolute_anchor = str(
        Path(__file__).resolve().parents[2]
        / "docs/BUILDEROPS_MODEL_INQUIRY/PROMOTION_AND_TRACEABILITY.md"
    )
    absolute_anchor_service = _consensus_service(
        tmp_path / "absolute-anchor",
        issue_body=_issue_body().replace(
            "docs/BUILDEROPS_MODEL_INQUIRY/PROMOTION_AND_TRACEABILITY.md",
            absolute_anchor,
        ),
    )
    absolute_anchor_client = FakeIssueClient()
    absolute_anchor_gateway = ModelInquiryPromotionGateway(
        absolute_anchor_service,
        repository="example/repo",
        client=absolute_anchor_client,
    )
    absolute_result = absolute_anchor_gateway.evaluate("inq_promotion_test")
    assert absolute_result["readiness"]["outcome"] == "needs_input"
    assert "repository-relative" in absolute_result["readiness"]["rationale"]
    assert absolute_anchor_client.create_calls == 0

    malformed_service = _consensus_service(
        tmp_path / "malformed-proposal",
        proposal_override='{"wrong_schema": true}',
    )
    malformed_gateway = ModelInquiryPromotionGateway(
        malformed_service,
        repository="example/repo",
        client=FakeIssueClient(),
    )
    malformed = malformed_gateway.evaluate("inq_promotion_test")
    assert malformed["readiness"]["outcome"] == "needs_input"
    assert "embedded issue proposal contract" in malformed["readiness"]["rationale"]

    no_consensus_vault = tmp_path / "no-consensus-vault"
    no_consensus_vault.mkdir()
    no_consensus_service = ModelInquiryService(no_consensus_vault)
    no_consensus_service.start(
        question="No consensus yet",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_no_consensus",
        source_refs=[{"ref_type": "github_issue", "ref": "#3293"}],
    )
    no_consensus_gateway = ModelInquiryPromotionGateway(
        no_consensus_service,
        repository="example/repo",
        client=FakeIssueClient(),
    )
    with pytest.raises(ModelInquiryPromotionError, match="terminal inquiry run"):
        no_consensus_gateway.evaluate("inq_no_consensus")
    assert not (
        no_consensus_vault
        / "model-inquiries"
        / "inq_no_consensus"
        / "readiness.json"
    ).exists()

    unavailable_vault = tmp_path / "unavailable-vault"
    unavailable_vault.mkdir()
    unavailable_service = ModelInquiryService(unavailable_vault)
    unavailable_service.start(
        question="Provider unavailable",
        workflow="fable-gpt-architecture",
        inquiry_id="inq_unavailable",
        source_refs=[{"ref_type": "github_issue", "ref": "#3293"}],
    )
    terminal = ModelInquiryRunner(unavailable_service, env={}).run("inq_unavailable")
    assert terminal["outcome"] == "provider_unavailable"
    unavailable_gateway = ModelInquiryPromotionGateway(
        unavailable_service,
        repository="example/repo",
        client=FakeIssueClient(),
    )
    unavailable = unavailable_gateway.evaluate("inq_unavailable")
    assert unavailable["readiness"]["outcome"] == "not_ready"

    symlink_service = _consensus_service(tmp_path / "symlink-input")
    symlink_trace = symlink_service.trace("inq_promotion_test")
    symlink_service.commit_readiness(
        "inq_promotion_test",
        outcome="issue_ready",
        rationale="Symlink input must fail closed.",
        input_artifact_refs=["synthesis"],
        source_refs=symlink_trace["source_refs"],
    )
    synthesis_path = (
        tmp_path
        / "symlink-input"
        / "vault"
        / "model-inquiries"
        / "inq_promotion_test"
        / "synthesis.json"
    )
    outside_synthesis = tmp_path / "outside-synthesis.json"
    outside_synthesis.write_text(synthesis_path.read_text(encoding="utf-8"), encoding="utf-8")
    synthesis_path.unlink()
    synthesis_path.symlink_to(outside_synthesis)
    with pytest.raises(BuilderOpsValidationError, match="artifact must not be a symlink"):
        symlink_service.commit_readiness_receipt(
            "inq_promotion_test",
            source_refs=symlink_trace["source_refs"],
        )
    assert not (
        synthesis_path.parent / "receipts" / "readiness-terminal.json"
    ).exists()


def test_promote_creates_issue_and_receipt(tmp_path: Path) -> None:
    service = _consensus_service(tmp_path)
    client = FakeIssueClient()
    inquiry_dir = tmp_path / "vault" / "model-inquiries" / "inq_promotion_test"
    client.before_create = lambda: (inquiry_dir / "promotion-intent.json").is_file() or pytest.fail(
        "promotion intent must persist before REST creation"
    )
    gateway = ModelInquiryPromotionGateway(
        service,
        repository="EXAMPLE/Repo",
        client=client,
    )
    evaluated = gateway.evaluate("inq_promotion_test")
    result = gateway.promote("inq_promotion_test")

    assert evaluated["readiness"]["outcome"] == "issue_ready"
    assert result["issue_number"] == 501
    assert result["reconciled"] is False
    assert client.create_calls == 1
    trace = service.trace("inq_promotion_test", include_delivery=True)
    assert trace["promotion_intent"]["object_type"] == "PromotionIntent"
    assert trace["delivery_refs"] == [
        {
            "ref_type": "github_issue",
            "ref": "example/repo#501",
            "authority_surface": "github",
        }
    ]


def test_completed_promotion_retry_with_different_actor_returns_existing_issue(
    tmp_path: Path,
) -> None:
    """Terminal promotion retries do not rewrite actor-bound immutable intent."""
    service = _consensus_service(tmp_path)
    client = FakeIssueClient()
    gateway = ModelInquiryPromotionGateway(
        service,
        repository="example/repo",
        client=client,
    )
    gateway.evaluate("inq_promotion_test", actor="first-promoter")

    created = gateway.promote("inq_promotion_test", actor="first-promoter")
    retried = gateway.promote("inq_promotion_test", actor="retrying-promoter")

    assert retried["issue_number"] == created["issue_number"]
    assert retried["receipt_id"] == created["receipt_id"]
    assert retried["reconciled"] is True
    assert client.create_calls == 1


def test_completed_promotion_retry_with_different_repository_fails_closed(
    tmp_path: Path,
) -> None:
    """A terminal receipt cannot be replayed through another repository target."""
    service = _consensus_service(tmp_path)
    source_client = FakeIssueClient()
    source_gateway = ModelInquiryPromotionGateway(
        service,
        repository="example/repo",
        client=source_client,
    )
    source_gateway.evaluate("inq_promotion_test")
    source_gateway.promote("inq_promotion_test")

    other_client = FakeIssueClient()
    other_gateway = ModelInquiryPromotionGateway(
        service,
        repository="other/repo",
        client=other_client,
    )

    with pytest.raises(ModelInquiryPromotionError, match="target does not match"):
        other_gateway.promote("inq_promotion_test")

    assert source_client.create_calls == 1
    assert other_client.create_calls == 0


def test_retry_reconciles_issue_after_receipt_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _consensus_service(tmp_path)
    client = FakeIssueClient()
    gateway = ModelInquiryPromotionGateway(
        service,
        repository="EXAMPLE/Repo",
        client=client,
    )
    gateway.evaluate("inq_promotion_test")
    original = service.commit_promotion_receipt

    def fail_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise OSError("simulated local persistence failure")

    monkeypatch.setattr(service, "commit_promotion_receipt", fail_receipt)
    with pytest.raises(OSError, match="simulated"):
        gateway.promote("inq_promotion_test")
    assert client.create_calls == 1

    monkeypatch.setattr(service, "commit_promotion_receipt", original)
    retried = gateway.promote("inq_promotion_test")
    assert retried["issue_number"] == 501
    assert retried["reconciled"] is True
    assert client.create_calls == 1
    assert client.find_calls == 2

    wrong_authority_service = _consensus_service(tmp_path / "wrong-authority")
    wrong_authority_client = FakeIssueClient()
    wrong_authority_client.issue_url = "https://attacker.example/not-github/501"
    wrong_authority_gateway = ModelInquiryPromotionGateway(
        wrong_authority_service,
        repository="example/repo",
        client=wrong_authority_client,
    )
    wrong_authority_gateway.evaluate("inq_promotion_test")
    with pytest.raises(ModelInquiryPromotionError, match="incomplete or mismatched"):
        wrong_authority_gateway.promote("inq_promotion_test")


def test_gh_api_client_uses_rest_only_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "<!-- builderops-inquiry-promotion:inq_test:abc -->"
    calls: list[tuple[list[str], str | None]] = []
    responses = iter(
        [
            [
                {"number": 1, "body": marker, "pull_request": {"url": "ignored"}},
                {
                    "number": 2,
                    "title": "Ready",
                    "body": f"Body\n{marker}\n",
                    "html_url": "https://github.com/example/repo/issues/2",
                    "created_at": "2026-07-10T12:00:00Z",
                },
            ],
            {
                "number": 3,
                "title": "Ready",
                "body": f"Body\n{marker}\n",
                "html_url": "https://github.com/example/repo/issues/3",
                "created_at": "2026-07-10T12:01:00Z",
            },
        ]
    )

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs.get("input")))
        return subprocess.CompletedProcess(args, 0, json.dumps(next(responses)), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = GhApiIssueClient("example/repo")
    found = client.find_issue_by_marker(marker)
    created = client.create_issue(
        title="Ready",
        body=f"Body\n{marker}\n",
        labels=["type:task"],
    )

    assert found and found["number"] == 2
    assert created["number"] == 3
    assert all(call[0][:4] == ["gh", "api", "--hostname", "github.com"] for call in calls)
    assert all("graphql" not in call[0] for call in calls)
    assert calls[0][0][4:7] == ["--method", "GET", "repos/example/repo/issues"]
    assert calls[1][0][4:7] == ["--method", "POST", "repos/example/repo/issues"]
    assert json.loads(calls[1][1] or "{}")["labels"] == ["type:task"]

    full_page = [{"number": index, "body": "other"} for index in range(100)]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args,
            0,
            json.dumps(full_page),
            "",
        ),
    )
    with pytest.raises(ModelInquiryPromotionError, match="truncated"):
        GhApiIssueClient("example/repo", max_pages=1).find_issue_by_marker(marker)
