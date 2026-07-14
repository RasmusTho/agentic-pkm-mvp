---
name: owner-decision-brief
description: "Gate and format every escalation to the owner: first test whether an agent can take the decision itself (then act, do not ask); when the decision is genuinely the owner's, deliver a plain-language decision brief — one decision, options with consequences, a recommendation — with zero project jargon."
---

# Owner Decision Brief

Micro-skill, invoked at the moment any workflow is about to ask the owner for a decision —
an `agent:needs-human` label, an operator acknowledgment, an inline "should I...?" in chat,
an open question in an Issue or PR. It applies to the *ask itself*, wherever it surfaces.

Scope boundary, stated first because it is load-bearing: **contractual operator gates are
never re-tested away.** An ask that another skill defines as unconditional — the promotion
plan's operator acknowledgment, consent-class changes, any prod-touching step whose owning
skill requires an explicit human ack — skips Step 1 entirely and goes straight to Step 2:
the gate fires exactly as its skill defines, and this skill only shapes the *form* of that
ask. Step 1 filters discretionary escalations only.

The canonical policy lives in `AGENTS.md :: Agency default` (when to escalate at all) and
`AGENTS.md :: Communicating with the owner` (Problem → Options → Consequences). This skill
operationalizes those sections into a mandatory two-step check and a fixed output shape; it
does not restate or override them.

Two failure modes motivate this skill, and it must close both:

1. **Escalations that should not exist.** Decisions an agent can take as well as or better
   than the owner keep reaching him. Every unnecessary ask costs owner time and cognitive
   load (the dominant TCD term).
2. **Escalations in project jargon.** When a decision *is* the owner's, it arrives wrapped
   in internal terminology, so he must first decode the question before he can decide.

## Local vault-binding preflight

When the apparent blocker is a missing local vault binding, mount, or path, complete this preflight
before adding `agent:needs-human` or asking the owner. A missing binding is often a reparable
channel-bootstrap/configuration problem, not an owner decision.

1. Inspect the deploy environment files selected for the target channel and identify the variables
   that supply the vault source and target. Check presence and resolved path shape only; never copy
   secret values into chat, Issues, PRs, or receipts.
2. Inspect the effective Compose file and overlays for the target service, including the resolved
   mount/bind source and container target. Confirm that the deploy environment and Compose wiring
   agree.
3. Check the configured source path and the standard local Obsidian locations, including
   `~/Library/Mobile Documents/iCloud~md~obsidian/Documents` and `~/Documents/Obsidian`, then the
   intended vault subdirectory. Confirm that a candidate is readable, not merely present.
4. If these checks expose a source-authorized, reversible repair, create or repair the bounded Issue
   and continue delivery; do not ask the owner for confirmation. If the source is absent or several
   legitimate vaults remain and the owner must choose one, retain the command/path evidence in the
   durable record and proceed to Step 1.

This preflight is inspection-only unless the governing issue or source authority already permits the
resulting bounded repair. It does not authorize a real-vault write, a deployment, or disclosure of
environment-file contents.

## Step 1 — The filter: is this discretionary decision the owner's at all?

Before writing anything owner-facing, test the decision against the escalation gate of
`AGENTS.md :: Agency default`, which is canonical over this list. The owner decides only
when at least one of these holds:

- **Irreversible** — the action cannot be undone by git, a log entry, a rollback, or a
  re-run. (Reversible work proceeds without asking; `log + Git` is the safety net.)
- **External-facing** — the effect leaves the repo/trusted environment: publishing,
  spending money, contacting people, writing to third-party services, or any new
  prod/real-vault effect beyond what the governing contract and its gates already cover.
- **Genuinely the owner's by authority** — the authority is ambiguous (it is unclear whose
  call this is — unclear authority escalates, it does not default to acting) or explicitly
  owner-reserved: product direction, scope trade-offs, taste, personal data, priority
  rulings.

If none holds: **do not escalate.** Act (or route through agent-review), log the decision
where the work already leaves a trail (commit, PR body, Issue comment, BuilderOps record),
and report it afterwards as a done decision, not a question.

