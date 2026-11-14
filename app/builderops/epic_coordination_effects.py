"""Bounded directive delivery through the existing OpenHands conversation API.

The controller reserves an attempt in run-state before POSTing. Once reserved it is
never re-posted, even if a reply or event read is lost. A later pass can reconcile
it using the randomly marked user MessageEvent. Delivery is not work progress.
"""
from __future__ import annotations

import secrets
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import quote

from app.builderops import epic_coordination as coord
from app.builderops import epic_run_state
from app.builderops import epic_workspace as ew

EFFECT_KIND = "epic_coordination_effect"
DIRECTIVE_ACTIONS = ("change_approach", "repair_technical_dependency")
PENDING = ("reserved", "unknown", "delivered_run_deferred")
Http = Callable[..., tuple[int, Any]]


def compose(decision: Mapping[str, Any], marker: str) -> str:
    head = f"[{marker}] Message from the epic coordinator about Issue #{decision['issue']}."
    if decision["action"] == "change_approach":
        return (f"{head} Recent coordinator passes found no new work evidence. Do not repeat the same attempt. "
                "Choose a different hypothesis, then make a change or run a check that produces new evidence. "
                "If genuinely blocked, write .codex-tmp/worker-blocker.json (schema worker_blocker.v1, field summary).")
    return (f"{head} You declared this blocker: {decision.get('declared_blocker', '')!r}. Check the Issue's "
            "source authority and use the simplest in-scope technical approach. Follow issue-maintenance-change-control "
            ":: Repair technical constraints and resume; give any needed Issue repair to the trusted coordinator, "
            "who owns GitHub writes. Continue within the current contract and update the blocker file if resolved.")


def _ended(state: Mapping[str, Any], issue: int, conversation_id: Any) -> bool:
    """True once the effect's conversation ended with a verified container stop: it can no longer write."""
    mapping = state.get("issue_mappings", {}).get(str(issue), {})
    rows = [*mapping.get("conversation_history", []), mapping.get("conversation")] if isinstance(mapping, Mapping) else []
    return any(isinstance(row, Mapping) and row.get("id") == conversation_id and row.get("status") == ew.CONVERSATION_ENDED
               for row in rows)


def _pending(state: Mapping[str, Any], issue: int) -> list[dict[str, Any]]:
    """Unresolved effects that still bind this Issue's writer.

    An effect whose conversation verifiably ended keeps its outcome and obligations in its own
    record, but it no longer blocks (or is reconciled against) a successor assignment.
    """
    return [r for r in state.get("dispatch_decisions", []) if isinstance(r, dict)
            and r.get("kind") == EFFECT_KIND and r.get("issue") == issue and r.get("outcome") in PENDING
            and not _ended(state, issue, r.get("conversation_id"))]


def _cooling(state: Mapping[str, Any], issue: int) -> bool:
    """Leave time for an accepted run to become visible before another directive."""
    for record in state.get("dispatch_decisions", []):
        if (isinstance(record, Mapping) and record.get("kind") == EFFECT_KIND
                and record.get("issue") == issue and record.get("outcome") == "delivered"):
            completed = record.get("post_completed_at")
            if not isinstance(completed, (int, float)) or time.time() - completed < coord.STALL_SECONDS:
                return True
    return False


def _binding(mapping: Mapping[str, Any], effect: Mapping[str, Any], worker: str) -> bool:
    """The current mapping is still exactly the assignment the effect was reserved for."""
    conversation = mapping.get("conversation")
    return (mapping.get("worker") == worker == effect.get("worker") and mapping.get("runtime") == "openhands"
            and mapping.get("state") == "running" and isinstance(conversation, Mapping)
            and conversation.get("status") == "created" and conversation.get("id") == effect.get("conversation_id")
            and isinstance(effect.get("assignment"), Mapping) and ew.assignment_of(mapping) == effect["assignment"])


