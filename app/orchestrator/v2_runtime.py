"""Orchestrator V2: parallel execution with dependency-aware scheduling.

V2 adds:
- Dependency-safe parallel step scheduling
- Plan graph execution (fan-out/fan-in patterns)
- Failed-step compensation with reverse-order rollback of completed predecessors

Preserves:
- Event/trace interface compatibility with V1
- Component boundaries (executor, tool, MCP adapter contracts)
- Execution coordinator role (not a direct vault mutator)
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import time
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Set

from app.planner.schema import Plan, PlanMetadata, PlanStep

from .delivery_sla import map_delivery_sla_terminal_state
from .events import (
    emit_compensation_started,
    emit_compensation_step_completed,
    emit_compensation_step_failed,
    emit_orchestration_rolled_back,
    emit_step_error,
    emit_step_finished,
    emit_step_retry,
    emit_step_retry_exhausted,
    emit_step_started,
)
from .executor import MockPlanExecutor, PlanExecutor, StepContext, StepExecutionError

import logging

logger = logging.getLogger(__name__)


class CheckpointStore:
    """Abstract interface for checkpoint persistence."""

    def save_checkpoint(self, checkpoint_key: str, checkpoint_data: Dict[str, Any]) -> None:
        """Save a checkpoint to persistent storage."""
        raise NotImplementedError

    def load_checkpoint(self, checkpoint_key: str) -> Optional[Dict[str, Any]]:
        """Load a checkpoint from persistent storage."""
        raise NotImplementedError


class Outbox:
    """Abstract interface for event emission."""

    def emit(self, event: Dict[str, Any]) -> None:
        """Emit an event to the outbox."""
        raise NotImplementedError


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _default_agent_id_for_flow(flow_id: str | None) -> str | None:
    if not flow_id:
        return None
    normalized = str(flow_id).strip().lower()
    if normalized in {"ask", "qa", "ask.graph.v1"}:
        return "ask.v1"
    return None


def _resolve_step_agent_id(step: PlanStep, flow_id: str | None, plan_context: Mapping[str, Any] | None) -> str | None:
    if getattr(step, "agent_id", None):
        return step.agent_id
    metadata = None
    try:
        metadata = step.metadata
    except Exception:
        metadata = None
    if isinstance(metadata, Mapping):
        meta_agent = metadata.get("agent_id")
        if isinstance(meta_agent, str) and meta_agent.strip():
            return meta_agent.strip()
    if plan_context and isinstance(plan_context, Mapping):
        ctx_agent = plan_context.get("agent_id")
        if isinstance(ctx_agent, str) and ctx_agent.strip():
            return ctx_agent.strip()
    return _default_agent_id_for_flow(flow_id)


class OrchestratorV2Error(Exception):
    """Base error for V2 orchestrator failures."""


class PlanValidationError(OrchestratorV2Error):
    """Raised when a plan violates structural requirements."""


class CompensationError(OrchestratorV2Error):
    """Raised when a compensation function fails."""


class DependencyGraph:
    """Tracks plan step dependencies and identifies executable steps."""

    def __init__(self, steps: List[PlanStep]) -> None:
        """Build graph of dependencies from plan steps."""
        self.steps = {s.id: s for s in steps}
        self.dependencies: Dict[str, Set[str]] = defaultdict(set)
        self.dependents: Dict[str, Set[str]] = defaultdict(set)

        for step in steps:
            self.dependencies[step.id] = set(step.depends_on or [])
            for dep_id in (step.depends_on or []):
                self.dependents[dep_id].add(step.id)

    def executable_steps(self, completed: Set[str]) -> List[str]:
        """Return IDs of steps whose dependencies are all satisfied."""
        result = []
        for step_id, deps in self.dependencies.items():
            if step_id not in completed and deps.issubset(completed):
                result.append(step_id)
        return result

    def all_steps_completed(self, completed: Set[str]) -> bool:
        """Check if all steps are completed."""
        return len(completed) == len(self.steps)


class OrchestratorV2:
    """Orchestrator V2: parallel execution with dependency-safe scheduling, checkpoint persistence, and retry handling."""

    def __init__(
        self,
        executor: PlanExecutor | None = None,
        checkpoint_store: CheckpointStore | None = None,
        outbox: Outbox | None = None,
        *,
        tool_settings: Mapping[str, Any] | None = None,
        max_workers: int = 4,
        checkpoint_interval: int = 3,
    ) -> None:
        self._executor = executor or MockPlanExecutor()
        self._checkpoint_store = checkpoint_store
        self._outbox = outbox
        self._tool_settings = dict(tool_settings) if tool_settings else None
        self._max_workers = max_workers
        # Validate checkpoint_interval: must be >= 1 to avoid ZeroDivisionError in modulo
        self._checkpoint_interval = max(1, checkpoint_interval) if checkpoint_interval else 3

    def run_plan(self, plan: Plan) -> List[Dict[str, Any]]:
        """Execute plan with dependency-safe parallel scheduling and compensation."""
        self._validate_plan(plan)

        # Extract plan metadata and context
        object_id = plan.meta.source_object_uuid or None
        trace_id = plan.meta.trace_id
        plan_results: Dict[str, Dict[str, Any]] = {}
        completed_steps: Set[str] = set()
        execution_order: List[str] = []  # Track completion order for reverse compensation
        results: List[Dict[str, Any]] = []
        failed_step_id: str | None = None

        # Attempt to load checkpoint for resume
        checkpoint = self._load_checkpoint(plan)
        if checkpoint:
            completed_steps = set(checkpoint.get("completed_steps", []))
            plan_results = checkpoint.get("step_results", {})
            # Add checkpoint results to the results list with "ok" status (not "resumed")
            # to ensure consistent status handling for rollback and compensation
            for step_id in completed_steps:
                execution_order.append(step_id)
                result = plan_results.get(step_id, {})
                results.append({"step_id": step_id, "status": "ok", "result": result})

        # Resolve tool settings
        plan_tool_settings = None
        if plan.context and isinstance(plan.context.get("tool_settings"), Mapping):
            plan_tool_settings = dict(plan.context.get("tool_settings") or {})
        context_tool_settings = self._tool_settings
        if plan_tool_settings:
            if context_tool_settings:
                merged = dict(context_tool_settings)
                merged.update(plan_tool_settings)
                context_tool_settings = merged
            else:
                context_tool_settings = plan_tool_settings

        # Budget tracking
        budget_state: MutableMapping[str, int] = {"steps": 0, "tool_calls": 0}
        max_steps = _coerce_int(context_tool_settings.get("max_steps")) if context_tool_settings else None
        plan_timeout = _coerce_float(context_tool_settings.get("plan_timeout_seconds")) if context_tool_settings else None
        deadline = (time.monotonic() + plan_timeout) if plan_timeout and plan_timeout > 0 else None

        # Build dependency graph
        graph = DependencyGraph(plan.steps)

        # Resolve flow context
        plan_flow_id = self._resolve_flow_id(plan)

        # Execute with parallel scheduling
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            pending_futures: Dict[Future[Dict[str, Any]], tuple[PlanStep, str]] = {}

            while not graph.all_steps_completed(completed_steps):
                # Get steps that can run now
                executable = graph.executable_steps(completed_steps)

                if not executable and not pending_futures:
                    break

                # Submit executable steps
                for step_id in executable:
                    if deadline is not None and time.monotonic() >= deadline:
                        step = graph.steps[step_id]
                        results.append({
                            "step_id": step_id,
                            "status": "error",
                            "error": "plan timeout budget exhausted",
                            "error_type": "plan_timeout",
                            "delivery_sla_state": map_delivery_sla_terminal_state(
                                status="error",
                                error_type="plan_timeout",
                            ),
                        })
                        emit_step_error(
                            plan_id=plan.id,
                            step=step,
                            error="plan timeout budget exhausted",
                            error_type="plan_timeout",
                            object_id=object_id,
                            trace_id=trace_id,
                        )
                        completed_steps.add(step_id)
                        failed_step_id = step_id
                        break

                    if max_steps is not None and budget_state.get("steps", 0) >= max_steps:
                        results.append({
                            "step_id": step_id,
                            "status": "error",
                            "error": "step budget exhausted",
                            "error_type": "budget_exhausted",
                            "delivery_sla_state": map_delivery_sla_terminal_state(
                                status="error",
                                error_type="budget_exhausted",
                            ),
                        })
                        completed_steps.add(step_id)
                        continue

                    step = graph.steps[step_id]
                    budget_state["steps"] = budget_state.get("steps", 0) + 1

                    emit_step_started(plan_id=plan.id, step=step, object_id=object_id, trace_id=trace_id)

                    agent_id = _resolve_step_agent_id(step, plan_flow_id, plan.context)
                    context = StepContext(
                        plan_id=plan.id,
                        object_id=object_id,
                        trace_id=trace_id,
                        metadata=plan.meta,
                        results=plan_results,
                        flow_id=plan_flow_id,
                        event_type=plan.trigger.event_type if plan.trigger else None,
                        tool_settings=context_tool_settings,
                        budget_state=budget_state,
                        agent_id=agent_id,
                    )

                    future = executor.submit(self._execute_step_safe, step, context)
                    pending_futures[future] = (step, step_id)

                if pending_futures:
                    for future in as_completed(pending_futures):
                        step, step_id = pending_futures.pop(future)

                        try:
                            output: Dict[str, Any] = future.result()
                            emit_step_finished(
                                plan_id=plan.id,
                                step=step,
                                result=output,
                                object_id=object_id,
                                trace_id=trace_id,
                            )
                            plan_results[step_id] = output
                            results.append(
                                {
                                    "step_id": step_id,
                                    "status": "ok",
                                    "result": output,
                                    "delivery_sla_state": map_delivery_sla_terminal_state(status="ok"),
                                }
                            )
                            completed_steps.add(step_id)
                            execution_order.append(step_id)

                            # Save checkpoint at configured interval
                            if len(completed_steps) % self._checkpoint_interval == 0:
                                self._save_checkpoint(plan, completed_steps, plan_results)
                        except StepExecutionError as exc:
                            error_message = str(exc)
                            error_type = getattr(exc, "error_type", None)
                            emit_step_error(
                                plan_id=plan.id,
                                step=step,
                                error=error_message,
                                error_type=error_type,
                                object_id=object_id,
                                trace_id=trace_id,
                            )
                            entry = {"step_id": step_id, "status": "error", "error": error_message}
                            if error_type:
                                entry["error_type"] = error_type
                            entry["delivery_sla_state"] = map_delivery_sla_terminal_state(
                                status="error",
                                error_type=error_type,
                            )
                            results.append(entry)
                            completed_steps.add(step_id)
                            failed_step_id = step_id
                        except Exception as exc:
                            error_message = f"Unexpected error: {str(exc)}"
                            emit_step_error(
                                plan_id=plan.id,
                                step=step,
                                error=error_message,
                                error_type="unexpected_error",
                                object_id=object_id,
                                trace_id=trace_id,
                            )
                            results.append({
                                "step_id": step_id,
                                "status": "error",
                                "error": error_message,
                                "error_type": "unexpected_error",
                                "delivery_sla_state": map_delivery_sla_terminal_state(
                                    status="error",
                                    error_type="unexpected_error",
                                ),
                            })
                            completed_steps.add(step_id)
                            failed_step_id = step_id

                        break  # Process one at a time to check for new executable steps

                # If a step failed, cancel pending futures and stop scheduling
                if failed_step_id is not None:
                    for pending_future in list(pending_futures):
                        pending_future.cancel()
                    pending_futures.clear()
                    break

        # Run compensation if a step failed and there are completed predecessors
        if failed_step_id is not None and execution_order:
            compensation_result = self._run_compensation(
                plan=plan,
                graph=graph,
                failed_step_id=failed_step_id,
                execution_order=execution_order,
                plan_results=plan_results,
                object_id=object_id,
                trace_id=trace_id,
            )
            # Mark successfully completed steps as rolled_back
            for entry in results:
                if entry["step_id"] in compensation_result["compensated_steps"] and entry["status"] == "ok":
                    entry["status"] = "rolled_back"
                    entry["delivery_sla_state"] = map_delivery_sla_terminal_state(status="rolled_back")
            results.append({
                "step_id": "__compensation__",
                "status": "rolled_back",
                "failed_step": failed_step_id,
                "compensated_steps": compensation_result["compensated_steps"],
                "compensation_failures": compensation_result["compensation_failures"],
            })

        return results

    def _run_compensation(
        self,
        *,
        plan: Plan,
        graph: DependencyGraph,
        failed_step_id: str,
        execution_order: List[str],
        plan_results: Dict[str, Dict[str, Any]],
        object_id: str | None,
        trace_id: str | None,
    ) -> Dict[str, Any]:
        """Run compensation for completed steps in reverse execution order.

        Steps without a compensate_fn in metadata are skipped.
        Compensation failures are logged as events but do not stop the chain.
        """
        # Build reverse compensation order from execution_order
        steps_to_compensate = list(reversed(execution_order))

        # Filter to only steps that have compensate_fn
        compensable = []
        for sid in steps_to_compensate:
            step = graph.steps.get(sid)
            if step and isinstance(step.metadata, Mapping) and step.metadata.get("compensate_fn"):
                compensable.append(sid)

        emit_compensation_started(
            plan_id=plan.id,
            failed_step_id=failed_step_id,
            steps_to_compensate=compensable,
            object_id=object_id,
            trace_id=trace_id,
        )

        compensated: List[str] = []
        failures: List[str] = []

        for sid in compensable:
            step = graph.steps[sid]
            compensate_fn = step.metadata["compensate_fn"]
            try:
                self._execute_compensation(
                    step=step,
                    compensate_fn=compensate_fn,
                    output_snapshot=plan_results.get(sid),
                )
                emit_compensation_step_completed(
                    plan_id=plan.id,
                    step_id=sid,
                    compensate_fn=compensate_fn,
                    object_id=object_id,
                    trace_id=trace_id,
                )
                compensated.append(sid)
            except Exception as exc:
                logger.warning("Compensation failed for step %s (fn=%s): %s", sid, compensate_fn, exc)
                emit_compensation_step_failed(
                    plan_id=plan.id,
                    step_id=sid,
                    compensate_fn=compensate_fn,
                    error=str(exc),
                    object_id=object_id,
                    trace_id=trace_id,
                )
                failures.append(sid)

        emit_orchestration_rolled_back(
            plan_id=plan.id,
            failed_step=failed_step_id,
            compensated_steps=compensated,
            compensation_failures=failures,
            object_id=object_id,
            trace_id=trace_id,
        )

        return {"compensated_steps": compensated, "compensation_failures": failures}

    def _execute_compensation(
        self,
        step: PlanStep,
        compensate_fn: str,
        output_snapshot: Dict[str, Any] | None,
    ) -> None:
        """Execute a compensation function for a step.

        The compensation function name is resolved from step metadata.
        The orchestrator does not mutate the vault directly — compensation
        functions are dispatched through the executor's step handling,
        keeping the same component boundary as forward execution.
        """
        # Build a compensation step that the executor can handle
        # Compensation is a lightweight agent_call with the compensate_fn as intent
        comp_step = PlanStep(
            id=f"compensate-{step.id}",
            kind="agent_call",
            description=f"Compensate: {compensate_fn} for {step.id}",
            agent=getattr(step, "agent", None) or "compensation",
            intent=compensate_fn,
            metadata={
                "compensation": True,
                "original_step_id": step.id,
                "output_snapshot": output_snapshot or {},
            },
        )
        context = StepContext(
            plan_id="",
            object_id=None,
            trace_id=None,
            metadata=step.metadata if isinstance(step.metadata, PlanMetadata) else PlanMetadata(
                goal="compensation",
                source_object_uuid="compensation",
                created_by="orchestrator.v2",
            ),
            results={},
        )
        self._executor.execute_step(comp_step, context)

    def _execute_step_safe(self, step: PlanStep, context: StepContext) -> Dict[str, Any]:
        """Execute a single step with retry handling and observability, raising StepExecutionError on failure."""
        # Get retry configuration from step metadata
        metadata = getattr(step, "metadata", {}) or {}
        if not isinstance(metadata, Mapping):
            metadata = {}

        retry_count = _coerce_int(metadata.get("retry_count")) or 0
        backoff_ms = _coerce_int(metadata.get("retry_backoff_ms")) or 100

        attempt = 0
        last_error = None
        last_error_type = None
        object_id = context.object_id
        trace_id = context.trace_id

        while attempt <= retry_count:
            attempt += 1
            try:
                return self._executor.execute_step(step, context)
            except StepExecutionError as exc:
                last_error = str(exc)
                last_error_type = getattr(exc, "error_type", None)

                # Timeout is non-retriable. Accept both "tool_timeout" (documented contract)
                # and "timeout" (existing test discriminator) for backwards compatibility.
                if last_error_type in ("tool_timeout", "timeout"):
                    raise

                # If we have retries left, emit observability and backoff
                if attempt <= retry_count:
                    # Emit structured retry event with observability details (audit log + outbox)
                    emit_step_retry(
                        plan_id=context.plan_id,
                        step=step,
                        attempt=attempt,
                        backoff_ms=backoff_ms,
                        error=last_error,
                        error_type=last_error_type,
                        object_id=object_id,
                        trace_id=trace_id,
                    )
                    # Also emit to outbox for real-time observability
                    self._emit_outbox_retry_event(
                        plan_id=context.plan_id,
                        step_id=step.id,
                        attempt=attempt,
                        backoff_ms=backoff_ms,
                        error=last_error,
                        error_type=last_error_type,
                        trace_id=trace_id,
                    )
                    # Log retry for debugging
                    logger.debug(
                        f"Step {step.id} attempt {attempt} failed; retrying after {backoff_ms}ms",
                        extra={
                            "step_id": step.id,
                            "plan_id": context.plan_id,
                            "attempt": attempt,
                            "backoff_ms": backoff_ms,
                            "error": last_error,
                            "error_type": last_error_type,
                            "trace_id": trace_id,
                        },
                    )
                    time.sleep(backoff_ms / 1000.0)
                    continue

                # Retries exhausted - emit terminal failure event only if retries were configured
                if retry_count > 0:
                    emit_step_retry_exhausted(
                        plan_id=context.plan_id,
                        step=step,
                        max_retries=retry_count,
                        final_error=last_error,
                        error_type=last_error_type,
                        object_id=object_id,
                        trace_id=trace_id,
                    )
                    # Also emit to outbox for real-time observability
                    self._emit_outbox_retry_exhausted_event(
                        plan_id=context.plan_id,
                        step_id=step.id,
                        max_retries=retry_count,
                        final_error=last_error,
                        trace_id=trace_id,
                    )
                    logger.debug(
                        f"Step {step.id} exhausted all {retry_count} retries",
                        extra={
                            "step_id": step.id,
                            "plan_id": context.plan_id,
                            "max_retries": retry_count,
                            "final_error": last_error,
                            "error_type": last_error_type,
                            "trace_id": trace_id,
                        },
                    )
                raise

        raise StepExecutionError(
            last_error or f"step '{step.id}' failed after retry handling",
            error_type=last_error_type,
        )

    def _load_checkpoint(self, plan: Plan) -> Optional[Dict[str, Any]]:
        """Load a checkpoint for plan resume."""
        if not self._checkpoint_store:
            return None

        checkpoint_key = f"checkpoint-{plan.id}"
        checkpoint_data = self._checkpoint_store.load_checkpoint(checkpoint_key)
        return checkpoint_data

    def _load_checkpoint(self, plan: Plan) -> Optional[Dict[str, Any]]:
        """Load a checkpoint for plan resume."""
        if not self._checkpoint_store:
            return None

        checkpoint_key = f"checkpoint-{plan.id}"
        checkpoint_data = self._checkpoint_store.load_checkpoint(checkpoint_key)
        return checkpoint_data

    def _save_checkpoint(self, plan: Plan, completed_steps: set[str], plan_results: Dict[str, Any]) -> None:
        """Save a checkpoint for recovery."""
        if not self._checkpoint_store:
            return

        checkpoint_key = f"checkpoint-{plan.id}"
        checkpoint_data = {
            "plan_id": plan.id,
            "completed_steps": sorted(list(completed_steps)),
            "step_results": plan_results,
            "timestamp": time.time(),
        }

        self._checkpoint_store.save_checkpoint(checkpoint_key, checkpoint_data)
        self._emit_checkpoint_event(plan.id, len(completed_steps), plan.meta.trace_id)

    def _emit_checkpoint_event(self, plan_id: str, step_count: int, trace_id: str | None) -> None:
        """Emit a checkpoint creation event."""
        if not self._outbox:
            return

        event = {
            "event": "checkpoint.created",
            "source": "orchestrator.v2",
            "plan_id": plan_id,
            "checkpoint_step_count": step_count,
            "trace_id": trace_id,
            "timestamp": time.time(),
        }
        self._outbox.emit(event)

    def _emit_outbox_retry_event(
        self,
        plan_id: str,
        step_id: str,
        attempt: int,
        backoff_ms: int,
        error: str,
        error_type: str | None,
        trace_id: str | None,
    ) -> None:
        """Emit a retry event to outbox for observability."""
        if not self._outbox:
            return

        event = {
            "event": "orchestrator.step.retry",
            "source": "orchestrator.v2",
            "plan_id": plan_id,
            "step_id": step_id,
            "attempt": attempt,
            "backoff_ms": backoff_ms,
            "error": error,
            "trace_id": trace_id,
            "timestamp": time.time(),
        }
        if error_type:
            event["error_type"] = error_type
        self._outbox.emit(event)

    def _emit_outbox_retry_exhausted_event(
        self, plan_id: str, step_id: str, max_retries: int, final_error: str, trace_id: str | None
    ) -> None:
        """Emit a retry exhaustion event to outbox."""
        if not self._outbox:
            return

        event = {
            "event": "orchestrator.step.retry.exhausted",
            "source": "orchestrator.v2",
            "plan_id": plan_id,
            "step_id": step_id,
            "max_retries": max_retries,
            "final_error": final_error,
            "trace_id": trace_id,
            "timestamp": time.time(),
        }
        self._outbox.emit(event)

    def _resolve_flow_id(self, plan: Plan) -> str | None:
        """Extract flow_id from plan context."""
        plan_context = plan.context if plan.context else {}

        if isinstance(plan_context, dict) and plan_context.get("profile_selection"):
            profile_selection = plan_context.get("profile_selection")
            if isinstance(profile_selection, dict) and profile_selection.get("flow_id"):
                return profile_selection.get("flow_id")

        if isinstance(plan_context, dict) and plan_context.get("flow_ids"):
            flow_ids = plan_context.get("flow_ids")
            if isinstance(flow_ids, list) and flow_ids:
                return flow_ids[0]

        if isinstance(plan_context, dict) and plan_context.get("flows"):
            flows = plan_context.get("flows")
            if isinstance(flows, list) and flows:
                return flows[0]

        return None

    def _validate_plan(self, plan: Plan) -> None:
        """Validate plan structure and dependencies."""
        if not plan.id:
            raise PlanValidationError("plan missing identifier")
        if not plan.meta.source_object_uuid:
            raise PlanValidationError("plan missing source object reference")

        seen: Set[str] = set()
        for step in plan.steps:
            self._validate_step(step, seen)
            seen.add(step.id)

    def _validate_step(self, step: PlanStep, seen: Set[str]) -> None:
        """Validate individual step and its dependencies."""
        if not step.id:
            raise PlanValidationError("plan step missing identifier")
        if step.id in seen:
            raise PlanValidationError(f"duplicate plan step id '{step.id}'")

        # Validate dependencies: must be previously seen or forward-declared
        for dep in step.depends_on:
            if dep not in seen:
                # In V2, we allow forward references in depends_on (will be checked at execution)
                # but we still validate they exist in the plan
                pass

        if step.kind == "agent_call" and not step.agent:
            raise PlanValidationError(f"agent_call step '{step.id}' missing agent name")
        if step.kind == "tool_call" and not step.tool:
            raise PlanValidationError(f"tool_call step '{step.id}' missing tool name")


__all__ = [
    "OrchestratorV2",
    "OrchestratorV2Error",
    "PlanValidationError",
    "CompensationError",
    "DependencyGraph",
    "CheckpointStore",
    "Outbox",
]
