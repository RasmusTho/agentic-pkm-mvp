---
name: klart
description: "Assess a development-time builder session at closeout, choose one next-step recommendation, and route allowed follow-up through the owning workflow skill."
allowed-tools: Read, Grep, Glob, Skill, Bash(gh api:*), Bash(gh issue view:*), Bash(gh issue list:*), Bash(gh pr view:*), Bash(gh pr list:*), Bash(gh pr checks:*), Bash(git status:*), Bash(git log:*), Bash(git branch:*), Bash(git diff:*), Bash(python3 -m app.dispatcher status:*), Bash(python3 -m app.dispatcher show:*)
---

# Builder-session closeout

Use this skill before a development-time builder session or builder agent returns a terminal
response, hands off, goes idle, or otherwise stops. This skill is the central closeout gate required
by `AGENTS.md :: Builder-session closeout gate`.

This skill applies only to Builder System work governed by the repository's `AGENTS.md`. It does not
govern Product/Runtime agents or the `mimer-*` product-lane app-agent skills. It does not create a
new task store, ledger, registry, delivery authority, or finals-response interceptor.

## Contract

`klart` performs one fresh, read-only closeout assessment and selects exactly one pair:

```text
destination: continue_here | existing_successor | new_session_thread | end
secure_first: true | false
```

Interpret the pair as follows:

- `continue_here`, `false`: remaining work is small and depends on this session's context; keep working.
- `existing_successor`, `false`: a verified successor already carries the same task and authority; hand off there.
- `new_session_thread`, `false`: remaining work is bounded but no verified successor exists; provide a copyable start prompt. Creating, navigating to, or archiving a Codex task/thread still requires the user's explicit request.
- Any destination with `true`: secure the work first through the owning workflow, then perform one fresh closeout assessment.
- `end`, `false`: the goal is verified, no important work is unsaved or unfinished, and the session may close.

Only a final `destination: end` with `secure_first: false` permits an unqualified session close. A
closeout recommendation never means that an Issue, PR, or delivery is `Done`.

One active `klart` invocation owns the closeout attempt. Delegated workflow calls do not recursively
reopen the gate. After those calls complete, `klart` performs one fresh assessment and reports the
resulting state.

## Fresh status

Identify relevant GitHub Issues, PRs, branches, and dispatcher tasks from the conversation and local
checkout. Do not reuse earlier status as current proof. Read, as applicable:

- `git status --short` and `git branch --show-current`;
- `git diff` and `git log` for unfinished or uncommitted work;
- `gh pr view --json number,state,title,statusCheckRollup,url` for a safely identified current PR;
- `gh issue view <number> --json number,state,labels,updatedAt,title,url` for each safely identified Issue;
- `python3 -m app.dispatcher status --json` and, only when the repository and Issue number are certain,
  `python3 -m app.dispatcher show <task-id> --json`.

Derive a dispatcher task id only from a certain repository and Issue number, using
`github-<owner>--<repo>-issue-<number>`. Never select an arbitrary queue item. If no Issue can be
identified safely, do not search a broad queue; state that no Issue was bound. If a command fails,
report the exact status-verification error rather than guessing.

GitHub is authoritative for Issue and PR lifecycle. Dispatcher state is local coordination evidence.
If they disagree, report the conflict and do not treat the work as safely complete.

## Assessment

Reconstruct the requested goal and distinguish verified completion from remaining work. Check:

- important uncommitted or untracked work and unrelated dirty work;
- open or incomplete acceptance and `Verify:` targets;
- pending or failed CI, unresolved review, stale-head or merge-readiness evidence;
- Issue, PR, dispatcher, branch, and worktree lifecycle drift;
- decisions or constraints that exist only in the conversation;
- whether a Codex successor already exists and carries the same authority/task;
- whether the current context is still needed for the remaining work.

For issue-backed work, bind only a safely identified Issue/PR. An open verification, pending CI,
lifecycle drift, important unsaved delta, or missing authority forbids `end`. Merge and delivery
closure always route through `verification-and-closure`; lifecycle correction routes through
`issue-maintenance-change-control`.

For issue-free work, do not invent or derive an Issue. Assess the current branch/worktree, any
governance or docs PR, and the deliverable named by the request. Route unfinished work through
`resume-work` or `publish-pr` as appropriate. When a standalone analysis is itself the terminal
response's deliverable, that response is the delivery act; do not create a circular requirement
that it must be delivered before closeout. It may close only when the result is complete and the
`.codex/skills/README.md` BuilderOps analysis checkpoint is satisfied, or the material is genuinely
trivial to lose.

## Action gate

The recommendation is an action decision, not merely a suggestion. When the next step is bounded,
reversible, within the existing task, and does not require an owner decision, invoke the skill or
tool that owns it in the same response:

- `resume-work` for interrupted work that must be reconstructed safely;
- `issue-to-code` for remaining implementation under a certain Issue contract;
- `publish-pr` for local work ready for governed publication;
- `pr-integration` only for a concrete readiness, mergeability, CI-attachment, or review repair;
- `verification-and-closure` for current-head verification, merge, and truthful lifecycle closure;
- `issue-maintenance-change-control` for Issue/PR/label lifecycle drift.

Do not perform those mutations directly from this skill. `klart` owns only read-only assessment and
routing. The owning skill retains its authority, verification requirements, and stop conditions.
Do not ask a general "should I continue?" question. Stop only for an owning skill's contractual
operator approval, a genuine owner decision, an external or irreversible action, unclear authority,
missing permission, or a verified blocking failure. Route a genuine owner decision through
`owner-decision-brief`.

If securing is recommended, do not blindly stash, commit, or push. The owning skill determines
whether the correct action is a small `.codex-tmp/HANDOFF.md`, publication, recovery receipt, or a
truthful blocker handoff. Leave unrelated dirty work untouched.

## Handoff and terminal response

If the result is a successor or handoff, include a compact, copyable context containing the goal,
verified current state, exact branch/worktree or task identity, constraints, evidence, blocker, and
the first remaining action. A handoff is not delivery proof.

Never upgrade or invent `subagent_handoff_receipt.final_state`. Its allowed terminal values remain
`blocked | needs-human | handoff`; `done` is not a valid self-attested worker state. `klart` never
establishes Issue/PR delivery, merge, closure, or runtime capability.

Use the user's language and keep the terminal response concise. Include only the fields that affect
the decision:

- **Recommendation** — the selected `destination` and `secure_first` pair;
- **Thread handling** — only in Codex, and only what the current evidence permits;
- **Goal** — the reconstructed target;
- **Status verification** — GitHub, PR/CI, dispatcher, branch/worktree, and any errors/conflicts;
- **Complete** — what is actually verified;
- **Remaining** — what is not complete;
- **Action** — what the owning workflow actually did, or the exact blocking gate;
- **Next step** — one concrete action;
- **Value** — why that step matters;
- **Risk at close** — what remains risky if the session ends.

Do not claim `end` unless the final fresh assessment satisfies the contract above.