def _update(layout: ew.Layout, effect: Mapping[str, Any], *, next_action: str) -> dict[str, Any]:
    """Record an effect outcome in its own record; touch the mapping only for the same assignment."""
    updated: dict[str, Any] = {}
    def updater(state: dict[str, Any]) -> dict[str, Any]:
        for record in state["dispatch_decisions"]:
            if isinstance(record, dict) and record.get("id") == effect["id"]:
                if record.get("outcome") in PENDING:
                    for field in ("event_id", "event_timestamp", "execution_status"):
                        if effect.get(field) is not None:
                            record[field] = effect[field]
                    if "post_status" in effect:
                        record["post_status"] = effect["post_status"]
                        if effect["post_status"]:
                            record["post_completed_at"] = time.time()
                        if effect["post_status"] == 429:
                            obligation = "Run capacity was full: reconcile the existing conversation and use its /run endpoint when safe."
                            pending = record.setdefault("pending_obligations", [])
                            if obligation not in pending:
                                pending.append(obligation)
                    if effect.get("not_sent"):
                        record.update(outcome="refused", attempts=0, reason=effect.get("reason"))
                    elif record.get("event_id") and record.get("post_status") == 429:
                        record["outcome"] = "delivered_run_deferred"
                    elif record.get("event_id") and record.get("post_status") in (200, 201):
                        record["outcome"] = "delivered"
                    elif "post_status" in effect:
                        record["outcome"] = "unknown"
                    mapping = state["issue_mappings"][str(effect["issue"])]
                    if _binding(mapping, record, str(record.get("worker"))):
                        mapping["next_action"] = next_action
                    else:
                        # A newer stop or assignment owns the mapping; this attempt's result and
                        # obligations stay here, in the old attempt's own record.
                        record["assignment_superseded"] = True
                updated.update(record)
                break
        return state
    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=updater,
                                         expected_epic_issue_number=layout.epic)
    return updated


def _reserve(layout: ew.Layout, issue: int, worker: str, decision: Mapping[str, Any], tick: str,
             observed: Mapping[str, Any]) -> dict[str, Any] | None:
    """Reserve one attempt iff the decision, the observation and the current mapping are one assignment."""
    reserved: dict[str, Any] = {}
    def updater(state: dict[str, Any]) -> dict[str, Any]:
        mapping = state["issue_mappings"][str(issue)]
        conversation = mapping.get("conversation")
        records = state["dispatch_decisions"]
        prior = [r for r in records if isinstance(r, dict) and r.get("decision_id") == decision["id"]]
        if (_pending(state, issue) or _cooling(state, issue)
                or len(prior) > 1 or any(r.get("outcome") != "refused" or r.get("attempts") != 0 for r in prior)
                or mapping.get("worker") != worker or mapping.get("runtime") != "openhands" or mapping.get("state") != "running"
                or ew.assignment_of(mapping) != observed or decision.get("assignment") != observed
                or not isinstance(conversation, Mapping) or conversation.get("status") != "created" or not conversation.get("id")):
            return state
        reserved.update({"id": f"effect:{decision['id']}", "kind": EFFECT_KIND, "schema": coord.SCHEMA,
                         "issue": issue, "worker": worker, "conversation_id": conversation["id"],
                         "container_id": mapping.get("container_id"), "port": mapping.get("port"), "checkout": mapping.get("checkout"), "branch": mapping.get("branch"),
                         "assignment": dict(observed),
                         "decision_id": decision["id"], "action": decision["action"], "tick": tick,
                         "marker": "coordination-directive:" + secrets.token_hex(16), "attempts": 1,
                         "outcome": "reserved", "result": None,
                         "pending_obligations": ([f"Trusted coordinator: {coord.REPAIR_WORKFLOW}"]
                                                 if decision["action"] == "repair_technical_dependency" else [])})
        if decision.get("while_active"):
            reserved["while_active"] = True
        if prior:
            refusal = {"tick": prior[0].get("tick"), "reason": prior[0].get("reason")}
            prior[0].clear()
            prior[0].update(reserved, previous_refusal=refusal)
            reserved["previous_refusal"] = refusal
        else:
            records.append(dict(reserved))
        mapping["next_action"] = "Reconcile the reserved directive by its conversation event marker; never resend an unknown attempt."
        return state
    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=updater,
                                         expected_epic_issue_number=layout.epic)
    return reserved or None


