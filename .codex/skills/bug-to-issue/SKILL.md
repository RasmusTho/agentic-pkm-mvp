---
name: bug-to-issue
description: "Route confirmed bugs to a bounded GitHub Issue or the deterministic deferred Known Defects registry, with canonical evidence, labels, contracts, and promotion links."
---

# Bug To Issue

## Overview

Turn a discovered bug into either:

- a normal bounded GitHub `type:bug` Issue that is ready for implementation routing; or
- one uniquely identified entry in the rolling GitHub Known Defects registry when a confirmed P2
  review defect is intentionally deferred.

Default to the current repo unless the user specifies another one. This is defect intake, not the
cold-path maintenance lane. GitHub remains the canonical backlog surface; never maintain a parallel
hand-edited Markdown defect backlog.

## Classify before writing

Choose exactly one path:

1. **Confirmed and implementation-bound now, or P0/P1:** create/update a normal bounded bug Issue
   using the workflow below. High-impact defects are never parked in the deferred registry.
2. **Confirmed P2 review defect, intentionally deferred:** use the deterministic Known Defects
   registry intake. This avoids one expanded implementation Issue per observation while preserving
   durable evidence and promotion triggers.
3. **Maintainability suggestion:** leave it as review feedback or route it through the appropriate
   maintenance/learning workflow. It is not a defect and must not enter the registry.
4. **Unproven observation:** gather reproduction evidence or keep it in the source review. Do not
   label speculation as a known defect.

P3 is informational/non-defect under the canonical review-severity contract and follows path 3,
not registry intake.

The classification decision may require engineering judgment, but appending, deduplicating, and
looking up a confirmed registry entry do not require an LLM coordinator.

## Deferred Known Defects registry

The rolling registry is one open, locked Issue carrying `type:bug` and `state:known-defect`. It is a
container for schema-marked comments, not an implementation contract, carries no `agent:*` state,
and must never carry `agent:ready`. Locking limits comments to repository collaborators so marker
comments remain within the builder authority boundary. `state:known-defect` is defined centrally in
`.codex/skills/_shared/LABEL_TAXONOMY.md`.

Use the stdlib-only REST helper:

```bash
python3 .codex/skills/bug-to-issue/scripts/known_defects.py intake \
  --classification confirmed-defect \
  --severity P2 \
  --source-pr <PR> \
  --source-sha <FULL_40_CHARACTER_SHA> \
  --review-url <PR_OR_REVIEW_THREAD_URL> \
  --symptom "<reproducible symptom>" \
  --evidence "<concrete review or reproduction evidence>" \
  --impact "<who or what is affected>" \
  --workaround "<known workaround or 'none known'>" \
  --trigger "<explicit re-evaluation or promotion trigger>"
```

The helper:

- rejects maintainability and unproven classifications without GitHub mutation;
- sends P0/P1 defects back to the normal bug-Issue path;
- derives `KD-<12 uppercase hex>` deterministically from source identity and normalized symptom;
- accepts `--defect-key <stable-key>` when later source SHAs or evidence wording should deduplicate
  to the same defect;
- finds or creates and locks the single rolling registry Issue;
- rejects unlocked or mislabeled registries and parses only exact first-line markers with the
  expected schema shape;
- detects the exact defect marker across existing registries before appending;
- posts one compact JSON `known-defect-receipt.v1` with `created`, `duplicate`, `excluded`, or
  `promotion_required` status.

Every entry records:

- defect id;
- source PR, exact SHA, and PR/review link;
- reproducible symptom and concrete evidence;
- impact and P2 severity;
- workaround, including `none known` when truthful;
- an explicit re-evaluation/promotion trigger.

Lookup is deterministic and read-only:

```bash
python3 .codex/skills/bug-to-issue/scripts/known_defects.py lookup \
  --defect-id KD-<12_HEX>
```

If multiple open registry Issues are ever found, intake fails closed instead of guessing. Reconcile
the duplicate registry state before retrying; `--registry-issue <N>` can select the already-verified
single open registry but cannot override ambiguous registry authority.

