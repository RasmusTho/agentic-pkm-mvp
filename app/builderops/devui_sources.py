"""Finite managed transports into the existing Cockpit read model.

Source permissions stay with the authenticated API and gh. Candidate documents
are baked, content-addressed image inputs, never an operator-selected directory.
This module has no source writes, store fallback, or Product bootstrap.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.builderops import cockpit_docs_plane, cockpit_github_plane
from app.builderops.cockpit_chain import parse_timestamp
from app.builderops.devui_focus_inputs import FocusInputError, read_focus_inputs
from app.builderops.devui_assets import validate_packaged_assets
from app.builderops.cockpit_registry import _SourceRead, _Sources, compose_registry
from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneAuthError,
    ControlPlaneScopeError,
    ControlPlaneUnavailableError,
    StaleLeaseError,
)
from app.builderops.control_plane.models import EnvelopeValidationError, canonical_repository

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_MAX_TASKS = 200
_MAX_RECEIPTS = 200


class SourceConfigurationError(ValueError):
    """Contradictory managed source configuration; safe to report by type only."""


class SourceReadRefusal(ValueError):
    """A bounded source observation cannot support its claim."""


@dataclass(frozen=True)
class SourceConfiguration:
    repository: str | None
    authority_epoch: int | None
    api_environment: Mapping[str, str] = field(repr=False)
    github_enabled: bool
    github_config_dir: Path | None
    candidate_root: Path
    candidate_sha: str


def _manifest(root: Path) -> dict[str, Any]:
    if root.is_symlink() or (root / "manifest.json").is_symlink():
        raise SourceReadRefusal("candidate_path_refused")
    value = json.loads((root / "manifest.json").read_text())
    if not isinstance(value, dict):
        raise SourceReadRefusal("candidate_manifest_invalid")
    return value


def load_source_configuration(
    environment: Mapping[str, str], *, candidate_root: Path, source_sha: str
) -> SourceConfiguration:
    repo = environment.get("DEVUI_REPOSITORY", "")
    epoch = environment.get("DEVUI_BUILDEROPS_AUTHORITY_EPOCH", "")
    github = environment.get("DEVUI_GITHUB_ENABLED", "false")
    api = {
        key: environment[key]
        for key in ("BUILDEROPS_API_URL", "BUILDEROPS_API_TOKEN", "BUILDEROPS_API_TOKEN_FILE")
        if environment.get(key)
    }
    try:
        if repo:
            repo = canonical_repository(repo)
        if epoch and (not epoch.isascii() or not epoch.isdecimal() or int(epoch) < 1):
            raise SourceConfigurationError()
        if github not in {"true", "false"} or (not repo and (api or epoch or github == "true")):
            raise SourceConfigurationError()
        if any(
            environment.get(key)
            for key in (
                "COCKPIT_REGISTRY_DB",
                "COCKPIT_DOCS_ROOT",
                "COCKPIT_GITHUB_REPO",
                "DEVUI_DOCS_ROOT",
                "BUILDEROPS_STORE_MODE",
                "BUILDEROPS_DATABASE_URL",
            )
        ):
            raise SourceConfigurationError()
        if api.get("BUILDEROPS_API_TOKEN") and api.get("BUILDEROPS_API_TOKEN_FILE"):
            raise SourceConfigurationError()
        if url := api.get("BUILDEROPS_API_URL"):
            parsed = urlsplit(url)
            if (
                parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
                or not parsed.hostname
            ):
                raise SourceConfigurationError()
            if parsed.scheme != "https":
                if parsed.scheme != "http" or not ip_address(parsed.hostname).is_loopback:
                    raise SourceConfigurationError()
        if github == "true" and environment.get("GH_HOST", "github.com") != "github.com":
            raise SourceConfigurationError()
        if repo and (candidate_root / "manifest.json").exists():
            identity = _manifest(candidate_root)
            if identity.get("repository") != repo or identity.get("source_sha") != source_sha:
                raise SourceConfigurationError()
    except (ValueError, OSError, TypeError, EnvelopeValidationError) as exc:
        raise SourceConfigurationError("managed source binding is invalid") from exc
    return SourceConfiguration(
        repo or None,
        int(epoch) if epoch else None,
        api,
        github == "true",
        Path(environment["GH_CONFIG_DIR"]) if environment.get("GH_CONFIG_DIR") else None,
        candidate_root,
        source_sha,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _reference(row: dict[str, Any], *, repository: str) -> dict[str, Any]:
    envelope = row.get("authority_envelope")
    if not isinstance(envelope, dict) or envelope.get("repository") != repository:
        raise SourceReadRefusal("repository_mismatch")
    return envelope


def _task(row: dict[str, Any], *, repository: str) -> dict[str, Any] | None:
    _reference(row, repository=repository)
    payload = row.get("payload")
    if (
        row.get("repository") != repository
        or not isinstance(payload, dict)
        or ("repo" in payload and payload["repo"] != repository)
    ):
        raise SourceReadRefusal("task_scope_mismatch")
    task_id = row.get("task_id")
    if (
        not isinstance(task_id, str)
        or _ID.fullmatch(task_id) is None
        or ("task_id" in payload and payload["task_id"] != task_id)
    ):
        raise SourceReadRefusal("task_identity_invalid")
    if (
        type(row.get("version")) is not int
        or row["version"] < 1
        or parse_timestamp(row.get("updated_at")) is None
    ):
        raise SourceReadRefusal("task_version_invalid")
    if not isinstance(row.get("state"), str):
        raise SourceReadRefusal("task_state_invalid")
    lease = row.get("lease")
    if lease is not None and (
        not isinstance(lease, dict)
        or lease.get("repository") != repository
        or lease.get("resource_id") != task_id
        or lease.get("lease_kind") != "task"
        or not isinstance(lease.get("holder"), str)
        or type(lease.get("fencing_token")) is not int
        or lease["fencing_token"] < 1
        or parse_timestamp(lease.get("expires_at")) is None
        or (lease.get("updated_at") is not None and parse_timestamp(lease["updated_at"]) is None)
    ):
        raise SourceReadRefusal("task_lease_mismatch")
    # The API also stores generic CLI tasks and native verification documents.
    # Neither supplies the GitHub-Issue subject required by the existing Now
    # adapter. Keep their addressed observations explicit without guessing an
    # issue/title or treating them as malformed Cockpit task records.
    if not {"repo", "task_id", "issue_number", "title"}.issubset(payload):
        return None
    if (
        (payload.get("status") is not None and payload["status"] != row.get("state"))
        or type(payload.get("issue_number")) is not int
        or payload["issue_number"] <= 0
        or not isinstance(payload.get("title"), str)
        or not payload["title"].strip()
        or (
            payload.get("last_heartbeat_at") is not None
            and parse_timestamp(payload["last_heartbeat_at"]) is None
        )
    ):
        raise SourceReadRefusal("task_payload_invalid")
    # Copy only existing Cockpit fields; never expose the authority envelope or
    # arbitrary source payload (including embedded credentials/diagnostics).
    result = {
        key: payload[key]
        for key in (
            "task_id",
            "repo",
            "issue_number",
            "title",
            "status",
            "priority",
            "created_at",
            "updated_at",
            "last_heartbeat_at",
            "linked_pr",
            "blocked_reason",
            "sync_state",
        )
        if key in payload
    }
    result["updated_at"], result["status"] = row["updated_at"], row["state"]
    # TaskRecord.to_dict carries a mapping; the existing Cockpit seam expects
    # the equivalent database JSON representation, with the same source fields.
    if isinstance(result.get("sync_state"), dict):
        result["sync_state"] = json.dumps(result["sync_state"])
    if lease is not None:
        result.update(claimed_by=lease["holder"], lease_expires_at=lease["expires_at"])
        # The lease writer owns activity across claim, heartbeat and completion.
        # Keep that timestamp distinct from task updates and native heartbeats.
        if lease.get("updated_at") is not None:
            result["lease_updated_at"] = lease["updated_at"]
    return result


def _receipt_address(reference: Any, repository: str) -> tuple[str, str, str | None] | None:
    if not isinstance(reference, str) or not reference.startswith("/v1/receipts/"):
        return None
    parsed = urlsplit(reference)
    parts = parsed.path.split("/")
    query = parse_qs(parsed.query, strict_parsing=True)
    if (
        len(parts) != 5
        or parts[3] not in {"records", "attempts", "promotions"}
        or _ID.fullmatch(parts[4]) is None
        or parsed.fragment
        or query.get("repository") != [repository]
        or set(query) - {"repository", "task_id"}
    ):
        raise SourceReadRefusal("receipt_scope_mismatch")
    task_ids = query.get("task_id", [])
    if (
        (parts[3] == "attempts" and len(task_ids) != 1)
        or len(task_ids) > 1
        or (task_ids and _ID.fullmatch(task_ids[0]) is None)
    ):
        raise SourceReadRefusal("receipt_task_invalid")
    return parts[3], parts[4], task_ids[0] if task_ids else None


def _api_reads(
    config: SourceConfiguration, sources: _Sources, transports: dict[str, Any]
) -> list[dict[str, Any]] | None:
    repo = config.repository
    work: dict[str, Any] = {
        "repository": repo,
        "authority_epoch": config.authority_epoch,
        "outcome": "unavailable",
        "source_refs": [],
        "projection_scope": "source-explicit-github-issue-tasks",
        "unprojected_task_refs": [],
    }
    receipts: dict[str, Any] = {**work, "source_refs": []}
    transports["dispatcher-store"], transports["verification-runs"] = work, receipts
    tasks = None
    read_at = None
    api_read_complete = False
    try:
        if (
            not repo
            or not config.authority_epoch
            or not config.api_environment.get("BUILDEROPS_API_URL")
            or not (
                config.api_environment.get("BUILDEROPS_API_TOKEN")
                or config.api_environment.get("BUILDEROPS_API_TOKEN_FILE")
            )
        ):
            raise SourceReadRefusal("source_not_configured")
        with BuilderOpsControlPlaneClient(
            ClientConfig.from_env(config.api_environment), max_retries=0
        ) as client:
            if client.status().get("authority_epoch") != config.authority_epoch:
                raise StaleLeaseError("source epoch changed")
            rows = client.list_tasks(repository=repo)
            if len(rows) > _MAX_TASKS:
                raise SourceReadRefusal("task_collection_partial")
            current: list[dict[str, Any]] = []
            seen: set[str] = set()
            receipt_reads = 0
            observed_rows = []
            for listed in rows:
                _task(listed, repository=repo)
                task_id = listed["task_id"]
                if task_id in seen:
                    raise SourceReadRefusal("duplicate_task")
                seen.add(task_id)
                row = client.get_task(repository=repo, task_id=task_id)
                item = _task(row, repository=repo)
                if row["version"] != listed["version"] or row["payload"] != listed["payload"]:
                    raise SourceReadRefusal("task_snapshot_changed")
                observed_rows.append(row)
                reference = f"/v1/tasks/{task_id}?repository={repo}#version={row['version']}"
                work["source_refs"].append(reference)
                if item is None:
                    work["unprojected_task_refs"].append(reference)
                else:
                    current.append(item)
                for reference in _reference(row, repository=repo).get("source_refs", []):
                    address = _receipt_address(reference, repo)
                    if address is None:
                        continue
                    if receipt_reads >= _MAX_RECEIPTS:
                        receipts["outcome"] = "partial"
                        break
                    receipt_reads += 1
                    try:
                        value = client.get_receipt(
                            repository=repo,
                            object_kind=address[0],
                            object_id=address[1],
                            task_id=address[2],
                        )
                        _reference(value, repository=repo)
                        digest = hashlib.sha256(
                            json.dumps(value, sort_keys=True).encode()
                        ).hexdigest()
                        receipts["source_refs"].append(reference + "#sha256=" + digest)
                    except Exception:
                        receipts["outcome"] = "partial"
            if client.status().get("authority_epoch") != config.authority_epoch:
                raise StaleLeaseError("source epoch changed")
            api_read_complete, read_at = True, _now()
            work["read_at"] = read_at
            # A fully read but unprojectable collection is an unknown work
            # view, never a complete empty set. Mixed collections retain only
            # the source-explicit Issue facts and name their partial scope.
            tasks = current if current or not rows else None
            work["source_refs"].append(
                f"builderops-api:{repo}@epoch={config.authority_epoch}#sha256="
                + hashlib.sha256(json.dumps(observed_rows, sort_keys=True).encode()).hexdigest()
            )
            work["outcome"] = "partial" if work["unprojected_task_refs"] else "available"
            if receipts["outcome"] != "partial" and receipts["source_refs"]:
                receipts["outcome"] = "available"
    except (ControlPlaneAuthError, ControlPlaneScopeError):
        work["outcome"] = "refused"
    except StaleLeaseError:
        work["outcome"] = "mismatched"
    except ControlPlaneUnavailableError:
        work["outcome"] = "unavailable"
    except SourceReadRefusal as exc:
        code = str(exc)
        work["outcome"] = (
            "unavailable"
            if code == "source_not_configured"
            else "mismatched"
            if "mismatch" in code
            else "partial"
            if code in {"task_collection_partial", "task_snapshot_changed"}
            else "refused"
        )
        work["code"] = code
    except Exception:
        work["outcome"] = "unavailable"
    if not api_read_complete:
        receipts["outcome"], receipts["source_refs"] = "unavailable", []
    sources.add(
        _SourceRead(
            "dispatcher-store",
            "fresh" if tasks is not None else "unavailable",
            read_at if tasks is not None else None,
            "BuilderOps API task read",
            configured=True,
        )
    )
    # Generic source receipts carry provenance only. Their mere existence never
    # becomes a verification run, terminal success, readiness or acceptance.
    sources.add(
        _SourceRead(
            "verification-runs",
            "unavailable",
            None,
            "verification facts require their source-owned run contract",
        )
    )
    return tasks


def _candidate_docs(
    config: SourceConfiguration,
) -> tuple[cockpit_docs_plane.DocsPlaneResult, list[str]]:
    root = config.candidate_root
    manifest = _manifest(root)
    if (
        manifest.get("repository") != config.repository
        or manifest.get("source_sha") != config.candidate_sha
    ):
        raise SourceReadRefusal("candidate_identity_mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise SourceReadRefusal("candidate_files_missing")
    actual = {
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and p != root / "manifest.json"
    }
    if actual != set(files):
        raise SourceReadRefusal("candidate_files_mismatch")
    for name, digest in files.items():
        path = root / name
        if (
            not isinstance(name, str)
            or name.startswith("/")
            or ".." in Path(name).parts
            or any(p.is_symlink() for p in (path, *path.parents))
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise SourceReadRefusal("candidate_content_mismatch")
    for key in ("capabilities", "matrix"):
        if manifest.get(key) not in files:
            raise SourceReadRefusal("candidate_input_missing")
    result = cockpit_docs_plane.read_docs_plane(
        docs_root=root / "docs",
        capabilities_yaml_path=root / manifest["capabilities"],
        matrix_path=root / manifest["matrix"],
    )
    return result, [
        f"https://github.com/{config.repository}/blob/{config.candidate_sha}/{name}#sha256={digest}"
        for name, digest in files.items()
        # The shell is copied under package aliases, not repository paths.
        # It remains in the fully checked inventory above, not document provenance.
        if not name.startswith("assets/")
    ]


def read_managed_cockpit(config: SourceConfiguration) -> dict[str, Any]:
    sources = _Sources()
    transports: dict[str, Any] = {}
    tasks = _api_reads(config, sources, transports)
    github = None
    meta: dict[str, Any] = {
        "repository": config.repository,
        "outcome": "unavailable",
        "source_refs": [],
    }
    try:
        if (
            config.repository
            and config.github_enabled
            and config.github_config_dir is not None
            and config.github_config_dir.is_dir()
        ):
            github = cockpit_github_plane.default_github_reader(config.repository)
            meta["unavailable_check_heads"] = sorted(github.check_read_failures)
            meta.update(
                outcome="partial" if github.check_read_failures else "available",
                source_refs=[
                    f"github-rest:{config.repository}@{github.read_at}#sha256="
                    + hashlib.sha256(repr(github).encode()).hexdigest(),
                    *[
                        f"https://github.com/{config.repository}/tree/{p.head_sha}"
                        for p in github.pulls.values()
                    ],
                ],
            )
    except Exception:
        # Never log gh stderr, token configuration, HTTP bodies or exceptions.
        pass
    transports["github-live"] = meta
    sources.add(
        _SourceRead(
            "github-live",
            "fresh" if github else "unavailable",
            github.read_at if github else None,
            "bounded GitHub REST read",
            configured=config.github_enabled,
        )
    )
    docs = None
    meta = {
        "repository": config.repository,
        "candidate_sha": config.candidate_sha,
        "outcome": "unavailable",
        "source_refs": [],
    }
    result = None
    try:
        if config.repository:
            result, refs = _candidate_docs(config)
            docs = result.snapshot
            meta.update(outcome="available" if docs else "unavailable", source_refs=refs)
    except SourceReadRefusal:
        meta["outcome"] = "mismatched"
    except Exception:
        pass
    transports["docs-frontmatter"] = meta
    sources.add(
        _SourceRead(
            "docs-frontmatter",
            result.state if result else "unavailable",
            result.last_successful_read if result else None,
            "image-baked candidate documents",
            configured=bool(config.repository),
        )
    )
    sources.add(
        _SourceRead(
            "deploy-receipts",
            "unavailable",
            None,
            "VM102 receipt evidence is composed independently",
        )
    )
    payload = compose_registry(
        tasks=tasks,
        verification={},
        deployments=[],
        sources=sources,
        github_snapshot=github,
        docs_snapshot=docs,
        github_repo=config.repository,
    )
    for source in payload["sources"]:
        if source["name"] in transports:
            source["transport"] = transports[source["name"]]
            if source["state"] == "stale":
                source["transport"]["outcome"] = "stale"
    return payload


def read_managed_focus(config: SourceConfiguration, subject: str) -> dict[str, Any]:
    """Read only the addressed Issue via the same admitted gh REST owner."""
    if not (
        config.repository
        and config.github_enabled
        and config.github_config_dir
        and config.github_config_dir.is_dir()
    ):
        raise FocusInputError("selected Issue source is unavailable")

    def read_issue(repository: str, number: str) -> Any:
        issue = cockpit_github_plane._run_gh(["api", f"repos/{repository}/issues/{number}"])
        locator = issue.get("html_url") if isinstance(issue, dict) else None
        addressed_issue = (
            re.fullmatch(
                r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)",
                locator,
            )
            if isinstance(locator, str)
            else None
        )
        if (
            not isinstance(issue, dict)
            or type(issue.get("number")) is not int
            or issue.get("number") != int(number)
            or parse_timestamp(issue.get("updated_at")) is None
            or addressed_issue is None
            or canonical_repository(addressed_issue[1]) != canonical_repository(repository)
            or addressed_issue[2] != number
        ):
            raise FocusInputError("selected Issue response identity is invalid")
        return issue

    return read_focus_inputs(subject, repository=config.repository, issue_reader=read_issue)


def package_candidate(
    root: Path, *, repository: str, source_sha: str, capabilities: str, matrix: str
) -> None:
    """Image build only: record the finite copied candidate inputs."""
    repo = canonical_repository(repository)
    if not _SHA.fullmatch(source_sha) or set(source_sha) == {"0"}:
        raise SourceConfigurationError("immutable candidate SHA required")
    files = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p != root / "manifest.json"
    }
    if capabilities not in files or matrix not in files or not files:
        raise SourceConfigurationError("candidate inputs missing")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "repository": repo,
                "source_sha": source_sha,
                "capabilities": capabilities,
                "matrix": matrix,
                "files": files,
            },
            sort_keys=True,
        )
    )

    validate_packaged_assets(root, source_sha=source_sha, repository=repo)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Package image-baked DevUI candidate documents")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--capabilities", required=True)
    parser.add_argument("--matrix", required=True)
    args = parser.parse_args()
    package_candidate(
        args.root,
        repository=args.repository,
        source_sha=args.source_sha,
        capabilities=args.capabilities,
        matrix=args.matrix,
    )
