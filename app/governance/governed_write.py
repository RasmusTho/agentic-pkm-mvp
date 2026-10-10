"""Transitional adapter for `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol
from uuid import uuid4

from app.write_guard import WriteGuard

CONTRACT_VERSION = "governed_write_protocol.v0"

PolicyDecisionStatus = Literal["approved"]
AuthorityReceiptOutcome = Literal["applied", "failed"]


class GovernedWriteProtocolError(RuntimeError):
    """Base error for visible governed-write transition failures."""


class MissingDecisionTokenError(GovernedWriteProtocolError):
    """Raised when a mutation result is recorded without a pre-mutation token."""


class MissingAuthorityReceiptError(GovernedWriteProtocolError):
    """Raised when a state owner mutation produces no mappable receipt."""


class InvalidDecisionTokenError(GovernedWriteProtocolError):
    """Raised when a token is not valid for the mutation receipt being recorded."""


class _MutationLocator(Protocol):
    path: str


class _MutationReceipt(Protocol):
    operation: str
    locator: _MutationLocator
    adapter: str
    trace_id: str | None
    fallback_used: bool


@dataclass(frozen=True)
class PolicyDecision:
    decision_id: str
    status: PolicyDecisionStatus
    action: str
    write_class: str
    actor: str
    resource: str
    reason: str
    issued_at: str
    source: str = "WriteGuard"
    contract_version: str = CONTRACT_VERSION


@dataclass(frozen=True)
class DecisionToken:
    token_id: str
    decision_id: str
    action: str
    write_class: str
    actor: str
    resource: str
    issued_at: str
    valid: bool = True
    contract_version: str = CONTRACT_VERSION


@dataclass(frozen=True)
class GovernedWriteGrant:
    policy_decision: PolicyDecision
    decision_token: DecisionToken


@dataclass(frozen=True)
class AuthorityReceipt:
    receipt_id: str
    decision_token_id: str
    decision_id: str
    action: str
    write_class: str
    actor: str
    resource: str
    outcome: AuthorityReceiptOutcome
    operation: str
    adapter: str
    state_owner: str
    source_receipt_ref: str
    fallback_used: bool
    recorded_at: str
    trace_id: str | None = None
    effect_id: str | None = None
    contract_version: str = CONTRACT_VERSION


class GovernedWriteAdapter:
    """Map current WriteGuard and state-owner receipts into GOV concepts.

    GOV owns admissibility and accountability here. The state owner still
    performs the actual mutation and returns the source mutation receipt.
    """

    def issue_decision_token(
        self,
        *,
        write_guard: WriteGuard,
        action: str,
        write_class: str,
        actor: str,
        resource: str,
    ) -> GovernedWriteGrant:
        write_guard.assert_writes_allowed(action)
        issued_at = _utc_now()
        resource_ref = normalize_resource_ref(resource)
        decision = PolicyDecision(
            decision_id=_id("policy_decision"),
            status="approved",
            action=action,
            write_class=write_class,
            actor=actor,
            resource=resource_ref,
            reason="WriteGuard allowed the bounded durable mutation.",
            issued_at=issued_at,
        )
        token = DecisionToken(
            token_id=_id("decision_token"),
            decision_id=decision.decision_id,
            action=action,
            write_class=write_class,
            actor=actor,
            resource=resource_ref,
            issued_at=issued_at,
        )
        return GovernedWriteGrant(policy_decision=decision, decision_token=token)

    def issue_human_decision_token(
        self,
        *,
        action: str,
        write_class: str,
        actor: str,
        resource: str,
    ) -> GovernedWriteGrant:
        """Issue a GOV token for an explicit human authority decision.

        A human disposition is authorized by the named reviewer through GOV;
        WriteGuard remains a separate state-owner write precondition. Keeping
        those concerns separate prevents health or write availability from
        becoming the accountability record for the reviewer decision.
        """
        if not actor or not actor.strip():
            raise InvalidDecisionTokenError("human decision actor is required")
        issued_at = _utc_now()
        resource_ref = normalize_resource_ref(resource)
        decision = PolicyDecision(
            decision_id=_id("policy_decision"),
            status="approved",
            action=action,
            write_class=write_class,
            actor=actor,
            resource=resource_ref,
            reason="Explicit human reviewer decision authorized by GOV.",
            issued_at=issued_at,
            source="human_review",
        )
        token = DecisionToken(
            token_id=_id("decision_token"),
            decision_id=decision.decision_id,
            action=action,
            write_class=write_class,
            actor=actor,
            resource=resource_ref,
            issued_at=issued_at,
        )
        return GovernedWriteGrant(policy_decision=decision, decision_token=token)

    def validate_decision_token(
        self,
        *,
        decision_token: DecisionToken | None,
        action: str,
        write_class: str,
        actor: str,
        resource: str,
    ) -> DecisionToken:
        """Validate a token against the effect request before it is executed.

        The adapter is the GOV boundary for this check.  Callers must not treat
        the presence of a token object as authorization: every binding field is
        compared to the concrete effect request before the state owner or EXE
        performs its effect.
        """
        if decision_token is None:
            raise MissingDecisionTokenError(
                "authority-bearing effect requires a prevalidated DecisionToken"
            )
        if not decision_token.valid:
            raise InvalidDecisionTokenError("DecisionToken is not valid")
        expected = {
            "action": action,
            "write_class": write_class,
            "actor": actor,
            "resource": normalize_resource_ref(resource),
        }
        actual = {
            "action": decision_token.action,
            "write_class": decision_token.write_class,
            "actor": decision_token.actor,
            "resource": normalize_resource_ref(decision_token.resource),
        }
        mismatched = [key for key, value in expected.items() if actual[key] != value]
        if mismatched:
            raise InvalidDecisionTokenError(
                "DecisionToken does not match effect request: "
                + ", ".join(mismatched)
            )
        return decision_token

    def record_authority_receipt(
        self,
        *,
        decision_token: DecisionToken | None,
        mutation_receipt: _MutationReceipt | None,
        state_owner: str,
        outcome: AuthorityReceiptOutcome = "applied",
        trace_id: str | None = None,
        resource: str | None = None,
        effect_id: str | None = None,
    ) -> AuthorityReceipt:
        if decision_token is None:
            raise MissingDecisionTokenError(
                "authority receipt recording requires a pre-mutation DecisionToken"
            )
        if not decision_token.valid:
            raise InvalidDecisionTokenError("DecisionToken is not valid")
        if mutation_receipt is None:
            raise MissingAuthorityReceiptError(
                "authority receipt recording requires the state owner's mutation receipt"
            )

        mutation_resource = normalize_resource_ref(mutation_receipt.locator.path)
        bound_resource = normalize_resource_ref(resource or mutation_resource)
        if bound_resource != normalize_resource_ref(decision_token.resource):
            raise InvalidDecisionTokenError(
                "DecisionToken resource does not match governed effect target"
            )

        return AuthorityReceipt(
            receipt_id=_id("authority_receipt"),
            decision_token_id=decision_token.token_id,
            decision_id=decision_token.decision_id,
            action=decision_token.action,
            write_class=decision_token.write_class,
            actor=decision_token.actor,
            resource=bound_resource,
            outcome=outcome,
            operation=mutation_receipt.operation,
            adapter=mutation_receipt.adapter,
            state_owner=state_owner,
            source_receipt_ref=(
                f"{mutation_receipt.adapter}:{mutation_receipt.operation}:{mutation_resource}"
            ),
            fallback_used=mutation_receipt.fallback_used,
            recorded_at=_utc_now(),
            trace_id=trace_id or mutation_receipt.trace_id,
            effect_id=effect_id,
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def normalize_resource_ref(resource: str) -> str:
    return resource.strip().replace("\\", "/")


__all__ = [
    "AuthorityReceipt",
    "DecisionToken",
    "GovernedWriteAdapter",
    "GovernedWriteGrant",
    "GovernedWriteProtocolError",
    "InvalidDecisionTokenError",
    "MissingAuthorityReceiptError",
    "MissingDecisionTokenError",
    "PolicyDecision",
    "normalize_resource_ref",
]