Registry discovery unions the mutable `state:known-defect` selector with an exact-title GitHub Issue
identity search. Title-discovered Issue numbers are cached only as identities and reread live when
the selector query no longer returns them. The title search is refreshed monotonically at the final
pre-create boundary. Removing the selector label therefore becomes explicit, fail-closed registry
drift instead of hiding committed comments or permitting duplicate authority.

Registry creation is crash-convergent across the create/lock boundary. Intake may lock and reuse
exactly one structurally canonical open bootstrap Issue, then rereads the Issue and all comments
before appending. Every schema entry and promotion marker must come from a GitHub author association
of `OWNER`, `MEMBER`, or `COLLABORATOR`; untrusted or missing associations fail closed. This prevents
comments posted during the brief pre-lock bootstrap interval from gaining registry authority.

GitHub comment creation has no compare-and-swap operation. Sequential retries are idempotent; two
truly concurrent same-id intakes can still append identical comments after the same stale read.
Those comments represent one defect id, and lookup deterministically treats the earliest comment as
canonical. Registry reconciliation may remove later identical comments; it must never create a
second implementation Issue from them.

Intake performs its final strict single-open-registry check immediately before comment creation.
If that check observes closure, intake makes one bounded retry against a new open registry; body,
label, lock, or competing-registry drift fails closed before the write. New entry comments begin
with `phase=pending`, which is not visible defect authority but is a durable reservation. GitHub's
immutable comment creation time, with stable numeric comment id as the tie-breaker, orders all
trusted reservations for the defect across registry generations. The earliest eligible reservation
is canonical and later duplicates cannot preempt it. Finalization changes that exact reservation to
`phase=final`. An applied final marker is a committed idempotent result, while an unapplied pending
marker remains available for deterministic retry. An ambiguous comment-create response is
immediately reconciled from live Issue/comment inventories.

Intake starts a reservation only while exactly one canonical open registry exists. Once GitHub
accepts the pending comment, closure, structural drift, or competing-registry creation cannot
rewrite or relocate that accepted reservation; reconciliation finalizes the earliest reservation
and removes only later pending duplicates. Lookup can still read the canonical entry while later
registry drift independently blocks new intake. This avoids pretending that GitHub REST provides an
atomic transaction across Issue lifecycle and comment writes.

### Promotion

Promote an entry when it is selected for implementation or its impact, repetition, or failed
workaround satisfies the recorded trigger:

1. Create/update a normal bounded `type:bug` Issue using the canonical workflow below.
2. Give that Issue exactly one priority and one truthful normal agent state. A promoted Issue is not
   `state:known-defect`.
3. Link the registry entry only after the normal Issue has the canonical `bug: <short bounded
   outcome>` title, every concrete canonical section and SBS field, ACs, and `Verify:` targets:

```bash
python3 .codex/skills/bug-to-issue/scripts/known_defects.py promote \
  --defect-id KD-<12_HEX> \
  --issue <BUG_ISSUE_NUMBER>
```

The link operation is idempotent and emits a compact promotion receipt. Each pending promotion
comment is a trusted immutable validation snapshot: it binds the target number to a SHA-256 digest
of the target's validated title, body, lifecycle, type, priority, agent state, and allowed lane
authority. Immutable comment creation time plus stable comment id orders promotion reservations
across every registry generation. The earliest reservation is canonical; later same-target
duplicates or conflicting targets are non-authoritative and cannot preempt the link. Reconciliation
finalizes the canonical reservation and may remove later pending reservations. Ambiguous create or
PATCH responses are resolved from the full all-generation inventory, so retry converges without an
LLM or a hand-edited backlog.

The digest records the helper's validated snapshot immediately before reservation; it is not a
continuing lock on the implementation Issue. The promoted Issue owns subsequent body, claim, review,
and lifecycle changes. Same-target retries return the existing snapshot receipt without rereading
mutable target authority. This avoids false transactional claims across two GitHub Issues while
still proving that the snapshot came from a canonical bug contract, ACs, `Verify:` targets, and
truthful labels.
The promoted Issue owns implementation scope and closure; the registry entry remains durable source
evidence. If the entry's registry has since closed, the helper writes and discovers promotion
authority across the current open registry instead of reopening history or duplicating the entry.

