"""Runtime-neutral dispatch planning for deliver-issue-set epic runs."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from app.builderops.epic_run_state import validate_run_id

SCHEMA_VERSION = 2
DEFAULT_MAX_PARALLEL = 2
FAST_LANE_MAX_PARALLEL = 2
MAX_NON_ROOT_AGENT_SLOTS = 2
VALID_PATHS = {"inline", "script", "subagent", "skip"}

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

    def __init__(self, message: str, *, session_id: str | None = None) -> None:
        self.session_id = session_id
        super().__init__(message)


class IssueSessionLauncher(Protocol):
    """Minimal transitional seam for one fresh issue-worker session."""

    def launch(self, context_pack: Mapping[str, Any]) -> Mapping[str, Any]: ...


_TCD_CODEX_ROUTE = {
    "low-cost": ("gpt-5.6-luna", "low"),
    "standard": ("gpt-5.6-terra", "medium"),
    "high-reasoning": ("gpt-5.6-sol", "high"),
}


class CodexIssueSessionLauncher:
    """Run one issue context pack to terminal in a fresh local Codex session."""

    def __init__(
        self,
        *,
        repo_root: Path,
        adapter_path: Path | None = None,
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

    def command(self, context_pack: Mapping[str, Any]) -> list[str]:
        model, reasoning_effort = self._tcd_route(context_pack)
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

    def launch(self, context_pack: Mapping[str, Any]) -> Mapping[str, Any]:
        prompt = self.prompt(context_pack)
        result = self.runner(
            self.command(context_pack),
            cwd=self.repo_root,
            input=prompt,
            capture_output=True,
            text=True,
            check=False,
        )
        session_id: str | None = None
        worker_receipt: object | None = None
        terminal_error: str | None = None
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

    @staticmethod
    def _tcd_route(context_pack: Mapping[str, Any]) -> tuple[str, str]:
        runtime = context_pack.get("runtime")
        if not isinstance(runtime, Mapping) or runtime.get("runtime") != "codex":
            raise EpicDispatchError("serial session launcher supports codex runtime only")
        model_class = runtime.get("model_class")
        if not isinstance(model_class, str) or model_class not in _TCD_CODEX_ROUTE:
            raise EpicDispatchError("context pack has no supported TCD model class")
        return _TCD_CODEX_ROUTE[model_class]

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
    runtime_targets: Iterable[str] = ("codex", "claude"),
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


def dispatch_issue_sessions(
    plan: Mapping[str, Any],
    launcher: IssueSessionLauncher,
) -> dict[str, Any]:
    """Execute a frozen dispatch plan serially, with one fresh session per Issue."""

    run_id, ordered = _validated_session_contexts(plan)
    sessions: list[dict[str, Any]] = []
    seen_session_ids: set[str] = set()

    for decision, context_pack in ordered:
        issue_number = decision["issue_number"]
        context_pack_id = decision["context_pack_id"]
        try:
            launch_result = launcher.launch(context_pack)
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
            sessions.append(
                {
                    "issue_number": issue_number,
                    "context_pack_id": context_pack_id,
                    "session_id": session_id,
                    "fresh_session": True,
                    "status": final_state,
                    "worker_receipt": worker_receipt,
                }
            )
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
            sessions.append(
                {
                    "issue_number": issue_number,
                    "context_pack_id": context_pack_id,
                    "session_id": failed_session_id,
                    "fresh_session": True,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": (str(exc).strip() or type(exc).__name__)[-2_000:],
                }
            )
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
        ordered.append((decision, matching_context))
    return run_id, ordered


def _dispatch_slot(decision: Mapping[str, Any]) -> int:
    return _normalize_positive_int(
        decision.get("dispatch_slot"),
        "decision.dispatch_slot",
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

    return {
        "issue_number": issue_number,
        "selected_path": selected_path,
        "expected_value": candidate["expected_value"],
        "runtime_model_hint": {
            "runtime": runtime_target,
            "model_class": _model_class_for(risk),
            "runtime_difference": "invocation-hint-only",
        },
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
            "discovered_overlap": "typed-coordinator-exception",
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
    return {
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
    return {
        "issue_number": issue_number,
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
        "runtime_hint": _normalize_optional_string(candidate.get("runtime_hint")),
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
    return list(dict.fromkeys(runtimes))


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
]
