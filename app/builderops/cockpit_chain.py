"""Chain-derived states for the BuilderOps cockpit registry.

Implements BUILDEROPS_COCKPIT/CHAIN_DERIVED_STATES.md (BOPS-COCKPIT-04, #4452).

The delivered v1 banding mapped dispatcher *status words* to bands. The owner's
model is stronger: the five thread states are **positions in the process
chain**, and deficiency types are **predicates derived over that chain** rather
than an enumerated list a writer has to keep current.

Two ideas carry the whole module:

- **Chain position** — where a thread sits between backlog and delivery, derived
  from typed fields on the joined planes (dispatcher status, movement
  timestamps, lease expiry, live PR existence). Derivation is purely rule-based
  and deterministic: no LLM call, no fuzzy classification, no heuristic over
  free text. Two renders of the same planes produce byte-identical positions,
  which is what makes this surface CI-testable at all.
- **Flaw predicate** — a named, evidence-bearing statement that some link in the
  chain is missing its next link or its verification. A predicate declares the
  source planes it needs; when any of those is not fresh the predicate is *not
  evaluated* and says so in the flaws band header, rather than firing on absent
  evidence or being silently omitted.

Honesty rules this module enforces (mirrors ``cockpit_registry`` itself):

- Fail-closed positions: a thread whose position cannot be computed lands in the
  registry's explicit ``unclassified`` list, never guessed into a band.
- Forgotten is never age alone (decision Q1): the stall predicate is a
  conjunction of an age threshold **and** the absence of movement in the
  thread's own authority. Either conjunct alone leaves the thread in progress.
- Dual band, single identity: a thread holds exactly one *position* band and
  additionally appears in the flaws band when any predicate fires. The flaws
  band holds the same object, never a copy.
- Within-band ordering only (EXT-7): the risk meter is four discrete ticks, is
  never a displayed scalar, never reorders across bands, and never hides or
  demotes a card. Per ADR-0057 A1 a risk number is a signal to read, never a
  selection or ranking input.

Nothing here persists. Every value is recomputed from the joined planes on
every ``build_registry`` call (decision Q5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = [
    "CHAIN_POSITIONS",
    "FLAW_PREDICATES",
    "FORGOTTEN_STALL_DAYS",
    "OPEN_STATUSES",
    "POSITION_BAND",
    "RISK_MAX_TICKS",
    "RUNG_SOURCE",
    "SOURCE_STALE_AFTER_DAYS",
    "TERMINAL_STATUSES",
    "TRIED_TIER_REASON",
    "UNREAD_FLAW_PREDICATES",
    "ChainPosition",
    "ThreadContext",
    "amber_if_stale",
    "derive_position",
    "evaluate_flaws",
    "flaws_band_header",
    "order_within_band",
    "parse_timestamp",
    "risk_meter",
    "stale_source_names",
    "why_now",
]

# --------------------------------------------------------------------------
# Named thresholds
# --------------------------------------------------------------------------

# How long a thread's own authority must be silent before the *age* half of the
# forgotten conjunct is satisfied. Two weeks is the scale at which a builder
# thread stops being "in flight, quietly" and starts being genuinely dropped;
# below it the forgotten band would fill with work that is simply between
# sessions. Age alone never suffices — see :func:`derive_position`.
FORGOTTEN_STALL_DAYS = 14

# How old a source's own ``last_successful_read`` watermark may be before that
# source is *stale* (EXT-3's accepted third pill state, enacted here for the
# first time: #4450/#4451 shipped only fresh/empty/unavailable).
#
# Why seven days: four of the five sources (dispatcher-store, verification-runs,
# deploy-receipts, github-live) are read at render time, so their watermark is
# always "now" and this threshold can never fire for them in production — the
# github-live and verification-runs amber/withdrawn-count paths below are only
# reachable through a test fixture that hand-constructs an old watermark. The
# one source whose watermark is genuinely a content age is ``docs-frontmatter``,
# whose watermark is the newest mtime among the spec files it read. Seven days
# is the cadence at which this repo's spec directories actually move; a shorter
# window would paint the docs plane amber on every render (noise, not honesty),
# and a much longer one would let a genuinely abandoned spec tree keep claiming
# freshness. This is a named threshold, not a configuration surface.
SOURCE_STALE_AFTER_DAYS = 7

# EXT-7, as accepted: four ticks maximum, amber up to three, destructive at
# four. No scalar is ever displayed and the meter never selects.
RISK_MAX_TICKS = 4

# --------------------------------------------------------------------------
# Chain positions
# --------------------------------------------------------------------------

# The chain positions this module can derive. ``tried_by_owner`` is reserved:
# it is never derived, because the owner-acceptance receipt contract does not
# exist yet (INV-DG-7, owner-gated). It is listed so its emptiness is a named
# reservation rather than an omission.
CHAIN_POSITIONS: tuple[str, ...] = (
    "in_progress",
    "delivered",
    "tried_by_owner",
    "forgotten",
)

# Position -> band key. ``tried_by_owner`` maps to no band: it is a *tier*
# inside the done band (EXT-2 / decision Q3), rendered empty by contract.
POSITION_BAND: dict[str, str] = {
    "in_progress": "working",
    "delivered": "done",
    "forgotten": "forgotten",
}

TRIED_TIER_REASON = (
    "reserved: no owner-acceptance receipt contract exists yet (INV-DG-7 is"
    " owner-gated), so every delivered thread is delivered-never-tried by"
    " construction. Visible absence, not a red mark."
)

# Dispatcher statuses that mean the chain reached its end in the register.
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "done"})

# Dispatcher statuses that mean the thread still holds a position somewhere
# between backlog and merge. ``ready``/``backlog`` are included deliberately:
# the register's first question includes the queue, so an open unclaimed ready
# issue is *in progress*, not forgotten, until it meets the stall condition.
# ``blocked`` is included because a blocked thread still occupies a link in the
# chain — what is wrong with it is a flaw predicate, not a different position.
OPEN_STATUSES: frozenset[str] = frozenset(
    {"backlog", "ready", "claimed", "in_progress", "review", "blocked"}
)

# Which named source produced each rung's value. Used to turn a rung amber when
# the source behind it is stale — precisely, so a rung proven from a fresh
# source is never ambered by an unrelated stale one.
RUNG_SOURCE: dict[str, str | None] = {
    "intention": None,
    "capability": "docs-frontmatter",
    "epic": "docs-frontmatter",
    "slice": "dispatcher-store",
    "pr": None,  # resolved per rung: dispatcher-store or github-live
    "ci_sha": None,  # resolved per rung: verification-runs or github-live
    "receipt": "verification-runs",
    "tried": None,
}

# Deficiency predicates whose evidence lives on a plane this capability does
# not read at all. Named in the flaws band header so their absence is visible
# rather than implied — the same honesty idiom as ``UNREAD_PLANES``.
UNREAD_FLAW_PREDICATES: tuple[dict[str, str], ...] = (
    {
        "predicate": "unpushed_local_worktree",
        "plane": "git working trees",
        "reason": "the cockpit reads no git working tree; a thread whose only"
        " work is an uncommitted or unpushed local branch cannot be seen from"
        " here",
    },
    {
        "predicate": "unlanded_session_insight",
        "plane": "session records",
        "reason": "the cockpit reads no session record; insight that never"
        " left an agent session cannot be seen from here",
    },
    {
        "predicate": "closed_issue_without_owner_doc_receipt",
        "plane": "issue comments",
        "reason": "the cockpit does not fetch issue comments; the post-merge"
        " owner-doc writeback receipt is a comment, so its absence cannot be"
        " distinguished from an unread plane",
    },
)

_BRANCH_ISSUE_TOKEN = "(?:^|[^0-9]){number}(?:[^0-9]|$)"
_RED_CHECK_STATES: frozenset[str] = frozenset({"failure", "error"})


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp to an aware UTC datetime, or ``None``.

    Returning ``None`` for anything unparseable is load-bearing: a position
    whose stall test needs a timestamp it cannot read must fail closed into
    ``unclassified``, never silently assume "now" (which would read as
    "recently moved") or "epoch" (which would read as "forgotten").
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Position derivation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainPosition:
    """One thread's derived position, or an explicit refusal to derive one."""

    position: str | None
    evidence: dict[str, Any]
    unresolved_reason: str | None = None

    @property
    def band(self) -> str | None:
        if self.position is None:
            return None
        return POSITION_BAND.get(self.position)


