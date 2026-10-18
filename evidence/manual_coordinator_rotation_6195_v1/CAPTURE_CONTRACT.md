# Frozen manual role-rotation capture contract

This contract was frozen before native successor admission. It governs one explicit manual
experiment for terminal reconciliation of closed Issue #6195 and merged PR #6200, not an active
epic or whole-session replacement. The operator and incumbent experimental coordinator are
`/root`; the sole implementation/lifecycle writer remains `/root/implement_manual_rotation_6236`.
The intended history-free successor is `/root/manual_rotation_successor_6236`.

The actor boundary is manually observed, not runtime fencing. The operator is an agent acting
under the owner's express mandate; no human click or attestation is claimed. Root model/reasoning,
independent engine identity, tokens, cost, model-active time and human effort are unknown.

## Immutable anchors

All serialized refs resolve from the dedicated worktree:
`/Volumes/ColimaT7/workspace-root/runtime/tmp/manual-coordinator-rotation-20261018`.

- Packet: `context-pack.json`, 45,052 bytes,
  SHA256 `5e917cf2b3fc9fefc6be2fde37164539cc91c7fb32d63fcb723faead94635d7e`.
- Capture contract: `capture-contract.json`, 1,472 bytes,
  SHA256 `838c7168547a01872969adda61885792d97a1f03f90d3f02b7260354da19f931`.
- Complete closed producer/ingestion schemas: `ingestion-contract.json`, 26,589 bytes,
  SHA256 `f34d7a8255e40f7ab9012afa1b51dc2beb269de15ab948db102d69a43ecae755`.
- Actual evaluator source: `accepted/source-checkpoint.json`, 3,804 bytes,
  SHA256 `76d17b2be5dbd9d92001731e463b8541cde0fb036d5f781ff5f6e525987d08bc`.
- Accepted run-state readback: `accepted/run-state-readback.json`, 4,513 bytes,
  SHA256 `ca793eccac74c7f5c680c77f77d1b72d48a20b025a7abf6faa7dd8f6a7a33667`.

The capture JSON binds the exact packet, source, run-state and ingestion schemas. The verifier
requires a separate caller-selected capture binding; replacing the whole input graph cannot
self-authorize a changed packet, target or actor. Custody does not authenticate upstream truth.

## Native admission and initial observation

The parent independently verifies the anchors, records a named UTC pre-invocation tick, and
requests native `coordination` capability with `fork_turns=none` and task name
`manual_rotation_successor_6236`. The currently resolved request is `gpt-6-luna/low`, a planned
configuration until actual native acceptance. No other context, chat, implementation reasoning,
test source or prior experiment evidence is supplied. The successor receives only the exact
packet, its carried instructions, output locations and operational admission metadata.

After successful native admission the parent creates `operator/admission.json`, matching
`manual_rotation_native_admission` in the frozen schemas. It records actual requested/admitted
configuration, native receipt, actor, observed UTC tick and `fork_turns=none`; the initial context
binds only this packet. The parent sends the exact admission metadata before live reads. In the
initial response `agent.start_observed_at` equals that tick, and admitted fields plus engine
identity/source exactly equal the admission original. This finite run does not silently accept
a different admitted capability; a rejection/fallback needs explicit reconciliation.

The initial create-only output refs are:

- `evidence/manual_coordinator_rotation_6195_v1/successor/initial/live-read-github.json`
- `evidence/manual_coordinator_rotation_6195_v1/successor/initial/live-read-repository.json`
- `evidence/manual_coordinator_rotation_6195_v1/successor/initial/live-read-dispatcher.json`
- `evidence/manual_coordinator_rotation_6195_v1/successor/initial/agent-response.original.json`

The packet contains the complete closed response and live-read schemas, field-specific packet
pointers and exact `agent:manual_coordinator_rotation_6195` reporting provenance. Response target
has exactly five keys; envelope target has exactly three keys; packet-only `slice_id` is excluded.
Each original is created once with `apply_patch`, then hashed/counts exact UTF-8 bytes. No output
may be reformatted, corrected or replaced after creation. Drift and unknown fields remain visible.

Every command uses the dedicated worktree and these literal vectors, with no prose punctuation:

```json
["gh","issue","view","6195","--repo","RasmusTho/agentic-pkm-mvp","--json","number,url,state,labels,closedAt"]
["gh","pr","view","6200","--repo","RasmusTho/agentic-pkm-mvp","--json","number,url,state,mergedAt,isDraft,headRefOid,mergeCommit,statusCheckRollup"]
["git","ls-remote","--exit-code","origin","refs/heads/main"]
["/Users/rasmus/.pyenv/versions/3.12.7/bin/python3","-m","app.dispatcher","status","--json"]
```

Complete review-thread reads use `gh api graphql -f query=<query>`, selecting
`repository(owner:"RasmusTho",name:"agentic-pkm-mvp"){pullRequest(number:6200){reviewThreads(first:100,after:<cursor>){nodes{isResolved comments(first:1){nodes{url}}} pageInfo{hasNextPage endCursor}}}}`.
The exact initial query uses `after:null`, and every later cursor comes from the preceding live
page until `hasNextPage=false`. No comment bodies or implementation reasoning are read.

