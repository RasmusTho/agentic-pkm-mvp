"""Evidence-based progress judgement for the running epic coordinator (#6619).

One ``coordinate`` pass reads, per running OpenHands worker, the evidence that actually changes
when work advances (checkout content, test result, PR state, failure signature) and ignores what
changes without work (heartbeats, event/tool counts, agent narration). Equivalent evidence over
``stall_limit`` ticks climbs a bounded ladder (changed approach, one independent diagnosis,
handoff, then a recorded stop). A worker-declared blocker is repaired through its owning workflow
unless an Issue blocker-action receipt shows a decision only a non-builder party can take; that
authority stop is preserved while every other worker keeps being judged. Decisions land in the
existing ``dispatch_decisions`` / ``stop_conditions``; run-state stays coordination evidence
(GitHub Issues/PRs/CI win). Engine-level failures are classified by the existing
``epic_workspace.classify_failure``: only task failures climb the ladder; quota, context,
authentication and policy failures record their own pending obligation and hold that item.

Judging starts, stops and publishes nothing. With ``apply`` the pass additionally delivers the
``change_approach`` and ``repair_technical_dependency`` directives through
``epic_coordination_effects`` (the upstream conversation message API, reserved before the effect
and reconciled by event readback).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from app.builderops import blocker_actions, epic_run_state
from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_observation as github_read

SCHEMA = "epic_coordination.v1"
KIND = "epic_coordination"
STALL_LIMIT = 3
STALL_SECONDS = 60.0
LADDER = ("change_approach", "bounded_diagnosis", "handoff")
# An active conversation is diagnosed first; its changed-approach directive then supersedes the
# in-flight prompt (upstream run=True semantics) once it loops, or once one operation has produced
# no new event for ACTIVE_OPERATION_SECONDS (a legitimately long tool or backoff gets that long).
ACTIVE_LADDER = ("bounded_diagnosis", "change_approach", "handoff")
ACTIVE_OPERATION_SECONDS = 1800.0
BLOCKER_FILE = ".codex-tmp/worker-blocker.json"
BLOCKER_SCHEMA = "worker_blocker.v1"
REPAIR_WORKFLOW = "issue-maintenance-change-control :: Repair technical constraints and resume"
AUTHORITY_RECEIPT_ID = "blocker-action:{issue}"
LIFECYCLE_LABELS = frozenset({"agent:blocked", "agent:needs-human"})
HOLD_CLASSES = {  # engine-level failure class -> (decision kind, held state); none of these is a task failure
    "quota_exhausted": ("engine_quota", "held_quota_exhausted"),
    "context_exhausted": ("context_exhausted", "held_context_exhausted"),
    "authentication": ("authentication", "held_authentication"),
    "policy": ("policy", "held_policy"),
    "transient_network": ("transient_network", "held_transient_network"),
}
_MAX_BLOCKER_BYTES = 8192
_MAX_RECEIPT_CHARS = 4096
TEST_CACHE_FILE = ".pytest_cache/v/cache/lastfailed"
_MAX_TEST_CACHE_BYTES = 65536
_COMMENT_PAGES = 3
Fetch = github_read.Fetch
_TICK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$")
_PR_KEYS = ("number", "state", "draft", "head", "checks", "review")
_VALIDATION_KEYS = ("result", "command", "summary", "head")
_NEXT_ACTION = {
    "change_approach": "Deliver the changed-approach directive to the live conversation, then require new diff/test/PR evidence before another equivalent retry.",
    "bounded_diagnosis": "Read-only diagnosis executed without interrupting the worker (helper budget 0): conversation, event page, checkout and test evidence; its result is recorded on this decision and the ladder continues.",
    "handoff": "worker-stop with verified absence (unique work preserved), then conversation-start a successor on the same branch.",
    "progress_resumed": "Continue normal judgement; the ladder reset on new evidence.",
    "no_progress_exhausted": "Ladder spent without new evidence: redirect or reassign this item; peers continue.",
    "engine_quota": "Engine quota reached: takeover belongs to #6618 (verified worker-stop, then a successor). Preserve the checkout; no automatic engine or model switch; no task retry.",
    "context_exhausted": "Context exhausted: not an approach problem. Needs a successor conversation after a verified worker-stop (one-writer rule); preserve the checkout first.",
    "authentication": "Subscription authentication failed: re-establish the worker's login through the documented credential procedure (never print it). A directive cannot fix this; do not switch engines.",
    "policy": "Investigate the policy or billing error using the existing launch rules; do not infer credential contents or switch engines.",
    "transient_network": "Recheck the worker's network and conversation state with bounded backoff; retain the writer and do not repeat the task blindly.",
    "repair_technical_dependency": f"Repair the unsupported dependency through {REPAIR_WORKFLOW}, keep the current claim and writer, resume the worker.",
}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _pick(value: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: value[key] for key in keys if key in value}


# --------------------------------------------------------------------------- observation


def _read_bounded(checkout: Path, relative: str, limit: int) -> tuple[bytes | None, str | None]:
    """No-follow, size-bounded read of a worker-controlled file: (bytes, gap); absent is (None, None)."""

    parts = Path(relative).parts
    if not parts or any(part in (".", "..", "/") for part in parts):
        return None, "malformed"
    directory: int | None = None
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_NONBLOCK
        if not checkout.is_absolute():
            return None, "malformed"
        directory = os.open("/", flags)
        for part in (*checkout.parts[1:], *parts[:-1]):
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None, None
    except OSError:
        return None, "unavailable"
    finally:
        if directory is not None:
            os.close(directory)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None, "malformed"
        raw = os.read(fd, limit + 1)
    except OSError:
        return None, "unavailable"
    finally:
        os.close(fd)
    return (raw, None) if len(raw) <= limit else (None, "malformed")


def _read_declared_blocker(checkout: Path) -> tuple[dict[str, Any] | None, str | None]:
    """The worker's blocker declaration: (declaration, gap). It is a statement, never authority."""

    raw, gap = _read_bounded(checkout, BLOCKER_FILE, _MAX_BLOCKER_BYTES)
    if raw is None:
        return None, gap
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    summary = data.get("summary") if isinstance(data, dict) else None
    if not (isinstance(data, dict) and data.get("schema") == BLOCKER_SCHEMA and isinstance(summary, str) and summary.strip()):
        return None, "malformed"
    return {"summary": summary.strip()[:400], "digest": _digest(summary.strip())}, None