def _last_movement(task: dict[str, Any]) -> tuple[datetime | None, str | None]:
    """The latest timestamp the dispatcher authority carries for this thread."""
    best: datetime | None = None
    best_text: str | None = None
    for field in ("updated_at", "last_heartbeat_at"):
        parsed = parse_timestamp(task.get(field))
        if parsed is None:
            continue
        if best is None or parsed > best:
            best = parsed
            best_text = str(task.get(field))
    return best, best_text


def derive_position(
    task: dict[str, Any],
    *,
    now: datetime,
    live_pull: Any | None = None,
) -> ChainPosition:
    """Derive one thread's chain position. Deterministic, fail-closed.

    Rule order:

    1. A terminal dispatcher status is *delivered* — the chain reached its end
       in the register. Whether that delivery carries a verification receipt is
       a **flaw predicate**, not a gate on the position: gating it would hide
       an unverified merge from the done band entirely, which is the opposite
       of what the flaws band exists to show.
    2. An open status is *in progress* unless the thread has stalled.
    3. Stalled = aged past the threshold **and** no movement in the thread's own
       authority (decision Q1). Both conjuncts are required; age alone would
       turn the forgotten band into a seniority list.
    4. Anything else is unresolvable and lands in ``unclassified`` — never
       guessed into a band.
    """
    status = str(task.get("status") or "")
    movement_at, movement_text = _last_movement(task)
    # Only a genuinely open PR counts as live movement — a closed/merged
    # pull sitting in the snapshot (a future reader may not filter by state
    # the way the default one does) must not permanently exempt a thread
    # from the forgotten-stall test.
    open_pull = (
        getattr(live_pull, "number", None)
        if getattr(live_pull, "state", None) == "open"
        else None
    )

    if status in TERMINAL_STATUSES:
        return ChainPosition(
            position="delivered",
            evidence={
                "dispatcher_status": status,
                "last_movement_at": movement_text,
            },
        )

    if status not in OPEN_STATUSES:
        return ChainPosition(
            position=None,
            evidence={"dispatcher_status": status},
            unresolved_reason=(
                f"status {status!r} maps to no chain position"
                " (neither terminal nor open)"
            ),
        )

    if open_pull is not None:
        # An open PR is live movement in the thread's own authority, which
        # settles the forgotten conjunct on its own: whatever the dispatcher
        # timestamps say, this thread is not stalled. Deciding here means a
        # thread with unreadable dispatcher timestamps is still resolvable
        # from the live plane — fail-closed, not fail-blind.
        return ChainPosition(
            position="in_progress",
            evidence={
                "dispatcher_status": status,
                "last_movement_at": movement_text,
                "stall_threshold_days": FORGOTTEN_STALL_DAYS,
                "aged_past_threshold": (
                    None
                    if movement_at is None
                    else now - movement_at >= timedelta(days=FORGOTTEN_STALL_DAYS)
                ),
                "open_authority_work": open_pull,
            },
        )

    if movement_at is None:
        # The stall conjunct cannot be evaluated at all, so neither
        # "in progress" nor "forgotten" can be claimed. Refuse.
        return ChainPosition(
            position=None,
            evidence={
                "dispatcher_status": status,
                "updated_at": task.get("updated_at"),
                "last_heartbeat_at": task.get("last_heartbeat_at"),
            },
            unresolved_reason=(
                "open thread carries no readable movement timestamp, so the"
                " forgotten stall test cannot be evaluated"
            ),
        )

    aged = now - movement_at >= timedelta(days=FORGOTTEN_STALL_DAYS)
    evidence = {
        "dispatcher_status": status,
        "last_movement_at": movement_text,
        "stall_threshold_days": FORGOTTEN_STALL_DAYS,
        "aged_past_threshold": aged,
        "open_authority_work": None,
    }

    # Both conjuncts, always. The open-PR branch above already returned for
    # every thread with live authority movement, so reaching here means there
    # is none — age is the only remaining question, and it is never enough on
    # its own to reach this line (decision Q1).
    if aged:
        return ChainPosition(position="forgotten", evidence=evidence)
    return ChainPosition(position="in_progress", evidence=evidence)


