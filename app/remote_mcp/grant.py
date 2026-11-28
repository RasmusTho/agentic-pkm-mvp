"""The single host-side remote grant (ADR-0070 §3).

One owner-readable JSON file names exactly one vault binding, the granted v1
tools, an expiry, and the SHA-256 of the remote-subject credential. It is read
on every request, so revoking or expiring it takes effect on the next request.
Any missing, unreadable, or malformed grant fails closed.

The credential is a high-entropy random secret, so a plain SHA-256 digest is a
sufficient verifier; the plaintext is printed once at issue and never stored.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

GRANT_SCHEMA = "mimer_remote_grant.v1"
GRANTABLE_TOOLS = frozenset({"mimer.health", "mimer.capture"})
GRANT_PATH_ENV = "MIMER_REMOTE_GRANT_PATH"


class GrantRefused(Exception):
    """A request is not admitted by the remote grant."""

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


@dataclass(frozen=True)
class RemoteGrant:
    grant_id: str
    vault_binding_id: str
    tools: frozenset[str]
    expires_at: datetime
    credential_sha256: str
    active: bool

    def as_payload(self) -> dict[str, object]:
        return {
            "schema": GRANT_SCHEMA,
            "grant_id": self.grant_id,
            "vault_binding_id": self.vault_binding_id,
            "tools": sorted(self.tools),
            "expires_at": self.expires_at.isoformat(),
            "credential_sha256": self.credential_sha256,
            "active": self.active,
        }


def _digest(credential: str) -> str:
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()


def load_grant(path: Path) -> RemoteGrant:
    """Parse the grant file or raise ``GrantRefused(503)``."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema") != GRANT_SCHEMA:
            raise ValueError("schema")
        tools = raw["tools"]
        if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
            raise ValueError("tools")
        if not set(tools) <= GRANTABLE_TOOLS:
            raise ValueError("ungrantable tool")
        expires_at = datetime.fromisoformat(raw["expires_at"])
        if expires_at.tzinfo is None:
            raise ValueError("naive expiry")
        fields = (raw["grant_id"], raw["vault_binding_id"], raw["credential_sha256"])
        if not all(isinstance(value, str) and value for value in fields):
            raise ValueError("fields")
        if not isinstance(raw["active"], bool):
            raise ValueError("active")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise GrantRefused(503, "remote_grant_unavailable") from exc
    return RemoteGrant(
        grant_id=raw["grant_id"],
        vault_binding_id=raw["vault_binding_id"],
        tools=frozenset(tools),
        expires_at=expires_at,
        credential_sha256=raw["credential_sha256"],
        active=raw["active"],
    )


def admit(path: Path, presented: str | None, *, now: datetime | None = None) -> RemoteGrant:
    """Return the grant that admits ``presented``, or raise ``GrantRefused``."""

    grant = load_grant(path)
    if not presented:
        raise GrantRefused(401, "remote_credential_required")
    if not hmac.compare_digest(_digest(presented), grant.credential_sha256):
        raise GrantRefused(401, "remote_credential_invalid")
    if not grant.active:
        raise GrantRefused(403, "remote_grant_revoked")
    if (now or datetime.now(timezone.utc)) >= grant.expires_at:
        raise GrantRefused(403, "remote_grant_expired")
    return grant


def _write(path: Path, grant: RemoteGrant) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(grant.as_payload(), handle, indent=2)
    os.replace(tmp, path)


def issue_grant(
    path: Path, *, vault_binding_id: str, tools: Sequence[str], days: int
) -> tuple[RemoteGrant, str]:
    """Write a new grant (replacing any previous one) and return its credential."""

    if not set(tools) <= GRANTABLE_TOOLS or not tools:
        raise ValueError(f"tools must be a non-empty subset of {sorted(GRANTABLE_TOOLS)}")
    if not 1 <= days <= 90:
        raise ValueError("days must be between 1 and 90")
    credential = secrets.token_urlsafe(32)
    grant = RemoteGrant(
        grant_id=f"rg_{secrets.token_hex(8)}",
        vault_binding_id=vault_binding_id,
        tools=frozenset(tools),
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
        credential_sha256=_digest(credential),
        active=True,
    )
    _write(path, grant)
    return grant, credential


def revoke_grant(path: Path) -> RemoteGrant:
    grant = load_grant(path)
    withdrawn = RemoteGrant(**{**grant.__dict__, "active": False})
    _write(path, withdrawn)
    return withdrawn


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.remote_mcp.grant")
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue", help="issue a grant; prints the credential once")
    issue.add_argument("--path", type=Path, required=True)
    issue.add_argument("--vault-binding-id", required=True)
    issue.add_argument("--tool", action="append", dest="tools", required=True)
    issue.add_argument("--days", type=int, default=30)
    revoke = sub.add_parser("revoke", help="revoke the grant (authoritative kill)")
    revoke.add_argument("--path", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "issue":
            grant, credential = issue_grant(
                args.path, vault_binding_id=args.vault_binding_id, tools=args.tools, days=args.days
            )
            print(json.dumps({"grant_id": grant.grant_id, "credential": credential}))
        else:
            print(json.dumps({"grant_id": revoke_grant(args.path).grant_id, "revoked": True}))
    except (ValueError, GrantRefused) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
