"""Runtime-neutral dispatch planning for deliver-issue-set epic runs."""

from __future__ import annotations

import json
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping, Protocol, cast

from app.builderops.delivery_orchestration_contracts import canonical_hash
from app.builderops.epic_run_state import validate_run_id
from app.builderops.execution_routing import (
    AllocationObservation,
    CapabilityTier,
    ExecutionAttemptObservation,
    ExecutionRouteDecision,
    ExecutionRouteRequest,
    ResolvedExecutionTarget,
    WorkClass,
    admit_phase2_canary,
    build_execution_routing_canary_receipt,
    create_execution_attempt,
    resolve_bounded_fast_route,
    resolve_execution_target,
    validate_route_decision,
)
from app.builderops.execution_routing_receipts import (
    ReceiptStore,
    append_attempt_intent,
    append_attempt_outcome,
    attempt_intent_exists,
)
from app.components.settings.providers_loader import load_provider_census
from app.dispatcher.verification_consumer import _is_codex_usage_limit_event

SCHEMA_VERSION = 2
DEFAULT_MAX_PARALLEL = 2
FAST_LANE_MAX_PARALLEL = 2
MAX_NON_ROOT_AGENT_SLOTS = 2
VALID_PATHS = {"inline", "script", "subagent", "skip"}
_DECLARED_PROVIDER_CENSUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "settings"
    / "models"
    / "providers.yaml"
)

HANDOFF_RECEIPT_SCHEMA: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "schema_name": "subagent_handoff_receipt",
    "required_fields": [
        "role",
        "task",
        "skill_loaded",
        "branch",
        "worktree",
        "actions",
        "ac_verdicts",
        "lifecycle_mutations",
        "validation",
        "owner_doc_result",
        "residual_risk",
        "final_state",
        "next_step",
        "context_cost",
    ],
}


class EpicDispatchError(ValueError):
    """Raised when dispatch planning input is invalid or unsafe."""