# --------------------------------------------------------------------------
# Flaw predicates
# --------------------------------------------------------------------------


@dataclass
class ThreadContext:
    """Everything one flaw predicate may read about one thread.

    Deliberately a plain value object over already-fetched snapshots: no
    predicate performs I/O, so no predicate can fail a read or raise past
    ``build_registry``.
    """

    task: dict[str, Any]
    repo: str
    issue_number: int | None
    position: str | None
    pr_number: int | None
    live_pull: Any | None
    verification_run: dict[str, Any] | None
    github_snapshot: Any | None
    docs_snapshot: Any | None
    now: datetime

    @property
    def status(self) -> str:
        return str(self.task.get("status") or "")


def _flaw(name: str, text: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"predicate": name, "text": text, "evidence": evidence}


def _branch_names_issue(branch: str, issue_number: int) -> bool:
    """Does a branch name carry this issue number as a whole token?

    Digit boundaries on both sides so ``issue-445`` never matches issue 4452
    and ``issue-44520`` never matches 4452 either.
    """
    pattern = _BRANCH_ISSUE_TOKEN.format(number=issue_number)
    return re.search(pattern, branch) is not None


def _pushed_branch_without_pr(ctx: ThreadContext) -> dict[str, Any] | None:
    if ctx.github_snapshot is None or ctx.issue_number is None:
        return None
    open_head_refs = {
        pull.head_ref
        for pull in ctx.github_snapshot.pulls.values()
        if getattr(pull, "head_ref", None)
    }
    for branch in ctx.github_snapshot.branches:
        if branch in open_head_refs:
            continue
        if not _branch_names_issue(branch, ctx.issue_number):
            continue
        return _flaw(
            "pushed_branch_without_pr",
            f"branch {branch!r} is pushed with no open PR",
            {"branch": branch, "issue_number": ctx.issue_number},
        )
    return None


