"""Live protected-repository and host-credential adapters for BCP-05."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.builderops.control_plane.routing import RepoRef
from app.dispatcher.verification_merge import (
    MergeAuthorityError,
    ProtectedDeliveryManifest,
)
from app.dispatcher.verification_contract import (
    has_closing_issue_attempt,
    resolve_neutralized_issue_authority,
)
from app.dispatcher.verified_merge import (
    FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
    fixed_verified_merge_commit_title,
    resolve_verified_merge_authority_receipt,
    resolve_verified_merge_phase,
)

_DEFAULT_MANIFEST_PATH = ".builderops/delivery-manifest.json"
_MAX_MANIFEST_BYTES = 65_536
_REQUIRED_VERIFICATION_CHECK = "Unit tests (not pg)"
_REQUIRED_VERIFICATION_WORKFLOW = ".github/workflows/ci-smoke.yaml"


def _latest_github_result(
    rows: list[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Select one authoritative rerun, failing closed on ambiguous history."""

    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    ordered: list[tuple[str, int, Mapping[str, Any]]] = []
    for row in rows:
        timestamp = next(
            (
                row.get(field)
                for field in (
                    "completed_at",
                    "updated_at",
                    "started_at",
                    "created_at",
                )
                if isinstance(row.get(field), str) and row.get(field)
            ),
            None,
        )
        row_id = row.get("id")
        if (
            not isinstance(timestamp, str)
            or not isinstance(row_id, int)
            or isinstance(row_id, bool)
        ):
            return None
        ordered.append((timestamp, row_id, row))
    return max(ordered, key=lambda item: (item[0], item[1]))[2]


class ConditionalMergeTransport(Protocol):
    """GitHub-enforced merge queue/conditional transport.

    A direct REST merge implementation is intentionally not supplied because
    GitHub's ordinary merge endpoint cannot atomically fence both protected
    base OID and manifest blob OID. Deployments must provide a merge-queue
    transport that revalidates the queue-selected base.
    """

    def merge(
        self,
        repository: str,
        pr_number: int,
        *,
        expected_head_sha: str,
        expected_base_sha: str,
        expected_manifest_blob_sha: str,
        commit_title: str,
        commit_message: str,
        credential: object,
    ) -> Mapping[str, object]: ...


