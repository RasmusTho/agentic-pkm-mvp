---
name: owner-decision-brief
description: "Gate and format every escalation to the owner: first test whether an agent can take the decision itself (then act, do not ask); when the decision is genuinely the owner's, deliver a plain-language decision brief — one decision, options with consequences, a recommendation — with zero project jargon."
---

# Owner Decision Brief

Micro-skill, invoked at the moment any workflow is about to ask the owner for a decision —
an `agent:needs-human` label, an operator acknowledgment, an inline "should I...?" in chat,
an open question in an Issue or PR. It applies to the *ask itself*, wherever it surfaces.

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

## Step 1 — The filter: is this decision the owner's at all?

Before writing anything owner-facing, test the decision against the escalation gate. The
owner decides only when at least one of these holds:

- **Irreversible** — the action cannot be undone by git, a log entry, a rollback, or a
  re-run. (Reversible work proceeds without asking; `log + Git` is the safety net.)
- **External-facing** — the effect leaves the repo/trusted environment: publishing,
  spending money, contacting people, writing to third-party services, touching the real
  vault or prod outside an already-authorized flow.
- **A value or priority call only the owner holds** — product direction, scope trade-offs,
  taste, personal data, or explicitly owner-reserved rulings.

If none holds: **do not escalate.** Act (or route through agent-review), log the decision
where the work already leaves a trail (commit, PR body, Issue comment, BuilderOps record),
and report it afterwards as a done decision, not a question.

Disqualified reasons to escalate — these never justify an owner ask on their own:

- The work is hard, risky-feeling, or unfamiliar → escalate *capability* instead
  (`AGENTS.md :: Total Cost of Development`), not the human.
- You want confirmation that an in-scope, reversible plan is OK → it is; proceed.
- An Issue carries `agent:needs-human` or `blocked` → usually defensive posture; classify
  on evidence first and try to resolve it yourself before deferring.
- Several small calls accumulated → resolve the agent-grade ones, then check whether any
  owner-grade decision actually remains.

Existing operator gates (promotion acknowledgment, prod-touching steps, consent-class
changes) stay exactly as their skills define them. This skill never removes a gate; it
governs the *form* of the ask that the gate produces.

## Step 2 — The brief: one decision, plain language

Everything that survives Step 1 is delivered in this shape — nothing else. Render the brief
in the language the owner is currently using (Swedish when he writes Swedish); the field
labels below are structural, translate them with the content.

```
**Decision:** <one sentence: what is being decided>
**Why you:** <one sentence: irreversible / external / your value call — why no agent can take this>
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
  option exists, that is not a decision — go back to Step 1 and act.
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
- **Issue:** post the brief as the comment that accompanies `agent:needs-human`; the label
  without a brief is an incomplete escalation.
- **PR:** put the brief in the PR body or a top-level comment when a merge waits on the
  owner.

## Output format

1. Either the acted-on decision reported afterwards (Step 1 outcome: no escalation), or
   one brief per surviving owner decision in the template above
2. A link to where the durable detail lives (Issue, PR, receipt) when one exists
3. Continue with the interrupted task — never block reversible work while waiting on an
   unrelated brief