def _observe(port: int, key: str, cid: str, marker: str, http: Http, *, layout: ew.Layout,
             issue: int, worker: str) -> tuple[str | None, str | None, str | None]:
    """Read back the marked user MessageEvent; call only inside the owning ``_session``."""
    try:
        code, body = http("GET", port, key,
                          f"/conversations/{cid}/events/search?kind=MessageEvent&source=user&body={quote(marker)}&limit=20",
                          None, 10.0)
        if code != 200 or not isinstance(body, Mapping) or not isinstance(body.get("items"), list):
            return None, None, None
        event_id = None
        timestamp = None
        for event in body["items"]:
            if not isinstance(event, Mapping) or event.get("kind") != "MessageEvent" or event.get("source") != "user":
                continue
            message = event.get("llm_message")
            if not isinstance(message, Mapping) or message.get("role") != "user" or not isinstance(message.get("content"), list):
                continue
            if any(isinstance(c, Mapping) and c.get("type") == "text" and isinstance(c.get("text"), str)
                   and c["text"].startswith(f"[{marker}] ") for c in message["content"]):
                if isinstance(event.get("id"), str) and event["id"]:
                    event_id = event["id"]
                    timestamp = event.get("timestamp") if isinstance(event.get("timestamp"), str) else None
                    break
        ccode, info = http("GET", port, key, f"/conversations/{cid}", None, 10.0)
        if ccode != 200 or not ew._conversation_bound(info, layout, issue, worker, cid):
            return None, None, None
        status = info.get("execution_status")
        return event_id, status, timestamp
    except Exception:  # noqa: BLE001 - one unreadable effect stays unknown
        return None, None, None


@contextmanager
def _session(layout: ew.Layout, issue: int, worker: str, expected: Mapping[str, Any], *,
             runner: ew.Runner, http: Http) -> Iterator[tuple[int, str, str, str, tuple[int, int]]]:
    """The bound conversation endpoint, fenced against stop/start/port reuse for the whole block."""
    conversation = expected.get("conversation")
    if (expected.get("worker") != worker or expected.get("runtime") != "openhands"
            or not isinstance(conversation, Mapping) or conversation.get("status") != "created"):
        raise ValueError("current worker conversation is unavailable")
    cid = str(conversation.get("id") or "")
    uuid.UUID(cid)
    identity = ew._checkout_mount_identity(layout, worker, expected)
    if identity is None:
        raise ValueError("worker checkout does not match")
    with ew._endpoint_session(layout, worker, issue, expected, runner) as (port, key):
        if ew._checkout_mount_identity(layout, worker, expected) != identity:
            raise ValueError("worker checkout changed before session access")
        code, info = http("GET", port, key, f"/conversations/{cid}", None, 10.0)
        if code != 200 or not ew._conversation_bound(info, layout, issue, worker, cid):
            raise ValueError("conversation identity does not match")
        yield port, key, cid, str(info.get("execution_status") or "").lower(), identity


def _fresh_authority(layout: ew.Layout, issue: int, mapping: Mapping[str, Any], fetch: coord.Fetch | None) -> bool:
    if fetch is None:
        return False
    try:
        receipt = coord.read_issue_authority(issue, fetch)
        authority = coord.authority_for({"compact_receipts": [receipt]}, issue)
        rows = coord.github_read._Reader(fetch, time.monotonic).pages(
            f"/repos/{coord.github_read.REPOSITORY}/pulls?state=open", coord.github_read.MAX_PAGES)
        coord._live_pr_part(issue, mapping.get("branch"), rows)
        return authority.get("kind") in ("none", "technical")
    except Exception:  # noqa: BLE001 - unavailable or conflicting live authority fails closed
        return False


def _refuse(layout: ew.Layout, issue: int, worker: str, tick: str, decision: Mapping[str, Any], reason: str,
            observed: Mapping[str, Any]) -> dict[str, Any]:
    def updater(state: dict[str, Any]) -> dict[str, Any]:
        record = {"id": f"effect:{decision['id']}", "kind": EFFECT_KIND, "schema": coord.SCHEMA,
                  "issue": issue, "worker": worker, "decision_id": decision["id"], "action": decision["action"],
                  "tick": tick, "outcome": "refused", "attempts": 0, "reason": reason}
        if not any(isinstance(r, Mapping) and r.get("id") == record["id"] for r in state["dispatch_decisions"]):
            state["dispatch_decisions"].append(record)
            mapping = state["issue_mappings"][str(issue)]
            if ew.assignment_of(mapping) == observed:
                mapping["next_action"] = f"Directive refused: {reason}; reconcile the worker identity before a new decision."
        return state
    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=updater,
                                         expected_epic_issue_number=layout.epic)
    return {"decision_id": decision["id"], "action": decision["action"], "outcome": "refused", "event_id": None}