def _test_result_digest(checkout: Path) -> tuple[str | None, str | None]:
    """The worker's last failing test ids, as pytest itself recorded them in the checkout cache."""

    raw, gap = _read_bounded(checkout, TEST_CACHE_FILE, _MAX_TEST_CACHE_BYTES)
    if gap:
        return None, gap
    if raw is None:
        return "none", None
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "malformed"
    return (_digest(sorted(data)), None) if isinstance(data, dict) else (None, "malformed")


def _checkout_digest(layout: ew.Layout, worker: str, runner: ew.Runner) -> str | None:
    checkout = layout.checkout(worker)
    work = ew.inspect_checkout(layout, worker, runner=runner)
    if not work.get("present") or work.get("readable") is not True:
        return None
    # The worker's own blocker declaration is a statement, not work: it must not count as a change.
    paths = [p for p in work["uncommitted_paths"] if p != BLOCKER_FILE]
    count = work.get("uncommitted_count", 0) - (len(work["uncommitted_paths"]) - len(paths))
    if count > len(paths):
        return None  # do not silently ignore paths beyond the bounded status page
    hashes = []
    for path in paths:
        if path.startswith('"') or " -> " in path:
            return None
        raw, gap = _read_bounded(checkout, path, 1_048_576)
        if gap:
            return None
        hashes.append((path, hashlib.sha256(raw).hexdigest() if raw is not None else "absent"))
    return _digest({
        "head": work.get("head"), "unpublished": work.get("unpublished_commits"),
        "count": count, "content": hashes,
    })


def _failure_signature(layout: ew.Layout, worker: str, http: Callable[..., tuple[int, Any]], runner: ew.Runner) -> tuple[str | None, str | None, str | None, str | None, dict[str, Any]]:
    """Return the error signature, failure class, evidence gap, execution status and activity."""

    try:
        status = ew.conversation_status(layout, worker, http=http, runner=runner)
    except Exception:  # noqa: BLE001 - any transport/decode failure is a gap for this item only
        return None, None, "conversation_unreachable", None, {}
    if status.get("conversation") is None:
        return "none", None, None, None, {}
    if status.get("reachable") is not True:
        return None, None, "lifecycle_busy" if status.get("lifecycle_busy") else "conversation_unreachable", None, {}
    if status.get("events_reachable") is not True:
        return None, None, "event_stream_unavailable", None, {}
    # Activity is diagnosis input only; events and tool counts never count as progress.
    activity = {"latest_event": status.get("latest_event"), "event_kinds_tail": list(status.get("event_kinds") or [])[-5:]}
    errors = status.get("errors") or []
    if not errors:
        return "none", None, None, str(status.get("execution_status") or ""), activity
    normalized = re.sub(r"\s+", " ", re.sub(r"[0-9a-f]{8,}|\d+", "#", str(errors[-1]).lower())).strip()
    return (_digest([status.get("failure_class"), normalized])[:16], status.get("failure_class"), None,
            str(status.get("execution_status") or ""), activity)


