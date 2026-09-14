"""API-only client CLI for the BuilderOps control plane.

This is the canonical MacBook entry point for authority-bearing BuilderOps
operations. It reaches the independent service over one authenticated API
boundary and exposes **no** direct database path, local SQLite construction, or
SSH-to-database-owning-CLI mode. Base URL and credential are resolved from host
secret configuration by :class:`ClientConfig`. Every command names exactly one
repository explicitly; there is no current-working-directory repo inference.

Run as ``python -m app.builderops.control_plane.client <command> ...``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import sys
from collections.abc import Callable, Sequence
from typing import Any

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneClientError,
    ControlPlaneNotFoundError,
)
from app.builderops.control_plane.routing import (
    DeliveryManifestRegistry,
    RepoRef,
    RoutePolicy,
    RoutingError,
)

ClientFactory = Callable[[ClientConfig], BuilderOpsControlPlaneClient]

# Exit code for a fail-closed client error (unavailable/auth/scope/conflict/
# stale). A non-zero exit is the shell-visible fail-closed signal; the command
# never degrades to a local store or fabricated lease.
_FAIL_CLOSED_EXIT = 3
_CONFIG_EXIT = 2

# Every authority-bearing CLI command carries an envelope and must resolve the
# addressed repository's delivery-manifest route before it can dispatch.  Read
# commands (status, receipt) intentionally stay outside this mutation gate.
_MUTATING_COMMANDS = frozenset(
    {
        "record",
        "task-import-issue",
        "inquiry",
        "task-claim",
        "task-heartbeat",
        "task-complete",
        "lease-claim",
        "attempt",
        "promotion",
    }
)
# Commands with a --ttl-seconds argument the resolved route's policy may
# advise a default for.
_TTL_COMMANDS = frozenset({"task-claim", "task-heartbeat", "lease-claim"})
_DEFAULT_TTL_SECONDS = 5400


def _default_factory(config: ClientConfig) -> BuilderOpsControlPlaneClient:
    return BuilderOpsControlPlaneClient(config)


def _add_envelope_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--repository",
        required=True,
        help="Explicit owner/name repository this mutation addresses (no CWD inference).",
    )
    sub.add_argument("--scope", required=True, help="Authority scope, e.g. issue:3791.")
    sub.add_argument("--stack", required=True, help="Delivery stack identifier.")
    sub.add_argument(
        "--source-ref",
        dest="source_refs",
        action="append",
        required=True,
        help="Traceable source reference (repeatable).",
    )


def _envelope(args: argparse.Namespace) -> dict[str, Any]:
    # Fail closed on an ambiguous/blank repository reference before any request.
    repo = RepoRef.parse(args.repository)
    return {
        "repository": repo.canonical,
        "scope": args.scope,
        "stack": args.stack,
        "source_refs": list(args.source_refs),
    }


def _json_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON payload: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="builderops-control-plane",
        description=(
            "Authenticated API-only client for the BuilderOps control plane. "
            "No direct database, SQLite, or SSH store mode is exposed."
        ),
    )
    parser.add_argument(
        "--delivery-manifest-dir",
        help=(
            "Directory of per-repository delivery-manifest JSON documents "
            "(see app.builderops.control_plane.routing). Required for every "
            "mutating command: the addressed repository's manifest is loaded "
            "and routed by (RepoRef, stack, task-class) before dispatch; a "
            "missing, ambiguous, stale cached/prior, or cross-repository route "
            "fails closed. "
            "Routing is advisory request shaping only, never privileged authority."
        ),
    )
    parser.add_argument(
        "--task-class",
        help="Task-class half of the (RepoRef, stack, task-class) routing key. "
        "Required for every mutating command.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Read the current authority epoch and schema version.")

    importer = sub.add_parser("task-import-issue", help="Import one strict Ready GitHub Issue, without claiming or launching it.")
    importer.add_argument("--repository", required=True)
    importer.add_argument("--scope", required=True)
    importer.add_argument("--stack", required=True)
    importer.add_argument("--issue", type=int, required=True)

    record = sub.add_parser("record", help="Commit a record authority object.")
    _add_envelope_arguments(record)
    record.add_argument("--record-id", required=True)
    record.add_argument("--record-type", required=True)
    record.add_argument("--state", required=True)
    record.add_argument("--payload", help="JSON object payload.")
    record.add_argument("--idempotency-key", required=True)

    inquiry = sub.add_parser("inquiry", help="Commit a model-inquiry authority object.")
    _add_envelope_arguments(inquiry)
    inquiry.add_argument("--inquiry-id", required=True)
    inquiry.add_argument("--state", required=True)
    inquiry.add_argument("--payload", help="JSON object payload.")
    inquiry.add_argument("--idempotency-key", required=True)

    task_claim = sub.add_parser("task-claim", help="Claim a task and its fenced lease.")
    _add_envelope_arguments(task_claim)
    task_claim.add_argument("--task-id", required=True)
    task_claim.add_argument("--idempotency-key", required=True)
    task_claim.add_argument(
        "--ttl-seconds",
        type=int,
        default=None,
        help=f"Defaults to the resolved delivery-manifest route's policy "
        f"ttl_seconds if routing is engaged, else {_DEFAULT_TTL_SECONDS}.",
    )

    task_heartbeat = sub.add_parser("task-heartbeat", help="Heartbeat a claimed task lease.")
    _add_envelope_arguments(task_heartbeat)
    task_heartbeat.add_argument("--lease", required=True, help="JSON lease object from claim.")
    task_heartbeat.add_argument("--idempotency-key", required=True)
    task_heartbeat.add_argument(
        "--ttl-seconds",
        type=int,
        default=None,
        help=f"Defaults to the resolved delivery-manifest route's policy "
        f"ttl_seconds if routing is engaged, else {_DEFAULT_TTL_SECONDS}.",
    )

    task_complete = sub.add_parser("task-complete", help="Complete a claimed task.")
    _add_envelope_arguments(task_complete)
    task_complete.add_argument("--lease", required=True, help="JSON lease object from claim.")
    task_complete.add_argument("--idempotency-key", required=True)

    lease_claim = sub.add_parser("lease-claim", help="Claim a generic fenced lease.")
    _add_envelope_arguments(lease_claim)
    lease_claim.add_argument("--resource-id", required=True)
    lease_claim.add_argument("--idempotency-key", required=True)
    lease_claim.add_argument(
        "--ttl-seconds",
        type=int,
        default=None,
        help=f"Defaults to the resolved delivery-manifest route's policy "
        f"ttl_seconds if routing is engaged, else {_DEFAULT_TTL_SECONDS}.",
    )

    attempt = sub.add_parser("attempt", help="Commit a fenced attempt authority object.")
    _add_envelope_arguments(attempt)
    attempt.add_argument("--task-id", required=True)
    attempt.add_argument("--attempt-id", required=True)
    attempt.add_argument("--state", required=True)
    attempt.add_argument("--payload", help="JSON object payload.")
    attempt.add_argument("--idempotency-key", required=True)
    attempt.add_argument("--lease", required=True, help="JSON lease object from claim.")

    promotion = sub.add_parser("promotion", help="Commit a promotion authority object.")
    _add_envelope_arguments(promotion)
    promotion.add_argument("--promotion-id", required=True)
    promotion.add_argument("--status", required=True)
    promotion.add_argument("--payload", help="JSON object payload.")
    promotion.add_argument("--idempotency-key", required=True)
    promotion.add_argument(
        "--lease",
        help=(
            "JSON fenced lease object. Required by the service when updating an "
            "existing promotion; stale or missing evidence fails closed."
        ),
    )

    receipt = sub.add_parser("receipt", help="Read a committed authority-object receipt.")
    receipt.add_argument("--repository", required=True)
    receipt.add_argument(
        "--object-kind", required=True, choices=["records", "attempts", "promotions"]
    )
    receipt.add_argument("--object-id", required=True)
    receipt.add_argument("--task-id", help="Required for attempt receipts.")

    return parser


def _dispatch(
    args: argparse.Namespace, client: BuilderOpsControlPlaneClient
) -> dict[str, Any]:
    command = args.command
    if command == "status":
        return client.status()
    if command == "task-import-issue":
        return _import_issue(args, client)
    if command == "record":
        return client.commit_record(
            envelope=_envelope(args),
            record_id=args.record_id,
            record_type=args.record_type,
            state=args.state,
            payload=_json_payload(args.payload),
            idempotency_key=args.idempotency_key,
        )
    if command == "inquiry":
        return client.create_inquiry(
            envelope=_envelope(args),
            inquiry_id=args.inquiry_id,
            state=args.state,
            payload=_json_payload(args.payload),
            idempotency_key=args.idempotency_key,
        )
    if command == "task-claim":
        return client.claim_task(
            envelope=_envelope(args),
            task_id=args.task_id,
            idempotency_key=args.idempotency_key,
            ttl_seconds=args.ttl_seconds,
        )
    if command == "task-heartbeat":
        return client.heartbeat_task(
            envelope=_envelope(args),
            lease=_json_payload(args.lease),
            idempotency_key=args.idempotency_key,
            ttl_seconds=args.ttl_seconds,
        )
    if command == "task-complete":
        return client.complete_task(
            envelope=_envelope(args),
            lease=_json_payload(args.lease),
            idempotency_key=args.idempotency_key,
        )
    if command == "lease-claim":
        return client.claim_lease(
            envelope=_envelope(args),
            resource_id=args.resource_id,
            idempotency_key=args.idempotency_key,
            ttl_seconds=args.ttl_seconds,
        )
    if command == "attempt":
        return client.commit_attempt(
            envelope=_envelope(args),
            task_id=args.task_id,
            attempt_id=args.attempt_id,
            state=args.state,
            payload=_json_payload(args.payload),
            idempotency_key=args.idempotency_key,
            lease=_json_payload(args.lease),
        )
    if command == "promotion":
        return client.commit_promotion(
            envelope=_envelope(args),
            promotion_id=args.promotion_id,
            status=args.status,
            payload=_json_payload(args.payload),
            idempotency_key=args.idempotency_key,
            lease=_json_payload(args.lease) if args.lease else None,
        )
    if command == "receipt":
        return client.get_receipt(
            repository=args.repository,
            object_kind=args.object_kind,
            object_id=args.object_id,
            task_id=args.task_id,
        )
    raise ValueError(f"unknown command: {command}")


def _source_contract_ready(body: str) -> bool:
    """Reuse strict content predicates without a checkout-dependent file test.

    Source owners and candidate document evidence own file availability. A
    pure retained-source check cannot infer it from this process's checkout.
    """
    from scripts import validate_issue_readiness as readiness

    sections = readiness.extract_sections(body)
    present = [name for name in readiness.REQUIRED_SECTIONS
               if readiness._section_content(sections, name) is not None]
    items = readiness._extract_acceptance_items(readiness._section_content(sections, "Acceptance Criteria"))
    targets = [tuple(readiness._declared_verify_targets(item)) for item in items]
    return (
        len(present) == len(readiness.REQUIRED_SECTIONS)
        and not readiness._unknown_body(body, [readiness._normalize_heading(name) for name in present])
        and bool(readiness._non_placeholder_lines(readiness._section_content(sections, "Source Docs")))
        and bool(items)
        and all(group and len(set(group)) == len(group)
                and all(readiness.is_resolvable_verify_target(target) for target in group) for group in targets)
        and readiness._parent_reference_problem(body) is None
        and readiness.admission_contract_problem(body) is None
        and not readiness._contains_any(
            (*readiness.NOT_AGENTABLE_PATTERNS, *readiness.AUTHORITY_RISK_PATTERNS, *readiness.AMBIGUOUS_PATTERNS), body)
    )


def issue_source_task(
    issue: Any, *, repository: str, number: int, observed_at: str, authority_epoch: int
) -> dict[str, Any]:
    """Pure source binding, also checked against independently collected evidence.

    Only the explicit CLI fetch below may use this to prepare a write. Neither
    this deterministic mapping nor its output authenticates an importer.
    """
    from app.dispatcher.sync_github import normalize_github_issue
    from app.ops.builderops_vm_rebuild_activation import _contains_secret

    try:
        repo = RepoRef.parse(repository).canonical
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if observed.tzinfo is None or type(authority_epoch) is not int or authority_epoch < 1:
            raise ValueError()
        if not isinstance(issue, dict) or _contains_secret(issue) or {"createdAt", "updatedAt"} & issue.keys():
            raise ValueError()
        labels = [item["name"] for item in issue["labels"]]
        url = f"https://github.com/{repo}/issues/{number}"
        if (
            type(number) is not int or number < 1 or type(issue["number"]) is not int
            or issue["number"] != number or "pull_request" in issue
            or issue["state"] != "open" or not isinstance(issue["title"], str)
            or not issue["title"].strip() or not isinstance(issue["body"], str)
            or {label for label in labels if label.startswith("agent:")} != {"agent:ready"}
            or issue["html_url"].lower() != url
            or issue["url"].lower() != f"https://api.github.com/repos/{repo}/issues/{number}"
            or issue["repository_url"].lower() != f"https://api.github.com/repos/{repo}"
            or not _source_contract_ready(issue["body"])
        ):
            raise ValueError()
        created, updated = (
            datetime.fromisoformat(issue[key].replace("Z", "+00:00"))
            for key in ("created_at", "updated_at")
        )
        if created.tzinfo is None or updated.tzinfo is None or not created <= updated <= observed:
            raise ValueError()
        payload = normalize_github_issue(issue, repo, now=observed_at).to_dict()
        payload["source_anchor_refs"] = [url]
        payload["sync_state"].update(
            body_sha256=hashlib.sha256(issue["body"].encode()).hexdigest(),
            authority_epoch=authority_epoch,
        )
        return payload
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Issue source identity, readiness or observation is invalid") from exc


def validate_import_readback(row: Any, request: dict[str, Any]) -> None:
    """A native Ready row is necessary, but is never transaction evidence."""
    envelope = request["envelope"]
    if (
        not isinstance(row, dict) or row.get("repository") != envelope["repository"]
        or row.get("task_id") != request["task_id"] or row.get("state") != "ready"
        or type(row.get("version")) is not int or row["version"] != 1
        or "lease" not in row or row["lease"] is not None or row.get("payload") != request["request"]
        or not isinstance(row.get("authority_envelope"), dict)
        or any(row["authority_envelope"].get(key) != value for key, value in envelope.items())
    ):
        raise ValueError("Issue TaskRecord readback is incompatible or changed")


def validate_import_response(response: Any, request: dict[str, Any]) -> None:
    result = response.get("result") if isinstance(response, dict) else None
    if (
        not isinstance(result, dict)
        or set(result) != {"repository", "task_id", "state", "receipt_sequence", "recovery_lsn", "operation_key", "replayed"}
        or result["repository"] != request["envelope"]["repository"]
        or result["task_id"] != request["task_id"] or result["state"] != "ready"
        or type(result["receipt_sequence"]) is not int or result["receipt_sequence"] < 1
        or not isinstance(result["recovery_lsn"], str)
        or re.fullmatch(r"[0-9A-F]+/[0-9A-F]+", result["recovery_lsn"]) is None
        or result["recovery_lsn"] == "0/0" or result["operation_key"] is not None
        or type(result["replayed"]) is not bool
    ):
        raise ValueError("Observed initial transition response is invalid")


def _import_issue(args: argparse.Namespace, client: BuilderOpsControlPlaneClient) -> dict[str, Any]:
    from app.builderops import cockpit_github_plane
    from app.dispatcher.sync_github import github_issue_task_id

    repository = RepoRef.parse(args.repository).canonical
    if args.issue < 1 or args.scope != f"issue:{args.issue}" or not args.stack.strip():
        raise ValueError("Issue import requires its exact Issue scope and stack")
    address = ["api", f"repos/{repository}/issues/{args.issue}"]
    try:
        issue = cockpit_github_plane._run_gh(address)
        observed_at = datetime.now(timezone.utc).isoformat()
        epoch = client.authority_epoch
        payload = issue_source_task(issue, repository=repository, number=args.issue,
                                    observed_at=observed_at, authority_epoch=epoch)
        task_id = github_issue_task_id(repository, args.issue)
        try:
            previous = client.get_task(repository=repository, task_id=task_id)
        except ControlPlaneNotFoundError:
            previous = None
        if previous is not None:
            # Preserve the first source observation only after comparing every
            # other native source field; never rewrite an existing task.
            if not isinstance(previous.get("payload"), dict) or not isinstance(previous["payload"].get("sync_state"), dict):
                raise ValueError("Existing task has no Issue source binding")
            original_time = previous["payload"]["sync_state"].get("last_pull_at")
            payload = issue_source_task(issue, repository=repository, number=args.issue,
                                        observed_at=original_time, authority_epoch=epoch)
        envelope = {"repository": repository, "scope": args.scope, "stack": args.stack,
                    "source_refs": payload["source_anchor_refs"]}
        identity = {"envelope": envelope, "task_id": task_id, "source_version": issue["updated_at"],
                    "body_sha256": payload["sync_state"]["body_sha256"], "authority_epoch": epoch}
        key = "issue-import:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        request: dict[str, Any] = {"envelope": envelope, "task_id": task_id, "to_state": "ready", "idempotency_key": key,
                   "request": payload, "outbox": None, "lease": None, "expected_states": None,
                   "expected_version": None}
        if previous is not None:
            validate_import_readback(previous, request)
        response = client.transition_task(**request)
        validate_import_response(response, request)
        row = client.get_task(repository=repository, task_id=task_id)
        validate_import_readback(row, request)
        fresh = cockpit_github_plane._run_gh(address)
        if issue_source_task(fresh, repository=repository, number=args.issue,
                             observed_at=payload["sync_state"]["last_pull_at"], authority_epoch=epoch) != payload:
            raise ValueError("Issue source changed during import")
        if client.status().get("authority_epoch") != epoch:
            raise ValueError("Issue import authority epoch changed")
        return {"observed_at": observed_at, "authority_epoch": epoch, "transition_request": request,
                "transition_response": response, "task": row}
    except cockpit_github_plane.GithubReadError as exc:
        raise ControlPlaneClientError("Issue source unavailable") from exc


def _resolve_route(args: argparse.Namespace) -> RoutePolicy | None:
    """Resolve the addressed repo's (RepoRef, stack, task-class) route.

    Read commands return ``None`` because they cannot mutate authority. Every
    mutating command is a full commitment to fail-closed routing: a missing
    manifest directory/task class, or a missing, ambiguous, stale cached/prior,
    or cross-repo-reused manifest/route raises before a client is constructed
    or a request is dispatched. The manifest is reloaded for every invocation;
    no previous route can authorize a later mutation. The resolved policy is
    advisory request-shaping only
    — never privileged authority; BCP-05 independently re-resolves
    protected-base policy before any privileged effect.
    """
    manifest_dir = getattr(args, "delivery_manifest_dir", None)
    if args.command not in _MUTATING_COMMANDS:
        return None
    if not manifest_dir:
        raise ValueError("--delivery-manifest-dir is required for mutating commands")
    if not getattr(args, "task_class", None):
        raise ValueError(
            "--task-class is required for mutating commands"
        )
    repo = RepoRef.parse(args.repository)
    registry = DeliveryManifestRegistry.from_directory(manifest_dir)
    return registry.resolve_route(repo, args.stack, args.task_class)


def _apply_route_policy(args: argparse.Namespace, route: RoutePolicy | None) -> None:
    """Apply the resolved route's advisory policy to unset CLI defaults.

    Only fields the caller left unset (``None``) are affected; an explicit
    ``--ttl-seconds`` always wins over the manifest's advisory default.
    """
    if args.command not in _TTL_COMMANDS or getattr(args, "ttl_seconds", None) is not None:
        return
    if route is None:
        args.ttl_seconds = _DEFAULT_TTL_SECONDS
        return
    policy_ttl = route.policy.get("ttl_seconds", _DEFAULT_TTL_SECONDS)
    if type(policy_ttl) is not int or not 1 <= policy_ttl <= 86400:
        raise ValueError(
            f"delivery manifest route ({route.repository}, {route.stack}, "
            f"{route.task_class}) has an invalid ttl_seconds policy value"
        )
    args.ttl_seconds = policy_ttl


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: ClientFactory = _default_factory,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        route = _resolve_route(args)
        _apply_route_policy(args, route)
    except RoutingError as exc:
        # Missing/ambiguous manifests and cross-repo prior reuse fail closed.
        print(f"builderops-control-plane: {type(exc).__name__}: {exc}", file=sys.stderr)
        return _FAIL_CLOSED_EXIT
    except ValueError as exc:
        print(f"builderops-control-plane: invalid request: {exc}", file=sys.stderr)
        return _CONFIG_EXIT
    if route is not None:
        print(
            f"builderops-control-plane: resolved delivery route "
            f"({route.repository}, {route.stack}, {route.task_class}): "
            f"{json.dumps(dict(route.policy), sort_keys=True)}",
            file=sys.stderr,
        )
    try:
        config = ClientConfig.from_env()
    except ControlPlaneClientError as exc:
        print(f"builderops-control-plane: configuration error: {exc}", file=sys.stderr)
        return _CONFIG_EXIT
    client = client_factory(config)
    try:
        result = _dispatch(args, client)
    except (ControlPlaneClientError, RoutingError) as exc:
        # Fail closed: report the typed error and exit non-zero. No local
        # authority, SQLite database, or fabricated lease is created.
        print(f"builderops-control-plane: {type(exc).__name__}: {exc}", file=sys.stderr)
        return _FAIL_CLOSED_EXIT
    except ValueError as exc:
        print(f"builderops-control-plane: invalid request: {exc}", file=sys.stderr)
        return _CONFIG_EXIT
    finally:
        client.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
