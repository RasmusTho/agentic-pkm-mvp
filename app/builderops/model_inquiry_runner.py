"""Bounded, artifact-first execution of pre-ticket model inquiry turns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.model_inquiry_adapters import (
    AdapterExecutionError,
    AdapterUnavailableError,
    ModelTurnAdapter,
    load_adapter_descriptors,
    load_adapters,
    sanitized_adapter_identity,
)
from app.builderops.model_inquiry_contract import (
    MODEL_TURN_SYSTEM_PROMPT,
    ModelTurnResponse,
    canonical_hash,
    initial_context_packet,
    model_turn_request_hash,
    parse_model_turn_response,
)
from app.builderops.models import BuilderOpsValidationError

ROLES = ("fable", "gpt_codex")


@dataclass(frozen=True)
class TurnExecution:
    turn: dict[str, Any]
    response: ModelTurnResponse


class ModelInquiryRunner:
    def __init__(
        self,
        service: ModelInquiryService,
        adapters: Mapping[str, ModelTurnAdapter] | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.service = service
        self._adapters = dict(adapters) if adapters is not None else None
        self._env = dict(env) if env is not None else None

    def plan(self, inquiry_id: str, *, max_rounds: int) -> dict[str, Any]:
        _validate_max_rounds(max_rounds)
        trace = self.service.trace(inquiry_id)
        context = _initial_context(trace)
        descriptors = load_adapter_descriptors(self._env)
        draft_requests = [
            self._request_packet(
                trace,
                role=role,
                phase="draft",
                round_index=0,
                input_refs=["question"],
                reviewed_refs=[],
                adapter_identity=descriptors[role],
                context_hash=context["context_hash"],
            )
            for role in ROLES
        ]
        unavailable = [role for role in ROLES if not descriptors[role].get("available")]
        planned_reviews = []
        for round_index in range(max_rounds):
            for role in ROLES:
                basis = {
                    "schema": "builderops.model-turn-request-plan.v1",
                    "inquiry_id": inquiry_id,
                    "role": role,
                    "phase": "review",
                    "round_index": round_index,
                    "context_hash": context["context_hash"],
                    "adapter_identity": descriptors[role],
                    "input_basis": "latest persisted role artifacts",
                }
                planned_reviews.append(
                    {
                        "turn_id": f"review-{round_index:03d}-{role}",
                        "phase": "review",
                        "role": role,
                        "round_index": round_index,
                        "request_hash": canonical_hash(basis),
                        "adapter_request_id": f"adapter_req_{canonical_hash(basis)[:32]}",
                        "context_hash": context["context_hash"],
                    }
                )
        return {
            "schema": "builderops.model-inquiry-run-plan.v1",
            "inquiry_id": inquiry_id,
            "dry_run": True,
            "context_hash": context["context_hash"],
            "question_artifact_hash": trace["question"]["artifact_hash"],
            "max_rounds": max_rounds,
            "adapter_descriptors": descriptors,
            "unavailable_roles": unavailable,
            "planned_turns": [
                {
                    "turn_id": f"draft-{request['role']}",
                    "phase": "draft",
                    "role": request["role"],
                    "request_hash": request["request_hash"],
                    "adapter_request_id": request["adapter_request_id"],
                    "context_hash": request["context_hash"],
                }
                for request in draft_requests
            ]
            + planned_reviews,
        }

    def run(
        self,
        inquiry_id: str,
        *,
        max_rounds: int = 3,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if dry_run:
            return self.plan(inquiry_id, max_rounds=max_rounds)
        _validate_max_rounds(max_rounds)
        with self.service.inquiry_runner_lock(inquiry_id):
            trace = self.service.trace(inquiry_id)
            terminal = _terminal_run_receipt(trace)
            if terminal is not None:
                return _terminal_result(inquiry_id, terminal, replayed=True)
            try:
                adapters = self._adapters if self._adapters is not None else load_adapters(self._env)
            except (AdapterUnavailableError, BuilderOpsValidationError):
                return self._configuration_failure(
                    inquiry_id,
                    trace,
                )
            if set(adapters) != set(ROLES):
                return self._configuration_failure(
                    inquiry_id,
                    trace,
                )
            context_hash = _initial_context(trace)["context_hash"]
            drafts: list[TurnExecution] = []
            for role in ROLES:
                execution = self._execute_turn(
                    inquiry_id,
                    role=role,
                    phase="draft",
                    round_index=0,
                    input_refs=["question"],
                    reviewed_refs=[],
                    adapter=adapters[role],
                    context_hash=context_hash,
                )
                if isinstance(execution, dict):
                    return execution
                drafts.append(execution)

            latest_refs = [item.turn["turn_id"] for item in drafts]
            for round_index in range(max_rounds):
                reviews: list[TurnExecution] = []
                for role in ROLES:
                    execution = self._execute_turn(
                        inquiry_id,
                        role=role,
                        phase="review",
                        round_index=round_index,
                        input_refs=list(latest_refs),
                        reviewed_refs=list(latest_refs),
                        adapter=adapters[role],
                        context_hash=context_hash,
                    )
                    if isinstance(execution, dict):
                        return execution
                    reviews.append(execution)
                accepted = {item.response.accepted_artifact_hash for item in reviews}
                if all(item.response.stance == "accept" for item in reviews) and len(accepted) == 1:
                    consensus_hash = next(iter(accepted))
                    trace = self.service.trace(inquiry_id)
                    accepted_turn = next(
                        (
                            turn
                            for turn in trace["turns"]
                            if turn["artifact_hash"] == consensus_hash
                        ),
                        None,
                    )
                    if accepted_turn is None:
                        return self._terminate(
                            inquiry_id,
                            "malformed_output",
                            {"classification": "consensus hash does not name a persisted artifact"},
                            trace,
                        )
                    self.service.commit_synthesis(
                        inquiry_id,
                        content=accepted_turn["content"],
                        input_artifact_refs=[accepted_turn["turn_id"]],
                        source_refs=trace["source_refs"],
                    )
                    return self._terminate(
                        inquiry_id,
                        "consensus",
                        {
                            "accepted_artifact_hash": consensus_hash,
                            "round_index": round_index,
                        },
                        self.service.trace(inquiry_id),
                    )
                latest_refs = [item.turn["turn_id"] for item in reviews]
            return self._terminate(
                inquiry_id,
                "max_rounds_exhausted",
                {"max_rounds": max_rounds},
                self.service.trace(inquiry_id),
            )

    def _execute_turn(
        self,
        inquiry_id: str,
        *,
        role: str,
        phase: str,
        round_index: int,
        input_refs: list[str],
        reviewed_refs: list[str],
        adapter: ModelTurnAdapter,
        context_hash: str,
    ) -> TurnExecution | dict[str, Any]:
        trace = self.service.trace(inquiry_id)
        turn_id = f"draft-{role}" if phase == "draft" else f"review-{round_index:03d}-{role}"
        request = self._request_packet(
            trace,
            role=role,
            phase=phase,
            round_index=round_index,
            input_refs=input_refs,
            reviewed_refs=reviewed_refs,
            adapter_identity=sanitized_adapter_identity(adapter),
            context_hash=context_hash,
        )
        existing = next((turn for turn in trace["turns"] if turn["turn_id"] == turn_id), None)
        if existing is not None:
            mismatch = _existing_turn_mismatch(
                existing,
                request=request,
                role=role,
                phase=phase,
                round_index=round_index,
                input_refs=input_refs,
                adapter=adapter,
            )
            if mismatch is not None:
                return self._attempt_failure(
                    inquiry_id,
                    "provider_error",
                    request,
                    trace,
                    RuntimeError(mismatch),
                )
            self.service.commit_terminal_turn_receipt(
                inquiry_id,
                turn_id=turn_id,
                outcome="accepted",
                source_refs=trace["source_refs"],
            )
            return TurnExecution(existing, parse_model_turn_response(existing["content"]))
        prior_attempt = next(
            (
                receipt
                for receipt in trace["receipts"]
                if receipt.get("event_type") == "inquiry_provider_attempt_terminal"
                and receipt.get("adapter_request_id") == request["adapter_request_id"]
            ),
            None,
        )
        if prior_attempt is not None:
            return self._terminate(
                inquiry_id,
                str(prior_attempt["outcome"]),
                dict(prior_attempt.get("details", {})),
                trace,
            )
        try:
            result = adapter.execute(request)
        except AdapterUnavailableError as exc:
            return self._attempt_failure(inquiry_id, "provider_unavailable", request, trace, exc)
        except AdapterExecutionError as exc:
            return self._attempt_failure(inquiry_id, "provider_error", request, trace, exc)
        except Exception as exc:
            return self._attempt_failure(inquiry_id, "provider_error", request, trace, exc)
        output_hash = canonical_hash(result.response_text)
        try:
            provider_request_id = _safe_provider_request_id(result.provider_request_id)
        except BuilderOpsValidationError as exc:
            return self._attempt_failure(
                inquiry_id,
                "provider_error",
                request,
                trace,
                exc,
                output_hash=output_hash,
            )
        try:
            response = parse_model_turn_response(result.response_text)
            output_hash = canonical_hash(response.to_dict())
            if response.reviewed_artifact_refs != reviewed_refs:
                raise BuilderOpsValidationError(
                    "model response reviewed_artifact_refs do not match persisted request inputs"
                )
            if response.stance == "refuse":
                return self._attempt_failure(
                    inquiry_id,
                    "provider_refused",
                    request,
                    trace,
                    RuntimeError("provider returned refusal stance"),
                    output_hash=output_hash,
                )
            if phase == "draft" and response.stance != "draft":
                raise BuilderOpsValidationError("independent draft must use draft stance")
            if phase == "review" and response.stance == "draft":
                raise BuilderOpsValidationError("review turn cannot use draft stance")
        except BuilderOpsValidationError as exc:
            return self._attempt_failure(
                inquiry_id,
                "malformed_output",
                request,
                trace,
                exc,
                output_hash=output_hash,
            )
        if response.accepted_artifact_hash is not None and not any(
            turn["artifact_hash"] == response.accepted_artifact_hash
            and turn["turn_id"] in reviewed_refs
            for turn in trace["turns"]
        ):
            return self._attempt_failure(
                inquiry_id,
                "malformed_output",
                request,
                trace,
                RuntimeError("accepted_artifact_hash is not a current reviewed artifact"),
                output_hash=output_hash,
            )
        metadata = {
            "adapter_request_id": request["adapter_request_id"],
            "provider_request_id": provider_request_id,
            "adapter_id": adapter.adapter_id,
            "provider": adapter.provider,
            "model": adapter.model,
            "context_hash": context_hash,
            "request_hash": request["request_hash"],
            "input_hash": request["input_hash"],
            "output_hash": output_hash,
            "phase": phase,
            "round_index": round_index,
            "stance": response.stance,
            "accepted_artifact_hash": response.accepted_artifact_hash,
        }
        sequence = max((turn["sequence"] for turn in trace["turns"]), default=-1) + 1
        try:
            turn = self.service.commit_turn(
                inquiry_id,
                turn_id=turn_id,
                sequence=sequence,
                role=role,
                content=response.canonical_json(),
                input_artifact_refs=input_refs,
                source_refs=trace["source_refs"],
                provider_metadata=metadata,
            )
        except Exception as exc:
            return self._attempt_failure(
                inquiry_id,
                "persistence_failed",
                request,
                trace,
                exc,
                output_hash=output_hash,
            )
        self.service.commit_terminal_turn_receipt(
            inquiry_id,
            turn_id=turn_id,
            outcome="accepted",
            source_refs=trace["source_refs"],
        )
        return TurnExecution(turn, response)

    def _request_packet(
        self,
        trace: Mapping[str, Any],
        *,
        role: str,
        phase: str,
        round_index: int,
        input_refs: list[str],
        reviewed_refs: list[str],
        adapter_identity: Mapping[str, Any],
        context_hash: str,
    ) -> dict[str, Any]:
        artifacts = {"question": trace["question"], **{turn["turn_id"]: turn for turn in trace["turns"]}}
        if any(ref not in artifacts for ref in input_refs):
            raise BuilderOpsValidationError("runner request contains non-persisted input artifact")
        inputs = [
            {
                "artifact_id": ref,
                "artifact_hash": artifacts[ref]["artifact_hash"],
                "content": artifacts[ref]["content"],
            }
            for ref in input_refs
        ]
        input_hash = canonical_hash(
            [
                {"artifact_id": item["artifact_id"], "artifact_hash": item["artifact_hash"]}
                for item in inputs
            ]
        )
        identity = dict(adapter_identity)
        request_hash = model_turn_request_hash(
            inquiry_id=str(trace["inquiry"]["inquiry_id"]),
            role=role,
            phase=phase,
            round_index=round_index,
            context_hash=context_hash,
            input_hash=input_hash,
            input_artifact_refs=input_refs,
            adapter_id=str(identity.get("adapter_id", "")),
            provider=str(identity.get("provider", "")),
            model=str(identity.get("model", "")),
        )
        base = {
            "schema": "builderops.model-turn-request.v1",
            "inquiry_id": trace["inquiry"]["inquiry_id"],
            "role": role,
            "phase": phase,
            "round_index": round_index,
            "system_prompt": MODEL_TURN_SYSTEM_PROMPT,
            "context_hash": context_hash,
            "input_hash": input_hash,
            "input_artifacts": inputs,
            "reviewed_artifact_refs": reviewed_refs,
            "adapter_identity": identity,
        }
        return {
            **base,
            "request_hash": request_hash,
            "adapter_request_id": f"adapter_req_{request_hash[:32]}",
        }

    def _attempt_failure(
        self,
        inquiry_id: str,
        outcome: str,
        request: Mapping[str, Any],
        trace: Mapping[str, Any],
        error: Exception,
        *,
        output_hash: str | None = None,
    ) -> dict[str, Any]:
        details = {
            "adapter_request_id": request["adapter_request_id"],
            "request_hash": request["request_hash"],
            "context_hash": request["context_hash"],
            "input_hash": request["input_hash"],
            "output_hash": output_hash,
            "classification": _error_classification(error, outcome),
        }
        self.service.commit_provider_attempt_receipt(
            inquiry_id,
            adapter_request_id=str(request["adapter_request_id"]),
            outcome=outcome,
            details=details,
            source_refs=trace["source_refs"],
        )
        return self._terminate(inquiry_id, outcome, details, self.service.trace(inquiry_id))

    def _configuration_failure(
        self,
        inquiry_id: str,
        trace: Mapping[str, Any],
    ) -> dict[str, Any]:
        request_id = "adapter_req_configuration"
        details = {
            "adapter_request_id": request_id,
            "classification": "explicit role adapter unavailable",
        }
        self.service.commit_provider_attempt_receipt(
            inquiry_id,
            adapter_request_id=request_id,
            outcome="provider_unavailable",
            details=details,
            source_refs=list(trace["source_refs"]),
        )
        return self._terminate(
            inquiry_id,
            "provider_unavailable",
            details,
            self.service.trace(inquiry_id),
        )

    def _terminate(
        self,
        inquiry_id: str,
        outcome: str,
        details: Mapping[str, Any],
        trace: Mapping[str, Any],
    ) -> dict[str, Any]:
        receipt = self.service.commit_run_terminal_receipt(
            inquiry_id,
            outcome=outcome,
            details=details,
            source_refs=list(trace["source_refs"]),
        )
        return _terminal_result(inquiry_id, receipt, replayed=False)


def _initial_context(trace: Mapping[str, Any]) -> dict[str, Any]:
    packet = initial_context_packet(
        inquiry_id=str(trace["inquiry"]["inquiry_id"]),
        workflow=str(trace["inquiry"]["workflow"]),
        question_artifact_id=str(trace["question"]["artifact_id"]),
        question_artifact_hash=str(trace["question"]["artifact_hash"]),
        source_refs=list(trace["question"]["source_refs"]),
    )
    return {"packet": packet, "context_hash": canonical_hash(packet)}


def _terminal_run_receipt(trace: Mapping[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            receipt
            for receipt in trace["receipts"]
            if receipt.get("event_type") == "inquiry_run_terminal"
        ),
        None,
    )


def _terminal_result(
    inquiry_id: str,
    receipt: Mapping[str, Any],
    *,
    replayed: bool,
) -> dict[str, Any]:
    return {
        "schema": "builderops.model-inquiry-run-result.v1",
        "inquiry_id": inquiry_id,
        "outcome": receipt["outcome"],
        "terminal_receipt_id": receipt["id"],
        "details": receipt.get("details", {}),
        "replayed": replayed,
    }


def _validate_max_rounds(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 20:
        raise BuilderOpsValidationError("max_rounds must be between 1 and 20")


def _error_classification(error: Exception, outcome: str) -> str:
    if outcome == "malformed_output":
        return "provider output failed strict response validation"
    if outcome == "provider_refused":
        return "provider returned explicit refusal"
    if outcome == "provider_unavailable":
        return "explicit role adapter unavailable"
    if outcome == "provider_error":
        return "provider adapter execution failed"
    if outcome == "persistence_failed":
        return "provider result was not durably committed"
    return type(error).__name__


def _safe_provider_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    lowered = cleaned.lower()
    if (
        not cleaned
        or len(cleaned) > 256
        or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for char in cleaned)
        or any(token in lowered for token in ("secret", "credential", "bearer", "api_key", "token"))
    ):
        raise BuilderOpsValidationError("provider request ID failed safe identifier validation")
    return cleaned


def _existing_turn_mismatch(
    turn: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    role: str,
    phase: str,
    round_index: int,
    input_refs: list[str],
    adapter: ModelTurnAdapter,
) -> str | None:
    expected = {
        "role": role,
        "phase": phase,
        "round_index": round_index,
        "input_artifact_refs": input_refs,
        "adapter_id": adapter.adapter_id,
        "provider": adapter.provider,
        "model": adapter.model,
        "context_hash": request["context_hash"],
        "request_hash": request["request_hash"],
        "input_hash": request["input_hash"],
        "adapter_request_id": request["adapter_request_id"],
    }
    if any(turn.get(field) != value for field, value in expected.items()):
        return "persisted deterministic turn does not match the configured request"
    return None


__all__ = ["ModelInquiryRunner"]