Use the existing scoped `sandbox_permissions=require_escalated` boundary for `gh`/`git` network
reads when needed; a default-sandbox failure is not proof that this allowed boundary is unavailable.
Retain actual failed command/actor/UTC/exit/permission mode and any invocation correction in notes.
No credential, ACL, DNS, network, provider or global configuration change is authorized.
Per-command temporary storage is `.codex-tmp/successor` in this external-volume worktree;
`PYTHONDONTWRITEBYTECODE=1` is permitted. No source or global `PYTHONPATH` workaround is needed.

The operator uses unchanged v2 `compare`, `telemetry` and `receipt` consumers against those exact
initial originals. Retain their create-only outputs in `successor/initial/` as `comparison.json`,
`execution.json`, `telemetry.json` and `probe-receipt.json`. The existing v2 execution log counts
only its own initial packet/response transfers and one actual native admission, with unknown usage.
Initial comparison is evidence for inspection, not an activation predicate or score.

## Separate manual decision and same-actor activation

The parent inspects the actual field comparison and independently chooses whether to proceed.
When proceeding, it creates `operator/manual-decision.json` and then `operator/quiescence.json`,
under the frozen `manual_rotation_operator_decision` and
`manual_rotation_incumbent_quiescence` schemas. Both bind exact predecessors and name `/root`.
The decision is explicit operator action, never a comparison-derived rule. Quiescence stops only
the incumbent experimental read-only coordinator role; the outer writer remains unchanged.

The operator next sends a bounded native follow-up to the SAME successor requesting acknowledgment
of those exact originals. The successor independently timestamps and creates
`successor/acknowledgment.original.json` under the carried closed schema. It binds the same packet,
manual decision and quiescence and confirms the writer's authority is unchanged. This is not yet
activation. The parent reads/hash-checks that original and then separately creates
`operator/activation.json`, naming the exact acknowledgment and decision. Decision, quiescence,
acknowledgment and activation have strictly ordered UTC times.

Only then does the parent send a second bounded native follow-up to that SAME successor: explicit
manual activation for one actual read-only terminal continuation. No new native successor is
started and no writer/dispatcher/worktree authority is transferred. The new continuation starts
strictly after activation; pre-activation plans or earlier shadow responses cannot substitute.

## Actual post-activation continuation

The successor independently repeats the allowed live reads and complete review pagination. New
envelopes in `successor/continuation/` use the same v2 read contract, with timestamps between the
continuation's start and completion, strictly after activation. They cannot alias initial or
source evidence. Retain returned Issue/PR inputs once at `live-issue-6195.json` and
`live-pr-6200.json`, matching exactly the objects in the new GitHub envelope.

Run exactly this existing no-effect planner and retain its original output once at
`successor/continuation/terminal-plan.original.json`:

```json
["/Users/rasmus/.pyenv/versions/3.12.7/bin/python3","-m","app.builderops","builderops","epic-run-state","lifecycle-plan","--transition","terminal","--issue-file","evidence/manual_coordinator_rotation_6195_v1/successor/continuation/live-issue-6195.json","--pr-file","evidence/manual_coordinator_rotation_6195_v1/successor/continuation/live-pr-6200.json","--repo","RasmusTho/agentic-pkm-mvp","--json"]
```

The successor creates `successor/continuation/continuation.original.json` under the exact carried
`manual_rotation_successor_continuation` schema. It binds activation, three new reads, exact planner
argv/inputs/output, observed terminal facts and one recommendation-only next action. Every effect
list is empty. Proposed optional Project repairs remain unexecuted. No claims, labels, comments,
leases, CI/review changes, delivery, dispatch, launch or Product-memory effects are authorized.

## Complete-scope event capture and replay

The parent records `operator/execution.json` using the frozen execution schema, with observed
UTC interval from its pre-admission request marker through original continuation readback. This
is recorder wall time, not model-active or human time. Successful start and packet handoff ticks
are recorder confirmation observations, not precise carrier instants.

Required distinct events bind exact originals: `agent_start`, `packet_handoff`,
`admission_metadata_handoff`, `response_handoff`, `acknowledgment_request_handoff`,
`acknowledgment_response_handoff`, `activation_handoff`, and `continuation_handoff`.
They represent one successful native start, two role-follow-up request handoffs and seven protocol
artifact transfers. Admission metadata delivery is counted separately from those two later role
follow-ups. Extra corrections/retries, if any, require separate strict correction originals and
are counted in their own category. Zero requires complete-scope recorder attestation. Writer and
later reviewer admissions, pre-capture implementation fixes and whole-delivery totals are excluded
from this experiment interval and must be reported separately; they are not silently zero.

The outer writer builds `input.json` from the exact bindings, then uses the serialized production
verifier in a separate process with the independently pinned capture digest. Replay reopens and
rederives the accepted source, unchanged v2 chain, phase links, refreshed live facts, actual terminal
plan and scoped measurements. No receipt can perform the manual action it records. Existing and
aliased output evidence remain unchanged on refusal. The frozen schemas and originals are never
edited to fit a later response.
