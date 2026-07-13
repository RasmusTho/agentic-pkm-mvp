"""PR-wide review/repair accounting for verification coordinator hosts."""

from __future__ import annotations

import hashlib
import json
from typing import Callable, Mapping, Sequence

from app.dispatcher.verification_dispatch import VerificationDispatchLedger


class VerificationAgentLoop:
    # Durable ledger enforcement: independent re-review requires a fresh session.
    def __init__(
        self,
        ledger: VerificationDispatchLedger,
        run_id: str,
        *,
        holder: str,
        lease_id: str,
        strongest_capability: str = "gpt-5.6-sol",
    ) -> None:
        self.ledger = ledger
        self.run_id = run_id
        self.holder = holder
        self.lease_id = lease_id
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
            holder=self.holder,
            lease_id=self.lease_id,
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
        verifications = [row for row in attempts if row["kind"] == "verification"]
        if not repairs and not verifications:
            raise ValueError("review requires a recorded verification or repair")
        latest = repairs[-1] if repairs else verifications[-1]
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
            holder=self.holder,
            lease_id=self.lease_id,
        )
        return ordinal

    def apply_events(
        self,
        events: Sequence[Mapping[str, object]],
        *,
        context: Mapping[str, object],
    ) -> None:
        """Atomically persist one replay-safe coordinator event batch."""
        if not events:
            return
        head_sha = self._head()
        context_hash = hashlib.sha256(
            json.dumps(
                dict(context),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        batch_payload = {
            "context_hash": context_hash,
            "events": [dict(event) for event in events],
            "head_sha": head_sha,
        }
        batch_id = hashlib.sha256(
            json.dumps(
                batch_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()

        def plan(
            attempts: list[dict[str, object]],
            attempt_id_for: Callable[[int], str],
        ) -> list[dict[str, object]]:
            working = list(attempts)
            planned: list[dict[str, object]] = []
            for index, event in enumerate(events):
                session_id = str(event["session_id"])
                capability = str(event["capability"])
                reasoning_effort = str(event["reasoning_effort"])
                outcome = str(event["outcome"])
                attempt_id = attempt_id_for(index)
                event_kind = event.get("kind")
                if event_kind == "repair":
                    finding_id = str(event["finding_id"])
                    if not finding_id:
                        raise ValueError("repair requires a stable finding id")
                    repairs = [
                        row
                        for row in working
                        if row["kind"] in {"standard_repair", "escalated_repair"}
                    ]
                    if repairs:
                        latest = repairs[-1]["attempt_id"]
                        reviews = [
                            row
                            for row in working
                            if row["kind"] == "review"
                            and isinstance(row["receipt"], Mapping)
                            and row["receipt"].get("reviewed_attempt_id") == latest
                        ]
                        if not reviews or reviews[-1]["outcome"] != "blocking":
                            raise ValueError(
                                "each additional repair requires a fresh blocking review"
                            )
                    strongest = bool(event.get("strongest", False))
                    if strongest and (
                        capability != self.strongest_capability
                        or reasoning_effort not in {"high", "xhigh"}
                    ):
                        raise ValueError(
                            "escalated repair must use the configured strongest capability"
                        )
                    kind = "escalated_repair" if strongest else "standard_repair"
                    ordinal = sum(row["kind"] == kind for row in working) + 1
                    if ordinal > 2:
                        raise ValueError(f"{kind} budget exhausted")
                    if strongest:
                        standard = sum(
                            row["kind"] == "standard_repair" for row in working
                        )
                        if standard < 2:
                            raise ValueError(
                                "strongest capability is only allowed after two standard attempts"
                            )
                    receipt: dict[str, object] = {
                        "finding_id": finding_id,
                        "head_sha": head_sha,
                    }
                elif event_kind == "review":
                    normalized = outcome.lower()
                    if normalized not in {"blocking", "clean"}:
                        raise ValueError("review outcome must be blocking or clean")
                    if any(row["session_id"] == session_id for row in working):
                        raise ValueError("independent re-review requires a fresh session")
                    repairs = [
                        row
                        for row in working
                        if row["kind"] in {"standard_repair", "escalated_repair"}
                    ]
                    verifications = [
                        row for row in working if row["kind"] == "verification"
                    ]
                    if not repairs and not verifications:
                        raise ValueError("review requires a recorded verification or repair")
                    latest = repairs[-1] if repairs else verifications[-1]
                    reviews = [
                        row
                        for row in working
                        if row["kind"] == "review"
                        and isinstance(row["receipt"], Mapping)
                        and row["receipt"].get("reviewed_attempt_id")
                        == latest["attempt_id"]
                    ]
                    if reviews and reviews[-1]["outcome"] == "blocking":
                        raise ValueError("blocking review requires repair before another review")
                    if len(reviews) >= 2:
                        raise ValueError("independent clean re-review budget is complete")
                    kind = "review"
                    outcome = normalized
                    ordinal = sum(row["kind"] == kind for row in working) + 1
                    receipt = {
                        "reviewed_attempt_id": latest["attempt_id"],
                        "head_sha": head_sha,
                        "verdict": normalized,
                    }
                else:
                    raise ValueError("unknown verification review event kind")
                row = {
                    "attempt_id": attempt_id,
                    "kind": kind,
                    "ordinal": ordinal,
                    "session_id": session_id,
                    "capability": capability,
                    "reasoning_effort": reasoning_effort,
                    "context_hash": context_hash,
                    "outcome": outcome,
                    "receipt": receipt,
                }
                working.append(row)
                planned.append(row)
            return planned

        self.ledger.record_attempt_batch(
            self.run_id,
            batch_id,
            len(events),
            head_sha,
            plan,
            holder=self.holder,
            lease_id=self.lease_id,
        )

    def closure_ready(self) -> bool:
        return self.ledger.closure_ready(self.run_id)

    def stop(self, failure_class: str, packet: Mapping[str, object]) -> str:
        exception_id = self.ledger.exception(
            self.run_id,
            failure_class,
            packet,
            holder=self.holder,
            lease_id=self.lease_id,
        )
        self.ledger.terminal(
            self.run_id,
            "needs_human",
            {"exception_id": exception_id, "failure_class": failure_class},
            reason=failure_class,
            holder=self.holder,
            lease_id=self.lease_id,
        )
        return exception_id
