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
import json
import sys
from collections.abc import Callable, Sequence
from typing import Any

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneClientError,
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
# commands (status, receipt, outbox-status) intentionally stay outside this mutation gate.
_MUTATING_COMMANDS = frozenset(
    {
        "record",
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

    outbox_status = sub.add_parser(
        "outbox-status",
        help="Read one exact effect-outbox intent and its durable reconciliation phase.",
    )
    outbox_status.add_argument("--repository", required=True)
    outbox_status.add_argument("--operation-key", required=True)

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
    if command == "outbox-status":
        return client.get_outbox_status(
            repository=RepoRef.parse(args.repository).canonical,
            operation_key=args.operation_key,
        )
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