class GitHubProtectedRepositoryAuthority:
    """REST read authority plus an explicitly injected conditional effect."""

    def __init__(
        self,
        token: str,
        *,
        manifest_path: str = _DEFAULT_MANIFEST_PATH,
        http_client: httpx.Client | None = None,
        conditional_transport: ConditionalMergeTransport | None = None,
    ) -> None:
        if not token.strip():
            raise MergeAuthorityError("GitHub read credential is unavailable")
        if not manifest_path or manifest_path.startswith("/"):
            raise MergeAuthorityError(
                "protected delivery manifest path must be repository-relative"
            )
        self._token = token
        self.manifest_path = manifest_path
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url="https://api.github.com", timeout=20.0
        )
        self.conditional_transport = conditional_transport

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def _get(self, path: str, **params: object) -> Mapping[str, Any]:
        response = self._http.get(
            path,
            params={key: str(value) for key, value in params.items()},
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if response.status_code >= 400:
            raise MergeAuthorityError(
                f"GitHub protected-repository read failed ({response.status_code})"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise MergeAuthorityError("GitHub returned malformed JSON") from exc
        if not isinstance(body, Mapping):
            raise MergeAuthorityError("GitHub returned an unexpected response")
        return body

    def _get_list(
        self, path: str, **params: object
    ) -> list[Mapping[str, Any]]:
        response = self._http.get(
            path,
            params={key: str(value) for key, value in params.items()},
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if response.status_code >= 400:
            raise MergeAuthorityError(
                f"GitHub protected-repository read failed ({response.status_code})"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise MergeAuthorityError("GitHub returned malformed JSON") from exc
        if not isinstance(body, list) or any(
            not isinstance(row, Mapping) for row in body
        ):
            raise MergeAuthorityError("GitHub returned an unexpected response")
        return body

    def _graphql(
        self, query: str, variables: Mapping[str, object]
    ) -> Mapping[str, Any]:
        response = self._http.post(
            "/graphql",
            json={"query": query, "variables": dict(variables)},
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
            },
        )
        if response.status_code >= 400:
            raise MergeAuthorityError(
                f"GitHub merge-authority read failed ({response.status_code})"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise MergeAuthorityError("GitHub returned malformed JSON") from exc
        if (
            not isinstance(body, Mapping)
            or body.get("errors")
            or not isinstance(body.get("data"), Mapping)
        ):
            raise MergeAuthorityError(
                "GitHub merge-authority response is malformed"
            )
        return body

    def _repository(self, repository: str) -> Mapping[str, Any]:
        canonical = RepoRef.parse(repository).canonical
        return self._get(f"/repos/{canonical}")

    def _default_branch(self, repository: str) -> str:
        branch = self._repository(repository).get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise MergeAuthorityError("GitHub default branch is unavailable")
        return branch

    def protected_base_sha(self, repository: str) -> str:
        canonical = RepoRef.parse(repository).canonical
        branch = self._default_branch(canonical)
        ref = self._get(f"/repos/{canonical}/git/ref/heads/{branch}")
        target = ref.get("object")
        sha = target.get("sha") if isinstance(target, Mapping) else None
        if not isinstance(sha, str) or len(sha) != 40:
            raise MergeAuthorityError("protected default-branch OID is malformed")
        return sha

    def delivery_manifest(
        self, repository: str, base_sha: str
    ) -> ProtectedDeliveryManifest:
        canonical = RepoRef.parse(repository).canonical
        response = self._get(
            f"/repos/{canonical}/contents/{self.manifest_path}",
            ref=base_sha,
        )
        if (
            response.get("type") != "file"
            or response.get("encoding") != "base64"
            or not isinstance(response.get("sha"), str)
            or not isinstance(response.get("content"), str)
        ):
            raise MergeAuthorityError("protected delivery manifest is unavailable")
        try:
            content = base64.b64decode(
                str(response["content"]), validate=True
            )
        except (ValueError, TypeError) as exc:
            raise MergeAuthorityError(
                "protected delivery manifest encoding is invalid"
            ) from exc
        if len(content) > _MAX_MANIFEST_BYTES:
            raise MergeAuthorityError("protected delivery manifest is oversized")
        try:
            document = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MergeAuthorityError(
                "protected delivery manifest is malformed"
            ) from exc
        if not isinstance(document, Mapping):
            raise MergeAuthorityError(
                "protected delivery manifest must be an object"
            )
        return ProtectedDeliveryManifest.from_document(
            document,
            repository=canonical,
            base_sha=base_sha,
            blob_sha=str(response["sha"]),
        )

    def _pull(self, repository: str, pr_number: int) -> Mapping[str, Any]:
        canonical = RepoRef.parse(repository).canonical
        return self._get(f"/repos/{canonical}/pulls/{pr_number}")

    def current_pr_head(self, repository: str, pr_number: int) -> str:
        pull = self._pull(repository, pr_number)
        head = pull.get("head")
        sha = head.get("sha") if isinstance(head, Mapping) else None
        if not isinstance(sha, str) or len(sha) != 40:
            raise MergeAuthorityError("pull request head OID is malformed")
        return sha

    def _issue_comments(
        self, repository: str, pr_number: int
    ) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        for page in range(1, 11):
            batch = self._get_list(
                f"/repos/{repository}/issues/{pr_number}/comments",
                per_page=100,
                page=page,
            )
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise MergeAuthorityError(
            "GitHub merge-authority comments exceed bounded scan"
        )

    def _closing_issue_references(
        self, repository: str, pr_number: int
    ) -> Sequence[Mapping[str, Any]]:
        owner, name = RepoRef.parse(repository).canonical.split("/", 1)
        body = self._graphql(
            """
            query($owner: String!, $name: String!, $number: Int!) {
              repository(owner: $owner, name: $name) {
                pullRequest(number: $number) {
                  closingIssuesReferences(first: 11) {
                    nodes {
                      number
                      repository { nameWithOwner }
                    }
                    pageInfo { hasNextPage }
                  }
                }
              }
            }
            """,
            {"owner": owner, "name": name, "number": pr_number},
        )
        data = body["data"]
        repository_row = data.get("repository")
        pull = (
            repository_row.get("pullRequest")
            if isinstance(repository_row, Mapping)
            else None
        )
        closing = (
            pull.get("closingIssuesReferences")
            if isinstance(pull, Mapping)
            else None
        )
        nodes = closing.get("nodes") if isinstance(closing, Mapping) else None
        page_info = (
            closing.get("pageInfo")
            if isinstance(closing, Mapping)
            else None
        )
        if (
            not isinstance(nodes, list)
            or any(not isinstance(row, Mapping) for row in nodes)
            or not isinstance(page_info, Mapping)
            or page_info.get("hasNextPage") is not False
        ):
            raise MergeAuthorityError(
                "GitHub closing-reference evidence is incomplete"
            )
        return nodes

    def verified_merge_prepared(
        self,
        repository: str,
        pr_number: int,
        *,
        run_id: str,
        head_sha: str,
        expected_repair_budget: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Authenticate the exact neutralized/prepared merge window."""

        canonical = RepoRef.parse(repository).canonical
        pull = self._pull(canonical, pr_number)
        body = pull.get("body")
        title = pull.get("title")
        head = pull.get("head")
        observed_head = (
            head.get("sha") if isinstance(head, Mapping) else None
        )
        neutralized = resolve_neutralized_issue_authority(body)
        if (
            pull.get("number") != pr_number
            or pull.get("state") != "open"
            or pull.get("merged") is True
            or pull.get("merged_at") is not None
            or observed_head != head_sha
            or neutralized is None
            or has_closing_issue_attempt(title)
            or has_closing_issue_attempt(body)
        ):
            raise MergeAuthorityError(
                "real merge requires the exact neutralized live PR"
            )
        comments = self._issue_comments(canonical, pr_number)
        authority = resolve_verified_merge_authority_receipt(
            comments,
            pr=pull,
            repository=canonical,
            expected_run_id=run_id,
            expected_repair_budget=expected_repair_budget,
        )
        if authority is None:
            raise MergeAuthorityError(
                "real merge requires one authenticated authority receipt"
            )
        phase = resolve_verified_merge_phase(
            comments,
            authority_receipt=authority,
            pr=pull,
        )
        if (
            phase is None
            or phase.get("phase") != "prepared"
            or phase.get("closed_issues") != []
            or phase.get("reopened_unauthorized_issues") != []
            or phase.get("merge_commit_sha") is not None
            or self._closing_issue_references(canonical, pr_number)
        ):
            raise MergeAuthorityError(
                "real merge requires empty closers and a continuous prepared phase"
            )

        def digest(value: Mapping[str, object]) -> str:
            return hashlib.sha256(
                json.dumps(
                    dict(value),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()

        return {
            "contract": "verified_merge_prepared_gate.v1",
            "repository": canonical,
            "pr_number": pr_number,
            "run_id": run_id,
            "head_sha": head_sha,
            "governing_issue": authority.get("governing_issue"),
            "closing_issues": authority.get("closing_issues"),
            "neutralized_body_sha256": authority.get(
                "neutralized_body_sha256"
            ),
            "authority_sha256": digest(authority),
            "phase_sha256": digest(phase),
            "closing_reference_count": 0,
            "fixed_commit_title": fixed_verified_merge_commit_title(pr_number),
            "fixed_commit_message": FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
        }

    def _check_runs(
        self, repository: str, head_sha: str
    ) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        for page in range(1, 11):
            payload = self._get(
                f"/repos/{repository}/commits/{head_sha}/check-runs",
                per_page=100,
                page=page,
                filter="all",
            )
            batch = payload.get("check_runs")
            total = payload.get("total_count")
            if (
                not isinstance(batch, list)
                or not isinstance(total, int)
                or isinstance(total, bool)
                or total < len(rows) + len(batch)
                or any(not isinstance(row, Mapping) for row in batch)
            ):
                raise MergeAuthorityError("GitHub check-run listing is malformed")
            rows.extend(batch)
            if len(rows) == total:
                return rows
            if len(batch) < 100:
                raise MergeAuthorityError("GitHub check-run listing is incomplete")
        raise MergeAuthorityError("GitHub check-run listing exceeds bounded scan")

    def _commit_statuses(
        self, repository: str, head_sha: str
    ) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        for page in range(1, 11):
            payload = self._get(
                f"/repos/{repository}/commits/{head_sha}/status",
                per_page=100,
                page=page,
            )
            batch = payload.get("statuses")
            total = payload.get("total_count")
            if (
                not isinstance(batch, list)
                or not isinstance(total, int)
                or isinstance(total, bool)
                or total < len(rows) + len(batch)
                or any(not isinstance(row, Mapping) for row in batch)
            ):
                raise MergeAuthorityError(
                    "GitHub commit-status listing is malformed"
                )
            rows.extend(batch)
            if len(rows) == total:
                return rows
            if len(batch) < 100:
                raise MergeAuthorityError(
                    "GitHub commit-status listing is incomplete"
                )
        raise MergeAuthorityError("GitHub commit-status listing exceeds bounded scan")

    def _workflow_runs(
        self, repository: str, head_sha: str
    ) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        for page in range(1, 11):
            payload = self._get(
                f"/repos/{repository}/actions/runs",
                head_sha=head_sha,
                per_page=100,
                page=page,
            )
            batch = payload.get("workflow_runs")
            total = payload.get("total_count")
            if (
                not isinstance(batch, list)
                or not isinstance(total, int)
                or isinstance(total, bool)
                or total < len(rows) + len(batch)
                or any(not isinstance(row, Mapping) for row in batch)
            ):
                raise MergeAuthorityError(
                    "GitHub workflow-run listing is malformed"
                )
            rows.extend(batch)
            if len(rows) == total:
                return rows
            if len(batch) < 100:
                raise MergeAuthorityError(
                    "GitHub workflow-run listing is incomplete"
                )
        raise MergeAuthorityError(
            "GitHub workflow-run listing exceeds bounded scan"
        )

    def required_gates(
        self, repository: str, pr_number: int, head_sha: str
    ) -> Mapping[str, bool]:
        canonical = RepoRef.parse(repository).canonical
        pull = self._pull(canonical, pr_number)
        default_branch = self._default_branch(canonical)
        head = pull.get("head")
        base = pull.get("base")
        base_repo = base.get("repo") if isinstance(base, Mapping) else None
        base_ref = base.get("ref") if isinstance(base, Mapping) else None
        observed_head = head.get("sha") if isinstance(head, Mapping) else None
        base_full_name = (
            base_repo.get("full_name") if isinstance(base_repo, Mapping) else None
        )
        rows = self._check_runs(canonical, head_sha)
        statuses = self._commit_statuses(canonical, head_sha)
        protection_document = self._get(
            f"/repos/{canonical}/branches/{default_branch}/protection"
        )
        required_status_checks = protection_document.get(
            "required_status_checks"
        )
        required: set[tuple[str, int | None]] = set()
        if isinstance(required_status_checks, Mapping):
            contexts = required_status_checks.get("contexts", [])
            checks = required_status_checks.get("checks", [])
            if not isinstance(contexts, list) or not isinstance(checks, list):
                raise MergeAuthorityError(
                    "GitHub required-status-check policy is malformed"
                )
            for context in contexts:
                if not isinstance(context, str) or not context:
                    raise MergeAuthorityError(
                        "GitHub required status context is malformed"
                    )
                required.add((context, None))
            for check in checks:
                if (
                    not isinstance(check, Mapping)
                    or not isinstance(check.get("context"), str)
                    or not check.get("context")
                    or (
                        check.get("app_id") is not None
                        and (
                            not isinstance(check.get("app_id"), int)
                            or isinstance(check.get("app_id"), bool)
                        )
                    )
                ):
                    raise MergeAuthorityError(
                        "GitHub required check policy is malformed"
                    )
                required.add((str(check["context"]), check.get("app_id")))
        protected_required = bool(required)
        # verification-and-closure retains this behavioral gate even if
        # branch protection exposes it through the legacy contexts shape or
        # is temporarily misconfigured. A legacy status can never substitute
        # for the authenticated ci-smoke workflow run.
        required.add((_REQUIRED_VERIFICATION_CHECK, None))
        status_history: dict[str, list[Mapping[str, Any]]] = {}
        for row in statuses:
            context = row.get("context")
            if isinstance(context, str):
                status_history.setdefault(context, []).append(row)
        latest_statuses = {
            context: _latest_github_result(history)
            for context, history in status_history.items()
        }
        workflow_rows = self._workflow_runs(canonical, head_sha)
        workflows_by_suite: dict[int, list[Mapping[str, Any]]] = {}
        for workflow in workflow_rows:
            suite_id = workflow.get("check_suite_id")
            if isinstance(suite_id, int) and not isinstance(suite_id, bool):
                workflows_by_suite.setdefault(suite_id, []).append(workflow)
        pull_request_workflow_suites = {
            suite_id
            for suite_id, candidates in workflows_by_suite.items()
            if len(candidates) == 1
            and candidates[0].get("event") == "pull_request"
            and candidates[0].get("head_sha") == head_sha
        }
        check_history: dict[
            tuple[str, int | None], list[Mapping[str, Any]]
        ] = {}
        for row in rows:
            name = row.get("name")
            app = row.get("app")
            app_id = app.get("id") if isinstance(app, Mapping) else None
            suite = row.get("check_suite")
            suite_id = (
                suite.get("id") if isinstance(suite, Mapping) else None
            )
            if (
                isinstance(app, Mapping)
                and app.get("slug") == "github-actions"
                and suite_id not in pull_request_workflow_suites
            ):
                continue
            if isinstance(name, str):
                check_history.setdefault((name, app_id), []).append(row)
        latest_checks = {
            identity: _latest_github_result(history)
            for identity, history in check_history.items()
        }
        authenticated_workflow_suites: set[int] = set()
        if any(
            context == _REQUIRED_VERIFICATION_CHECK
            for context, _app_id in required
        ):
            authenticated_workflow_suites = {
                suite_id
                for suite_id, candidates in workflows_by_suite.items()
                if suite_id in pull_request_workflow_suites
                and candidates[0].get("path")
                == _REQUIRED_VERIFICATION_WORKFLOW
            }

        def successful_status(context: str) -> bool:
            row = latest_statuses.get(context)
            return isinstance(row, Mapping) and row.get("state") == "success"

        def successful_check(context: str, app_id: int | None) -> bool:
            candidates = (
                [latest_checks.get((context, app_id))]
                if app_id is not None
                else [
                    row
                    for (name, _candidate_app), row in latest_checks.items()
                    if name == context
                ]
            )
            return any(
                isinstance(row, Mapping)
                and row.get("status") == "completed"
                and row.get("conclusion") == "success"
                and (
                    context != _REQUIRED_VERIFICATION_CHECK
                    or (
                        isinstance(row.get("app"), Mapping)
                        and row["app"].get("slug") == "github-actions"
                        and isinstance(row.get("check_suite"), Mapping)
                        and row["check_suite"].get("id")
                        in authenticated_workflow_suites
                    )
                )
                for row in candidates
            )

        latest_repo_checks = [
            row
            for row in latest_checks.values()
            if isinstance(row, Mapping)
        ]
        repo_standard_checks_green = bool(latest_repo_checks) and all(
            row.get("status") == "completed"
            and row.get("conclusion")
            in {"success", "skipped", "neutral"}
            for row in latest_repo_checks
        )
        ci = bool(
            required
            and repo_standard_checks_green
            and all(
                (
                    successful_check(context, app_id)
                    if (
                        app_id is not None
                        or context == _REQUIRED_VERIFICATION_CHECK
                    )
                    else (
                        successful_status(context)
                        or successful_check(context, None)
                    )
                )
                for context, app_id in required
            )
        )
        protection = (
            isinstance(required_status_checks, Mapping)
            and protected_required
        )
        return {
            "ci": ci,
            # The executor independently requires ledger.closure_ready(); this
            # flag records that the repository adapter did not weaken it.
            "review": True,
            "protection": protection,
            "scope": (
                isinstance(base_full_name, str)
                and base_full_name.lower() == canonical
                and base_ref == default_branch
            ),
            "current_head": observed_head == head_sha,
        }

    def conditional_merge(
        self,
        repository: str,
        pr_number: int,
        *,
        expected_head_sha: str,
        expected_base_sha: str,
        expected_manifest_blob_sha: str,
        commit_title: str,
        commit_message: str,
        credential: object,
    ) -> Mapping[str, object]:
        if self.conditional_transport is None:
            raise MergeAuthorityError(
                "no GitHub-enforced merge-queue/conditional transport is configured"
            )
        return self.conditional_transport.merge(
            repository,
            pr_number,
            expected_head_sha=expected_head_sha,
            expected_base_sha=expected_base_sha,
            expected_manifest_blob_sha=expected_manifest_blob_sha,
            commit_title=commit_title,
            commit_message=commit_message,
            credential=credential,
        )

    def merge_readback(
        self, repository: str, pr_number: int
    ) -> Mapping[str, object]:
        pull = self._pull(repository, pr_number)
        head = pull.get("head")
        merge_commit_sha = pull.get("merge_commit_sha")
        merge_commit_title: str | None = None
        merge_commit_message: str | None = None
        if pull.get("merged") is True and isinstance(merge_commit_sha, str):
            commit = self._get(
                f"/repos/{repository}/commits/{merge_commit_sha}"
            ).get("commit")
            raw_message = (
                commit.get("message")
                if isinstance(commit, Mapping)
                else None
            )
            if isinstance(raw_message, str):
                title, separator, message = raw_message.partition("\n")
                merge_commit_title = title
                merge_commit_message = (
                    message.lstrip("\n") if separator else ""
                )
        return {
            "merged": pull.get("merged") is True,
            "head_sha": head.get("sha") if isinstance(head, Mapping) else None,
            "merge_commit_sha": merge_commit_sha,
            "merge_commit_title": merge_commit_title,
            "merge_commit_message": merge_commit_message,
            "merged_at": pull.get("merged_at"),
        }


class HostCredentialManifestResolver:
    """Resolve an exact repo/id/generation binding from host-owned files."""

    def __init__(self, manifest_file: str | Path) -> None:
        self.manifest_file = Path(manifest_file)

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> "HostCredentialManifestResolver":
        source = os.environ if env is None else env
        path = source.get(
            "BUILDEROPS_EXECUTOR_CREDENTIAL_MANIFEST_FILE", ""
        ).strip()
        if not path:
            raise MergeAuthorityError(
                "BUILDEROPS_EXECUTOR_CREDENTIAL_MANIFEST_FILE is required"
            )
        return cls(path)

    def resolve(
        self,
        *,
        repository: str,
        credential_id: str,
        rotation_generation: int,
    ) -> object:
        canonical = RepoRef.parse(repository).canonical
        try:
            document = json.loads(
                self.manifest_file.read_text(encoding="utf-8")
            )
            entries = document["credentials"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise MergeAuthorityError(
                "host credential manifest is unavailable"
            ) from exc
        if not isinstance(entries, list):
            raise MergeAuthorityError("host credential manifest is malformed")
        matches = [
            entry
            for entry in entries
            if isinstance(entry, Mapping)
            and str(entry.get("repository", "")).lower() == canonical
            and entry.get("credential_id") == credential_id
            and entry.get("rotation_generation") == rotation_generation
        ]
        if len(matches) != 1:
            raise MergeAuthorityError(
                "host credential binding is missing or ambiguous"
            )
        secret_file = matches[0].get("secret_file")
        if not isinstance(secret_file, str) or not secret_file:
            raise MergeAuthorityError("host credential secret reference is missing")
        try:
            token = Path(secret_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise MergeAuthorityError(
                "host credential secret is unavailable"
            ) from exc
        if not token:
            raise MergeAuthorityError("host credential secret is empty")
        return token


__all__ = [
    "ConditionalMergeTransport",
    "GitHubProtectedRepositoryAuthority",
    "HostCredentialManifestResolver",
]