Disqualified reasons to escalate — these never justify an owner ask on their own:

- The work is hard, risky-feeling, or unfamiliar → escalate *capability* instead
  (`AGENTS.md :: Total Cost of Development`), not the human.
- You want confirmation that an in-scope, reversible plan is OK → it is; proceed.
- An Issue carries `agent:needs-human` or `blocked` → often defensive posture; resolve it
  per the `agent:needs-human` rule in `AGENTS.md :: Agency default` before deferring.
- Several small calls accumulated → resolve the agent-grade ones, then check whether any
  owner-grade decision actually remains.

## Step 2 — The brief: one decision, plain language

Everything that survives Step 1 — plus every contractual operator gate's ask — is
delivered in this shape, nothing else. This template is the **Problem → Options →
Consequences** shape from `AGENTS.md :: Communicating with the owner` made concrete:
"Decision" states the problem, each option carries its consequence, and a recommendation
plus a no-answer default are added so the owner can decide in one read. Render the brief
in the language the owner is currently using (Swedish when he writes Swedish); the field
labels below are structural, translate them with the content.

```
**Decision:** <one sentence: what is being decided>
**Why you:** <one sentence: irreversible / external / genuinely yours (authority or value call) / a contractual gate — why no agent can take this>
**Options:**
1. <option in plain words> — <what the owner gains/loses/risks, one sentence>
2. <option in plain words> — <same>
**Recommendation:** <one option + a one-sentence reason>
**If you don't answer:** <what happens or stays blocked, and any safe default>
```

Hard rules:

- **One decision per brief.** Never a menu of codenamed decisions (no `OD-1`/`OD-2`
  batches, no option codenames). If several owner-grade decisions genuinely exist, send
  separate briefs, each standalone — the owner must be able to answer one without loading
  the others.
- **2–3 options, no more.** Collapse the rest into the recommendation. If only one sane
  option exists and no contractual gate requires the ask, that is not a decision — go back
  to Step 1 and act. (A contractual gate with one sane option still gets its brief: options
  become "approve" / "hold".)
- **Every option carries its consequence,** phrased as what the owner will notice, gain,
  lose, pay, or risk — not the mechanism that produces it. "Old links stop working" beats
  "the redirect table is not backfilled".
- **Always include a recommendation.** Presenting naked options outsources the analysis
  the agent was supposed to do.
- **Under a minute to read.** No reasoning trace, no background essay. Durable audit
  detail (receipts, `Verify:` targets, analysis) lives in the Issue/PR/record — link it,
  do not inline it.

### The jargon gate

Before sending, re-read the brief as someone smart who has never seen this repository:

- Every internal term, codename, acronym, or component name must be either removed or
  explained in plain words in the same sentence ("Heimdal (the wearable-capture service)").
  Terms the owner himself introduced in the conversation are fine.
- Each consequence line must answer "so what happens to me?" — if it describes system
  internals instead, rewrite it.
- No paths, IDs, or labels as load-bearing content in the brief body; they belong in the
  linked record.

If the brief fails the gate, rewrite it before sending. A correct decision delivered in
jargon still costs the owner the decoding time this skill exists to eliminate.

## Placement

The brief replaces free-form escalation text wherever the ask lives:

- **Chat / session summary:** the brief is the ask; put it at the top, not buried in a
  status report.
- **Issue:** post the brief in the same comment that adds `agent:needs-human`. Never delay
  the label while drafting — if the label somehow lands first, the brief follows
  immediately; a lasting label without a brief is an incomplete escalation.
- **PR:** put the brief in the PR body or a top-level comment when a merge waits on the
  owner.

## Output format

1. Either the acted-on decision reported afterwards (Step 1 outcome: no escalation), or
   one brief per owner decision — surviving Step 1 or contractual — in the template above
2. A link to where the durable detail lives (Issue, PR, receipt) when one exists
3. Continue with the interrupted task — never block reversible work while waiting on an
   unrelated brief
