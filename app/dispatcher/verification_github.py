"""Live protected-repository and host-credential adapters for BCP-05."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol, cast

import httpx

from app.builderops.control_plane.routing import RepoRef
from app.dispatcher.verification_merge import (
    MergeAuthorityError,
    ProtectedDeliveryManifest,
)
from app.dispatcher.verification_contract import (
    has_closing_issue_attempt,
    resolve_neutralized_issue_authority,
    resolve_issue_authority,
    resolve_final_review_rounds,
)
from app.dispatcher.verified_merge import (
    FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
    fixed_verified_merge_commit_title,
    neutralized_body_matches_authority,
    resolve_verified_merge_authority_receipt,
    resolve_verified_merge_phase,
    verified_merge_body_sha256,
    plan_post_merge_reconciliation,
    VERIFIED_MERGE_AUTHORITY_MARKER,
    VERIFIED_MERGE_PHASE_MARKER,
)

_DEFAULT_MANIFEST_PATH = ".builderops/delivery-manifest.json"
_MAX_MANIFEST_BYTES = 65_536
_REQUIRED_VERIFICATION_CHECK = "Unit tests (not pg)"
_REQUIRED_VERIFICATION_WORKFLOW = ".github/workflows/ci-smoke.yaml"
_NATIVE_WEB_ISSUE_REFERENCE = re.compile(
    r"https?://github[.]com/([0-9A-Za-z_.-]+)/([0-9A-Za-z_.-]+)/issues/([1-9][0-9]*)",
    re.IGNORECASE,
)
_NATIVE_API_ISSUE_REFERENCE = re.compile(
    r"https?://api[.]github[.]com/repos/([0-9A-Za-z_.-]+)/([0-9A-Za-z_.-]+)/issues/([1-9][0-9]*)",
    re.IGNORECASE,
)
_NATIVE_QUALIFIED_ISSUE_REFERENCE = re.compile(
    r"(?<![0-9A-Za-z_.-])([0-9A-Za-z_.-]+)/([0-9A-Za-z_.-]+)#([1-9][0-9]*)"
)


def _latest_github_result(
    rows: list[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Select one authoritative rerun, failing closed on ambiguous history."""

    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    ordered: list[tuple[datetime, int, Mapping[str, Any]]] = []
    for row in rows:
        timestamps: list[datetime] = []
        for field in (
            "completed_at",
            "updated_at",
            "started_at",
            "created_at",
        ):
            value = row.get(field)
            if value is None:
                continue
            if not isinstance(value, str) or not value:
                raise MergeAuthorityError(
                    "GitHub rerun history timestamp is malformed"
                )
            try:
                instant = datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise MergeAuthorityError(
                    "GitHub rerun history timestamp is malformed"
                ) from exc
            if instant.tzinfo is None:
                raise MergeAuthorityError(
                    "GitHub rerun history timestamp is malformed"
                )
            timestamps.append(instant)
        row_id = row.get("id")
        if (
            not timestamps
            or not isinstance(row_id, int)
            or isinstance(row_id, bool)
        ):
            raise MergeAuthorityError(
                "GitHub rerun history is malformed"
            )
        ordered.append((timestamps[0], row_id, row))
    return max(ordered, key=lambda item: (item[0], item[1]))[2]