def reconcile_item(layout: ew.Layout, issue: int, worker: str, *, http: Http, runner: ew.Runner,
                   fetch: coord.Fetch | None) -> list[dict[str, Any]]:
    state = ew._load_state(layout)
    mapping = state["issue_mappings"][str(issue)]
    outcomes = []
    for original in _pending(state, issue):
        effect = {"id": original["id"], "issue": issue}
        event_id = status = timestamp = None
        if _binding(mapping, original, worker):
            try:
                if not _fresh_authority(layout, issue, mapping, fetch):
                    raise ValueError("source authority unavailable")
                with _session(layout, issue, worker, mapping, runner=runner, http=http) as (port, key, cid, _, _identity):
                    event_id, status, timestamp = _observe(port, key, cid, str(original["marker"]), http,
                                                            layout=layout, issue=issue, worker=worker)
            except Exception:  # noqa: BLE001 - preserve uncertainty without blocking peers
                pass
        if event_id:
            effect.update(event_id=event_id, event_timestamp=timestamp, execution_status=status)
            nxt = ("Message observed; run capacity was full. Reconcile the conversation and use its existing /run endpoint when safe."
                   if original.get("post_status") == 429 else
                   "Message observed; retain any unresolved POST obligation before another directive.")
        else:
            nxt = ("The directive outcome is unknown. Reconcile its marker in the original conversation; "
                   "do not resend or replace the writer. Other issues may continue.")
        updated = _update(layout, effect, next_action=nxt)
        outcomes.append({"decision_id": original["decision_id"], "action": original["action"],
                         "outcome": updated.get("outcome"), "event_id": event_id})
    return outcomes


