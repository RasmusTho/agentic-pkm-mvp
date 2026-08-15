"""Verification review/repair accounting for coordinator hosts."""

from __future__ import annotations

import hashlib
import json
from typing import Callable, Mapping, Sequence

from app.dispatcher.verification_dispatch import VerificationDispatchLedger


HUMAN_EXCEPTION_FAILURE_CLASSES = frozenset(
    {
        "safety-critical",
        "authority-critical",
        "intent-critical",
        "autonomous-failure-critical",
    }
)
HUMAN_EXCEPTION_PACKET_FIELDS = frozenset(
    {
        "failure_class",
        "original_intent",
        "current_state",
        "tried_actions",
        "evidence",
        "why_unsafe",
        "options",
        "no_action_option",
        "recommended_option",
        "recommendation_rationale",
        "consequence_of_doing_nothing",
    }
)
_HUMAN_EXCEPTION_BINDING_FIELDS = frozenset(
    {"governing_issue", "head_sha", "receipt_ids", "summary"}
)


def valid_human_exception_packet(packet: object) -> bool:
    if not isinstance(packet, Mapping):
        return False
    keys = set(packet)
    if not HUMAN_EXCEPTION_PACKET_FIELDS.issubset(keys) or not keys.issubset(
        HUMAN_EXCEPTION_PACKET_FIELDS | _HUMAN_EXCEPTION_BINDING_FIELDS
    ):
        return False
    if packet.get("failure_class") not in HUMAN_EXCEPTION_FAILURE_CLASSES:
        return False
    for field in (
        "original_intent",
        "current_state",
        "why_unsafe",
        "no_action_option",
        "recommended_option",
        "recommendation_rationale",
        "consequence_of_doing_nothing",
    ):
        if not isinstance(packet.get(field), str) or not packet[field].strip():
            return False
    for field in ("tried_actions", "evidence"):
        values = packet.get(field)
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            return False
    options = packet["options"]
    if not isinstance(options, list) or not 2 <= len(options) <= 3:
        return False
    option_ids: list[str] = []
    for option in options:
        if not isinstance(option, Mapping) or set(option) != {
            "id",
            "label",
            "consequence",
        }:
            return False
        if any(
            not isinstance(option.get(field), str) or not option[field].strip()
            for field in ("id", "label", "consequence")
        ):
            return False
        option_ids.append(str(option["id"]))
    return (
        bool(packet["tried_actions"])
        and bool(packet["evidence"])
        and len(set(option_ids)) == len(option_ids)
        and packet["no_action_option"] in option_ids
        and packet["recommended_option"] in option_ids
    )


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

    @staticmethod
    def _progress_receipt(
        attempts: Sequence[Mapping[str, object]],
        *,
        finding_id: str,
        failure_domain: str,
        mechanism_id: str,
        head_sha: str,
        progress_evidence: Mapping[str, object] | None,
    ) -> dict[str, object] | None:
        """Bind a repeated repair to concrete progress on its prior repair."""
        def identity(row: Mapping[str, object], field: str) -> object:
            receipt = row.get("receipt")
            return row.get(field) or (
                receipt.get(field) if isinstance(receipt, Mapping) else None
            )

        prior_repairs = [
            row
            for row in attempts
            if row["kind"] in {"standard_repair", "escalated_repair"}
            and identity(row, "finding_id") == finding_id
            and identity(row, "failure_domain") == failure_domain
            and identity(row, "mechanism_id") == mechanism_id
        ]
        if not prior_repairs:
            return None
        if not isinstance(progress_evidence, Mapping):
            raise ValueError(
                "repeated repair requires durable progress evidence"
            )
        required = {
            "prior_attempt_id",
            "prior_review_attempt_id",
            "reviewed_head_sha",
            "mechanism_state_change",
            "validation_delta",
        }
        if set(progress_evidence) != required:
            raise ValueError("repair progress evidence is malformed")
        progress_values = [progress_evidence[field] for field in required]
        if any(
            not isinstance(value, str) or not value.strip() for value in progress_values
        ):
            raise ValueError("repair progress evidence is malformed")
        prior = prior_repairs[-1]
        prior_reviews = [
            row
            for row in attempts
            if row["kind"] == "review"
            and row["outcome"] == "blocking"
            and row.get("finding_id") == finding_id
            and row.get("failure_domain") == failure_domain
            and row.get("mechanism_id") == mechanism_id
            and isinstance(row.get("receipt"), Mapping)
            and identity(row, "reviewed_attempt_id") == prior["attempt_id"]
        ]
        if not prior_reviews:
            raise ValueError("repeated repair requires a fresh blocking review")
        prior_review = prior_reviews[-1]
        prior_review_receipt = prior_review.get("receipt")
        assert isinstance(prior_review_receipt, Mapping)
        if (
            progress_evidence["prior_attempt_id"] != prior["attempt_id"]
            or progress_evidence["prior_review_attempt_id"] != prior_review["attempt_id"]
            or progress_evidence["reviewed_head_sha"]
            != prior_review_receipt.get("head_sha")
            or prior_review_receipt.get("head_sha") != head_sha
        ):
            raise ValueError("repair progress evidence is not bound to the prior reviewed repair")
        return dict(progress_evidence)

    def repair(
        self,
        *,
        finding_id: str,
        failure_domain: str,
        mechanism_id: str,
        session_id: str,
        capability: str,
        reasoning_effort: str,
        context: Mapping[str, object],
        outcome: str,
        strongest: bool = False,
        progress_evidence: Mapping[str, object] | None = None,
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
        progress_receipt = self._progress_receipt(
            attempts,
            finding_id=finding_id,
            failure_domain=failure_domain,
            mechanism_id=mechanism_id,
            head_sha=self._head(),
            progress_evidence=progress_evidence,
        )
        receipt: dict[str, object] = {
            "finding_id": finding_id,
            "failure_domain": failure_domain,
            "mechanism_id": mechanism_id,
            "head_sha": self._head(),
        }
        if progress_receipt is not None:
            receipt["progress_evidence"] = progress_receipt
        ordinal = self.ledger.record_attempt(
            self.run_id,
            "escalated_repair" if strongest else "standard_repair",
            session_id,
            capability,
            reasoning_effort,
            context,
            outcome,
            receipt,
            holder=self.holder,
            lease_id=self.lease_id,
        )
        return ordinal

    def review(
        self,
        *,
        finding_id: str | None = None,
        failure_domain: str | None = None,
        mechanism_id: str | None = None,
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
        normalized = outcome.lower()
        if normalized not in {"blocking", "clean"}:
            raise ValueError("review outcome must be blocking or clean")
        same_blocking_round = bool(
            reviews
            and reviews[-1]["outcome"] == "blocking"
            and normalized == "blocking"
            and reviews[-1]["session_id"] == session_id
            and reviews[-1]["failure_domain"] == failure_domain
            and reviews[-1]["mechanism_id"] == mechanism_id
        )
        if reviews and reviews[-1]["outcome"] == "blocking" and not same_blocking_round:
            raise ValueError("blocking review requires repair before another review")
        if len(reviews) >= 2 and normalized == "clean":
            raise ValueError("independent clean re-review budget is complete")
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
                "finding_id": finding_id,
                "failure_domain": failure_domain,
                "mechanism_id": mechanism_id,
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
                    failure_domain = event.get("failure_domain")
                    mechanism_id = event.get("mechanism_id")
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
                    progress_evidence = event.get("progress_evidence")
                    progress_receipt = self._progress_receipt(
                        working,
                        finding_id=finding_id,
                        failure_domain=str(failure_domain),
                        mechanism_id=str(mechanism_id),
                        head_sha=head_sha,
                        progress_evidence=(
                            progress_evidence
                            if isinstance(progress_evidence, Mapping)
                            else None
                        ),
                    )
                    kind = "escalated_repair" if strongest else "standard_repair"
                    ordinal = sum(row["kind"] == kind for row in working) + 1
                    receipt: dict[str, object] = {
                        "finding_id": finding_id,
                        "failure_domain": failure_domain,
                        "mechanism_id": mechanism_id,
                        "head_sha": head_sha,
                    }
                    if progress_receipt is not None:
                        receipt["progress_evidence"] = progress_receipt
                elif event_kind == "review":
                    normalized = outcome.lower()
                    if normalized not in {"blocking", "clean"}:
                        raise ValueError("review outcome must be blocking or clean")
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
                    last_review_receipt = (
                        reviews[-1].get("receipt") if reviews else None
                    )
                    same_blocking_round = bool(
                        reviews
                        and reviews[-1]["outcome"] == "blocking"
                        and normalized == "blocking"
                        and reviews[-1]["session_id"] == session_id
                        and isinstance(last_review_receipt, Mapping)
                        and last_review_receipt.get("failure_domain")
                        == event.get("failure_domain")
                        and last_review_receipt.get("mechanism_id")
                        == event.get("mechanism_id")
                    )
                    reused_session = any(
                        row["session_id"] == session_id for row in working
                    )
                    if reused_session and not same_blocking_round:
                        raise ValueError("independent re-review requires a fresh session")
                    if reviews and reviews[-1]["outcome"] == "blocking" and not same_blocking_round:
                        raise ValueError("blocking review requires repair before another review")
                    if len(reviews) >= 2 and normalized == "clean":
                        raise ValueError("independent clean re-review budget is complete")
                    kind = "review"
                    outcome = normalized
                    ordinal = sum(row["kind"] == kind for row in working) + 1
                    receipt = {
                        "reviewed_attempt_id": latest["attempt_id"],
                        "head_sha": head_sha,
                        "verdict": normalized,
                        "finding_id": event.get("finding_id"),
                        "failure_domain": event.get("failure_domain"),
                        "mechanism_id": event.get("mechanism_id"),
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
        if (
            failure_class not in HUMAN_EXCEPTION_FAILURE_CLASSES
            or packet.get("failure_class") != failure_class
            or not valid_human_exception_packet(packet)
        ):
            raise ValueError("invalid Human Exception failure class or packet")
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
