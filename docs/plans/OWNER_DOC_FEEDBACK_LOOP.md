State: Plan. One agent that notices when shipped changes diverge from owner-doc claims, and acts on it. Human-first, not a compliance system.
Doc role: Plan
Authority: Defines the single addition to the delivery chain that closes the issue → owner-doc loop. Does not change classification rules in `AGENTS.md` or the shape of existing skills beyond one invocation hook.
Owner: Builder-agent workflow
Last reviewed: 2026-04-18

# Owner-Doc Feedback Loop

## The human problem

After an implementation PR merges, the repo's owner docs (`ARCHITECTURE.md`, `STATUS.md`, `ROADMAP.md`, `HUMAN-FLOWS.md`, and the other SoT docs) should still tell the truth about what the system does. Today they sometimes don't — merges land and owner docs lag, drift accumulates quietly, and the user has to notice.

The user has to stop being the one who notices.

## The one thing we add

One agent. One job.

After any implementation PR merges, invoke a `post-merge-owner-doc` agent that:

1. Reads the merge diff.
2. Reads the owner docs the diff could plausibly affect (picked by judgment from the diff's paths, the closed issue's Source Docs, and the docs registered in `DOCS_INDEX.md`).
3. Answers one question in plain prose: **does this merge change something an owner doc currently claims?**
4. Acts on the answer:
   - **Yes, and the change is clear** → opens a docs-only PR that updates the owner doc(s).
   - **Yes, but the right wording needs judgment** → opens one short follow-up issue that names the specific claim and the specific change.
   - **No** → leaves a one-line note on the closed issue: "post-merge owner-doc check: no owner-doc change implied."

That note is the receipt. If it's absent on a closed implementation issue, the loop didn't run.

## What this is not

- Not a CI gate. The gate is the agent running reliably; if it stops running, that's a normal operational problem, not a new compliance subsystem.
- Not a label taxonomy. No `class:*` labels, no attestation tokens, no PR-body grammar to parse.
- Not edits to four skills. One invocation hook, in one place.
- Not a human approval step. The user is never asked to classify, attest, or unblock.

## The single invocation hook

`verification-validation-feedback` already runs at merge time. It gains one step at the end: invoke the `post-merge-owner-doc` agent on the just-merged PR.

That is the entire workflow change.

## Why this works

- The signal is the diff, read with judgment. No proxy metadata to get wrong.
- The output is either a PR (which the user reviews as a normal docs PR) or a bounded issue (which surfaces the specific ambiguity). Both are artifacts the user already knows how to read.
- There is exactly one place the loop can fail silently: the agent didn't run. That's observable from the receipt note.
- Drift correction for historical merges is the same agent, invoked against a batch of recent closed issues. No separate nightly sweep, no separate audit skill — just the same agent with a different input set.

## What gets built

1. A new skill at `.codex/skills/post-merge-owner-doc/SKILL.md` describing the agent's job and judgment rules.
2. A one-paragraph addition to `.codex/skills/verification-validation-feedback/SKILL.md` that invokes it at the end of the merge step.
3. Nothing else.

## Acceptance

- After this lands, every merged implementation PR either leaves a docs-PR link or a "no owner-doc change implied" receipt on its closed issue.
- When run against the last 30 days of merges as a backfill, the agent produces docs PRs or follow-up issues for the known-drift cases (#394, #395, #470, #393's closed children) and leaves explicit receipts on the rest.
- No new labels, workflows, scripts, tokens, or gates are added.

## Related Documents

- `.codex/skills/verification-validation-feedback/SKILL.md`
- `.codex/skills/docs-authoring/SKILL.md` (the agent routes owner-doc PR authoring through this)
- `AGENTS.md`
