"""PR-wide review/repair accounting for verification coordinator hosts."""

from __future__ import annotations

from typing import Mapping

from app.dispatcher.verification_dispatch import VerificationDispatchLedger


class VerificationAgentLoop:
    # Durable ledger enforcement: independent re-review requires a fresh session.
    def __init__(
        self,
        ledger: VerificationDispatchLedger,
        run_id: str,
        *,
        strongest_capability: str = "gpt-5.6-sol",
    ) -> None:
        self.ledger = ledger
        self.run_id = run_id
        self.strongest_capability = strongest_capability

    def _head(self) -> str:
        run = self.ledger.get(self.run_id)
        if run is None:
            raise ValueError("verification run not found")
        return run.head_sha

    def repair(
        self,
        *,
        finding_id: str,
        session_id: str,
        capability: str,
        reasoning_effort: str,
        context: Mapping[str, object],
        outcome: str,
        strongest: bool = False,
    ) -> int:
        if not finding_id:
            raise ValueError("repair requires a stable finding id")
        attempts = self.ledger.attempts(self.run_id)
        repairs = [row for row in attempts if row["kind"] in {"standard_repair", "escalated_repair"}]
        if repairs:
            latest = repairs[-1]["attempt_id"]
            reviews = [
                row for row in attempts
                if row["kind"] == "review"
                and isinstance(row["receipt"], Mapping)
                and row["receipt"].get("reviewed_attempt_id") == latest
            ]
            if not reviews or reviews[-1]["outcome"] != "blocking":
                raise ValueError("each additional repair requires a fresh blocking review")
        if strongest and (
            capability != self.strongest_capability
            or reasoning_effort not in {"high", "xhigh"}
        ):
            raise ValueError("escalated repair must use the configured strongest capability")
        ordinal = self.ledger.record_attempt(
            self.run_id,
            "escalated_repair" if strongest else "standard_repair",
            session_id,
            capability,
            reasoning_effort,
            context,
            outcome,
            {"finding_id": finding_id, "head_sha": self._head()},
        )
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
        attempts = self.ledger.attempts(self.run_id)
        repairs = [row for row in attempts if row["kind"] in {"standard_repair", "escalated_repair"}]
        if not repairs:
            raise ValueError("review requires a recorded repair")
        latest = repairs[-1]
        reviews = [
            row for row in attempts
            if row["kind"] == "review"
            and isinstance(row["receipt"], Mapping)
            and row["receipt"].get("reviewed_attempt_id") == latest["attempt_id"]
        ]
        if reviews and reviews[-1]["outcome"] == "blocking":
            raise ValueError("blocking review requires repair before another review")
        if len(reviews) >= 2:
            raise ValueError("independent clean re-review budget is complete")
        normalized = outcome.lower()
        if normalized not in {"blocking", "clean"}:
            raise ValueError("review outcome must be blocking or clean")
        ordinal = self.ledger.record_attempt(
            self.run_id,
            "review",
            session_id,
            capability,
            reasoning_effort,
            context,
            normalized,
            {
                "reviewed_attempt_id": latest["attempt_id"],
                "head_sha": self._head(),
                "verdict": normalized,
            },
        )
        return ordinal

    def closure_ready(self) -> bool:
        return self.ledger.closure_ready(self.run_id)

    def stop(self, failure_class: str, packet: Mapping[str, object]) -> str:
        exception_id = self.ledger.exception(self.run_id, failure_class, packet)
        run = self.ledger.get(self.run_id)
        if run is None:
            raise ValueError("verification run not found")
        if run.status in {"claimed", "running"} and run.claimed_by and run.lease_id:
            claimed = run
        else:
            claimed = self.ledger.claim(self.run_id, "verification-agent-loop")
        self.ledger.terminal(
            self.run_id,
            "needs_human",
            {"exception_id": exception_id, "failure_class": failure_class},
            reason=failure_class,
            holder=claimed.claimed_by or "",
            lease_id=claimed.lease_id or "",
        )
        return exception_id