def _pr_ci_red_on_head_sha(ctx: ThreadContext) -> dict[str, Any] | None:
    if ctx.live_pull is None or ctx.github_snapshot is None:
        return None
    head_sha = str(getattr(ctx.live_pull, "head_sha", "") or "")
    if not head_sha:
        return None
    state = ctx.github_snapshot.check_state_for(head_sha)
    if state not in _RED_CHECK_STATES:
        return None
    return _flaw(
        "pr_ci_red_on_head_sha",
        f"PR #{ctx.live_pull.number} CI is {state} on head SHA {head_sha[:12]}",
        {
            "pr_number": ctx.live_pull.number,
            "head_sha": head_sha,
            "check_state": state,
        },
    )


def _pr_without_ci_on_head_sha(ctx: ThreadContext) -> dict[str, Any] | None:
    if ctx.live_pull is None or ctx.github_snapshot is None:
        return None
    head_sha = str(getattr(ctx.live_pull, "head_sha", "") or "")
    if not head_sha:
        return None
    if ctx.github_snapshot.check_state_for(head_sha) is not None:
        return None
    run = ctx.verification_run
    if run and run.get("verified_head_sha") == head_sha:
        return None
    return _flaw(
        "pr_without_ci_on_head_sha",
        f"PR #{ctx.live_pull.number} has no CI state on head SHA"
        f" {head_sha[:12]}",
        {"pr_number": ctx.live_pull.number, "head_sha": head_sha},
    )