def apply_item(layout: ew.Layout, issue: int, worker: str, tick: str, *, decision_id: str | None,
               observed: Mapping[str, Any], http: Http, runner: ew.Runner, fetch: coord.Fetch | None) -> list[dict[str, Any]]:
    """Deliver the judged directive to the observed assignment's conversation, or to nobody."""
    state = ew._load_state(layout)
    if _pending(state, issue):
        return []  # reconciliation precedes judgement; no other effect can pass an unknown one
    mapping = state["issue_mappings"][str(issue)]
    decision = next((d for d in state["dispatch_decisions"] if isinstance(d, Mapping) and d.get("kind") == coord.KIND
                     and d.get("issue") == issue and d.get("worker") == worker
                     and d.get("action") in DIRECTIVE_ACTIONS and d.get("id") == decision_id), None)
    if decision is None or any(isinstance(r, Mapping) and r.get("decision_id") == decision["id"]
                               and (r.get("outcome") != "refused" or r.get("attempts") != 0) for r in state["dispatch_decisions"]):
        return []
    conversation = mapping.get("conversation")
    if not (isinstance(conversation, Mapping) and conversation.get("status") == "created"
            and conversation.get("id") and mapping.get("worker") == worker and mapping.get("state") == "running"):
        return [_refuse(layout, issue, worker, tick, decision, "no created conversation bound to the current worker", observed)]
    try:
        uuid.UUID(str(conversation["id"]))
    except (ValueError, AttributeError):
        return [_refuse(layout, issue, worker, tick, decision, "invalid current conversation identity", observed)]
    if ew.assignment_of(mapping) != observed or decision.get("assignment") != observed:
        return [_refuse(layout, issue, worker, tick, decision, "the decision belongs to an earlier assignment", observed)]
    allowed = {"idle", "finished", "error", "stuck", *(("running",) if decision.get("while_active") else ())}
    effect: dict[str, Any] | None = None
    posted = False
    try:
        if not _fresh_authority(layout, issue, mapping, fetch):
            raise ValueError("current source authority does not permit observation")
        with _session(layout, issue, worker, mapping, runner=runner, http=http) as (port, key, cid, execution, identity):
            if execution not in allowed or not _fresh_authority(layout, issue, mapping, fetch):
                raise ValueError("current work or source authority does not permit a directive")
            effect = _reserve(layout, issue, worker, decision, tick, observed)
            if effect is None:
                return []
            marker = str(effect["marker"])
            current = ew._load_state(layout)["issue_mappings"][str(issue)]
            since = current.get("coordination", {}).get("unchanged_since")
            aged = isinstance(since, (int, float)) and time.time() - since >= coord.STALL_SECONDS
            blocker_matches = True
            if decision["action"] == "repair_technical_dependency":
                blocker, gap = coord._read_declared_blocker(layout.checkout(worker))
                blocker_matches = not gap and blocker is not None and blocker.get("summary") == decision.get("declared_blocker")
            if (not _binding(current, effect, worker) or ew._checkout_mount_identity(layout, worker, current) != identity
                    or (decision["action"] == "change_approach" and not aged) or not blocker_matches
                    or not _fresh_authority(layout, issue, current, fetch)):
                raise ValueError("effect boundary changed")
            payload = {"role": "user", "content": [{"type": "text", "text": compose(decision, marker)}], "run": True}
            posted = True
            try:
                code, _ = http("POST", port, key, f"/conversations/{cid}/events", payload, 30.0)
            except Exception:  # noqa: BLE001 - do not interpret a lost reply as a missing effect
                code = 0
            # Persist the POST response before another network request can be interrupted. A saved
            # event may race this write, but cannot complete the reservation without this response.
            _update(layout, {"id": effect["id"], "issue": issue, "post_status": code},
                    next_action=("Run capacity was full; retain the run obligation and reconcile the event."
                                 if code == 429 else "Reconcile the POST and its event before another directive."))
            current = ew._load_state(layout)["issue_mappings"][str(issue)]
            if _binding(current, effect, worker) and _fresh_authority(layout, issue, current, fetch):
                event_id, status, timestamp = _observe(port, key, cid, marker, http, layout=layout, issue=issue, worker=worker)
            else:
                event_id = status = timestamp = None
    except Exception:  # noqa: BLE001 - nothing was sent unless the POST was attempted
        if posted:
            raise  # the reservation stays pending/unknown; it is never re-posted
        if effect is None:
            return [_refuse(layout, issue, worker, tick, decision, "current endpoint, conversation or authority is unavailable", observed)]
        updated = _update(layout, {"id": effect["id"], "issue": issue, "not_sent": True, "reason": "effect boundary changed"},
                          next_action="Reconcile current worker and source authority.")
        return [{"decision_id": decision["id"], "action": decision["action"], "outcome": updated.get("outcome"), "event_id": None}]
    result = {"id": effect["id"], "issue": issue, "execution_status": status, "event_id": event_id, "event_timestamp": timestamp}
    if event_id:
        nxt = (f"Directive event {event_id} observed. " + ("Run capacity was full; use the existing /run endpoint when appropriate. " if code == 429 else "Reconcile any unknown POST outcome and confirm the conversation continues. ")
               + "Delivery itself is not progress; require new checkout, test or PR evidence.")
    else:
        nxt = "The directive outcome is unknown. Reconcile its marker in the original conversation; do not resend or replace the writer. Other issues may continue."
    updated = _update(layout, result, next_action=nxt)
    return [{"decision_id": decision["id"], "action": decision["action"], "outcome": updated.get("outcome"), "event_id": event_id}]


def record_results(state: dict[str, Any], issue: int, tick: str, changed: list[str]) -> None:
    evidence = sorted(set(changed) & {"checkout", "tests", "validation", "pr"})
    if not evidence:
        return
    for record in state["dispatch_decisions"]:
        if (isinstance(record, dict) and record.get("kind") == EFFECT_KIND and record.get("issue") == issue
                and record.get("outcome") == "delivered" and not record.get("result") and record.get("tick") != tick):
            record["result"] = {"state": "evidence_changed", "tick": tick, "changed_parts": evidence}
