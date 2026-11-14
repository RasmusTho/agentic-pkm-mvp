"""Quota continuation through the existing epic worker lifecycle.

Called by the existing coordinator while it holds the worker lifecycle lock. The record is a
continuation of the issue mapping, not a claim or publication authority. External ports remain the
same container engine, OpenHands and GitHub readers used by the coordinator.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_observation as github_read

TARGET_ENGINE = "codex"
TARGET_MODEL = "gpt-6.1-terra"


def _publication_readbacks(mapping: Mapping[str, Any], rows: list[Any] | None, *,
                           issue: int, epic: int) -> dict[str, dict[str, Any]]:
    """Use positive matching PR readback only; absence and unknown pushes remain quarantined."""
    if rows is None:
        return {}
    branch = mapping.get("branch")
    matches = []
    for row in rows:
        if not isinstance(row, Mapping):
            return {}
        head = row.get("head")
        if not isinstance(head, Mapping):
            return {}
        repo = head.get("repo")
        if head.get("ref") == branch and isinstance(repo, Mapping) and repo.get("full_name") == github_read.REPOSITORY:
            from app.builderops import epic_coordination

            if not epic_coordination._pr_matches_issue(issue, epic, row.get("body")):
                return {}
            matches.append({"number": row.get("number"), "url": row.get("html_url"), "state": row.get("state"),
                            "branch": branch, "sha": head.get("sha")})
    return {op["id"]: {"complete": True, "branch": branch, "pull_requests": matches}
            for op in mapping.get("publication_ops", []) if isinstance(op, Mapping)
            and op.get("kind") == "pr_create" and op.get("status") in ew._OP_UNRESOLVED
            and isinstance(op.get("id"), str)}


def _context(state: Mapping[str, Any], mapping: Mapping[str, Any], issue: int,
             readback: Mapping[str, Any]) -> dict[str, Any]:
    def compact(value: Any, keys: tuple[str, ...]) -> Any:
        if not isinstance(value, Mapping):
            return "unknown"
        return {key: str(value[key])[:400] if not isinstance(value[key], (int, bool)) else value[key]
                for key in keys if key in value and value[key] is not None}

    findings = [compact(row, ("severity", "summary", "file", "line", "status", "url"))
                for row in state.get("review_findings", []) if isinstance(row, Mapping)
                and row.get("issue") in (issue, str(issue))]
    pending_directives = [compact(row, ("id", "action", "outcome", "conversation_id"))
                          for row in state.get("dispatch_decisions", []) if isinstance(row, Mapping)
                          and row.get("kind") == "epic_coordination_effect" and row.get("issue") == issue
                          and row.get("outcome") in ("reserved", "unknown", "delivered_run_deferred")]
    return {
        "issue_contract": readback.get("continuation_contract") or "unavailable: read the governing Issue",
        "lifecycle_owner": mapping.get("lifecycle_owner") or mapping.get("owner") or "unknown",
        "builder_session": mapping.get("builder_session") or "unknown",
        "next_action": str(mapping.get("next_action") or "unknown")[:600],
        "last_meaningful_progress": str(mapping.get("last_meaningful_progress") or "unknown")[:600],
        "pr": compact(mapping.get("pr"), ("number", "url", "state", "head")),
        "validation": compact(state.get("validation_status", {}).get(str(issue)), ("result", "command", "summary", "head")),
        "review_findings": findings[:10] if findings else "none recorded; live review state remains authoritative",
        "pending_directives": pending_directives[:10] if pending_directives else "none recorded",
        "pending_directives_truncated": len(pending_directives) > 10,
    }


def _mark(layout: ew.Layout, worker: str, expected: Mapping[str, Any], **updates: Any) -> None:
    def update(entry: dict[str, Any]) -> None:
        current = entry.get("engine_handoff")
        if not isinstance(current, Mapping) or current.get("stop_intent") != expected.get("stop_intent"):
            raise ew.TakeoverRefused("engine handoff changed; retain the newer assignment")
        entry["engine_handoff"] = {**current, **updates}
    ew._mutate_mapping(layout, worker, update)


def continuation_context(layout: ew.Layout, worker: str, handoff: Mapping[str, Any]) -> dict[str, Any]:
    brief = ew.continuation_brief(layout, worker)
    state = ew._load_state(layout)
    issue = ew._issue_for_worker(state, worker)
    mapping = state["issue_mappings"][str(issue)]
    stopped = mapping.get("work_at_stop") if isinstance(mapping.get("work_at_stop"), Mapping) else {}
    retained = {k: stopped.get(k) for k in ("branch", "head", "uncommitted_count", "uncommitted_paths",
                                              "ignored_count", "unpublished_commits", "unique_work")}
    return {**handoff["context"], "actual_checkout": str(layout.checkout(worker)),
            "execution_branch": brief["execution_branch"], "execution_head": brief["execution_head"],
            "retained_work": retained, "publication_operations": brief["publication_operations"]}


def _prompt(layout: ew.Layout, worker: str, handoff: Mapping[str, Any]) -> str:
    return (ew.continuation_brief(layout, worker)["prompt"]
            + "\n\nCompact controller records (unknown means not established):\n"
            + json.dumps(continuation_context(layout, worker, handoff), ensure_ascii=True, sort_keys=True, default=str))


def _confirmed_quota(status: Mapping[str, Any], conversation: Mapping[str, Any]) -> bool:
    settings = status.get("agent_settings")
    return (conversation.get("engine") == "claude-code" and conversation.get("status") == "created"
            and status.get("reachable") is True and status.get("events_reachable") is True
            and status.get("failure_class") == "quota_exhausted" and status.get("failure_current") is True
            and str(status.get("execution_status") or "").lower() in {"idle", "finished", "error", "stuck"}
            and isinstance(settings, Mapping) and settings.get("agent_kind") == "acp"
            and settings.get("acp_server") == "claude-code" and settings.get("acp_model") == conversation.get("model")
            and settings.get("current_model_id") in (None, conversation.get("model")))


def advance_locked(layout: ew.Layout, issue: int, worker: str, *, observed: Mapping[str, Any],
                   readback: Mapping[str, Any], codex_home: Path | None, runner: ew.Runner,
                   http: Callable[..., tuple[int, Any]], fetch: github_read.Fetch | None) -> dict[str, Any]:
    """Reserve or resume exactly one quota continuation under the caller's worker lock."""
    state = ew._load_state(layout)
    mapping = state["issue_mappings"][str(issue)]
    handoff = mapping.get("engine_handoff")
    reserved_now = False
    if not isinstance(handoff, Mapping) or handoff.get("status") == "complete":
        if ew.assignment_of(mapping) != dict(observed):
            raise ew.TakeoverRefused("assignment changed before quota handoff")
        conversation = mapping.get("conversation")
        status = ew.conversation_status(layout, worker, http=http, runner=runner, include_messages=False)
        if not isinstance(conversation, Mapping) or not _confirmed_quota(status, conversation):
            raise ew.TakeoverRefused("current bound Claude quota failure is not confirmed")
        if codex_home is None:
            raise ew.LaunchRefused("configured Codex subscription home is unavailable")
        marker = {"status": "pending", "trigger": "quota_exhausted", "predecessor": dict(observed),
                  "operation_id": conversation.get("operation_id"),
                  "confirmation": {"engine": conversation.get("engine"), "model": conversation.get("model"),
                                   "latest_event": status.get("latest_event"), "execution_status": status.get("execution_status")},
                  "stop_intent": {"stop_id": uuid.uuid4().hex, "previous_stop_id": mapping.get("stop_id")},
                  "owner_binding": {key: mapping.get(key) for key in ("lifecycle_owner", "owner", "builder_session")},
                  "context": _context(state, mapping, issue, readback),
                  "image": mapping.get("image"), "budget": mapping.get("budget"), "network": mapping.get("network")}

        def reserve(entry: dict[str, Any]) -> None:
            if (ew.assignment_of(entry) != dict(observed) or entry.get("conversation") != conversation
                    or any(entry.get(key) != marker["owner_binding"][key] for key in marker["owner_binding"])):
                raise ew.TakeoverRefused("assignment changed before handoff reservation")
            existing = entry.get("engine_handoff")
            if isinstance(existing, Mapping) and existing.get("status") != "complete":
                raise ew.TakeoverRefused("another engine handoff is already pending")
            entry["engine_handoff"] = marker
        ew._mutate_mapping(layout, worker, reserve)
        handoff = marker
        reserved_now = True

    if handoff.get("status") not in ("pending", "awaiting_pr_cycle"):
        raise ew.TakeoverRefused("engine handoff state is unknown")
    confirmation = handoff.get("confirmation")
    if (handoff.get("trigger") != "quota_exhausted" or not isinstance(confirmation, Mapping)
            or confirmation.get("engine") != "claude-code" or not isinstance(confirmation.get("model"), str)
            or not confirmation.get("model")):
        raise ew.TakeoverRefused("persisted quota confirmation is unknown")
    predecessor = handoff.get("predecessor")
    intent = handoff.get("recovery_stop_intent") or handoff.get("stop_intent")
    if not isinstance(predecessor, Mapping) or not isinstance(intent, Mapping):
        raise ew.TakeoverRefused("engine handoff predecessor or stop generation is unknown")
    old_conversation = predecessor.get("conversation")
    old_id = predecessor.get("container_id")
    if not isinstance(old_conversation, Mapping) or not isinstance(old_id, str) or not ew._CONTAINER_ID.fullmatch(old_id):
        raise ew.TakeoverRefused("predecessor identity is unknown")
    mapping = ew._load_state(layout)["issue_mappings"][str(issue)]
    owner_binding = handoff.get("owner_binding")
    if (not isinstance(owner_binding, Mapping) or set(owner_binding) != {"lifecycle_owner", "owner", "builder_session"}
            or any(mapping.get(key) != value for key, value in owner_binding.items())):
        raise ew.TakeoverRefused("lifecycle owner or Builder session changed during handoff")
    conversation = mapping.get("conversation")
    if mapping.get("state") == "running" and isinstance(conversation, Mapping) and conversation.get("id") == old_conversation.get("id") and conversation.get("status") != ew.CONVERSATION_ENDED:
        if ew.assignment_of(mapping) != dict(predecessor):
            raise ew.TakeoverRefused("predecessor assignment changed before stop")
        if conversation.get("engine") != confirmation.get("engine") or conversation.get("model") != confirmation.get("model"):
            raise ew.TakeoverRefused("predecessor engine or model changed before stop")
        if not reserved_now and ew._id_present(old_id, runner):
            # The persisted confirmation permits recovery even if the old endpoint is gone. Positive
            # newer activity or a different failure, however, must not be stopped as stale quota.
            latest = ew.conversation_status(layout, worker, http=http, runner=runner, include_messages=False)
            if latest.get("reachable") is True:
                active = str(latest.get("execution_status") or "").lower() == "running"
                changed = latest.get("events_reachable") is True and not _confirmed_quota(latest, conversation)
                if active or changed:
                    raise ew.TakeoverRefused("predecessor has newer activity or a different failure; reobserve its assignment")
    elif mapping.get("state") == "stopped_verified":
        stopped_container = handoff.get("recovery_container_id") if handoff.get("recovery_stop_intent") else old_id
        if mapping.get("stop_id") != intent.get("stop_id") or mapping.get("container_id") != stopped_container:
            raise ew.TakeoverRefused("stop generation or predecessor container changed")
    elif mapping.get("state") == "starting":
        takeover = ew._takeover_of(mapping)
        if (takeover.get("status") != "consumed" or takeover.get("stop_id") != mapping.get("stop_id")
                or not isinstance(conversation, Mapping) or conversation.get("id") != old_conversation.get("id")
                or conversation.get("status") != ew.CONVERSATION_ENDED or ew._id_present(old_id, runner)):
            raise ew.TakeoverRefused("unknown successor launch cannot be bound to the stopped predecessor")
        recovery_intent = handoff.get("recovery_stop_intent")
        if isinstance(recovery_intent, Mapping) and recovery_intent.get("previous_stop_id") == mapping.get("stop_id"):
            if mapping.get("container_id") != handoff.get("recovery_container_id"):
                raise ew.TakeoverRefused("unknown successor container identity changed")
        elif intent.get("stop_id") == mapping.get("stop_id"):
            recovery = {"stop_id": uuid.uuid4().hex, "previous_stop_id": mapping.get("stop_id")}
            _mark(layout, worker, handoff, recovery_stop_intent=recovery,
                  recovery_container_id=mapping.get("container_id"))
            handoff = ew._load_state(layout)["issue_mappings"][str(issue)]["engine_handoff"]
            intent = recovery
        else:
            raise ew.TakeoverRefused("unknown successor stop generation changed")
    elif mapping.get("state") != "running":
        raise ew.TakeoverRefused("worker lifecycle state is unknown")

    if mapping.get("state") in ("stopped_verified", "starting") or (isinstance(conversation, Mapping)
            and conversation.get("id") == old_conversation.get("id") and conversation.get("status") != ew.CONVERSATION_ENDED):
        def readback_after_stop(current: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
            unresolved = any(isinstance(op, Mapping) and op.get("status") in ew._OP_UNRESOLVED
                             for op in current.get("publication_ops", []))
            if not unresolved or fetch is None:
                return {}
            rows = github_read._Reader(fetch, time.monotonic).pages(
                f"/repos/{github_read.REPOSITORY}/pulls?state=open", github_read.MAX_PAGES)
            return _publication_readbacks(current, rows, issue=issue, epic=layout.epic)

        ew._takeover_locked(layout, worker, reason="confirmed Claude quota exhaustion",
                            readback_provider=readback_after_stop, runner=runner,
                            stop_intent=intent,
                            expected_container_id=(handoff.get("recovery_container_id") if handoff.get("recovery_stop_intent") else old_id),
                            allow_starting=bool(handoff.get("recovery_stop_intent")))
        mapping = ew._load_state(layout)["issue_mappings"][str(issue)]
    if mapping.get("state") == "stopped_verified":
        budget = handoff.get("budget")
        if not isinstance(budget, Mapping) or codex_home is None:
            raise ew.LaunchRefused("successor launch configuration is unavailable")
        if not isinstance(handoff.get("image"), str) or not isinstance(handoff.get("network"), str):
            raise ew.LaunchRefused("successor image or network is unavailable")
        ew._start_openhands_worker_locked(layout, worker,
            budget=ew.Budget(budget.get("cpus"), budget.get("memory"), budget.get("pids")),
            codex_home=codex_home, image=handoff["image"], network=handoff["network"], runner=runner, http=http)
        mapping = ew._load_state(layout)["issue_mappings"][str(issue)]

    takeover = ew._takeover_of(mapping)
    if (mapping.get("state") != "running" or mapping.get("runtime") != "openhands"
            or mapping.get("container_id") == old_id or takeover.get("status") != "consumed"
            or takeover.get("stop_id") != intent.get("stop_id") or ew._id_present(old_id, runner)
            or ew._worker_inspect(layout, worker, mapping, runner) != "running"):
        raise ew.TakeoverRefused("successor or predecessor absence is not bound to the authorized takeover")
    conversation = mapping.get("conversation")
    if isinstance(conversation, Mapping) and conversation.get("id") != old_conversation.get("id"):
        if (conversation.get("id") != takeover.get("conversation_id") or conversation.get("engine") != TARGET_ENGINE
                or conversation.get("model") != TARGET_MODEL or conversation.get("operation_id") != handoff.get("operation_id")):
            raise ew.TakeoverRefused("successor conversation identity is ambiguous")
        if conversation.get("status") in ("creating", "unknown"):
            conversation = ew._reconcile_worker_conversation_locked(layout, worker, http=http, runner=runner)
        if conversation.get("status") == "created":
            _mark(layout, worker, handoff, status="complete", successor_conversation=conversation["id"])
        return {"state": "continued" if conversation.get("status") == "created" else "unknown_create",
                "conversation": dict(conversation)}
    if not isinstance(conversation, Mapping) or conversation.get("status") != ew.CONVERSATION_ENDED:
        raise ew.TakeoverRefused("predecessor conversation is not verified ended")
    if handoff.get("operation_id") is not None:
        # PR cycle reconstructs its report grammar and current contract from its own records.
        _mark(layout, worker, handoff, status="awaiting_pr_cycle")
        return {"state": "awaiting_pr_cycle", "operation_id": handoff["operation_id"]}
    conversation = ew._start_conversation_locked(layout, worker, engine=TARGET_ENGINE, model=TARGET_MODEL,
                                                  prompt=_prompt(layout, worker, handoff), runner=runner, http=http)
    if conversation.get("status") == "created":
        _mark(layout, worker, handoff, status="complete", successor_conversation=conversation["id"])
    return {"state": "continued" if conversation.get("status") == "created" else "unknown_create",
            "conversation": conversation}