def _delivered_without_verification_receipt(
    ctx: ThreadContext,
) -> dict[str, Any] | None:
    if ctx.position != "delivered":
        return None
    run = ctx.verification_run
    if run and run.get("terminal_receipt_json"):
        return None
    return _flaw(
        "delivered_without_verification_receipt",
        f"delivered ({ctx.status}) with no terminal verification receipt",
        {
            "issue_number": ctx.issue_number,
            "pr_number": ctx.pr_number,
            "dispatcher_status": ctx.status,
        },
    )


def _expired_lease(ctx: ThreadContext) -> dict[str, Any] | None:
    if ctx.position == "delivered":
        # A finished thread's leftover lease is bookkeeping, not a flaw.
        return None
    expires_at = parse_timestamp(ctx.task.get("lease_expires_at"))
    if expires_at is None or expires_at > ctx.now:
        return None
    holder = ctx.task.get("claimed_by")
    return _flaw(
        "expired_lease",
        f"lease held by {holder or 'an unnamed agent'} expired at"
        f" {ctx.task.get('lease_expires_at')}",
        {
            "lease_id": ctx.task.get("lease_id"),
            "holder": holder,
            "lease_expires_at": ctx.task.get("lease_expires_at"),
        },
    )


def _stale_epic_with_open_children(ctx: ThreadContext) -> dict[str, Any] | None:
    if (
        ctx.docs_snapshot is None
        or ctx.github_snapshot is None
        or ctx.issue_number is None
    ):
        return None
    spec_dir = next(
        (
            info
            for info in ctx.docs_snapshot.spec_dirs.values()
            if info.epic_issue == ctx.issue_number
        ),
        None,
    )
    if spec_dir is None:
        return None
    open_children = sorted(
        doc.github_issue
        for doc in ctx.docs_snapshot.task_docs
        if doc.spec_dir == spec_dir.name
        and doc.github_issue is not None
        and doc.github_issue in ctx.github_snapshot.issues
    )
    if not open_children:
        return None
    # An open live PR against the epic itself is the same "live movement"
    # signal derive_position already treats as settling the stall test —
    # a card must not carry stale_epic_with_open_children while its own
    # position rung says in_progress from that same open PR.
    if getattr(ctx.live_pull, "state", None) == "open":
        return None
    movement_at, movement_text = _last_movement(ctx.task)
    if movement_at is None:
        return None
    if ctx.now - movement_at < timedelta(days=FORGOTTEN_STALL_DAYS):
        return None
    return _flaw(
        "stale_epic_with_open_children",
        f"epic #{ctx.issue_number} has {len(open_children)} open children and"
        f" no movement since {movement_text}",
        {
            "epic_issue": ctx.issue_number,
            "spec_dir": spec_dir.name,
            "open_children": open_children,
            "last_movement_at": movement_text,
            "stall_threshold_days": FORGOTTEN_STALL_DAYS,
        },
    )


def _dispatcher_github_contradiction(ctx: ThreadContext) -> dict[str, Any] | None:
    if ctx.github_snapshot is None or ctx.issue_number is None:
        return None
    if ctx.status not in TERMINAL_STATUSES:
        return None
    if ctx.issue_number not in ctx.github_snapshot.issues:
        return None
    return _flaw(
        "dispatcher_github_contradiction",
        f"dispatcher says {ctx.status} but GitHub issue"
        f" #{ctx.issue_number} is still open",
        {
            "issue_number": ctx.issue_number,
            "dispatcher_status": ctx.status,
            "github_issue_state": "open",
        },
    )


def _blocked_without_next_link(ctx: ThreadContext) -> dict[str, Any] | None:
    reason = ctx.task.get("blocked_reason")
    if ctx.status != "blocked" or not reason:
        return None
    return _flaw(
        "blocked_without_next_link",
        f"blocked: {reason}",
        {"blocked_reason": str(reason), "dispatcher_status": ctx.status},
    )


