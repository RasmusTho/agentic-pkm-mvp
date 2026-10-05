"""Pure, bounded canvas intent judgment through the Product MARR client.

Only intent text crosses the judgment boundary. Typed inference grants no write
or confirmation authority; unavailable, invalid or uncertain results are UNKNOWN.
Generic chat routing and provider/SDK configuration remain with their owners.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from llm_contract import ChoiceJudgmentAnswer

from app.model_access.codex_remote_transport import CodexRemoteTransport
from app.model_access.executor_network_policy import EXECUTOR_NETWORK_PROFILE, resolve_executor_paths
from app.model_access.product_judgment_contract import ProductJudgmentResult, product_intent_request

logger = logging.getLogger(__name__)

# Consumer-owned acceptance floor, exercised at/below the boundary by deterministic
# contract tests. This is a conservative routing rule, not semantic calibration.
INTENT_CONFIDENCE_FLOOR = 0.8


class IntentClass(str, Enum):
    """The three intent classes from the Hybrid Chat Integration Schema,
    plus the explicit ``UNKNOWN`` failure class (KERNEL-07).

    ``UNKNOWN`` is the explicit no-match choice and the local failure result.
    It authorizes nothing.
    """

    CO_AUTHORING = "co_authoring"
    GOVERNANCE_BEARING = "governance_bearing"
    EXPLORATORY = "exploratory"
    UNKNOWN = "unknown"


class GovernanceActionType(str, Enum):
    """Governance action types recognised by the canvas-to-Panel bridge.

    Defined here (cognition layer) rather than in ``app.chat.governance_router``
    (interaction layer) so the classifier — which must name the action type it
    maps a governance-bearing intent to — never has to import upward into the
    protected interaction layer (#2853). ``app.chat.governance_router``
    re-exports this symbol for its existing importers; it is authoritative
    here.
    """

    FRONTMATTER_UPDATE = "frontmatter_update"
    MATURITY_TRANSITION = "maturity_transition"
    NOTE_LIFECYCLE = "note_lifecycle"
    CROSS_NOTE = "cross_note"


@dataclass(frozen=True)
class IntentClassification:
    """A routing signal only; UNKNOWN is unclassified and cannot authorize writes."""

    intent_class: IntentClass
    action_type: GovernanceActionType | None = None
    classified: bool = True
    rationale: str | None = None
    trace_id: str | None = None


class ProductIntentJudgmentClient(Protocol):
    """The existing Product operation, injectable without exposing route controls."""

    def judge_product_intent(self, intent_text: str) -> ProductJudgmentResult: ...


def _configured_product_client() -> CodexRemoteTransport:
    # Use exactly the first declared Product path; there is no path retry or
    # generic completion/model fallback. Missing configuration refuses pre-send.
    path = resolve_executor_paths(EXECUTOR_NETWORK_PROFILE)[0]
    return CodexRemoteTransport(
        endpoint=path.endpoint,
        path_adapter=path.adapter,
        tls_verify=path.tls_verify,
        client_certificate=path.client_certificate,
        timeout_seconds=30.0,
    )


class IntentClassifierCognition:
    """Validate minimal input and a typed Product result on every classify call."""

    def __init__(self, *, judgment_client: ProductIntentJudgmentClient | None = None) -> None:
        self._judgment_client = judgment_client

    def classify(self, *, intent: str, trace_id: str | None = None) -> IntentClassification:
        # The signature rejects current_body and every undeclared field before
        # constructing a client. Trace stays local and never enters the request.
        try:
            request = product_intent_request(intent)
        except (TypeError, ValueError, UnicodeError):
            return _unknown(trace_id, reason="input_invalid")
        try:
            if self._judgment_client is None:
                client = _configured_product_client()
                try:
                    result = client.judge_product_intent(intent)
                finally:
                    client.close()
            else:
                result = self._judgment_client.judge_product_intent(intent)
        except Exception:
            # No raw exception, caller text, endpoint or credential in diagnostics.
            # A possible send is terminal: never retry or fall back.
            return _unknown(trace_id, reason="judgment_unavailable")
        try:
            # Revalidate even injected or model_construct/mutated nested models.
            result = ProductJudgmentResult.model_validate(result.model_dump(mode="json"))
            if result.outcome != "success":
                return _unknown(trace_id, reason=result.outcome)
            assert result.judgment is not None
            judgment = result.judgment.validate_against(request)
            answers = {answer.question_id: answer for answer in judgment.answers}
            intent_answer = answers["intent_class"]
            action_answer = answers["action_type"]
            assert isinstance(intent_answer, ChoiceJudgmentAnswer)
            assert isinstance(action_answer, ChoiceJudgmentAnswer)
            if not _confident(intent_answer):
                return _unknown(trace_id, reason="low_confidence")
            intent_class = IntentClass(intent_answer.choice)
            if intent_class is IntentClass.UNKNOWN:
                return _unknown(trace_id, reason="no_match")
            action_type = None
            if intent_class is IntentClass.GOVERNANCE_BEARING:
                if not _confident(action_answer) or action_answer.choice == "unknown":
                    return _unknown(trace_id, reason="uncertain_action")
                action_type = GovernanceActionType(action_answer.choice)
            elif action_answer.choice != "unknown":
                return _unknown(trace_id, reason="inconsistent_action")
            return IntentClassification(intent_class, action_type=action_type, trace_id=trace_id)
        except Exception:
            return _unknown(trace_id, reason="response_invalid")


def _confident(answer: ChoiceJudgmentAnswer) -> bool:
    return (
        answer.confidence >= INTENT_CONFIDENCE_FLOOR
        and answer.probabilities[answer.choice] >= INTENT_CONFIDENCE_FLOOR
    )


def _unknown(trace_id: str | None, *, reason: str) -> IntentClassification:
    logger.warning("intent classification degraded to UNKNOWN: %s", reason)
    return IntentClassification(
        intent_class=IntentClass.UNKNOWN, classified=False, rationale=reason, trace_id=trace_id,
    )


__all__ = [
    "GovernanceActionType", "INTENT_CONFIDENCE_FLOOR", "IntentClass", "IntentClassification",
    "IntentClassifierCognition", "ProductIntentJudgmentClient",
]
