"""PR-wide review/repair accounting for verification coordinator hosts."""

from __future__ import annotations

from typing import Mapping

from app.dispatcher.verification_dispatch import VerificationDispatchLedger


class VerificationAgentLoop:
    def __init__(self, ledger: VerificationDispatchLedger, run_id: str) -> None:
        self.ledger = ledger
        self.run_id = run_id
        self._last_repair_session: str | None = None
        self._last_review_session: str | None = None

    def repair(
        self,
        *,
        session_id: str,
        capability: str,
        reasoning_effort: str,
        context: Mapping[str, object],
        outcome: str,
        strongest: bool = False,
    ) -> int:
        ordinal = self.ledger.record_attempt(
            self.run_id,
            "escalated_repair" if strongest else "standard_repair",
            session_id,
            capability,
            reasoning_effort,
            context,
            outcome,
        )
        self._last_repair_session = session_id
        return ordinal

    def review(
        self,
        *,
        session_id: str,
        capability: str,
        reasoning_effort: str,
        context: Mapping[str, object],
        outcome: str,
    ) -> int:
        if session_id in {self._last_repair_session, self._last_review_session}:
            raise ValueError("independent re-review requires a fresh session")
        ordinal = self.ledger.record_attempt(
            self.run_id,
            "review",
            session_id,
            capability,
            reasoning_effort,
            context,
            outcome,
        )
        self._last_review_session = session_id
        return ordinal

    def stop(self, failure_class: str, packet: Mapping[str, object]) -> str:
        exception_id = self.ledger.exception(self.run_id, failure_class, packet)
        self.ledger.terminal(
            self.run_id,
            "needs_human",
            {"exception_id": exception_id, "failure_class": failure_class},
            reason=failure_class,
        )
        return exception_id