# Ordered: the first predicate that fires supplies the card's ``why_now``, so
# the order is "most directly names the missing link" first. Order is fixed so
# two renders of the same planes produce the same phrasing.
FLAW_PREDICATES: tuple[dict[str, Any], ...] = (
    {
        "name": "blocked_without_next_link",
        "requires": ("dispatcher-store",),
        "fn": _blocked_without_next_link,
    },
    {
        "name": "dispatcher_github_contradiction",
        "requires": ("dispatcher-store", "github-live"),
        "fn": _dispatcher_github_contradiction,
    },
    {
        "name": "expired_lease",
        "requires": ("dispatcher-store",),
        "fn": _expired_lease,
    },
    {
        "name": "pr_ci_red_on_head_sha",
        "requires": ("github-live",),
        "fn": _pr_ci_red_on_head_sha,
    },
    {
        "name": "pr_without_ci_on_head_sha",
        "requires": ("github-live",),
        "fn": _pr_without_ci_on_head_sha,
    },
    {
        "name": "pushed_branch_without_pr",
        "requires": ("github-live",),
        "fn": _pushed_branch_without_pr,
    },
    {
        "name": "delivered_without_verification_receipt",
        "requires": ("dispatcher-store", "verification-runs"),
        "fn": _delivered_without_verification_receipt,
    },
    {
        "name": "stale_epic_with_open_children",
        "requires": ("docs-frontmatter", "github-live"),
        "fn": _stale_epic_with_open_children,
    },
)


def evaluable_predicates(source_state: dict[str, str]) -> tuple[list[str], list[dict]]:
    """Split the predicate set by whether its required planes are fresh.

    A predicate whose plane is unavailable, stale, or structurally empty is not
    evaluated *at all* — never fired on absent evidence, and never dropped
    silently: the second return value is what the flaws band header names.
    """
    evaluated: list[str] = []
    not_evaluated: list[dict[str, Any]] = []
    for predicate in FLAW_PREDICATES:
        missing = [
            name
            for name in predicate["requires"]
            if source_state.get(name) != "fresh"
        ]
        if missing:
            not_evaluated.append(
                {
                    "predicate": predicate["name"],
                    "requires": list(predicate["requires"]),
                    "reason": "required source(s) not fresh: "
                    + ", ".join(
                        f"{name} ({source_state.get(name, 'unavailable')})"
                        for name in missing
                    ),
                }
            )
        else:
            evaluated.append(predicate["name"])
    return evaluated, not_evaluated


def evaluate_flaws(
    ctx: ThreadContext, evaluated_names: list[str]
) -> list[dict[str, Any]]:
    """Run every evaluable predicate against one thread, in fixed order.

    Predicates are pure functions over already-fetched snapshots. They are
    wrapped defensively anyway: a predicate that hits an unexpected shape must
    degrade to "did not fire" rather than crash the whole registry build — the
    same broad-except-degrades boundary every source read in this capability
    uses.
    """
    allowed = set(evaluated_names)
    flaws: list[dict[str, Any]] = []
    for predicate in FLAW_PREDICATES:
        if predicate["name"] not in allowed:
            continue
        try:
            result = predicate["fn"](ctx)
        except Exception:  # noqa: BLE001 - a predicate never crashes the build
            continue
        if result is not None:
            flaws.append(result)
    return flaws


def flaws_band_header(
    evaluated: list[str], not_evaluated: list[dict[str, Any]]
) -> dict[str, Any]:
    """The flaws band's own header: what was checked, what was not, and why."""
    return {
        "evaluated": evaluated,
        "not_evaluated": not_evaluated,
        "unread": [dict(entry) for entry in UNREAD_FLAW_PREDICATES],
        "rendered_elsewhere": [
            {
                "predicate": "delivered_never_tried",
                "surface": "done band tried tier",
                "reason": "delivered-never-tried is visible as the empty tried"
                " tier, not as a red mark (EXT-2 / decision Q3; the #4438"
                " delivered posture stays)",
            }
        ],
    }


# --------------------------------------------------------------------------
# Within-band ordering (EXT-7) — never cross-band, never hides
# --------------------------------------------------------------------------