def observe_worker(layout: ew.Layout, worker: str, issue: int, state: Mapping[str, Any], *, runner: ew.Runner,
                   http: Callable[..., tuple[int, Any]], read_conversation: bool = True) -> dict[str, Any]:
    """Collect the changing-evidence parts for one worker; unreadable parts stay ``None`` with a gap."""

    key = str(issue)
    parts: dict[str, str | None] = {}
    gaps: dict[str, str] = {}
    mapping = state["issue_mappings"][key]
    recorded_checkout = mapping.get("checkout")
    bound = isinstance(recorded_checkout, str) and ew._checkout_mount_identity(layout, worker, mapping) is not None
    parts["checkout"] = _checkout_digest(layout, worker, runner) if bound else None
    if parts["checkout"] is None:
        gaps["checkout"] = "unavailable" if bound else "workspace_binding_mismatch"
    signature, failure_class, gap, execution_status, activity = (_failure_signature(layout, worker, http, runner)
                                                                 if read_conversation else (None, None, "source_authority_unavailable", None, {}))
    parts["failure"] = signature
    if gap:
        gaps["failure"] = gap
    for name, source, keys in (
        ("validation", state.get("validation_status", {}).get(key), _VALIDATION_KEYS),
        ("pr", state["issue_mappings"][key].get("pr"), _PR_KEYS),
    ):
        if source is None:
            parts[name] = "none"
        elif isinstance(source, Mapping):
            parts[name] = _digest(_pick(source, keys))
        else:
            parts[name], gaps[name] = None, "malformed"
    parts["tests"], gap = _test_result_digest(layout.checkout(worker)) if bound else (None, "workspace_binding_mismatch")
    if gap:
        gaps["tests"] = gap
    blocker, blocker_gap = _read_declared_blocker(layout.checkout(worker)) if bound else (None, "workspace_binding_mismatch")
    if blocker_gap:
        gaps["blocker"] = blocker_gap
    return {"parts": parts, "gaps": gaps, "failure_class": failure_class, "blocker": blocker,
            "execution_status": execution_status, "activity": activity}


def read_issue_authority(issue: int, fetch: Fetch) -> dict[str, Any]:
    """Read the live Issue's lifecycle/action labels and latest receipt through GitHub REST.

    A matching label and receipt are necessary but a public comment alone can be forged. Only
    repository-owner comments are accepted here; other authors require trusted reconciliation.
    """

    reader = github_read._Reader(fetch, time.monotonic)
    data = reader.get(f"/repos/{github_read.REPOSITORY}/issues/{issue}")
    if not isinstance(data, dict) or data.get("number") != issue or not isinstance(data.get("labels"), list):
        raise github_read.ObservationError("Issue identity mismatch")
    labels = sorted(blocker_actions.label_names(data))
    record: dict[str, Any] = {"id": AUTHORITY_RECEIPT_ID.format(issue=issue), "issue": issue, "state": data.get("state"),
                              "labels": labels, "comments": [], "source": "github-rest"}
    if set(labels) & LIFECYCLE_LABELS:
        rows = reader.pages(f"/repos/{github_read.REPOSITORY}/issues/{issue}/comments", _COMMENT_PAGES)
        markers = [r for r in rows if isinstance(r, dict) and blocker_actions.is_blocker_action_receipt_marker(r)]
        if markers and markers[-1].get("author_association") == "OWNER":
            record["comments"] = [{"body": str(markers[-1].get("body"))[:_MAX_RECEIPT_CHARS]}]
    return record


def _live_pr_part(issue: int, branch: Any, rows: list[Any]) -> str:
    """Project a complete public open-PR inventory onto this Issue's recorded branch."""
    if not isinstance(branch, str) or not branch:
        raise github_read.ObservationError("worker branch missing")
    matches = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise github_read.ObservationError("PR inventory entry malformed")
        head = row.get("head")
        if not isinstance(head, Mapping):
            raise github_read.ObservationError("PR head missing")
        if head.get("ref") != branch:
            continue
        repo = head.get("repo")
        if not isinstance(repo, Mapping) or repo.get("full_name") != github_read.REPOSITORY:
            continue
        body = row.get("body")
        if not isinstance(body, str) or github_read._governing_number(body) != issue:
            raise github_read.ObservationError("PR governing Issue does not match branch")
        if (type(row.get("number")) is not int or row.get("state") != "open"
                or type(row.get("draft")) is not bool or not isinstance(head.get("sha"), str)):
            raise github_read.ObservationError("PR fields malformed")
        matches.append({"number": row["number"], "state": row["state"], "draft": row["draft"], "head": head["sha"]})
    if len(matches) > 1:
        raise github_read.ObservationError("multiple PRs for the worker branch")
    return _digest(matches[0]) if matches else "none"


def authority_for(state: Mapping[str, Any], issue: int) -> dict[str, Any]:
    """Classify the Issue's recorded authority readback: stop / technical / none / malformed."""

    wanted = AUTHORITY_RECEIPT_ID.format(issue=issue)
    record = next((r for r in state.get("compact_receipts", []) if isinstance(r, Mapping) and r.get("id") == wanted), None)
    if record is None:
        return {"kind": "none"}
    labels, comments = record.get("labels"), record.get("comments")
    if not (isinstance(labels, list) and isinstance(comments, list)):
        return {"kind": "malformed"}
    if str(record.get("state", "open")).lower() != "open":
        return {"kind": "malformed"}
    if not set(map(str, labels)) & LIFECYCLE_LABELS:
        return {"kind": "none"}  # no live blocker label: nothing but a worker's words
    _, receipt = blocker_actions.receipt_for_context(map(str, labels), comments, open_issue=True)
    if receipt is None:
        return {"kind": "malformed"}  # an incomplete authority write is never acted on
    # Only a decision/action that a non-builder party must take is an authority boundary.
    is_stop = receipt["action"] in blocker_actions.HUMAN_ACTIONS or receipt["owner"] != "builder"
    return {"kind": "stop" if is_stop else "technical", "receipt": {k: receipt[k] for k in ("action", "owner", "next_action", "unblocks_when")},
            "digest": _digest(receipt)}