def _workflow_runs_by_suite(
    rows: list[Mapping[str, Any]],
    *,
    head_sha: str,
) -> dict[int, Mapping[str, Any]]:
    """Resolve one unambiguous workflow run per check suite."""

    candidates_by_suite: dict[int, list[Mapping[str, Any]]] = {}
    for row in rows:
        suite_id = row.get("check_suite_id")
        if (
            not isinstance(suite_id, int)
            or isinstance(suite_id, bool)
            or suite_id <= 0
            or not isinstance(row.get("workflow_id"), int)
            or isinstance(row.get("workflow_id"), bool)
            or row["workflow_id"] <= 0
            or not isinstance(row.get("path"), str)
            or not row["path"]
            or not isinstance(row.get("event"), str)
            or not row["event"]
            or row.get("head_sha") != head_sha
            or not isinstance(row.get("run_attempt"), int)
            or isinstance(row.get("run_attempt"), bool)
            or row["run_attempt"] <= 0
        ):
            raise MergeAuthorityError(
                "GitHub workflow-suite provenance is malformed"
            )
        candidates_by_suite.setdefault(suite_id, []).append(row)

    resolved: dict[int, Mapping[str, Any]] = {}
    for suite_id, candidates in candidates_by_suite.items():
        if len(candidates) > 1:
            identities = {
                (
                    candidate.get("workflow_id"),
                    candidate.get("path"),
                    candidate.get("event"),
                    candidate.get("head_sha"),
                    candidate.get("check_suite_id"),
                )
                for candidate in candidates
            }
            attempts = [candidate.get("run_attempt") for candidate in candidates]
            if (
                len(identities) != 1
                or any(
                    not isinstance(attempt, int)
                    or isinstance(attempt, bool)
                    or attempt <= 0
                    for attempt in attempts
                )
                or len(set(attempts)) != len(attempts)
            ):
                raise MergeAuthorityError(
                    "GitHub workflow-suite provenance is ambiguous"
                )
        selected = _latest_github_result(candidates)
        if selected is None:
            raise MergeAuthorityError(
                "GitHub workflow-suite provenance is unavailable"
            )
        resolved[suite_id] = selected
    return resolved


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
        expected_body_edit: Mapping[str, object],
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
        self._http = http_client or httpx.Client(base_url="https://api.github.com", timeout=20.0)
        self.conditional_transport = conditional_transport
        self._native_merge_lock = threading.RLock()
        self.closure_source: Any = None

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

    def issue_delivery_source(self, repository: str, number: int) -> Mapping[str, Any]:
        """Read the exact independently addressed tracking Issue."""
        canonical = RepoRef.parse(repository).canonical
        return self._get(f"/repos/{canonical}/issues/{number}")

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

    def _current_body_edit(
        self, repository: str, pr_number: int
    ) -> Mapping[str, object]:
        """Read the live, trusted body-edit identity for a prepared gate."""

        owner, name = RepoRef.parse(repository).canonical.split("/", 1)
        response = self._graphql(
            """
            query($owner: String!, $name: String!, $number: Int!) {
              repository(owner: $owner, name: $name) {
                pullRequest(number: $number) {
                  userContentEdits(first: 1) {
                    nodes { id editedAt editor { login } }
                    pageInfo { hasNextPage }
                  }
                }
              }
            }
            """,
            {"owner": owner, "name": name, "number": pr_number},
        )
        data = response["data"]
        repository_row = data.get("repository")
        pull = (
            repository_row.get("pullRequest")
            if isinstance(repository_row, Mapping)
            else None
        )
        edits = pull.get("userContentEdits") if isinstance(pull, Mapping) else None
        nodes = edits.get("nodes") if isinstance(edits, Mapping) else None
        page_info = edits.get("pageInfo") if isinstance(edits, Mapping) else None
        if (
            not isinstance(nodes, list)
            or len(nodes) != 1
            or not isinstance(nodes[0], Mapping)
            or not isinstance(page_info, Mapping)
            or not isinstance(page_info.get("hasNextPage"), bool)
        ):
            raise MergeAuthorityError("GitHub body-edit evidence is incomplete")
        edit = nodes[0]
        editor = edit.get("editor")
        login = editor.get("login") if isinstance(editor, Mapping) else None
        if (
            not isinstance(edit.get("id"), str)
            or not edit.get("id")
            or not isinstance(edit.get("editedAt"), str)
            or not edit.get("editedAt")
            or not isinstance(login, str)
            or not login
        ):
            raise MergeAuthorityError("GitHub body-edit identity is malformed")
        if login.casefold() == owner.casefold():
            association = "OWNER"
        else:
            permission = self._get(
                f"/repos/{repository}/collaborators/{login}/permission"
            ).get("permission")
            if permission not in {"admin", "maintain", "write"}:
                raise MergeAuthorityError(
                    "GitHub body editor is not an authenticated collaborator"
                )
            association = "COLLABORATOR"
        return {
            "node_id": edit["id"],
            "edited_at": edit["editedAt"],
            "editor_login": login,
            "editor_association": association,
        }

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
        assert isinstance(body, str)
        observed_body_sha256 = verified_merge_body_sha256(body)
        if not neutralized_body_matches_authority(body, authority, comments):
            raise MergeAuthorityError(
                "real merge neutralized body digest did not converge"
            )
        body_edit_before_projection = self._current_body_edit(
            canonical, pr_number
        )
        closing_references = self._closing_issue_references(
            canonical, pr_number
        )
        body_edit_after_projection = self._current_body_edit(
            canonical, pr_number
        )
        if body_edit_after_projection != body_edit_before_projection:
            raise MergeAuthorityError(
                "GitHub body edit changed during final closing projection read"
            )
        phase = resolve_verified_merge_phase(
            comments,
            authority_receipt=authority,
            pr=pull,
            current_body_edit=body_edit_after_projection,
        )
        if (
            phase is None
            or phase.get("phase") != "prepared"
            or phase.get("contract") != "verified_issue_set_merge_phase.v2"
            or phase.get("closed_issues") != []
            or phase.get("reopened_unauthorized_issues") != []
            or phase.get("merge_commit_sha") is not None
            or closing_references
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
            "neutralized_body_sha256": observed_body_sha256,
            "authority_sha256": digest(authority),
            "phase_sha256": digest(phase),
            "body_edit": dict(body_edit_after_projection),
            "closing_reference_count": 0,
            "fixed_commit_title": fixed_verified_merge_commit_title(pr_number),
            "fixed_commit_message": FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
        }

    def native_single_closer_prepared(
        self,
        repository: str,
        pr_number: int,
        *,
        run_id: str,
        head_sha: str,
    ) -> Mapping[str, object] | None:
        """Read an exact, complete single-closer snapshot; ambiguity grants no authority."""
        canonical = RepoRef.parse(repository).canonical
        pull = self._pull(canonical, pr_number)
        body, title = pull.get("body"), pull.get("title")
        authority = resolve_issue_authority(body)
        referenced_issues: set[int] = set()
        referenced_repositories: set[str] = set()
        if isinstance(body, str):
            referenced_issues.update(int(n) for n in re.findall(r"#([1-9][0-9]*)", body))
            for pattern in (
                _NATIVE_WEB_ISSUE_REFERENCE,
                _NATIVE_API_ISSUE_REFERENCE,
                _NATIVE_QUALIFIED_ISSUE_REFERENCE,
            ):
                for owner, name, number in pattern.findall(body):
                    referenced_repositories.add(f"{owner}/{name}".lower())
                    referenced_issues.add(int(number))
        if (
            authority is None
            or resolve_final_review_rounds(body) is None
            or authority.closing_issues != (authority.governing_issue,)
            or authority.supporting_issues
            or not isinstance(body, str)
            or not isinstance(title, str)
            or has_closing_issue_attempt(title)
            or referenced_repositories - {canonical}
            or referenced_issues != {authority.governing_issue}
        ):
            return None
        comments = self._issue_comments(canonical, pr_number)
        if any(VERIFIED_MERGE_AUTHORITY_MARKER in str(row.get("body", ""))
               or VERIFIED_MERGE_PHASE_MARKER in str(row.get("body", "")) for row in comments):
            return None
        base, head = pull.get("base"), pull.get("head")
        base_repo = base.get("repo") if isinstance(base, Mapping) else None
        exact_repository = base_repo.get("full_name") if isinstance(base_repo, Mapping) else None
        if (
            pull.get("number") != pr_number
            or pull.get("state") != "open"
            or pull.get("merged") is not False
            or pull.get("merged_at") is not None
            or pull.get("draft") is not False
            or not isinstance(head, Mapping)
            or head.get("sha") != head_sha
            or not isinstance(base, Mapping)
            or not isinstance(base.get("sha"), str)
            or len(base["sha"]) != 40
            or not isinstance(exact_repository, str)
            or exact_repository.lower() != canonical
            or base.get("ref") != self._default_branch(canonical)
            or pull.get("html_url") != f"https://github.com/{exact_repository}/pull/{pr_number}"
        ):
            raise MergeAuthorityError("native single-closer PR identity is incomplete")
        owner, name = exact_repository.split("/", 1)
        numbers: list[int] = []
        cursors: set[str] = set()
        cursor = None
        for _ in range(10):
            response = self._graphql(
                """
              query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
                repository(owner:$owner,name:$name) { pullRequest(number:$number) {
                  closingIssuesReferences(first:100,after:$cursor) {
                    nodes { number repository { nameWithOwner } }
                    pageInfo { hasNextPage endCursor }
                  }
                } }
              }
            """,
                {"owner": owner, "name": name, "number": pr_number, "cursor": cursor},
            )
            data = response["data"]
            repo_row = data.get("repository")
            pr_row = repo_row.get("pullRequest") if isinstance(repo_row, Mapping) else None
            links = pr_row.get("closingIssuesReferences") if isinstance(pr_row, Mapping) else None
            nodes = links.get("nodes") if isinstance(links, Mapping) else None
            page = links.get("pageInfo") if isinstance(links, Mapping) else None
            if (
                not isinstance(nodes, list)
                or len(nodes) > 100
                or not isinstance(page, Mapping)
                or type(page.get("hasNextPage")) is not bool
            ):
                raise MergeAuthorityError("native closing pagination is incomplete")
            for node in nodes:
                repo = node.get("repository") if isinstance(node, Mapping) else None
                number = node.get("number") if isinstance(node, Mapping) else None
                if (
                    type(number) is not int
                    or number < 1
                    or number in numbers
                    or not isinstance(repo, Mapping)
                    or repo.get("nameWithOwner") != exact_repository
                ):
                    raise MergeAuthorityError("native closing pagination identity drift")
                numbers.append(number)
            if page["hasNextPage"] is False:
                break
            next_cursor = page.get("endCursor")
            if (
                not nodes
                or not isinstance(next_cursor, str)
                or not next_cursor
                or next_cursor in cursors
            ):
                raise MergeAuthorityError("native closing cursor failed to advance")
            cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise MergeAuthorityError("native closing pagination exceeds bounded read")
        if numbers != [authority.governing_issue]:
            return None
        issue = self._get(f"/repos/{canonical}/issues/{authority.governing_issue}")
        if issue.get("state") != "open":
            return None
        if (
            issue.get("number") != authority.governing_issue
            or "pull_request" in issue
            or issue.get("repository_url") != f"https://api.github.com/repos/{exact_repository}"
            or not isinstance(issue.get("updated_at"), str)
            or not isinstance(issue.get("body"), str)
        ):
            raise MergeAuthorityError("native governing Issue snapshot is incomplete")
        threads = self._native_threads_resolved(canonical, pr_number)
        if (
            self._pull(canonical, pr_number) != pull
            or self._get(f"/repos/{canonical}/issues/{authority.governing_issue}") != issue
        ):
            raise MergeAuthorityError("native PR or Issue snapshot drifted during pagination")
        snapshot = {
            "repository": exact_repository,
            "pr_number": pr_number,
            "run_id": run_id,
            "head_sha": head_sha,
            "base_sha": base["sha"],
            "title": title,
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "governing_issue": authority.governing_issue,
            "final_review_rounds": resolve_final_review_rounds(body),
            "closing_issues": numbers,
            "issue_updated_at": issue["updated_at"],
            "issue_body_sha256": hashlib.sha256(issue["body"].encode()).hexdigest(),
            "review_threads_sha256": hashlib.sha256(
                json.dumps(threads, sort_keys=True).encode()
            ).hexdigest(),
        }
        return {
            "contract": "native_single_closer_gate.v1",
            **snapshot,
            "closing_reference_count": 1,
            "body_edit": {"native_snapshot": snapshot},
            "fixed_commit_title": fixed_verified_merge_commit_title(pr_number),
            "fixed_commit_message": FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
        }

    def _native_threads_resolved(self, repository: str, pr_number: int) -> list[object]:
        owner, name = repository.split("/", 1)
        cursor = None
        seen: set[str] = set()
        threads: list[object] = []
        for _ in range(10):
            response = self._graphql(
                """
              query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
                repository(owner:$owner,name:$name) { pullRequest(number:$number) {
                  reviewThreads(first:100,after:$cursor) {
                    nodes { id isResolved } pageInfo { hasNextPage endCursor }
                  }
                } }
              }
            """,
                {"owner": owner, "name": name, "number": pr_number, "cursor": cursor},
            )
            repo = response["data"].get("repository")
            pull = repo.get("pullRequest") if isinstance(repo, Mapping) else None
            connection = pull.get("reviewThreads") if isinstance(pull, Mapping) else None
            nodes = connection.get("nodes") if isinstance(connection, Mapping) else None
            page = connection.get("pageInfo") if isinstance(connection, Mapping) else None
            if (
                not isinstance(nodes, list)
                or len(nodes) > 100
                or not isinstance(page, Mapping)
                or type(page.get("hasNextPage")) is not bool
            ):
                raise MergeAuthorityError("native review-thread pagination is incomplete")
            for node in nodes:
                identifier = node.get("id") if isinstance(node, Mapping) else None
                if (
                    not isinstance(identifier, str)
                    or not identifier
                    or identifier in seen
                    or node.get("isResolved") is not True
                ):
                    raise MergeAuthorityError("native review thread is unresolved or ambiguous")
                seen.add(identifier)
                threads.append(dict(node))
            if page["hasNextPage"] is False:
                return threads
            next_cursor = page.get("endCursor")
            if (
                not nodes
                or not isinstance(next_cursor, str)
                or not next_cursor
                or next_cursor == cursor
            ):
                raise MergeAuthorityError("native review-thread cursor did not advance")
            cursor = next_cursor
        raise MergeAuthorityError("native review-thread evidence exceeds bounded read")

    def native_single_closer_reconcile(
        self,
        repository: str,
        pr_number: int,
        *,
        closing_issue: int,
        readback: Mapping[str, object],
        credential: object,
        snapshot: Mapping[str, object] | None = None,
        compensation_only: bool = False,
        before_compensation: Callable[[], None] | None = None,
    ) -> Mapping[str, object]:
        # Reuse the existing bounded event enumeration and exact PR/SHA attribution.
        from app.dispatcher.verification_consumer import GhCliVerificationSource

        source: Any = self.closure_source or GhCliVerificationSource()
        snapshot_drifted = False
        if snapshot is not None:
            pull = self._pull(repository, pr_number)
            body = pull.get("body")
            head = pull.get("head")
            base = pull.get("base")
            if (
                pull.get("merged") is not True
                or pull.get("merge_commit_sha") != readback.get("merge_commit_sha")
                or not isinstance(body, str)
                or hashlib.sha256(body.encode()).hexdigest() != snapshot.get("body_sha256")
                or pull.get("title") != snapshot.get("title")
                or not isinstance(head, Mapping)
                or head.get("sha") != snapshot.get("head_sha")
                or not isinstance(base, Mapping)
                or base.get("sha") != snapshot.get("base_sha")
            ):
                snapshot_drifted = True
        evidence = source.issue_set_closure_evidence(
            repository,
            pr_number,
            issue_numbers=[closing_issue],
            observed_issue_numbers=[],
            merged_at=readback.get("merged_at"),
            merge_commit_sha=readback.get("merge_commit_sha"),
            actor_login=readback.get("actor_login"),
        )
        if evidence.get("closure_scan_complete") is not True:
            raise MergeAuthorityError("native closure attribution is incomplete")
        observed = evidence.get("observed_closing_issues")
        issues = evidence.get("issue_evidence")
        if (
            not isinstance(observed, list)
            or not isinstance(issues, list)
            or any(not isinstance(row, Mapping) for row in issues)
        ):
            raise MergeAuthorityError("native closure evidence is malformed")
        plan = plan_post_merge_reconciliation(
            pr_number=pr_number,
            authenticated_closing_issues=[closing_issue],
            observed_closing_issues=cast(Sequence[int], observed),
            issue_evidence=cast(Sequence[Mapping[str, object]], issues),
        )
        for number in plan["reopen_unauthorized"]:
            # Revalidate the durable operation-bound refusal and current task
            # owner immediately before every external compensation write. A
            # task takeover between Issues cannot leave the former owner with
            # authority for the next PATCH.
            if before_compensation is None:
                raise MergeAuthorityError(
                    "native closure conflict lacks a durable recorder"
                )
            before_compensation()
            self._native_write(
                "PATCH", f"/repos/{repository}/issues/{number}", {"state": "open"}, credential
            )
            reopened = self._get(f"/repos/{repository}/issues/{number}")
            if (reopened.get("state") != "open" or reopened.get("number") != number
                    or reopened.get("repository_url") != f"https://api.github.com/repos/{repository}"):
                raise MergeAuthorityError("unexpected native closure reopen was not confirmed")
        if plan["unresolved_unauthorized_closures"]:
            raise MergeAuthorityError("unexpected native closure blocks terminal delivery")
        if plan["reopen_unauthorized"]:
            if compensation_only:
                return {
                    **dict(evidence),
                    "reopened_unauthorized_issues": list(plan["reopen_unauthorized"]),
                }
            raise MergeAuthorityError("unexpected native closure blocks terminal delivery")
        if snapshot_drifted:
            raise MergeAuthorityError("native post-merge PR snapshot drifted")
        expected = [row for row in issues if row.get("number") == closing_issue]
        if (
            len(expected) != 1
            or expected[0].get("state") != "closed"
            or expected[0].get("closed_by_delivery") is not True
            or expected[0].get("closed_by_pull_requests") != [pr_number]
        ):
            raise MergeAuthorityError("sole native closer is not closed by this exact PR")
        return evidence

    def _native_write(
        self, method: str, path: str, payload: Mapping[str, object], credential: object
    ) -> Mapping[str, Any]:
        if not isinstance(credential, str) or not credential.strip():
            raise MergeAuthorityError("native merge requires the resolved host credential")
        response = self._http.request(
            method,
            path,
            json=dict(payload),
            headers={
                "Authorization": f"Bearer {credential}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if response.status_code >= 400:
            raise MergeAuthorityError(
                f"native expected-head effect refused ({response.status_code})"
            )
        value = response.json()
        if not isinstance(value, Mapping):
            raise MergeAuthorityError("native effect response is malformed")
        return value

    def _counted_rows(
        self,
        endpoint: str,
        *,
        collection_key: str,
        label: str,
        **parameters: object,
    ) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        seen_ids: set[int] = set()
        expected_total: int | None = None
        for page in range(1, 11):
            payload = self._get(
                endpoint,
                per_page=100,
                page=page,
                **parameters,
            )
            batch = payload.get(collection_key)
            total = payload.get("total_count")
            if (
                not isinstance(batch, list)
                or not isinstance(total, int)
                or isinstance(total, bool)
                or total < 0
                or len(batch) > 100
                or any(not isinstance(row, Mapping) for row in batch)
            ):
                raise MergeAuthorityError(
                    f"GitHub {label} listing is malformed"
                )
            if expected_total is None:
                expected_total = total
                if expected_total > 1_000:
                    raise MergeAuthorityError(
                        f"GitHub {label} listing exceeds bounded scan"
                    )
            elif total != expected_total:
                raise MergeAuthorityError(
                    f"GitHub {label} listing total changed during scan"
                )
            for row in batch:
                assert isinstance(row, Mapping)
                row_id = row.get("id")
                if (
                    not isinstance(row_id, int)
                    or isinstance(row_id, bool)
                    or row_id <= 0
                    or row_id in seen_ids
                ):
                    raise MergeAuthorityError(
                        f"GitHub {label} listing is malformed"
                    )
                seen_ids.add(row_id)
                rows.append(row)
            if len(rows) > expected_total:
                raise MergeAuthorityError(
                    f"GitHub {label} listing is malformed"
                )
            if len(rows) == expected_total:
                return rows
            if len(batch) < 100:
                raise MergeAuthorityError(
                    f"GitHub {label} listing is incomplete"
                )
        raise MergeAuthorityError(
            f"GitHub {label} listing exceeds bounded scan"
        )

    def _check_runs(
        self, repository: str, head_sha: str
    ) -> list[Mapping[str, Any]]:
        return self._counted_rows(
            f"/repos/{repository}/commits/{head_sha}/check-runs",
            collection_key="check_runs",
            label="check-run",
            filter="all",
        )

    def _commit_statuses(
        self, repository: str, head_sha: str
    ) -> list[Mapping[str, Any]]:
        return self._counted_rows(
            f"/repos/{repository}/commits/{head_sha}/status",
            collection_key="statuses",
            label="commit-status",
        )

    def _workflow_runs(
        self, repository: str, head_sha: str
    ) -> list[Mapping[str, Any]]:
        return self._counted_rows(
            f"/repos/{repository}/actions/runs",
            collection_key="workflow_runs",
            label="workflow-run",
            head_sha=head_sha,
        )

    def _delivery_reviews_ready(self, repository: str, pr_number: int, head_sha: str,
                                protection: Mapping[str, Any]) -> bool:
        """Issue delivery has no verification-loop ledger to supply this gate."""
        policy = protection.get("required_pull_request_reviews")
        count = policy.get("required_approving_review_count", 1) if isinstance(policy, Mapping) else 1
        if type(count) is not int or count < 0:
            raise MergeAuthorityError("GitHub review policy is malformed")
        latest: dict[str, Mapping[str, Any]] = {}
        seen: set[int] = set()
        for page in range(1, 11):
            rows = self._get_list(f"/repos/{repository}/pulls/{pr_number}/reviews", per_page=100, page=page)
            for row in rows:
                actor = row.get("user")
                login = actor.get("login") if isinstance(actor, Mapping) else None
                identifier, submitted = row.get("id"), row.get("submitted_at")
                if (type(identifier) is not int or identifier in seen or not isinstance(login, str)
                    or not login or not isinstance(submitted, str) or not submitted
                    or row.get("state") not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED", "COMMENTED"}):
                    raise MergeAuthorityError("GitHub review evidence is malformed or ambiguous")
                seen.add(identifier)
                if row["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                    previous = latest.get(login.casefold())
                    if previous is None or (submitted, identifier) > (previous["submitted_at"], previous["id"]):
                        latest[login.casefold()] = row
            if len(rows) < 100:
                break
        else:
            raise MergeAuthorityError("GitHub review evidence exceeds its bounded read")
        return (sum(row.get("state") == "APPROVED" and row.get("commit_id") == head_sha
                    and row.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"}
                    for row in latest.values()) >= max(1, count)
                and not any(row.get("state") == "CHANGES_REQUESTED" for row in latest.values()))

    def required_gates(
        self, repository: str, pr_number: int, head_sha: str,
        *, verification_checks: tuple[str, ...] | None = None,
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
        required.update((name, None) for name in (
            (_REQUIRED_VERIFICATION_CHECK,) if verification_checks is None else verification_checks
        ))
        status_history: dict[str, list[Mapping[str, Any]]] = {}
        for row in statuses:
            context = row.get("context")
            state = row.get("state")
            if (
                not isinstance(context, str)
                or not context
                or not isinstance(state, str)
                or not state
            ):
                raise MergeAuthorityError(
                    "GitHub commit-status evidence is malformed"
                )
            status_history.setdefault(context, []).append(row)
        latest_statuses = {
            context: _latest_github_result(history)
            for context, history in status_history.items()
        }
        workflow_rows = self._workflow_runs(canonical, head_sha)
        workflows_by_suite = _workflow_runs_by_suite(
            workflow_rows,
            head_sha=head_sha,
        )
        pull_request_workflow_suites = {
            suite_id
            for suite_id, workflow in workflows_by_suite.items()
            if workflow.get("event") == "pull_request"
        }
        check_history: dict[
            tuple[
                str,
                str | None,
                int,
                int | None,
                str | None,
            ],
            list[Mapping[str, Any]],
        ] = {}
        for row in rows:
            name = row.get("name")
            app = row.get("app")
            app_id = app.get("id") if isinstance(app, Mapping) else None
            app_slug = app.get("slug") if isinstance(app, Mapping) else None
            status = row.get("status")
            conclusion = row.get("conclusion")
            suite = row.get("check_suite")
            suite_id = (
                suite.get("id") if isinstance(suite, Mapping) else None
            )
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(app, Mapping)
                or not isinstance(app_id, int)
                or isinstance(app_id, bool)
                or app_id <= 0
                or (
                    app_slug is not None
                    and (
                        not isinstance(app_slug, str)
                        or not app_slug
                    )
                )
                or not isinstance(status, str)
                or not status
                or (
                    conclusion is not None
                    and not isinstance(conclusion, str)
                )
            ):
                raise MergeAuthorityError(
                    "GitHub check-run evidence is malformed"
                )
            if (
                app_slug == "github-actions"
                and (
                    not isinstance(suite_id, int)
                    or isinstance(suite_id, bool)
                    or suite_id <= 0
                    or suite_id not in workflows_by_suite
                )
            ):
                raise MergeAuthorityError(
                    "GitHub Actions check-suite evidence is malformed"
                )
            if (
                app_slug == "github-actions"
                and suite_id not in pull_request_workflow_suites
            ):
                continue
            workflow = (
                workflows_by_suite.get(suite_id)
                if app_slug == "github-actions"
                and isinstance(suite_id, int)
                and not isinstance(suite_id, bool)
                else None
            )
            workflow_id = (
                workflow.get("workflow_id")
                if isinstance(workflow, Mapping)
                else None
            )
            workflow_path = (
                workflow.get("path")
                if isinstance(workflow, Mapping)
                else None
            )
            check_history.setdefault(
                (
                    name,
                    app_slug,
                    app_id,
                    (
                        workflow_id
                        if isinstance(workflow_id, int)
                        and not isinstance(workflow_id, bool)
                        else None
                    ),
                    workflow_path
                    if isinstance(workflow_path, str)
                    else None,
                ),
                [],
            ).append(row)
        latest_checks = {
            identity: _latest_github_result(
                [
                    row
                    for row in history
                    if not _is_skipped_conclusion(row.get("conclusion"))
                ]
                or history
            )
            for identity, history in check_history.items()
        }
        authenticated_workflow_suites: set[int] = set()
        if any(
            context == _REQUIRED_VERIFICATION_CHECK
            for context, _app_id in required
        ):
            authenticated_workflow_suites = {
                suite_id
                for suite_id, workflow in workflows_by_suite.items()
                if suite_id in pull_request_workflow_suites
                and workflow.get("path")
                == _REQUIRED_VERIFICATION_WORKFLOW
            }

        def successful_status(context: str) -> bool:
            row = latest_statuses.get(context)
            return isinstance(row, Mapping) and row.get("state") == "success"

        def successful_check(context: str, app_id: int | None) -> bool:
            candidates = (
                [
                    row
                    for (
                        name,
                        _candidate_slug,
                        candidate_app_id,
                        _workflow_id,
                        _workflow_path,
                    ), row
                    in latest_checks.items()
                    if name == context and candidate_app_id == app_id
                ]
                if app_id is not None
                else [
                    row
                    for (
                        name,
                        _candidate_slug,
                        _candidate_app,
                        _workflow_id,
                        _workflow_path,
                    ), row
                    in latest_checks.items()
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
            # The verification-loop caller independently requires its ledger's
            # closure_ready. The bounded Issue-delivery caller has no such ledger.
            "review": True if verification_checks is None else self._delivery_reviews_ready(
                canonical, pr_number, head_sha, protection_document),
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
        expected_body_edit: Mapping[str, object],
        commit_title: str,
        commit_message: str,
        credential: object,
        effect_revalidator: Callable[[], None] | None = None,
    ) -> Mapping[str, object]:
        snapshot = expected_body_edit.get("native_snapshot")
        if isinstance(snapshot, Mapping):
            with self._native_merge_lock:
                if (
                    self.protected_base_sha(repository) != expected_base_sha
                    or self.delivery_manifest(repository, expected_base_sha).blob_sha
                    != expected_manifest_blob_sha
                    or not all(
                        self.required_gates(repository, pr_number, expected_head_sha).values()
                    )
                ):
                    raise MergeAuthorityError("native protected-base or required gates drifted")
                gate = self.native_single_closer_prepared(
                    repository,
                    pr_number,
                    run_id=str(snapshot.get("run_id")),
                    head_sha=expected_head_sha,
                )
                if (
                    gate is None
                    or gate.get("body_edit") != expected_body_edit
                    or gate.get("base_sha") != expected_base_sha
                    or commit_title != fixed_verified_merge_commit_title(pr_number)
                    or commit_message != FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
                ):
                    raise MergeAuthorityError("native final snapshot or required gates drifted")
                if effect_revalidator is None:
                    raise MergeAuthorityError(
                        "native merge requires final outbox effect revalidation"
                    )
                effect_revalidator()
                result = self._native_write(
                    "PUT",
                    f"/repos/{repository}/pulls/{pr_number}/merge",
                    {
                        "sha": expected_head_sha,
                        "merge_method": "squash",
                        "commit_title": commit_title,
                        "commit_message": commit_message,
                    },
                    credential,
                )
                return result
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
            expected_body_edit=expected_body_edit,
            commit_title=commit_title,
            commit_message=commit_message,
            credential=credential,
        )

    def merge_readback(self, repository: str, pr_number: int) -> Mapping[str, object]:
        pull = self._pull(repository, pr_number)
        head = pull.get("head")
        merge_commit_sha = pull.get("merge_commit_sha")
        merge_commit_title: str | None = None
        merge_commit_message: str | None = None
        if pull.get("merged") is True and isinstance(merge_commit_sha, str):
            commit = self._get(f"/repos/{repository}/commits/{merge_commit_sha}").get("commit")
            raw_message = commit.get("message") if isinstance(commit, Mapping) else None
            if isinstance(raw_message, str):
                title, separator, message = raw_message.partition("\n")
                merge_commit_title = title
                merge_commit_message = message.lstrip("\n") if separator else ""
        readback: dict[str, object] = {
            "merged": pull.get("merged") is True,
            "head_sha": head.get("sha") if isinstance(head, Mapping) else None,
            "merge_commit_sha": merge_commit_sha,
            "merge_commit_title": merge_commit_title,
            "merge_commit_message": merge_commit_message,
            "merged_at": pull.get("merged_at"),
        }
        merged_by = pull.get("merged_by")
        actor_login = merged_by.get("login") if isinstance(merged_by, Mapping) else None
        if isinstance(actor_login, str) and actor_login:
            readback["actor_login"] = actor_login
        return readback


def _is_skipped_conclusion(value: object) -> bool:
    return isinstance(value, str) and value.lower() == "skipped"


class HostCredentialManifestResolver:
    """Resolve an exact repo/id/generation binding from host-owned files."""

    def __init__(self, manifest_file: str | Path) -> None:
        self.manifest_file = Path(manifest_file)

    def _entries(self) -> list[Mapping[str, object]]:
        try:
            document = json.loads(
                self.manifest_file.read_text(encoding="utf-8")
            )
            entries = document["credentials"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise MergeAuthorityError(
                "host credential manifest is unavailable"
            ) from exc
        if not isinstance(entries, list) or any(
            not isinstance(entry, Mapping) for entry in entries
        ):
            raise MergeAuthorityError("host credential manifest is malformed")
        for entry in entries:
            repository = entry.get("repository")
            credential_id = entry.get("credential_id")
            generation = entry.get("rotation_generation")
            secret_file = entry.get("secret_file")
            try:
                RepoRef.parse(repository if isinstance(repository, str) else None)
            except Exception as exc:
                raise MergeAuthorityError(
                    "host credential manifest is malformed"
                ) from exc
            if (
                not isinstance(credential_id, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", credential_id)
                is None
                or not isinstance(generation, int)
                or isinstance(generation, bool)
                or generation <= 0
                or not isinstance(secret_file, str)
                or not secret_file
            ):
                raise MergeAuthorityError("host credential manifest is malformed")
        return list(entries)

    @staticmethod
    def _read_secret(entry: Mapping[str, object]) -> str:
        secret_file = entry.get("secret_file")
        if not isinstance(secret_file, str) or not secret_file:
            raise MergeAuthorityError(
                "host credential secret reference is missing"
            )
        try:
            token = Path(secret_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise MergeAuthorityError(
                "host credential secret is unavailable"
            ) from exc
        if not token:
            raise MergeAuthorityError("host credential secret is empty")
        return token

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
        matches = [
            entry
            for entry in self._entries()
            if str(entry.get("repository", "")).lower() == canonical
            and entry.get("credential_id") == credential_id
            and entry.get("rotation_generation") == rotation_generation
        ]
        if len(matches) != 1:
            raise MergeAuthorityError(
                "host credential binding is missing or ambiguous"
            )
        return self._read_secret(matches[0])

    def resolve_repository_read_token(self, repository: str) -> str:
        """Bootstrap protected-repository reads from one host binding.

        The protected delivery manifest supplies the exact credential ID and
        generation used by the effect path.  This bootstrap read is allowed
        only when the host manifest has one unambiguous binding for the
        addressed repository; the merge executor later calls ``resolve`` to
        re-check the exact protected-manifest identity before any effect.
        """

        canonical = RepoRef.parse(repository).canonical
        matches = [
            entry
            for entry in self._entries()
            if str(entry.get("repository", "")).lower() == canonical
        ]
        if len(matches) != 1:
            raise MergeAuthorityError(
                "repository credential binding is missing or ambiguous"
            )
        return self._read_secret(matches[0])


__all__ = [
    "ConditionalMergeTransport",
    "GitHubProtectedRepositoryAuthority",
    "HostCredentialManifestResolver",
]