class IssueSessionLaunchError(RuntimeError):
    """Raised when one fresh worker session cannot finish truthfully."""

    def __init__(
        self,
        message: str,
        *,
        session_id: str | None = None,
        canary_receipt: Mapping[str, object] | None = None,
    ) -> None:
        self.session_id = session_id
        self.canary_receipt = (
            dict(canary_receipt) if canary_receipt is not None else None
        )
        super().__init__(message)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class IssueSessionLauncher(Protocol):
    """Minimal transitional seam for one fresh issue-worker session."""

    def launch(
        self,
        context_pack: Mapping[str, Any],
        *,
        execution_routing: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


_CAPABILITY_FOR_MODEL_CLASS = {
    "low-cost": "luna",
    "standard": "terra",
    "high-reasoning": "sol",
}
ACTIVE_WORKER_RUNTIME = "codex"


class CodexIssueSessionLauncher:
    """Run one issue context pack to terminal in a fresh local Codex session."""

    def __init__(
        self,
        *,
        repo_root: Path,
        adapter_path: Path | None = None,
        provider_census_path: Path | None = None,
        builder_channel: str = "dev",
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.adapter_path = adapter_path or (
            Path(__file__).resolve().parents[2]
            / ".codex"
            / "agents"
            / "slice-implementer.toml"
        )
        self.runner = runner or subprocess.run
        self.provider_census = load_provider_census(
            provider_census_path or _DECLARED_PROVIDER_CENSUS_PATH
        )
        self.builder_channel = builder_channel
        try:
            adapter = tomllib.loads(self.adapter_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise EpicDispatchError("slice_implementer adapter is unavailable") from exc
        if adapter.get("name") != "slice_implementer":
            raise EpicDispatchError("slice_implementer adapter contract mismatch")
        instructions = adapter.get("developer_instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise EpicDispatchError("slice_implementer instructions are missing")
        sandbox = adapter.get("sandbox_mode")
        if sandbox != "workspace-write":
            raise EpicDispatchError("slice_implementer sandbox contract mismatch")
        self.developer_instructions = instructions.strip()
        self.sandbox = sandbox

    def command(
        self,
        context_pack: Mapping[str, Any],
        *,
        execution_routing: Mapping[str, Any] | None = None,
    ) -> list[str]:
        model, reasoning_effort = self._tcd_route(context_pack)
        if execution_routing is not None:
            if execution_routing.get("mode") != "canary":
                raise EpicDispatchError("only a validated canary may override the launch target")
            target = ResolvedExecutionTarget.model_validate(
                execution_routing.get("proposed_target")
            )
            model = target.model
            reasoning_effort = target.reasoning_effort
        worktree = self._planned_worktree(context_pack)
        return [
            "codex",
            "exec",
            "--json",
            "--sandbox",
            self.sandbox,
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
            "-C",
            str(self.repo_root),
            "--add-dir",
            str(worktree.parent),
            "-",
        ]

    def prompt(self, context_pack: Mapping[str, Any]) -> str:
        try:
            serialized = json.dumps(
                context_pack,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            raise EpicDispatchError("context pack must be JSON serializable") from exc
        return (
            "Use the registered slice_implementer execution role.\n"
            f"{self.developer_instructions}\n"
            "Load and obey .codex/skills/issue-to-code/SKILL.md. "
            "Perform exactly the one Issue in this immutable context pack through publication, "
            "governed verification, merge, and truthful closure. Load publish-pr and "
            "verification-and-closure at their boundaries. "
            "Self-claim through issue-to-code before editing, work in the named dedicated "
            "worktree, and return only one JSON object matching the requested "
            "subagent_handoff_receipt; final_state=done is valid only after terminal delivery. "
            "This invocation is a fresh session; do not resume or reuse another Issue's session.\n"
            f"{serialized}\n"
        )

    def launch(
        self,
        context_pack: Mapping[str, Any],
        *,
        execution_routing: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        prompt = self.prompt(context_pack)
        canary_target = None
        if execution_routing is not None:
            canary_target = ResolvedExecutionTarget.model_validate(
                execution_routing.get("proposed_target")
            )
        result = self.runner(
            self.command(context_pack, execution_routing=execution_routing),
            cwd=self.repo_root,
            input=prompt,
            capture_output=True,
            text=True,
            check=False,
        )
        session_id: str | None = None
        worker_receipt: object | None = None
        terminal_error: str | None = None
        allocation_unavailable = False
        observed_input_tokens: int | None = None
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, Mapping):
                continue
            if event.get("type") == "thread.started":
                candidate = event.get("thread_id")
                if isinstance(candidate, str) and candidate.strip():
                    session_id = candidate.strip()
            if event.get("type") in {"turn.failed", "error"}:
                terminal_error = json.dumps(event, sort_keys=True)
            if event.get("allocation_state") == "allocation_unavailable":
                allocation_unavailable = canary_target is not None and canary_target.capability == "spark"
            if (
                canary_target is not None
                and canary_target.capability == "spark"
                and _is_codex_usage_limit_event(event)
            ):
                allocation_unavailable = True
            usage = event.get("usage")
            if isinstance(usage, Mapping):
                candidate_tokens = usage.get("input_tokens")
                if (
                    isinstance(candidate_tokens, int)
                    and not isinstance(candidate_tokens, bool)
                    and candidate_tokens >= 0
                ):
                    observed_input_tokens = candidate_tokens
            if event.get("type") == "item.completed":
                item = event.get("item")
                if isinstance(item, Mapping) and item.get("type") == "agent_message":
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        worker_receipt = _parse_worker_receipt(text)
        if allocation_unavailable:
            return {"allocation_state": "allocation_unavailable"}
        if result.returncode != 0 or terminal_error is not None:
            detail = result.stderr.strip() or terminal_error or "codex exec failed"
            raise IssueSessionLaunchError(
                detail[-2_000:],
                session_id=session_id,
            )
        if session_id is None:
            raise IssueSessionLaunchError("codex exec produced no session id")
        if worker_receipt is None:
            raise IssueSessionLaunchError(
                "codex exec produced no terminal worker receipt",
                session_id=session_id,
            )
        if isinstance(worker_receipt, Mapping):
            worker_receipt = dict(worker_receipt)
            raw_cost = worker_receipt.get("context_cost")
            if isinstance(raw_cost, Mapping):
                context_cost = dict(raw_cost)
                if observed_input_tokens is not None:
                    context_cost["input_tokens"] = observed_input_tokens
                    context_cost["measurement"] = "actual"
                baseline = context_pack.get("context_cost_baseline")
                if isinstance(baseline, Mapping):
                    pack_bytes = baseline.get("context_pack_bytes_excluding_baseline")
                    if isinstance(pack_bytes, int) and pack_bytes >= 0:
                        context_cost["context_pack_bytes"] = pack_bytes
                worker_receipt["context_cost"] = context_cost
        return {
            "session_id": session_id,
            "worker_receipt": worker_receipt,
        }

    def _tcd_route(self, context_pack: Mapping[str, Any]) -> tuple[str, str]:
        runtime = context_pack.get("runtime")
        if not isinstance(runtime, Mapping) or runtime.get("runtime") != "codex":
            raise EpicDispatchError("serial session launcher supports codex runtime only")
        model_class = runtime.get("model_class")
        if (
            not isinstance(model_class, str)
            or model_class not in _CAPABILITY_FOR_MODEL_CLASS
        ):
            raise EpicDispatchError("context pack has no supported TCD model class")
        capability = runtime.get("capability")
        if capability is None:
            capability = _CAPABILITY_FOR_MODEL_CLASS[model_class]
        if capability != _CAPABILITY_FOR_MODEL_CLASS[model_class]:
            raise EpicDispatchError("context pack capability conflicts with TCD model class")
        model_id = runtime.get("model")
        if model_id is not None and (
            not isinstance(model_id, str) or not model_id.strip()
        ):
            raise EpicDispatchError("context pack model must be a non-empty string")
        capability_tier = cast(CapabilityTier, capability)
        try:
            target = resolve_execution_target(
                self.provider_census,
                channel=self.builder_channel,
                capability=capability_tier,
                model_id=model_id,
            )
        except ValueError as exc:
            raise EpicDispatchError(str(exc)) from exc
        return target.model, target.reasoning_effort

    @staticmethod
    def _planned_worktree(context_pack: Mapping[str, Any]) -> Path:
        plan = context_pack.get("branch_worktree_plan")
        if not isinstance(plan, Mapping):
            raise EpicDispatchError("context pack has no branch/worktree plan")
        value = plan.get("worktree")
        if not isinstance(value, str) or not value.strip():
            raise EpicDispatchError("context pack has no planned worktree")
        worktree = Path(value)
        if not worktree.is_absolute() or "<" in value or ">" in value:
            raise EpicDispatchError("planned worktree must be an explicit absolute path")
        if not worktree.parent.is_dir():
            raise EpicDispatchError("planned worktree parent does not exist")
        return worktree


def build_dispatch_plan(
    *,
    epic_issue_number: int | None = None,
    independent_issue_numbers: Iterable[int] = (),
    run_id: str,
    candidates: Iterable[Mapping[str, Any]],
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    runtime_targets: Iterable[str] = (ACTIVE_WORKER_RUNTIME,),
    active_leases: Iterable[int | str | Mapping[str, Any]] = (),
    run_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a dry-run worker dispatch plan without external mutations.

    The returned plan is deterministic JSON data. It never claims issues, writes
    GitHub state, starts sub-agents, or creates worktrees. If the caller wants to
    persist the launch decisions, feed ``epic_run_state_update`` to the existing
    ``epic-run-state record`` command.
    """

    normalized_run_id = validate_run_id(run_id)
    independent_scope = _normalize_independent_issue_numbers(independent_issue_numbers)
    if epic_issue_number is None:
        if not independent_scope:
            raise EpicDispatchError(
                "dispatch scope requires epic_issue_number or independent_issue_numbers"
            )
        normalized_epic = None
    else:
        normalized_epic = _normalize_positive_int(epic_issue_number, "epic_issue_number")
        if independent_scope:
            raise EpicDispatchError(
                "independent_issue_numbers cannot be combined with epic_issue_number"
            )
    requested_max = _normalize_positive_int(max_parallel, "max_parallel")
    if independent_scope and requested_max > FAST_LANE_MAX_PARALLEL:
        raise EpicDispatchError(
            f"independent fast lane max_parallel must not exceed {FAST_LANE_MAX_PARALLEL}"
        )
    normalized_max = min(requested_max, MAX_NON_ROOT_AGENT_SLOTS)
    runtimes = _normalize_runtime_targets(runtime_targets)
    lease_issues = _normalize_active_leases(active_leases)
    normalized_candidates = [_normalize_candidate(item) for item in candidates]
    _validate_phase2_canary_plan_bound(
        normalized_candidates,
        source="dispatch candidates",
    )
    run_state_seen = run_state is not None
    if run_state is not None:
        _validate_run_state_owner(
            run_state,
            epic_issue_number=normalized_epic,
            independent_issue_numbers=independent_scope,
            run_id=normalized_run_id,
        )
    if independent_scope:
        _validate_independent_fast_lane_admission(
            normalized_candidates,
            independent_issue_numbers=independent_scope,
        )

    decisions: list[dict[str, Any]] = []
    context_packs: list[dict[str, Any]] = []
    selected_files: set[str] = set()
    selected_owner_docs: set[str] = set()
    selected_validation_resources: set[str] = set()
    selected_count = 0
    selected_helper_slots = 0
    discovered_overlap_policy = (
        "reject-whole-explicit-set-before-dispatch"
        if independent_scope
        else "typed-coordinator-exception"
    )

    for index, candidate in enumerate(normalized_candidates):
        decision = _build_tcd_decision(candidate, runtimes, lease_issues)
        selected_for_dispatch = False
        context_pack_id = None

        if decision["selected_path"] == "subagent" and decision["skip_reason"] is None:
            skip_reason = _parallel_skip_reason(
                candidate,
                selected_count=selected_count,
                max_parallel=normalized_max,
                selected_files=selected_files,
                selected_owner_docs=selected_owner_docs,
                selected_validation_resources=selected_validation_resources,
                selected_helper_slots=selected_helper_slots,
            )
            if skip_reason is not None:
                decision["selected_path"] = "skip"
                decision["skip_reason"] = skip_reason
            else:
                selected_count += 1
                selected_helper_slots += candidate["issue_local_helper_budget"]
                selected_for_dispatch = True
                context_pack_id = f"ctx-{candidate['issue_number']}"
                context_pack = _build_context_pack(
                    candidate,
                    decision=decision,
                    context_pack_id=context_pack_id,
                    dispatch_slot=selected_count,
                    discovered_overlap_policy=discovered_overlap_policy,
                )
                routing_input = candidate.get("execution_routing")
                if routing_input is not None:
                    decision["execution_routing"] = _build_execution_routing(
                        candidate,
                        routing_input=routing_input,
                        context_pack=context_pack,
                        incumbent_capability=decision["runtime_model_hint"][
                            "capability"
                        ],
                    )
                context_packs.append(context_pack)
                decision["context_cost_estimate"] = {
                    "measurement": "proxy",
                    "input_tokens": "unknown(pre-dispatch-runtime-dependent)",
                    "agent_starts": 1 + candidate["issue_local_helper_budget"],
                    "context_pack_bytes": context_pack["context_cost_baseline"][
                        "context_pack_bytes_excluding_baseline"
                    ],
                    "compactions": "unknown(pre-dispatch-runtime-dependent)",
                }
                selected_files.update(candidate["likely_touched_files"])
                if candidate["owner_doc_writeback_required"]:
                    selected_owner_docs.update(candidate["owner_docs"])
                selected_validation_resources.update(candidate["validation_resources"])

        decision.update(
            {
                "id": f"dispatch-{candidate['issue_number']}",
                "candidate_index": index,
                "issue_number": candidate["issue_number"],
                "title": candidate["title"],
                "selected_for_dispatch": selected_for_dispatch,
                "dispatch_slot": selected_count if selected_for_dispatch else None,
                "context_pack_id": context_pack_id,
            }
        )
        decisions.append(decision)

    result = {
        "schema_version": SCHEMA_VERSION,
        "run_id": normalized_run_id,
        "requested_max_parallel": requested_max,
        "max_parallel": normalized_max,
        "parallel_cap_reason": (
            "configured-non-root-agent-slot-cap"
            if requested_max > normalized_max
            else None
        ),
        "runtime_targets": runtimes,
        "selected_count": selected_count,
        "selected_helper_slots": selected_helper_slots,
        "decisions": decisions,
        "context_packs": context_packs,
        "epic_run_state_update": {
            "dispatch_decisions": [
                _dispatch_state_summary(decision) for decision in decisions
            ]
        },
        "github_mutations": [],
        "agent_spawns": [],
        "source": "builderops.epic_dispatch.dry_run",
        "run_state_seen": run_state_seen,
    }
    if independent_scope:
        result["scope"] = {
            "kind": "independent_issue_set",
            "issue_numbers": independent_scope,
            "parent_closure": "prohibited-without-real-governed-parent",
        }
    else:
        result["epic_issue_number"] = normalized_epic
    return result


def frozen_dispatch_plan_hash(plan: Mapping[str, Any]) -> str:
    """Hash the exact frozen plan bytes independently supplied at dispatch."""

    return canonical_hash(plan)


def _contains_execution_routing(value: object) -> bool:
    if isinstance(value, Mapping):
        return "execution_routing" in value or any(
            _contains_execution_routing(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_execution_routing(item) for item in value)
    return False


def _contains_canary_execution_routing(value: object) -> bool:
    """Return whether a selected dispatch decision needs the canary store."""

    if isinstance(value, Mapping):
        decisions = value.get("decisions")
        if isinstance(decisions, list):
            return any(
                isinstance(decision, Mapping)
                and decision.get("selected_for_dispatch") is True
                and isinstance(decision.get("execution_routing"), Mapping)
                and decision["execution_routing"].get("mode") == "canary"
                for decision in decisions
            )
    return False


def dispatch_issue_sessions(
    plan: Mapping[str, Any],
    launcher: IssueSessionLauncher,
    *,
    expected_plan_hash: str | None = None,
    canary_observed_at: str | None = None,
    receipt_store: ReceiptStore | None = None,
) -> dict[str, Any]:
    """Execute a frozen dispatch plan serially, with one fresh session per Issue."""

    routing_present = _contains_execution_routing(plan)
    if routing_present and expected_plan_hash is None:
        raise EpicDispatchError(
            "routed dispatch requires an independently preserved plan hash"
        )
    if expected_plan_hash is not None:
        if (
            len(expected_plan_hash) != 64
            or any(character not in "0123456789abcdef" for character in expected_plan_hash)
        ):
            raise EpicDispatchError("expected plan hash must be a lowercase SHA-256")
        if frozen_dispatch_plan_hash(plan) != expected_plan_hash:
            raise EpicDispatchError(
                "frozen dispatch plan does not match the independently preserved hash"
            )

    run_id, ordered = _validated_session_contexts(plan)
    sessions: list[dict[str, Any]] = []
    seen_session_ids: set[str] = set()

    for decision, context_pack in ordered:
        issue_number = decision["issue_number"]
        context_pack_id = decision["context_pack_id"]
        canary_receipt: dict[str, object] | None = None
        try:
            routing_payload = decision.get("execution_routing")
            if (
                isinstance(routing_payload, Mapping)
                and routing_payload.get("mode") == "canary"
            ):
                launch_result, canary_receipt = _launch_canary(
                    context_pack,
                    routing_payload=routing_payload,
                    launcher=launcher,
                    observed_at=canary_observed_at or _utc_now(),
                    receipt_store=receipt_store,
                )
            else:
                launch_result = launcher.launch(context_pack)
                canary_receipt = None
            if not isinstance(launch_result, Mapping):
                raise IssueSessionLaunchError(
                    "session launcher returned a non-object result"
                )
            session_id = _normalize_string(
                launch_result.get("session_id"),
                "launch_result.session_id",
            )
            if session_id in seen_session_ids:
                sessions.append(
                    {
                        "issue_number": issue_number,
                        "context_pack_id": context_pack_id,
                        "session_id": session_id,
                        "fresh_session": False,
                        "status": "rejected",
                        "error_type": "EpicDispatchError",
                        "error": "session id was already used by another Issue",
                    }
                )
                return _session_dispatch_receipt(
                    run_id,
                    sessions,
                    status="stopped",
                    stopped_reason="cross-issue-session-reuse",
                )
            seen_session_ids.add(session_id)
            worker_receipt = _validated_worker_receipt(
                launch_result.get("worker_receipt"),
                session_id=session_id,
            )
            final_state = worker_receipt["final_state"]
            session_record: dict[str, Any] = {
                "issue_number": issue_number,
                "context_pack_id": context_pack_id,
                "session_id": session_id,
                "fresh_session": True,
                "status": final_state,
                "worker_receipt": worker_receipt,
            }
            if canary_receipt is not None:
                session_record["execution_routing_canary_receipt"] = canary_receipt
            sessions.append(session_record)
            return _session_dispatch_receipt(
                run_id,
                sessions,
                status="stopped",
                stopped_reason=f"worker-{final_state}",
            )
        except Exception as exc:
            failed_session_id = getattr(exc, "session_id", None)
            if (
                not isinstance(failed_session_id, str)
                or not failed_session_id.strip()
            ):
                failed_session_id = None
            failed_session = {
                "issue_number": issue_number,
                "context_pack_id": context_pack_id,
                "session_id": failed_session_id,
                "fresh_session": True,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": (str(exc).strip() or type(exc).__name__)[-2_000:],
            }
            exception_receipt = getattr(exc, "canary_receipt", None)
            if isinstance(exception_receipt, Mapping):
                canary_receipt = dict(exception_receipt)
            if canary_receipt is not None:
                failed_session["execution_routing_canary_receipt"] = canary_receipt
            sessions.append(failed_session)
            return _session_dispatch_receipt(
                run_id,
                sessions,
                status="stopped",
                stopped_reason="session-launch-failed",
            )

    return _session_dispatch_receipt(
        run_id,
        sessions,
        status="completed",
        stopped_reason=None,
    )


def _launch_canary(
    context_pack: Mapping[str, Any],
    *,
    routing_payload: Mapping[str, Any],
    launcher: IssueSessionLauncher,
    observed_at: str,
    receipt_store: ReceiptStore | None,
) -> tuple[Mapping[str, Any], dict[str, object]]:
    """Execute one canary attempt and, only on typed capacity failure, one Luna fallback."""

    try:
        request = ExecutionRouteRequest.model_validate(routing_payload["route_request"])
        decision = ExecutionRouteDecision.model_validate(routing_payload["route_decision"])
        target = ResolvedExecutionTarget.model_validate(routing_payload["proposed_target"])
        launch_at = _normalize_string(observed_at, "canary_observed_at")
        if decision.selected_capability == "spark":
            observation = request.allocation_observation
            allocation_unavailable = observation is None or not observation.is_fresh_at(launch_at)
        else:
            allocation_unavailable = False
    except (KeyError, TypeError, ValueError) as exc:
        raise EpicDispatchError(f"invalid canary launch input: {exc}") from exc

    attempts: list[ExecutionAttemptObservation] = []
    first_result: Mapping[str, Any] | None = None
    first_error: Exception | None = None

    # The intent has a stable attempt identity (outcome is deliberately not
    # part of that identity) and must be durable before the launcher is called.
    intent_attempt = create_execution_attempt(
        request=request,
        decision=decision,
        target=target,
        attempt_number=1,
        mode="canary",
        outcome="started",
        observed_at=launch_at,
    )
    first_chain = None
    if receipt_store is not None:
        if attempt_intent_exists(receipt_store, request, decision, intent_attempt):
            raise IssueSessionLaunchError(
                "canary receipt recovery is indeterminate; relaunch refused"
            )
        first_chain = append_attempt_intent(
            receipt_store, request, decision, intent_attempt
        )

    if not allocation_unavailable:
        try:
            candidate_result = launcher.launch(
                context_pack,
                execution_routing=routing_payload,
            )
            if not isinstance(candidate_result, Mapping):
                raise IssueSessionLaunchError("canary launcher returned a non-object result")
            allocation_state = candidate_result.get("allocation_state")
            if allocation_state not in {None, "available", "allocation_unavailable"}:
                raise IssueSessionLaunchError(
                    "canary launcher returned an invalid allocation state"
                )
            first_result = candidate_result
            allocation_unavailable = allocation_state == "allocation_unavailable"
        except Exception as exc:
            first_error = exc

    first_outcome: Literal["started", "failed", "allocation_unavailable"] = (
        "failed"
        if first_error is not None
        else "allocation_unavailable"
        if allocation_unavailable
        else "started"
    )
    first_attempt = create_execution_attempt(
        request=request,
        decision=decision,
        target=target,
        attempt_number=1,
        mode="canary",
        outcome=first_outcome,
        observed_at=launch_at,
    )
    attempts.append(first_attempt)
    if first_chain is not None:
        assert receipt_store is not None
        append_attempt_outcome(
            receipt_store, first_chain, request, decision, first_attempt
        )
    if first_error is not None:
        receipt = build_execution_routing_canary_receipt(
            request=request,
            decision=decision,
            attempts=attempts,
            accepted_delivery_verification="not_run",
        )
        first_session_id = getattr(first_error, "session_id", None)
        raise IssueSessionLaunchError(
            "canary primary launcher failed",
            session_id=(
                first_session_id if isinstance(first_session_id, str) else None
            ),
            canary_receipt=receipt,
        ) from first_error
    if not allocation_unavailable:
        assert first_result is not None  # narrowed by the branch above
        receipt = build_execution_routing_canary_receipt(
            request=request,
            decision=decision,
            attempts=attempts,
            accepted_delivery_verification="not_run",
        )
        return first_result, receipt

    if decision.selected_capability != "spark":
        raise IssueSessionLaunchError(
            "Luna canary reported allocation unavailable without an authorized fallback"
        )

    fallback_target = resolve_execution_target(
        load_provider_census(_DECLARED_PROVIDER_CENSUS_PATH),
        channel="dev",
        capability="luna",
    )
    fallback_intent_attempt = create_execution_attempt(
        request=request,
        decision=decision,
        target=fallback_target,
        attempt_number=2,
        mode="canary",
        outcome="started",
        observed_at=launch_at,
        transition_kind="capacity_fallback",
        transition_reason="spark_allocation_unavailable_at_launch",
        triggering_attempt=first_attempt,
    )
    fallback_routing = dict(routing_payload)
    fallback_routing["proposed_target"] = fallback_target.receipt_fields()
    fallback_routing["attempt_observation"] = fallback_intent_attempt.model_dump(mode="json")
    fallback_result: Mapping[str, Any] | None = None
    fallback_error: Exception | None = None
    fallback_allocation_state: object = None
    fallback_chain = None
    if receipt_store is not None:
        if attempt_intent_exists(
            receipt_store, request, decision, fallback_intent_attempt
        ):
            raise IssueSessionLaunchError(
                "canary receipt recovery is indeterminate; relaunch refused"
            )
        fallback_chain = append_attempt_intent(
            receipt_store, request, decision, fallback_intent_attempt
        )
    try:
        candidate_result = launcher.launch(
            context_pack,
            execution_routing=fallback_routing,
        )
    except Exception as exc:
        fallback_error = exc
    else:
        if isinstance(candidate_result, Mapping):
            fallback_result = candidate_result
            fallback_allocation_state = candidate_result.get("allocation_state")

    fallback_outcome: Literal["failed", "started", "allocation_unavailable"]
    if fallback_error is not None or fallback_result is None:
        fallback_outcome = "failed"
    elif fallback_allocation_state == "allocation_unavailable":
        fallback_outcome = "allocation_unavailable"
    elif fallback_allocation_state in {None, "available"}:
        fallback_outcome = "started"
    else:
        fallback_outcome = "failed"
    fallback_attempt = create_execution_attempt(
        request=request,
        decision=decision,
        target=fallback_target,
        attempt_number=2,
        mode="canary",
        outcome=fallback_outcome,
        observed_at=launch_at,
        transition_kind="capacity_fallback",
        transition_reason="spark_allocation_unavailable_at_launch",
        triggering_attempt=first_attempt,
    )
    receipt = build_execution_routing_canary_receipt(
        request=request,
        decision=decision,
        attempts=(*attempts, fallback_attempt),
        accepted_delivery_verification="not_run",
    )
    if fallback_chain is not None:
        assert receipt_store is not None
        append_attempt_outcome(
            receipt_store, fallback_chain, request, decision, fallback_attempt
        )
    if fallback_error is not None:
        fallback_session_id = getattr(fallback_error, "session_id", None)
        raise IssueSessionLaunchError(
            "canary Luna fallback launcher failed",
            session_id=(
                fallback_session_id
                if isinstance(fallback_session_id, str)
                else None
            ),
            canary_receipt=receipt,
        ) from fallback_error
    if fallback_result is None:
        raise IssueSessionLaunchError(
            "canary fallback launcher returned a non-object result",
            canary_receipt=receipt,
        )
    if fallback_allocation_state == "allocation_unavailable":
        raise IssueSessionLaunchError(
            "canary Luna fallback reported allocation unavailable",
            canary_receipt=receipt,
        )
    if fallback_outcome == "failed":
        raise IssueSessionLaunchError(
            "canary fallback launcher returned an invalid allocation state",
            canary_receipt=receipt,
        )
    return fallback_result, receipt


def _validated_session_contexts(
    plan: Mapping[str, Any],
) -> tuple[str, list[tuple[dict[str, Any], dict[str, Any]]]]:
    if not isinstance(plan, Mapping):
        raise EpicDispatchError("dispatch plan must be an object")
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise EpicDispatchError(
            f"dispatch plan schema_version must be {SCHEMA_VERSION}; rebuild the frozen plan"
        )
    if plan.get("source") != "builderops.epic_dispatch.dry_run":
        raise EpicDispatchError("dispatch sessions requires a frozen dry-run plan")
    run_id = validate_run_id(_normalize_string(plan.get("run_id"), "plan.run_id"))
    decisions_raw = plan.get("decisions")
    contexts_raw = plan.get("context_packs")
    if not isinstance(decisions_raw, list) or not isinstance(contexts_raw, list):
        raise EpicDispatchError("dispatch plan decisions and context_packs must be lists")
    _validate_phase2_canary_plan_bound(
        decisions_raw,
        source="frozen dispatch plan",
    )
    run_state_update = plan.get("epic_run_state_update")
    expected_state_decisions = [
        _dispatch_state_summary(decision)
        for decision in decisions_raw
        if isinstance(decision, Mapping)
    ]
    if (
        not isinstance(run_state_update, Mapping)
        or run_state_update.get("dispatch_decisions") != expected_state_decisions
    ):
        raise EpicDispatchError(
            "epic run-state dispatch summary must exactly mirror the frozen decisions"
        )

    selected: list[dict[str, Any]] = []
    for raw in decisions_raw:
        if not isinstance(raw, Mapping):
            raise EpicDispatchError("dispatch decision must be an object")
        if raw.get("selected_for_dispatch") is True:
            selected.append(dict(raw))
    selected.sort(key=lambda item: _dispatch_slot(item))
    if [_dispatch_slot(item) for item in selected] != list(
        range(1, len(selected) + 1)
    ):
        raise EpicDispatchError("selected dispatch slots must be unique and contiguous")
    selected_count = plan.get("selected_count")
    if (
        not isinstance(selected_count, int)
        or isinstance(selected_count, bool)
        or selected_count != len(selected)
    ):
        raise EpicDispatchError("selected_count does not match selected decisions")

    contexts_by_id: dict[str, dict[str, Any]] = {}
    for raw in contexts_raw:
        if not isinstance(raw, Mapping):
            raise EpicDispatchError("context pack must be an object")
        context_payload = dict(raw)
        context_id = _normalize_string(
            context_payload.get("context_pack_id"),
            "context_pack_id",
        )
        if context_id in contexts_by_id:
            raise EpicDispatchError("context_pack_id must be unique")
        contexts_by_id[context_id] = context_payload
    if len(contexts_by_id) != len(selected):
        raise EpicDispatchError(
            "selected decisions must have exactly one context pack each"
        )

    ordered: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for decision in selected:
        issue_number = _normalize_positive_int(
            decision.get("issue_number"),
            "decision.issue_number",
        )
        context_id = _normalize_string(
            decision.get("context_pack_id"),
            "decision.context_pack_id",
        )
        matching_context = contexts_by_id.get(context_id)
        if matching_context is None:
            raise EpicDispatchError("selected decision is missing its context pack")
        if "run_state" in matching_context:
            raise EpicDispatchError(
                "context pack must not carry persisted run-state or lifecycle authority"
            )
        issue_contract = matching_context.get("issue_contract")
        runtime = matching_context.get("runtime")
        if (
            not isinstance(issue_contract, Mapping)
            or issue_contract.get("number") != issue_number
            or matching_context.get("dispatch_slot") != decision.get("dispatch_slot")
            or not isinstance(runtime, Mapping)
            or runtime.get("runtime") != "codex"
        ):
            raise EpicDispatchError("context pack does not match its selected decision")
        _validate_execution_routing_context(decision, matching_context)
        ordered.append((decision, matching_context))
    return run_id, ordered


def _validate_execution_routing_context(
    decision: Mapping[str, Any],
    context_pack: Mapping[str, Any],
) -> None:
    routing_payload = decision.get("execution_routing")
    if routing_payload is None:
        return
    if not isinstance(routing_payload, Mapping):
        raise EpicDispatchError("execution routing evidence must be an object")
    expected_routing_fields = {
        "schema_version",
        "mode",
        "route_request",
        "route_decision",
        "proposed_target",
        "shadow_comparison",
        "canary_admission",
        "attempt_observation",
        "authority",
    }
    if set(routing_payload) != expected_routing_fields:
        raise EpicDispatchError("execution routing evidence has an invalid field set")
    try:
        request = ExecutionRouteRequest.model_validate(
            routing_payload.get("route_request")
        )
        route = ExecutionRouteDecision.model_validate(
            routing_payload.get("route_decision")
        )
        attempt = ExecutionAttemptObservation.model_validate(
            routing_payload.get("attempt_observation")
        )
        target = ResolvedExecutionTarget.model_validate(
            routing_payload.get("proposed_target")
        )
    except (TypeError, ValueError) as exc:
        raise EpicDispatchError(f"invalid execution routing evidence: {exc}") from exc

    context_hash = canonical_hash(context_pack)
    issue_contract = context_pack.get("issue_contract")
    validation_ledger = context_pack.get("validation_ledger")
    runtime = context_pack.get("runtime")
    if not isinstance(issue_contract, Mapping) or not isinstance(
        validation_ledger, list
    ) or not isinstance(runtime, Mapping):
        raise EpicDispatchError("context pack lacks routing hash inputs")
    authority_hash = canonical_hash(issue_contract)
    verification_hash = canonical_hash(validation_ledger)
    try:
        validate_route_decision(request, route)
        census = load_provider_census(_DECLARED_PROVIDER_CENSUS_PATH)
        expected_target = resolve_execution_target(
            census,
            channel="dev",
            capability=route.selected_capability,
        )
        mode = _normalize_choice(
            routing_payload.get("mode"), "execution_routing.mode", {"shadow", "canary"}
        )
        canary_admission = routing_payload.get("canary_admission")
        if mode == "canary":
            if not isinstance(canary_admission, Mapping):
                raise EpicDispatchError("canary routing requires explicit admission evidence")
            sample_index = _normalize_positive_int(
                canary_admission.get("sample_index"), "canary_admission.sample_index"
            )
            sample_limit = _normalize_positive_int(
                canary_admission.get("sample_limit"), "canary_admission.sample_limit"
            )
            admit_phase2_canary(
                request,
                opt_in=canary_admission.get("opt_in") is True,
                sample_index=sample_index,
                sample_limit=sample_limit,
            )
            expected_admission: dict[str, object] | None = {
                "opt_in": True,
                "sample_index": 1,
                "sample_limit": 1,
            }
        else:
            expected_admission = None
        expected_attempt = create_execution_attempt(
            request=request,
            decision=route,
            target=expected_target,
            attempt_number=1,
            mode=cast(Literal["shadow", "canary"], mode),
            outcome="not_invoked",
            observed_at=request.decision_at,
            transition_reason=(
                "shadow_route_not_invoked" if mode == "shadow" else "initial_route"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EpicDispatchError(
            f"execution routing evidence cannot be replayed: {exc}"
        ) from exc
    expected_comparison = {
        "incumbent_capability": route.shadow_against_capability,
        "proposed_capability": route.selected_capability,
        "verification_profile_hash_unchanged": True,
        "launch_policy_changed": mode == "canary",
    }
    if (
        routing_payload.get("schema_version") != 1
        or routing_payload.get("mode") not in {"shadow", "canary"}
        or routing_payload.get("authority")
        != "evidence-only-no-launch-or-lifecycle-effect"
        or request.issue_number != issue_contract.get("number")
        or request.shadow_against_capability != runtime.get("capability")
        or target != expected_target
        or attempt != expected_attempt
        or routing_payload.get("shadow_comparison") != expected_comparison
        or routing_payload.get("canary_admission") != expected_admission
        or any(
            contract.context_pack_hash != context_hash
            or contract.authority_hash != authority_hash
            or contract.verification_profile_hash != verification_hash
            for contract in (request, route, attempt)
        )
    ):
        raise EpicDispatchError(
            "execution routing evidence does not bind the frozen context pack"
        )


def _dispatch_slot(decision: Mapping[str, Any]) -> int:
    return _normalize_positive_int(
        decision.get("dispatch_slot"),
        "decision.dispatch_slot",
    )


def _validate_phase2_canary_plan_bound(
    items: Iterable[Mapping[str, Any]],
    *,
    source: str,
) -> None:
    """Reject more than one canary declaration in one frozen dispatch plan."""

    canary_count = 0
    for item in items:
        if not isinstance(item, Mapping):
            continue
        routing = item.get("execution_routing")
        if isinstance(routing, Mapping) and routing.get("mode") == "canary":
            canary_count += 1
    if canary_count > 1:
        raise EpicDispatchError(
            f"Phase 2 canary sample limit permits one candidate per {source}"
        )


def _session_dispatch_receipt(
    run_id: str,
    sessions: list[dict[str, Any]],
    *,
    status: str,
    stopped_reason: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "execution_mode": "serial-fresh-sessions",
        "status": status,
        "sessions": sessions,
        "stopped_reason": stopped_reason,
        "github_mutations": [],
        "coordinator_claims": [],
        "source": "builderops.epic_dispatch.serial_sessions",
    }


def _parse_worker_receipt(text: str) -> object:
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped[-8_000:]
    return parsed


def _validated_worker_receipt(
    receipt: object,
    *,
    session_id: str,
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise IssueSessionLaunchError(
            "worker returned no structured handoff receipt",
            session_id=session_id,
        )
    missing = [
        field
        for field in HANDOFF_RECEIPT_SCHEMA["required_fields"]
        if field not in receipt
    ]
    if missing:
        raise IssueSessionLaunchError(
            f"worker handoff receipt is missing fields: {', '.join(missing)}",
            session_id=session_id,
        )
    final_state = receipt.get("final_state")
    if final_state not in {"blocked", "needs-human", "handoff"}:
        raise IssueSessionLaunchError(
            "worker handoff receipt has an invalid final_state",
            session_id=session_id,
        )
    _validate_context_cost(receipt.get("context_cost"), session_id=session_id)
    return dict(receipt)


def _validate_context_cost(value: object, *, session_id: str) -> None:
    if not isinstance(value, Mapping):
        raise IssueSessionLaunchError(
            "worker handoff receipt context_cost must be an object",
            session_id=session_id,
        )
    if value.get("measurement") not in {"actual", "proxy"}:
        raise IssueSessionLaunchError(
            "worker handoff receipt context_cost measurement must be actual or proxy",
            session_id=session_id,
        )
    for field in ("input_tokens", "agent_starts", "context_pack_bytes", "compactions"):
        item = value.get(field)
        valid_integer = isinstance(item, int) and not isinstance(item, bool) and item >= 0
        valid_unknown = (
            isinstance(item, str)
            and item.startswith("unknown(")
            and item.endswith(")")
            and len(item) > len("unknown()")
        )
        if not (valid_integer or valid_unknown):
            raise IssueSessionLaunchError(
                f"worker handoff receipt context_cost.{field} must be a non-negative integer or unknown(reason)",
                session_id=session_id,
            )


def _build_tcd_decision(
    candidate: Mapping[str, Any],
    runtimes: list[str],
    active_leases: set[int],
) -> dict[str, Any]:
    issue_number = candidate["issue_number"]
    skip_reason = _claimability_skip_reason(candidate, active_leases)
    selected_path = "skip" if skip_reason is not None else _selected_path(candidate)
    runtime_target = candidate["runtime_hint"] or runtimes[0]
    if runtime_target not in runtimes:
        runtime_target = runtimes[0]
    risk = candidate["risk"]

    if selected_path == "inline":
        skip_reason = skip_reason or "inline-local-cheaper"
    elif selected_path == "script":
        skip_reason = skip_reason or "script-deterministic"

    runtime_model_hint = {
        "runtime": runtime_target,
        "model_class": _model_class_for(risk),
        "capability": _capability_for_risk(risk),
        "runtime_difference": "invocation-hint-only",
    }
    model_override = candidate.get("model_override")
    if model_override is not None:
        runtime_model_hint["model"] = model_override

    return {
        "issue_number": issue_number,
        "selected_path": selected_path,
        "expected_value": candidate["expected_value"],
        "runtime_model_hint": runtime_model_hint,
        "budget_class": _budget_class_for(risk, candidate["expected_value"]),
        "context_cost_estimate": {
            "measurement": "proxy",
            "input_tokens": "unknown(no-fresh-agent-selected)",
            "agent_starts": 0,
            "context_pack_bytes": 0,
            "compactions": 0,
        },
        "stop_condition": candidate["stop_condition"]
        or "Return a subagent_handoff_receipt; stop on claim conflict, branch/worktree drift, missing Verify target, or authority ambiguity.",
        "skip_reason": skip_reason,
    }


def _build_context_pack(
    candidate: Mapping[str, Any],
    *,
    decision: Mapping[str, Any],
    context_pack_id: str,
    dispatch_slot: int,
    discovered_overlap_policy: str,
) -> dict[str, Any]:
    pack = {
        "schema_version": SCHEMA_VERSION,
        "context_pack_id": context_pack_id,
        "dispatch_slot": dispatch_slot,
        "issue_contract": {
            "number": candidate["issue_number"],
            "title": candidate["title"],
            "url": candidate["url"],
            "scope": candidate["scope"],
        },
        "runtime": decision["runtime_model_hint"],
        "skill_loaded": ".codex/skills/issue-to-code/SKILL.md",
        "source_anchors": candidate["source_anchors"],
        "owner_docs": sorted(candidate["owner_docs"]),
        "known_constraints": list(candidate["known_constraints"]),
        "branch_worktree_plan": {
            "branch": candidate["branch"],
            "worktree": candidate["worktree"],
            "worker_self_claim": True,
            "coordinator_preclaim": False,
        },
        "validation_ledger": candidate["validation"],
        "publication_closure_expectations": {
            "publish_skill": ".codex/skills/publish-pr/SKILL.md",
            "verification_skill": ".codex/skills/verification-and-closure/SKILL.md",
            "builderops_routing_required": True,
            "github_lifecycle_truth": "Issues/PRs/CI",
            "no_project_or_label_mutation_by_dispatch_planner": True,
            "terminal_delivery_expected": True,
        },
        "coordination": {
            "routine_worker_to_worker": "prohibited",
            "discovered_overlap": discovered_overlap_policy,
            "coordinator_scope": "cross_issue_only",
            "worker_scope": "one_issue_end_to_end",
            "issue_local_helper_budget": candidate["issue_local_helper_budget"],
            "issue_local_helper_rationale": candidate["issue_local_helper_rationale"],
            "sole_writer": "issue_agent",
        },
        "return_schema": HANDOFF_RECEIPT_SCHEMA,
    }
    pack["context_cost_baseline"] = {
        "measurement": "actual",
        "context_pack_bytes_excluding_baseline": len(
            json.dumps(pack, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ),
    }
    return pack


def _parallel_skip_reason(
    candidate: Mapping[str, Any],
    *,
    selected_count: int,
    max_parallel: int,
    selected_files: set[str],
    selected_owner_docs: set[str],
    selected_validation_resources: set[str],
    selected_helper_slots: int,
) -> str | None:
    if candidate["dependencies"] and not candidate["dependencies_satisfied"]:
        return "dependency-not-ready"
    if selected_files.intersection(candidate["likely_touched_files"]):
        return "likely-file-conflict"
    if (
        candidate["owner_doc_writeback_required"]
        and selected_owner_docs.intersection(candidate["owner_docs"])
    ):
        return "owner-doc-writeback-conflict"
    if selected_validation_resources.intersection(candidate["validation_resources"]):
        return "validation-resource-conflict"
    required_slots = (
        selected_count
        + selected_helper_slots
        + 1
        + candidate["issue_local_helper_budget"]
    )
    if selected_count >= max_parallel:
        return "parallel-slot-cap"
    if required_slots > max_parallel:
        return "parallel-helper-capacity-reserve"
    return None


def _claimability_skip_reason(
    candidate: Mapping[str, Any],
    active_leases: set[int],
) -> str | None:
    if candidate["issue_number"] in active_leases:
        return "active-lease-conflict"
    if candidate["state"] != "OPEN":
        return "issue-not-open"
    if "agent:ready" not in candidate["labels"]:
        return "missing-agent-ready-label"
    return None


def _selected_path(candidate: Mapping[str, Any]) -> str:
    preferred = candidate["preferred_path"]
    if preferred:
        if preferred not in VALID_PATHS:
            raise EpicDispatchError(f"preferred_path must be one of {sorted(VALID_PATHS)}")
        return preferred
    if candidate["risk"] in {"high", "critical"}:
        return "subagent"
    if candidate["expected_value"] == "high":
        return "subagent"
    if candidate["scriptable"]:
        return "script"
    if candidate["expected_value"] == "low" or candidate["task_class"] in {
        "mechanical",
        "small-doc",
        "trivial",
    }:
        return "inline"
    return "subagent"


def _dispatch_state_summary(decision: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        "id": decision["id"],
        "issue_number": decision["issue_number"],
        "selected_path": decision["selected_path"],
        "selected_for_dispatch": decision["selected_for_dispatch"],
        "runtime_model_hint": decision["runtime_model_hint"],
        "budget_class": decision["budget_class"],
        "stop_condition": decision["stop_condition"],
        "skip_reason": decision["skip_reason"],
        "context_pack_id": decision["context_pack_id"],
    }
    if "execution_routing" in decision:
        summary["execution_routing"] = decision["execution_routing"]
    return summary


def _normalize_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise EpicDispatchError("candidate must be an object")
    issue_number = _normalize_positive_int(
        candidate.get("issue_number", candidate.get("number")),
        "issue_number",
    )
    issue_local_helper_budget = candidate.get("issue_local_helper_budget", 0)
    if (
        not isinstance(issue_local_helper_budget, int)
        or isinstance(issue_local_helper_budget, bool)
        or issue_local_helper_budget not in {0, 1}
    ):
        raise EpicDispatchError("issue_local_helper_budget must be 0 or 1")
    risk = _normalize_choice(
        candidate.get("risk", "medium"),
        "risk",
        {"low", "medium", "high", "critical"},
    )
    task_class = _normalize_string(
        candidate.get("task_class", "implementation"), "task_class"
    )
    helper_rationale = _normalize_optional_string(
        candidate.get("issue_local_helper_rationale")
    )
    complex_task_classes = {"complex", "multi-layer", "architecture", "state-machine"}
    if (
        issue_local_helper_budget == 1
        and risk not in {"high", "critical"}
        and task_class.lower() not in complex_task_classes
    ):
        raise EpicDispatchError(
            "issue_local_helper_budget=1 requires high/critical risk or an explicit complex task_class"
        )
    if issue_local_helper_budget == 1 and helper_rationale is None:
        raise EpicDispatchError(
            "issue_local_helper_budget=1 requires an explicit issue_local_helper_rationale"
        )
    runtime_hint = _normalize_optional_string(candidate.get("runtime_hint"))
    if runtime_hint is not None and runtime_hint != ACTIVE_WORKER_RUNTIME:
        raise EpicDispatchError(
            "active Builder worker runtime is Codex-only; runtime_hint must be codex"
        )
    execution_routing = candidate.get("execution_routing")
    if execution_routing is not None and not isinstance(execution_routing, Mapping):
        raise EpicDispatchError("execution_routing must be an object when supplied")
    model_override = _normalize_optional_string(candidate.get("model_override"))
    repository = _normalize_optional_string(candidate.get("repository"))
    return {
        "issue_number": issue_number,
        "repository": repository,
        "title": _normalize_string(candidate.get("title"), "title"),
        "url": _normalize_optional_string(candidate.get("url")),
        "state": _normalize_string(candidate.get("state", "OPEN"), "state").upper(),
        "labels": set(_normalize_string_list(candidate.get("labels", []), "labels")),
        "risk": risk,
        "expected_value": _normalize_choice(
            candidate.get("expected_value", "medium"),
            "expected_value",
            {"low", "medium", "high"},
        ),
        "task_class": task_class,
        "preferred_path": _normalize_optional_string(candidate.get("preferred_path")),
        "runtime_hint": runtime_hint,
        "model_override": model_override,
        "scriptable": bool(candidate.get("scriptable", False)),
        "issue_local_helper_budget": issue_local_helper_budget,
        "issue_local_helper_rationale": helper_rationale,
        "stop_condition": _normalize_optional_string(candidate.get("stop_condition")),
        "dependencies": [
            _normalize_positive_int(value, "dependencies")
            for value in candidate.get("dependencies", candidate.get("depends_on", []))
        ],
        "dependencies_satisfied": bool(candidate.get("dependencies_satisfied", False)),
        "strict_ready": _normalize_optional_bool(candidate.get("strict_ready"), "strict_ready"),
        "dependencies_known": _normalize_optional_bool(
            candidate.get("dependencies_known"), "dependencies_known"
        ),
        "authority_ambiguous": _normalize_optional_bool(
            candidate.get("authority_ambiguous"), "authority_ambiguous"
        ),
        "has_migration": _normalize_optional_bool(
            candidate.get("has_migration"), "has_migration"
        ),
        "contract_surfaces": set(
            _normalize_string_list(
                candidate.get("contract_surfaces", []), "contract_surfaces"
            )
        ),
        "file_surfaces_known": "likely_touched_files" in candidate,
        "contract_surfaces_known": "contract_surfaces" in candidate,
        "likely_touched_files": set(
            _normalize_string_list(
                candidate.get("likely_touched_files", []),
                "likely_touched_files",
            )
        ),
        "owner_docs": set(_normalize_string_list(candidate.get("owner_docs", []), "owner_docs")),
        "owner_doc_writeback_required": bool(
            candidate.get("owner_doc_writeback_required", False)
        ),
        "validation_resources": set(
            _normalize_string_list(
                candidate.get(
                    "validation_resources",
                    candidate.get("exclusive_validation_groups", []),
                ),
                "validation_resources",
            )
        ),
        "source_anchors": _normalize_json_list(candidate.get("source_anchors", []), "source_anchors"),
        "known_constraints": _normalize_json_list(
            candidate.get("known_constraints", []),
            "known_constraints",
        ),
        "validation": _normalize_json_list(candidate.get("validation", []), "validation"),
        "scope": _normalize_optional_string(candidate.get("scope"))
        or "Read the issue body and satisfy its bounded Scope and Acceptance Criteria.",
        "branch": _normalize_optional_string(candidate.get("branch"))
        or f"codex/issue-{issue_number}",
        "worktree": _normalize_optional_string(candidate.get("worktree"))
        or f"<dedicated-worktree-for-issue-{issue_number}>",
        "execution_routing": (
            json.loads(json.dumps(dict(execution_routing), sort_keys=True))
            if isinstance(execution_routing, Mapping)
            else None
        ),
    }


def _build_execution_routing(
    candidate: Mapping[str, Any],
    *,
    routing_input: Mapping[str, Any],
    context_pack: Mapping[str, Any],
    incumbent_capability: str,
) -> dict[str, Any]:
    mode = routing_input.get("mode")
    if mode not in {"shadow", "canary"}:
        raise EpicDispatchError("execution routing supports shadow or explicit canary mode")
    repository = _normalize_optional_string(candidate.get("repository"))
    if mode == "canary" and repository is None:
        raise EpicDispatchError(
            "execution_routing canary requires candidate.repository"
        )
    if "risk" in routing_input:
        raise EpicDispatchError(
            "execution_routing.risk must come from the canonical candidate"
        )
    incumbent = _normalize_choice(
        incumbent_capability,
        "incumbent_capability",
        {"spark", "luna", "terra", "sol"},
    )
    work_class = _normalize_choice(
        routing_input.get("work_class"),
        "execution_routing.work_class",
        {
            "deterministic",
            "bounded_fast",
            "general_delivery",
            "complex_delivery",
            "frontier_high_risk",
        },
    )
    route_risk = _normalize_choice(
        candidate.get("risk"),
        "candidate.risk",
        {"low", "medium", "high", "critical"},
    )
    canonical_ambiguity = (
        "low" if candidate.get("authority_ambiguous") is False else "high"
    )
    canonical_protected_surface = (
        route_risk != "low"
        or candidate.get("authority_ambiguous") is not False
        or candidate.get("has_migration") is not False
        or not candidate.get("file_surfaces_known")
        or not candidate.get("contract_surfaces_known")
        or bool(candidate.get("contract_surfaces"))
        or bool(candidate.get("owner_doc_writeback_required"))
        or str(candidate.get("task_class", "")).lower()
        in {"complex", "multi-layer", "architecture", "state-machine"}
    )
    # Routing input is an assertion about canonical Issue/candidate facts; it
    # may not lower the ambiguity or protected-surface classification.
    if "ambiguity" in routing_input and routing_input["ambiguity"] != canonical_ambiguity:
        raise EpicDispatchError(
            "execution_routing.ambiguity must match canonical candidate evidence"
        )
    if (
        "protected_surface" in routing_input
        and routing_input["protected_surface"] is not canonical_protected_surface
    ):
        raise EpicDispatchError(
            "execution_routing.protected_surface must match canonical candidate evidence"
        )
    ambiguity = canonical_ambiguity
    protected_surface = canonical_protected_surface
    decision_at = _normalize_string(
        routing_input.get("decision_at"),
        "execution_routing.decision_at",
    )
    observation_payload = routing_input.get("allocation_observation")
    try:
        observation = (
            AllocationObservation.model_validate(observation_payload)
            if observation_payload is not None
            else None
        )
        context_pack_hash = canonical_hash(context_pack)
        authority_hash = canonical_hash(context_pack["issue_contract"])
        verification_hash = canonical_hash(context_pack["validation_ledger"])
        request = ExecutionRouteRequest(
            request_id=(
                f"execution-route-request:{candidate['issue_number']}:{context_pack_hash}"
            ),
            issue_number=candidate["issue_number"],
            repository=repository,
            work_class=cast(WorkClass, work_class),
            risk=cast(
                Literal["low", "medium", "high", "critical"], route_risk
            ),
            ambiguity=cast(Literal["low", "medium", "high"], ambiguity),
            protected_surface=protected_surface,
            decision_at=decision_at,
            context_pack_hash=context_pack_hash,
            authority_hash=authority_hash,
            verification_profile_hash=verification_hash,
            shadow_against_capability=cast(CapabilityTier, incumbent),
            allocation_observation=observation,
        )
        if mode == "canary":
            sample_index = _normalize_positive_int(
                routing_input.get("sample_index"), "execution_routing.sample_index"
            )
            sample_limit = _normalize_positive_int(
                routing_input.get("sample_limit"), "execution_routing.sample_limit"
            )
            route = admit_phase2_canary(
                request,
                opt_in=routing_input.get("opt_in") is True,
                sample_index=sample_index,
                sample_limit=sample_limit,
            )
        else:
            route = resolve_bounded_fast_route(request)
        census = load_provider_census(_DECLARED_PROVIDER_CENSUS_PATH)
        proposed_target = resolve_execution_target(
            census,
            channel="dev",
            capability=route.selected_capability,
        )
        attempt = create_execution_attempt(
            request=request,
            decision=route,
            target=proposed_target,
            attempt_number=1,
            mode=cast(Literal["shadow", "canary"], mode),
            outcome="not_invoked",
            observed_at=request.decision_at,
            transition_reason=(
                "shadow_route_not_invoked" if mode == "shadow" else "initial_route"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EpicDispatchError(f"invalid execution_routing input: {exc}") from exc

    return {
        "schema_version": 1,
        "mode": mode,
        "route_request": request.model_dump(mode="json"),
        "route_decision": route.model_dump(mode="json"),
        "proposed_target": proposed_target.receipt_fields(),
        "shadow_comparison": {
            "incumbent_capability": incumbent,
            "proposed_capability": route.selected_capability,
            "verification_profile_hash_unchanged": True,
            "launch_policy_changed": mode == "canary",
        },
        "canary_admission": (
            {
                "opt_in": True,
                "sample_index": 1,
                "sample_limit": 1,
            }
            if mode == "canary"
            else None
        ),
        "attempt_observation": attempt.model_dump(mode="json"),
        "authority": "evidence-only-no-launch-or-lifecycle-effect",
    }


def _validate_run_state_owner(
    run_state: Mapping[str, Any],
    *,
    epic_issue_number: int | None,
    independent_issue_numbers: list[int],
    run_id: str,
) -> None:
    state_epic = run_state.get("epic_issue_number")
    state_independent = _normalize_independent_issue_numbers(
        run_state.get("independent_issue_numbers", [])
    )
    state_run_id = _normalize_string(run_state.get("run_id"), "run_state.run_id")
    if state_epic != epic_issue_number or state_independent != independent_issue_numbers:
        if state_epic is not None:
            raise EpicDispatchError(
                f"run_id {run_id!r} already belongs to epic {state_epic}"
            )
        raise EpicDispatchError(
            f"run_id {run_id!r} belongs to a different dispatch scope"
        )
    if state_run_id != run_id:
        raise EpicDispatchError(
            f"loaded run-state id {state_run_id!r} does not match requested run_id {run_id!r}"
        )


def _normalize_active_leases(
    active_leases: Iterable[int | str | Mapping[str, Any]],
) -> set[int]:
    lease_issues: set[int] = set()
    for lease in active_leases:
        if isinstance(lease, Mapping):
            value = lease.get("issue_number", lease.get("issue"))
        else:
            value = lease
        lease_issues.add(_normalize_positive_int(value, "active_leases"))
    return lease_issues


def _normalize_independent_issue_numbers(values: Iterable[int]) -> list[int]:
    normalized = [_normalize_positive_int(value, "independent_issue_numbers") for value in values]
    if len(set(normalized)) != len(normalized):
        raise EpicDispatchError("independent_issue_numbers must be unique")
    return sorted(normalized)


def _validate_independent_fast_lane_admission(
    candidates: list[dict[str, Any]], *, independent_issue_numbers: list[int]
) -> None:
    by_number = {candidate["issue_number"]: candidate for candidate in candidates}
    if (
        len(candidates) != len(independent_issue_numbers)
        # Defense-in-depth: scope normalization and the length/set checks make
        # duplicate candidate numbers unreachable today. Keep this explicit so
        # future admission refactors cannot silently collapse duplicates here.
        or len(by_number) != len(candidates)
        or set(by_number) != set(independent_issue_numbers)
    ):
        raise EpicDispatchError(
            "independent issue set must match candidates exactly"
        )
    for candidate in candidates:
        if candidate["strict_ready"] is not True or candidate["state"] != "OPEN" or "agent:ready" not in candidate["labels"]:
            raise EpicDispatchError(f"issue {candidate['issue_number']} is not strictly ready")
        if candidate["dependencies_known"] is not True or candidate["dependencies"]:
            raise EpicDispatchError(f"issue {candidate['issue_number']} has dependencies")
        if candidate["authority_ambiguous"] is not False:
            raise EpicDispatchError(f"issue {candidate['issue_number']} has authority ambiguity")
        if candidate["has_migration"] is not False:
            raise EpicDispatchError(f"issue {candidate['issue_number']} includes a migration")
        if not candidate["file_surfaces_known"]:
            raise EpicDispatchError(
                f"issue {candidate['issue_number']} lacks likely mutation surface evidence"
            )
        if not candidate["contract_surfaces_known"]:
            raise EpicDispatchError(
                f"issue {candidate['issue_number']} lacks contract surface evidence"
            )
    touched: set[str] = set()
    contracts: set[str] = set()
    for candidate in candidates:
        overlap = touched.intersection(candidate["likely_touched_files"])
        if overlap:
            raise EpicDispatchError(
                f"independent issue set has likely shared mutation surface: {sorted(overlap)}"
            )
        touched.update(candidate["likely_touched_files"])
        contract_overlap = contracts.intersection(candidate["contract_surfaces"])
        if contract_overlap:
            raise EpicDispatchError(
                f"independent issue set has contract overlap: {sorted(contract_overlap)}"
            )
        contracts.update(candidate["contract_surfaces"])


def _normalize_runtime_targets(values: Iterable[str]) -> list[str]:
    runtimes = [_normalize_string(value, "runtime_targets") for value in values]
    if not runtimes:
        raise EpicDispatchError("runtime_targets must not be empty")
    normalized = list(dict.fromkeys(runtimes))
    unsupported = [runtime for runtime in normalized if runtime != ACTIVE_WORKER_RUNTIME]
    if unsupported:
        raise EpicDispatchError(
            "active Builder worker runtime is Codex-only; unsupported runtime target(s): "
            + ", ".join(unsupported)
        )
    return normalized


def _normalize_positive_int(value: Any, field: str) -> int:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EpicDispatchError(f"{field} must be a positive integer")
    return value


def _normalize_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EpicDispatchError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise EpicDispatchError(f"{field} must be a boolean when supplied")
    return value


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EpicDispatchError("optional string values must be non-empty strings")
    return value.strip()


def _normalize_choice(value: Any, field: str, allowed: set[str]) -> str:
    normalized = _normalize_string(value, field).lower()
    if normalized not in allowed:
        raise EpicDispatchError(f"{field} must be one of {sorted(allowed)}")
    return normalized


def _normalize_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise EpicDispatchError(f"{field} must be a list")
    return [_normalize_string(item, field) for item in value]


def _normalize_json_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise EpicDispatchError(f"{field} must be a list")
    try:
        return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise EpicDispatchError(f"{field} must be JSON serializable") from exc


def _model_class_for(risk: str) -> str:
    if risk in {"critical", "high"}:
        return "high-reasoning"
    if risk == "low":
        return "low-cost"
    return "standard"


def _capability_for_risk(risk: str) -> str:
    return _CAPABILITY_FOR_MODEL_CLASS[_model_class_for(risk)]


def _budget_class_for(risk: str, expected_value: str) -> str:
    if risk in {"critical", "high"} or expected_value == "high":
        return "high"
    if risk == "low" and expected_value == "low":
        return "low"
    return "medium"


__all__ = [
    "CodexIssueSessionLauncher",
    "DEFAULT_MAX_PARALLEL",
    "HANDOFF_RECEIPT_SCHEMA",
    "IssueSessionLaunchError",
    "IssueSessionLauncher",
    "SCHEMA_VERSION",
    "EpicDispatchError",
    "build_dispatch_plan",
    "dispatch_issue_sessions",
    "frozen_dispatch_plan_hash",
]