## Normal bounded bug-Issue workflow

1. Resolve repo:
   - If repo specified, use it.
   - If not, infer from current git remote; if still unknown, ask for `owner/repo`.
2. Check for existing issue:
   - Search open issues for the same symptom/title. If a matching issue exists, comment with new evidence instead of creating a duplicate.
3. Create or update Issue body:
   - Always use the canonical contract sections from `.codex/skills/_shared/ISSUE_CONTRACT.md`.
   - Classify the defect as Product/Runtime System, Builder System, or boundary work using
     `docs/architecture/SBS_OPERATING_MODEL.md :: Builder System Boundary And Work Classification`.
     Product/runtime defects route through the Product owner docs and SBS impact procedure; builder
     workflow defects route through the Builder System boundary/artifact map; boundary defects name
     both sides.
   - Include exact repro steps and observed/expected results when available.
   - **Verify Source Anchors own the behavior — a grep/keyword hit is a *candidate*, not a confirmed anchor.** Before naming a `file::symbol` as the seam or candidate fix location, open it and confirm it is on the actual call path and owns the state in question. If you cannot confirm the precise seam, anchor the *symptom site* (the endpoint/render/log that misbehaves) and write "trace from here" rather than asserting a specific, possibly-wrong fix location. A keyword-matched-but-wrong anchor sends every downstream implementer — and any parallel sibling — re-tracing the same ground.
   - Do not create a micro-issue for routine repair, reconciliation, or bookkeeping churn; route those signals to the maintenance skills instead.
   - Acceptance Criteria must carry `Verify:` markers:
     - The primary behavioral AC ("bug no longer reproduces") points to a regression test the fix will add: `Verify: \`tests/<path>::test_<bug_name>\`` — the test should fail against current code and go green after the fix.
     - Any non-behavioral AC (doc clarifications, roadmap/status wording) points to its observable target.
     - If the bug is real, bounded, and reversible but hard to express as a failing test, that escalates the test-strategy *effort* (higher reasoning per `AGENTS.md :: Total Cost of Development`), not the agent state — keep `agent:ready` and let the implementing agent design the regression test. Reserve `agent:needs-human` only for a repro that genuinely cannot be exercised without a human decision or external access the agent lacks (per `AGENTS.md :: Agency default`).
4. Labels:
   - Always add `type:bug`.
   - Add one priority: `prio:high`, `prio:med`, or `prio:low` based on impact.
   - Add `agent:ready` only if the scope is bounded, testable, and unblocked.
   - Otherwise add `agent:needs-human` or `agent:blocked`.
   - Never carry `state:known-defect` onto the normal implementation Issue.
5. Optional Project projection:
   - Project add/status operations are cold-path repair only; do not require ProjectV2 for Issue creation or `agent:ready`.
6. Output receipt: issue number, labels set, and whether it was created or updated.

## Heuristics for `agent:ready`

Set `agent:ready` when all are true:
- Concrete scope and acceptance criteria are present.
- Every AC carries a resolvable `Verify:` target; the repro is expressible as a named failing test.
- Source anchors point to specific files or docs **and are verified to own the behavior** (read the symbol/section to confirm it is the real seam, not merely a keyword match).
- No unresolved decisions or missing contract inputs.
- The bug is a real defect, not a low-signal maintenance correction that should be batched into audit or retrospective work.

Force `agent:needs-human` per `AGENTS.md :: Agency default` — reserve it for irreversible, external-facing, or genuinely ambiguous-authority decisions; default to `agent:ready` for buildable, bounded, reversible defects rather than deferring defensively. Specifically when:
- a named human decision, tradeoff, missing input, or authority question is required before work can proceed
- It is a Core Runtime ↔ Agentic Lab boundary move without explicit direction and module paths.
- The change would alter operator-facing defaults without explicit posture and validation plan.

## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong),
route it through `capture-learning` — it owns the invocation timing and the "name an upstream
artifact or don't log" gate. Builder workflow learning remains Builder System material; do not
classify it as runtime/user memory or HKA/MEM authority unless a Product System owner path explicitly
promotes it.