# --------------------------------------------------------------------------- judgement


def _diagnosis(tick: str, obs: Mapping[str, Any], *, stall: int, inactive: bool, stepping: bool, operation_age: float,
               next_step: str | None) -> dict[str, Any]:
    """The executed bounded read-only diagnosis: what this pass actually read, and what it means."""

    status = str(obs.get("execution_status") or "")
    activity = obs.get("activity") or {}
    if inactive:
        finding = f"the conversation is {status} with unchanged diff/test/PR evidence."
    elif stepping:
        finding = "the agent keeps taking steps without new diff/test/PR evidence (a loop)."
    else:
        finding = (f"one operation has produced no new event for {int(operation_age)}s "
                   "(a long tool, a provider backoff or a hung call).")
    return {"tick": tick, "helper_budget": 0, "read": ["conversation", "event_page", "checkout", "test_cache", "blocker_file"],
            "execution_status": status, "latest_event": activity.get("latest_event"),
            "event_kinds_tail": activity.get("event_kinds_tail"), "unchanged_ticks": stall,
            "failure_class": obs.get("failure_class"), "finding": finding, "next_step": next_step}


def _writer(assignment: Mapping[str, Any]) -> dict[str, Any]:
    """The writer identity within an assignment tuple (a conversation status change is not a new writer)."""
    conversation = assignment.get("conversation")
    return {**{k: v for k, v in assignment.items() if k not in ("state", "conversation")},
            "conversation": conversation.get("id") if isinstance(conversation, Mapping) else conversation}


