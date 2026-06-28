---
name: resume-work
description: "Resume interrupted dev/build work after a session breaks (quota, network, hung command, tool failure, context loss): reconstruct state from git first, keep a lightweight handoff, continue when the state is clear, and escalate only on destructive or contract/SoT ambiguity. Dev-time only, not a runtime/product feature."
---

# Resume Work

Dev-time recovery skill. It makes "continue", "resume", "pick up where we left off",
"fortsätt", and "återta" mean something concrete when a previous Codex/Claude/ChatGPT
session was cut off — by quota, network loss, a hung command, a tool failure, or lost
chat context.

This is a Builder System workflow about the *development flow*. It is not a product
capability: no app code, no AgentState, no runtime events, no vault/DB/store, no new
feature. The recovery substrate is the repository itself (git working tree, branch,
commits, stashes) plus one small scratch note — nothing that has to be running.

Bias: **continue, don't ceremony.** Re-entry is a fast read of repo state, not a recovery
ritual. Pull the owner in only when continuing could go the wrong way.

## When to use

- The user says continue / resume / pick up / fortsätt / återta / "what were we doing".
- A fresh session lands in this repo with a dirty tree or an unmerged feature branch and
  no clear in-conversation context.
- You are about to do something long or risky and want the next session to be able to
  pick up if you get cut off (see "Keep a lightweight handoff").

## Four situations to tell apart

1. **Normal continuation** — context and repo state are clear. Just keep working; no
   recovery steps, no handoff ceremony.
2. **Interrupted-work recovery** — context is thin but the repo shows in-progress work.
   Reconstruct from git (plus the handoff note), then continue.
3. **Unsafe / destructive ambiguity** — recovery would need a delete, overwrite, force
   action, reset, history rewrite, or anything hard to reverse, and the intent is
   unclear. Escalate.
4. **Contract / SoT-impacting ambiguity** — the in-progress work touches a contract,
   owner doc, schema, API, or other source of truth and the intended direction is
   unclear. Escalate.

Most resumes are situation 1 or 2 and need no human attention.

## First move: reconstruct state from the repo

Git is the source of truth for what was happening. Read it before asking anything — all
read-only:

```bash
# 1. Workspace state report — read-only and informational here: you are diagnosing, not
#    gating a publish, so tolerate a dirty tree and never let a non-zero exit hard-stop the
#    recipe. Surfaces dirty tree, in-progress git ops, branch/worktree drift, leases.
scripts/agent_workspace_preflight.sh --allow-dirty \
  --expected-branch "$(git branch --show-current)" \
  --expected-worktree "$(git rev-parse --show-toplevel)" || true

# 2. The diff and the recent trail
git status
git diff
git diff --staged
git log --oneline -12
git stash list
```

Then read the two context hints, if they exist:

- `.codex-tmp/HANDOFF.md` — intent, next step, decisions, last test result. A hint, not
  gospel; the diff outranks it if they disagree.
- The linked Issue/PR, only if the branch maps to one and the network is up
  (`gh pr view`, `gh issue view`). Never block recovery on network.

From that, classify into one of the four situations and act.

## Decide: continue or escalate

- **Continue on your own** when the state is clear (situation 1), or thin but safe to
  rebuild (situation 2): state the reconstruction in one line, then proceed. A
  reasonable, reversible reconstruction beats stalling on a question the repo can answer.
- **Escalate** only for situations 3 and 4, or a genuine wrong-direction risk. Keep it to
  one decision, framed Problem → Options → Consequences, and keep making safe progress in
  parallel where you can.

Do not stop before every write, and do not narrate the recovery. Lead with the chosen
action.

## Keep a lightweight handoff

So a quota or network cut never forces the next session to start over, keep one small note
while work is unfinished. Progressive and opportunistic — not a report after every step.

- One file: `.codex-tmp/HANDOFF.md` — disposable scratch in the dedicated Codex agent
  scratch dir. Never stage or commit it, and delete it once the work is finished or before
  you publish, so it never dirties the tree at closure. While work is unfinished it will
  show as untracked — that is expected. Update it in place; overwrite, don't grow a log.
- Update opportunistically: before a long or risky command, after a real decision, after a
  test run, when a step closes, or when you sense interruption risk. Skip it for trivial
  steps.
- Keep it tiny — blank fields are fine:

  ```
  # Handoff — <branch>
  Goal:       <what we're trying to achieve, one line>
  Issue/PR:   <#id or none>
  Now:        <step in progress>
  Next:       <next concrete step>
  Decisions:  <choices already made, so they aren't relitigated>
  Watch out:  <half-done edits, risks, anything destructive pending>
  Last test:  <command + pass/fail/last result>
  ```

- Do this without asking the user. It is cheap insurance, not a checkpoint system.
- Forward-compatible: when BuilderOps Vault is available, this is `AgentWorklog` material.
  The file is the always-on default; never block on the Vault.

## Stay in bounds

- No app code, no AgentState change, no runtime events, no store/DB/vault implementation,
  no new product feature, no heavy checkpoint machinery.
- The handoff note is dev-only scratch. If recovery is tempted to commit it, delete it
  instead — it is never repo or runtime truth.
- A real plan divergence found during recovery routes to `capture-learning`, not into this
  note.

## Output

- One line naming the situation (1–4) and the chosen action.
- Then either continue, or the single Problem → Options → Consequences decision when
  escalating.