def risk_meter(flaws: list[dict[str, Any]]) -> dict[str, Any]:
    """A four-tick reading signal, capped. Never a displayed scalar.

    Per ADR-0057 A1 this is a signal to read, never a selection input: it
    orders cards inside one band and does nothing else. Nothing in this module
    filters, hides, or demotes a card by ticks.
    """
    ticks = min(len(flaws), RISK_MAX_TICKS)
    if ticks == 0:
        tone = None
    elif ticks >= RISK_MAX_TICKS:
        tone = "destructive"
    else:
        tone = "amber"
    return {"ticks": ticks, "max_ticks": RISK_MAX_TICKS, "tone": tone}


def order_within_band(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order one band's cards. Returns every input card, never fewer.

    Composed stable sorts give a total, deterministic order: risk ticks
    descending, then most-recently-moved first, then task id. The function is
    only ever handed the items of a single band, so it structurally cannot move
    a card between bands.
    """
    ordered = list(items)
    ordered.sort(key=lambda item: str(item.get("id") or ""))
    ordered.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    ordered.sort(
        key=lambda item: int((item.get("risk_meter") or {}).get("ticks") or 0),
        reverse=True,
    )
    return ordered


# --------------------------------------------------------------------------
# Stale sources
# --------------------------------------------------------------------------


def stale_source_names(
    reads: list[Any], *, now: datetime | None = None
) -> frozenset[str]:
    """Names of fresh-but-old sources, and flip their state to ``stale``.

    Only a source that claims ``fresh`` and carries a parseable watermark can
    become stale; ``empty``/``unavailable`` already carry their own honest
    meaning and are never rewritten. ``last_successful_read`` is left untouched
    — the pill must keep naming the instant it actually read.
    """
    moment = now or datetime.now(timezone.utc)
    cutoff = timedelta(days=SOURCE_STALE_AFTER_DAYS)
    stale: set[str] = set()
    for read in reads:
        if read.state != "fresh":
            continue
        watermark = parse_timestamp(read.last_successful_read)
        if watermark is None:
            continue
        if moment - watermark >= cutoff:
            read.state = "stale"
            stale.add(read.name)
    return frozenset(stale)


def amber_if_stale(
    rung: dict[str, Any], source: str | None, stale_sources: frozenset[str]
) -> dict[str, Any]:
    """Downgrade a rung to amber when the source behind it went stale.

    Only ever a downgrade: ``absent`` stays ``absent`` (a stale source cannot
    conjure an object that does not exist), and a rung with no source behind it
    is untouched.
    """
    if source is None or source not in stale_sources:
        return rung
    if rung.get("class") not in ("proven", "derived"):
        return rung
    downgraded = dict(rung)
    downgraded["class"] = "amber"
    downgraded["stale_source"] = source
    return downgraded


# --------------------------------------------------------------------------
# why_now — the gate's own phrasing, never a score
# --------------------------------------------------------------------------


def why_now(
    task: dict[str, Any],
    position: ChainPosition,
    band: str,
    flaws: list[dict[str, Any]],
    evaluated_predicates: list[str] | None = None,
) -> str:
    """Which predicate fired, or which position the thread holds. Never a score.

    When a flaw fired, its own phrasing wins: the most useful thing to say
    about a thread with a missing link is the name of the missing link.
    """
    if flaws:
        return flaws[0]["text"]
    status = str(task.get("status") or "?")
    if band == "needs_you":
        if position.unresolved_reason:
            return f"{status} · labelled for a human · {position.unresolved_reason}"
        return f"{status} · labelled for a human"
    if position.position == "forgotten":
        last_movement = position.evidence.get("last_movement_at") or "unknown"
        return f"stalled without closure · no movement since {last_movement}"
    if position.position == "delivered":
        # A missing receipt would have fired delivered_without_verification_receipt
        # above; reaching here with that predicate genuinely unevaluated (its
        # source was unavailable) means we cannot claim a receipt exists —
        # claiming presence without evidence is the same overclaim class as
        # showing a zero over a dead source.
        if (
            evaluated_predicates is not None
            and "delivered_without_verification_receipt" not in evaluated_predicates
        ):
            return f"{status} · delivered, but the verification-runs source could not be read"
        return f"{status} · delivered with a terminal verification receipt"
    if task.get("claimed_by"):
        return f"{status} · claimed by {task['claimed_by']}"
    return status