def judge_item(issue: int, worker: str, prior: Mapping[str, Any] | None, obs: Mapping[str, Any], authority: Mapping[str, Any], *, tick: str, limit: int,
               assignment: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Pure per-item judgement: new coordination record, decisions, stop conditions, result.

    ``assignment`` is the observed full assignment tuple. A record judged for another assignment is
    not inherited, and every decision is stamped (and its id tagged) with the observed tuple so it can
    only be applied to that same assignment.
    """

    if (assignment is not None and isinstance(prior, Mapping) and isinstance(prior.get("assignment"), Mapping)
            and _writer(prior["assignment"]) != _writer(assignment)):
        prior = None  # a successor writer starts its own ladder
    prior = dict(prior or {})
    tag = f":{_digest(dict(assignment))[:8]}" if assignment is not None else ""
    seen_ticks = list(prior.get("seen_ticks", []))
    if prior.get("last_tick") and prior["last_tick"] not in seen_ticks:
        seen_ticks.append(prior["last_tick"])
    replayed = tick in seen_ticks
    # Replays never advance, but current authority and evidence still fence an old decision.
    if replayed and authority.get("kind") != "stop":
        result = dict(prior.get("last_result") or {})
        result.update(issue=issue, worker=worker, replayed=True, evidence_gaps=dict(obs["gaps"]))
        if obs["gaps"] or authority.get("kind") in ("malformed", "unavailable"):
            result.update(state="unknown", action=None, next_action="Reconcile current authority and evidence before directing this worker.")
        elif tick != prior.get("last_tick"):
            result.update(action=None, next_action="Older pass already applied; continue with a new tick.")
        return {"coordination": prior, "decisions": [], "stops": [], "result": result}

    gaps = dict(obs["gaps"])
    if authority["kind"] == "malformed":
        gaps["authority"] = "malformed"
    previous = prior.get("parts")
    known = {name: value for name, value in obs["parts"].items() if value is not None}
    parts = {**(previous or {}), **known}
    if previous is None:
        verdict, stall = "baseline", 0
    elif any(name != "failure" and previous.get(name) not in (None, value) for name, value in known.items()):
        verdict, stall = "progressing", 0
    elif gaps:
        verdict, stall = "unknown", int(prior.get("stall", 0))
    else:
        verdict, stall = "stalled", int(prior.get("stall", 0)) + 1
    changed = sorted(name for name, value in known.items() if name != "failure" and previous and previous.get(name) not in (None, value))
    failure_class, transient = obs.get("failure_class"), int(prior.get("transient", 0))
    if failure_class == "transient_network" and transient < limit:
        verdict, stall, transient = "waiting_transient", int(prior.get("stall", 0)), transient + 1
    elif failure_class != "transient_network":
        transient = 0
    stage = int(prior.get("stage", 0)) if verdict in ("stalled", "unknown", "waiting_transient") else 0
    if "directive" in gaps and previous is not None:
        # Preserve the pre-attempt baseline so changes remain visible after event reconciliation.
        parts = dict(previous)
    fingerprint = _digest(parts)[:12]
    decisions: list[dict[str, Any]] = []
    stops: list[dict[str, Any]] = []
    action: str | None = None
    next_action: str | None = None
    inactive = str(obs.get("execution_status") or "").lower() in {"idle", "finished", "error", "stuck"}
    now = time.time()
    since = now if previous is None or verdict == "progressing" else prior.get("unchanged_since", now)
    aged = isinstance(since, (int, float)) and now - since >= STALL_SECONDS
    # Activity (newest event id) is compared across passes for diagnosis only, never as progress.
    head = ((obs.get("activity") or {}).get("latest_event") or {}).get("id")
    prior_head, activity_since = prior.get("activity_head"), prior.get("activity_since")
    stepping = head is not None and prior_head is not None and head != prior_head
    if head is not None and (head != prior_head or not isinstance(activity_since, (int, float))):
        prior_head, activity_since = head, now
    elif not isinstance(activity_since, (int, float)):
        activity_since = now
    operation_age = now - activity_since

    def decision(kind: str, key: str, **fields: Any) -> dict[str, Any]:
        record = {"id": f"coord:{issue}:{kind}:{key}{tag}", "kind": KIND, "schema": SCHEMA, "issue": issue, "worker": worker,
                  "action": kind, "first_tick": tick, "evidence_fingerprint": fingerprint,
                  "next_responsible_action": {"owner": "coordinator", "step": _NEXT_ACTION[kind], **fields.pop("next", {})}, **fields}
        if assignment is not None:
            record["assignment"] = dict(assignment)
        return record

    if "directive" in gaps:
        # Do not advance or issue a new action while an earlier effect is unresolved.
        verdict, stall, stage = "unknown_effect", int(prior.get("stall", 0)), int(prior.get("stage", 0))
    done = list(prior.get("done", LADDER[:int(prior.get("stage", 0))])) if stage else []
    if prior.get("stage", 0) and verdict == "progressing":
        decisions.append(decision("progress_resumed", fingerprint, cleared_stage=prior["stage"]))
    if authority["kind"] == "stop":
        receipt = authority["receipt"]
        verdict, action = "authority_stop", "authority_stop"
        next_action = receipt["next_action"]
        stops.append({"id": f"coord-stop:{issue}:authority_stop:{authority['digest'][:12]}", "kind": KIND, "schema": SCHEMA,
                      "issue": issue, "worker": worker, "stop": "authority_stop", "action": receipt["action"], "owner": receipt["owner"],
                      "next_action": receipt["next_action"], "unblocks_when": receipt["unblocks_when"], "first_tick": tick,
                      "declared_blocker": obs["blocker"]["summary"] if obs["blocker"] else None})
    else:
        blocker = obs["blocker"]
        if blocker and failure_class not in HOLD_CLASSES and not gaps and inactive:
            action, next_action = "repair_technical_dependency", _NEXT_ACTION["repair_technical_dependency"]
            decisions.append(decision(
                "repair_technical_dependency", blocker["digest"][:12], declared_blocker=blocker["summary"],
                source_authority=authority.get("receipt") if authority["kind"] == "technical" else None,
                finding="worker-declared dependency has no non-builder authority; technical choice belongs to the delegated agent",
                next={"workflow": REPAIR_WORKFLOW}))
        hold = HOLD_CLASSES.get(failure_class) if isinstance(failure_class, str) and verdict not in ("unknown_effect", "waiting_transient") else None
        if hold:
            kind, verdict = hold
            action, next_action = kind, _NEXT_ACTION[kind]
            decisions.append(decision(kind, fingerprint, failure_class=failure_class, unchanged_ticks=stall,
                                      pending_obligation=_NEXT_ACTION[kind]))
            if kind == "policy":
                stops.append({"id": f"coord-stop:{issue}:policy:{fingerprint}", "kind": KIND, "schema": SCHEMA, "issue": issue,
                              "worker": worker, "stop": "policy_error", "owner": "coordinator", "next_action": _NEXT_ACTION[kind],
                              "unblocks_when": "the policy error is investigated and the existing launch requirements are satisfied", "first_tick": tick})
        elif action is None and verdict == "stalled" and stall >= limit and not aged:
            verdict = "waiting_active_or_backoff"
            next_action = "Allow the provider backoff to elapse before any directive; reobserve this worker later."
        elif action is None and verdict == "stalled" and stall >= limit:
            ladder = LADDER if inactive else ACTIVE_LADDER
            step = next((kind for kind in ladder if kind not in done), None)
            diagnosed = prior.get("diagnosis") or {}
            if step == "change_approach" and not inactive and not (stepping or operation_age >= ACTIVE_OPERATION_SECONDS):
                verdict = "waiting_active_or_backoff"
                next_action = (f"Bounded diagnosis {diagnosed.get('tick')} found that {diagnosed.get('finding')} The in-flight "
                               f"operation may continue for at most {int(ACTIVE_OPERATION_SECONDS - operation_age)}s; then the "
                               "changed-approach directive supersedes it. A loop gets it on the next unchanged pass.")
            elif step is None:
                action = "no_progress_exhausted"
                stops.append({"id": f"coord-stop:{issue}:no_progress_exhausted:{fingerprint}{tag}", "kind": KIND, "schema": SCHEMA,
                              "issue": issue, "worker": worker, "stop": "no_progress_exhausted", "owner": "coordinator",
                              "next_action": _NEXT_ACTION[action], "unblocks_when": "new diff, test or PR evidence, or a recorded redirect",
                              "first_tick": tick})
                verdict = "stopped_no_progress"
                next_action = _NEXT_ACTION[action]
            else:
                action = step
                fields: dict[str, Any] = {"bounded_by": {"stall_limit": limit, "step": len(done) + 1, "of": len(ladder)},
                                          "unchanged_ticks": stall, "failure_class": obs.get("failure_class")}
                next_action = _NEXT_ACTION[step]
                if step == "bounded_diagnosis":
                    following = next((kind for kind in ladder if kind not in (*done, step)), None)
                    diagnosed = _diagnosis(tick, obs, stall=stall, inactive=inactive, stepping=stepping,
                                           operation_age=operation_age, next_step=following)
                    fields.update(diagnosis=diagnosed, finding=diagnosed["finding"])
                    next_action = (f"Bounded read-only diagnosis executed at {tick}: {diagnosed['finding']} "
                                   f"Next ladder step: {following}.")
                elif step == "change_approach" and not inactive:
                    fields["while_active"] = True  # upstream run=True supersedes the in-flight prompt
                decisions.append(decision(step, fingerprint, **fields))
                done.append(step)
                stage, stall = len(done), 0

    if verdict == "waiting_transient":
        next_action = _NEXT_ACTION["transient_network"]
    elif verdict == "unknown" and next_action is None:
        next_action = "Reconcile this worker's missing evidence before directing it; peers continue."
    elif verdict == "unknown_effect":
        next_action = "Reconcile the unknown directive by marker in its original conversation; do not resend. Peers continue."
    result = {"issue": issue, "worker": worker, "state": verdict, "stage": stage, "unchanged_ticks": stall,
              "action": action, "next_action": next_action, "evidence_gaps": gaps, "evidence_fingerprint": fingerprint,
              "failure_class": failure_class, "changed_parts": changed,
              "decision_id": next((d["id"] for d in decisions if d["action"] == action), None)}
    if not replayed:
        seen_ticks.append(tick)
    coordination = {"parts": parts, "stall": stall, "stage": stage, "done": done if stage else [], "transient": transient,
                    "last_tick": tick, "last_result": result, "seen_ticks": seen_ticks, "unchanged_since": since,
                    "activity_head": prior_head, "activity_since": activity_since,
                    "diagnosis": prior.get("diagnosis") if stage else None,
                    "blocker_digest": obs["blocker"]["digest"] if obs["blocker"] else None}
    for made in decisions:
        if made["action"] == "bounded_diagnosis":
            coordination["diagnosis"] = made["diagnosis"]
    if assignment is not None:
        coordination["assignment"] = dict(assignment)
    return {"coordination": coordination, "decisions": decisions, "stops": stops, "result": result}


# --------------------------------------------------------------------------- production entrypoint


def _upsert(records: list[Any], new: list[dict[str, Any]]) -> None:
    present = {r.get("id") for r in records if isinstance(r, Mapping)}
    records.extend(r for r in new if r["id"] not in present)


def _runtime_state(layout: ew.Layout, worker: str, mapping: Mapping[str, Any], runner: ew.Runner) -> str:
    return ew._worker_inspect(layout, worker, mapping, runner)


def _hold_runtime(layout: ew.Layout, issue: int, worker: str, mapping: Mapping[str, Any], runtime: str, tick: str,
                  observed: Mapping[str, Any]) -> dict[str, Any]:
    steps = {
        "oom": "Local container OOM: preserve the assigned checkout and home; inspect runtime evidence and qualify absence and ownership before any recovery or replacement.",
        "exited": "Worker container exited: preserve the assigned checkout and home; inspect the exit and qualify absence and ownership before recovery or replacement.",
        "stopped": "Worker is stopped with unfinished work: retain its owner and checkout and reconcile the next authorized action before any successor.",
        "unknown": "Worker container state or identity is unknown: retain its owner and checkout; reconcile the exact container before another effect.",
    }
    next_action = steps[runtime]
    result = {"issue": issue, "worker": worker, "state": f"held_runtime_{runtime}", "action": None,
              "failure_class": "local_runtime_oom" if runtime == "oom" else None, "next_action": next_action,
              "checkout": mapping.get("checkout"), "branch": mapping.get("branch"),
              "lifecycle_owner": mapping.get("lifecycle_owner") or mapping.get("owner"), "remaining_outcome": None}
    def updater(state: dict[str, Any]) -> dict[str, Any]:
        entry = state["issue_mappings"][str(issue)]
        if ew.assignment_of(entry) != observed:
            result.update(state="held_assignment_changed", next_action="Reconcile the changed assignment before contacting its worker.")
            return state  # the newer assignment's record is kept
        record_id = f"coord:{issue}:runtime:{runtime}:{mapping.get('container_id')}"
        existing = next((r for r in state["dispatch_decisions"] if isinstance(r, Mapping) and r.get("id") == record_id), None)
        remaining = existing.get("remaining_outcome") if existing else entry.get("next_action")
        result["remaining_outcome"] = remaining
        entry["next_action"] = next_action
        _upsert(state["dispatch_decisions"], [{"id": record_id,
                "kind": KIND, "schema": SCHEMA, "issue": issue, "worker": worker, "action": "runtime_hold",
                "failure_class": result["failure_class"], "first_tick": tick, "checkout": mapping.get("checkout"),
                "branch": mapping.get("branch"), "lifecycle_owner": result["lifecycle_owner"], "remaining_outcome": remaining,
                "next_responsible_action": {"owner": "coordinator", "step": next_action}}])
        return state
    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=updater,
                                         expected_epic_issue_number=layout.epic)
    return result


_CHANGED = "Reconcile the changed assignment before contacting its worker."


def _coordinate_item(layout: ew.Layout, key: str, mapping: Mapping[str, Any], *, readback: dict[str, Any] | None,
                     authority: Mapping[str, Any], pr_part: str | None, pr_gap: bool, tick: str, stall_limit: int,
                     runner: ew.Runner, http: Callable[..., tuple[int, Any]], fetch: Fetch | None, apply: bool) -> dict[str, Any]:
    """Judge (and with ``apply`` direct) one worker; every write is bound to the observed assignment."""

    from app.builderops import epic_coordination_effects as effects

    issue, worker = int(key), mapping["worker"]
    changed = {"issue": issue, "worker": worker, "state": "held_assignment_changed", "action": None, "next_action": _CHANGED}
    # The authority and PR reads were made for the pass-start assignment; it must still be current.
    current_mapping = ew._load_state(layout)["issue_mappings"].get(key, {})
    if not isinstance(current_mapping, Mapping) or not ew._same_assignment(mapping, current_mapping):
        return changed
    observed = ew.assignment_of(current_mapping)
    may_observe = authority.get("kind") in ("none", "technical") and not pr_gap
    runtime = _runtime_state(layout, worker, current_mapping, runner)
    runtime_hold: dict[str, Any] | None = None
    if runtime != "running":
        runtime_hold = _hold_runtime(layout, issue, worker, current_mapping, runtime, tick, observed)
        if authority.get("kind") != "stop" or runtime_hold["state"] == "held_assignment_changed":
            return runtime_hold
        may_observe = False
    reconcile_error: str | None = None
    try:
        reconciled = effects.reconcile_item(layout, issue, worker, http=http, runner=runner, fetch=fetch) if apply and may_observe else []
    except Exception as exc:  # noqa: BLE001 - retain this item's uncertainty, continue peers
        reconciled = []
        reconcile_error = type(exc).__name__
    state = ew._load_state(layout)
    if ew.assignment_of(state["issue_mappings"].get(key, {})) != observed:
        return changed
    obs: dict[str, Any]
    try:
        obs = (observe_worker(layout, worker, issue, state, runner=runner, http=http, read_conversation=may_observe)
               if runtime_hold is None else {"parts": {}, "gaps": {"runtime": runtime}, "failure_class": None, "blocker": None})
    except Exception:  # noqa: BLE001 - unreadable evidence is a gap for this item only
        obs = {"parts": {"checkout": None}, "gaps": {"observation": "failed"}, "failure_class": None, "blocker": None}
    if apply:
        obs["parts"]["pr"] = pr_part
        if pr_gap:
            obs["gaps"]["pr"] = "unavailable"
    if reconcile_error or effects._pending(state, issue):
        obs["gaps"]["directive"] = "unknown_effect"
    elif effects._cooling(state, issue):
        obs["gaps"]["directive_backoff"] = "awaiting_run_observation"
    if readback is None:
        obs["gaps"]["authority"] = "unavailable"
    outcome: dict[str, Any] = {}

    def updater(current: dict[str, Any]) -> dict[str, Any]:
        if readback is not None:
            kept = [r for r in current["compact_receipts"] if not (isinstance(r, Mapping) and r.get("id") == readback["id"])]
            current["compact_receipts"] = [*kept, readback]
        entry = dict(current["issue_mappings"][str(issue)])
        if ew.assignment_of(entry) != observed:
            outcome.update(changed)  # judged from an earlier assignment: nothing lands on the newer one
            return current
        authority = ({"kind": "unavailable"} if obs["gaps"].get("authority") == "unavailable"
                     else authority_for(current, issue) if readback is not None else {"kind": "none"})
        judged = judge_item(issue, worker, entry.get("coordination"), obs, authority, tick=tick, limit=stall_limit, assignment=observed)
        entry["coordination"] = judged["coordination"]
        if judged["result"]["next_action"]:
            entry["next_action"] = judged["result"]["next_action"]
        current["issue_mappings"][str(issue)] = entry
        _upsert(current["dispatch_decisions"], judged["decisions"])
        _upsert(current["stop_conditions"], judged["stops"])
        if judged["result"]["state"] == "progressing" and not judged["result"].get("replayed"):
            effects.record_results(current, issue, tick, judged["result"]["changed_parts"])
        outcome.update(judged["result"])
        return current

    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=updater, expected_epic_issue_number=layout.epic)
    item = dict(outcome)
    if item["state"] == "held_assignment_changed":
        return item
    if runtime_hold is not None:
        item.update(runtime_state=runtime_hold["state"], remaining_outcome=runtime_hold["remaining_outcome"])
    if apply:
        try:
            may_apply = not item.get("evidence_gaps") and item["state"] not in {"authority_stop", "unknown", "unknown_effect", "stopped_no_progress", "waiting_transient", "waiting_active_or_backoff",
                                              *(value[1] for value in HOLD_CLASSES.values())}
            item["effects"] = reconciled + (effects.apply_item(layout, issue, worker, tick, decision_id=item.get("decision_id"), observed=observed,
                                                               http=http, runner=runner, fetch=fetch)
                                              if may_apply and item.get("action") in effects.DIRECTIVE_ACTIONS else [])
            if reconcile_error:
                item["effects"].append({"outcome": "error", "error": reconcile_error})
            pending = effects._pending(ew._load_state(layout), issue)
            if pending:
                deferred = any(effect.get("post_status") == 429 for effect in pending)
                item["directive_state"] = "run_deferred" if deferred else "unknown_effect"
                if item["state"] != "authority_stop":
                    item["state"] = "run_deferred" if deferred else "unknown_effect"
                    item["next_action"] = ("Reconcile the conversation and use its existing /run endpoint when safe; do not resend the directive."
                                           if deferred else "Reconcile the unknown directive in its original conversation; do not resend. Peers continue.")
        except Exception as exc:  # noqa: BLE001 - one item's effect failure must not stop its peers
            item["effects"] = [{"outcome": "error", "error": type(exc).__name__}]
    return item


def coordinate(layout: ew.Layout, *, tick: str, stall_limit: int = STALL_LIMIT, runner: ew.Runner = subprocess.run,
               http: Callable[..., tuple[int, Any]] = ew._http, fetch: Fetch | None = None, apply: bool = False) -> dict[str, Any]:
    """One idempotent coordinator pass over every running OpenHands worker of the epic.

    ``fetch`` supplies read-only GitHub authority and, on applied passes, the open-PR inventory.
    Without it applicable authority is unknown. ``apply`` additionally delivers
    directives (see ``epic_coordination_effects``).
    """

    if not isinstance(tick, str) or not _TICK.match(tick):
        raise ew.LaunchRefused(f"invalid tick {tick!r}; supply a stable pass id so a replay cannot advance the ladder")
    if type(stall_limit) is not int or not 1 <= stall_limit <= 20:
        raise ew.LaunchRefused(f"invalid stall limit {stall_limit!r}")
    state = ew._load_state(layout)
    pr_rows: list[Any] | None = None
    if apply and fetch is not None:
        try:
            pr_rows = github_read._Reader(fetch, time.monotonic).pages(
                f"/repos/{github_read.REPOSITORY}/pulls?state=open", github_read.MAX_PAGES)
        except Exception:  # noqa: BLE001 - a partial inventory cannot establish absence
            pr_rows = None
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for key in sorted(state.get("issue_mappings", {}), key=int):
        mapping = state["issue_mappings"][key]
        if not isinstance(mapping, Mapping) or "worker" not in mapping:
            continue
        issue, worker = int(key), mapping["worker"]
        if mapping.get("runtime") != "openhands":
            skipped.append({"issue": issue, "worker": worker, "reason": f"not an admitted openhands worker ({mapping.get('state')})"})
            continue
        readback: dict[str, Any] | None = None
        if fetch is not None:
            try:
                readback = read_issue_authority(issue, fetch)
            except Exception:  # noqa: BLE001 - no authority claim from an unavailable source
                pass
        authority = authority_for({"compact_receipts": [readback]}, issue) if readback is not None else {"kind": "unavailable"}
        pr_part: str | None = None
        pr_gap = False
        if apply:
            try:
                if pr_rows is None:
                    raise github_read.ObservationError("PR inventory unavailable")
                pr_part = _live_pr_part(issue, mapping.get("branch"), pr_rows)
            except github_read.ObservationError:
                pr_gap = True
        with contextlib.ExitStack() as hold:
            try:
                # The item owns this worker's lifecycle for its bounded duration: no stop, start or
                # conversation operation can replace the endpoint between observation and effect.
                hold.enter_context(ew._worker_lifecycle_lock(layout, worker))
            except ew.LifecycleBusy:
                results.append({"issue": issue, "worker": worker, "state": "held_lifecycle_busy", "action": None,
                                "next_action": "Another lifecycle operation owns this worker; reobserve it on a later pass. Peers continue."})
                continue
            results.append(_coordinate_item(layout, key, mapping, readback=readback, authority=authority, pr_part=pr_part,
                                            pr_gap=pr_gap, tick=tick, stall_limit=stall_limit, runner=runner, http=http,
                                            fetch=fetch, apply=apply))
    held_states = {"authority_stop", "stopped_no_progress", "unknown_effect", "run_deferred", "held_assignment_changed", "held_lifecycle_busy", *(f"held_runtime_{r}" for r in ("oom", "exited", "stopped", "unknown")),
                   *(state_name for _, state_name in HOLD_CLASSES.values())}
    return {
        "schema": SCHEMA, "epic": layout.epic, "tick": tick, "stall_limit": stall_limit, "applied": apply, "items": results, "skipped": skipped,
        "independent_work_continues": [r["issue"] for r in results if r["state"] not in held_states],
        "held": [r["issue"] for r in results if r["state"] in held_states],
        "authority": "coordination evidence only; GitHub Issues/PRs/CI win",
    }
