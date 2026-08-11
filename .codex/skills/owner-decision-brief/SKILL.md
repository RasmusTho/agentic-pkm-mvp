---
name: owner-decision-brief
description: "Yggdrasil profile for owner escalations: use the portable decision-quality skill, preserve contractual operator gates and repo authority, and render one plain-language owner decision without creating another decision or task authority."
---

# Owner Decision Brief

This is a thin Yggdrasil profile for the portable `decision-quality` skill. It applies whenever a
repository workflow is about to ask the owner for a decision: an `agent:needs-human` label, an
operator acknowledgment, an inline question, or an open question in an Issue or PR.

## Required method

Load and follow the complete `decision-quality` skill before researching, recommending, or drafting
the ask. Its seven-dimension diagnosis, weakest-link rule, decision ownership gate, decision-support
method, and post-decision activation handoff are the single authoritative decision method. This
profile adds repository constraints only; it must not copy, abbreviate, or redefine that method.

The dependency is registered in `.codex/skills/portable-skills.list` and provisioned through
`scripts/install_skills.sh` from the portable skill source root. Successful provisioning is a
precondition for environments that execute this profile.

If `decision-quality` is unavailable, do not reconstruct a local substitute or send a free-form
owner ask. Report the missing capability through the current workflow and keep only independently
safe, reversible work moving.

Apply the `decision-quality :: Yggdrasil profile` together with these repo authorities:

- `AGENTS.md :: Agency default` is canonical for whether a discretionary escalation may reach the
  owner.
- `AGENTS.md :: Communicating with the owner` is canonical for owner-facing language and the
  Problem -> Options -> Consequences shape.
- Current repo owner docs and live GitHub, Git, CI, dispatcher, or BuilderOps authority outrank
  screens, plans, generated projections, chat history, and agent memory.
- Keep observation, proposal, decision, command, and receipt distinct. This skill does not create a
  decision log, task store, lifecycle authority, or execution tracker.

## Contractual operator gates

Never use the decision ownership gate to remove an unconditional operator gate defined by another
skill or contract. Promotion acknowledgment, consent-class changes, and any prod-touching action
whose owning workflow requires explicit human acknowledgment still fire exactly as defined. Use
`decision-quality` to diagnose and prepare the ask, while this profile shapes its repository-safe
form.

For discretionary escalations, apply the canonical `AGENTS.md :: Agency default` gate during the
Decision Quality diagnosis. When no irreversible effect, external-facing consequence, material
authority ambiguity, or owner-reserved value choice remains, do not escalate. Take the authorized,
reversible action or route it through agent review, leave evidence in the existing authoritative
record, and report the decision afterwards.

## Contract-dominance preflight

Before creating an owner ask, adding `agent:needs-human`, or presenting options, apply the portable
method's contract-dominance preflight against live repository authority:

1. Read the current governing Issue body, its acceptance criteria and `Verify:` targets, the named
   owner-doc anchors, and any protected invariant or explicit operator gate that constrains the
   apparent choice.
2. Compare the contract with current Git and PR reality. Treat a missing implementation on current
   `main`, an integration or rebase conflict, source drift, and a recovery branch that cannot be
   transplanted mechanically as technical evidence, not as proof that product value is undecided.
3. Discard any proposed option that would weaken, retire, or supersede the established contract
   unless a current authority has explicitly reopened that value, mandate, or scope for owner
   decision. Agent uncertainty about why code moved is not such authority.
4. When the contract selects the outcome but the implementation path is uncertain, choose the
   smallest contract-compliant bounded integration or recovery, apply the required review and
   verification gates, and report the result afterwards. If that path cannot proceed, leave a
   `blocked_technical` receipt with the exact unblock condition; do not convert it to an owner ask.

Only an explicit choice that would change established product or operator value, owner mandate,
scope authority, or another human-reserved authority may pass this preflight. Contractual operator
gates remain unconditional as defined above.

Regression scenario: an Issue requires strict platform containment through technical acceptance
criteria and a protected fail-closed invariant; current `main` temporarily lacks the implementation,
and the preserved recovery cannot rebase mechanically. The correct route is bounded port/recovery,
current-head verification, and an after-the-fact receipt. Offering the owner “restore the contract,
retire it, or defer” is forbidden unless current authority explicitly reopened the containment value
or Issue scope.

## Local vault-binding preflight

When a missing local vault binding, mount, or path appears to be the blocker, first complete the
mandatory Decision Quality diagnosis. If the diagnosis identifies missing binding evidence as the
weakest material link, use this preflight as the focused next action before adding
`agent:needs-human` or asking the owner.

1. Inspect the deploy environment files selected for the target channel and identify the variables
   that supply the vault source and target. Use a non-emitting parser or check that returns only
   presence/path-class results; do not `cat`, source, echo, or otherwise print the file or its values.
2. Run the same non-emitting, structured check across every write-capable service and watcher binding
   for the target channel, not just the first failing service. It must exclude ambient/plain vault
   selectors and confirm that deploy environment and Compose wiring resolve to the same channel-owned
   source. Never run raw Compose config, doctor, startup, environment, or directory-listing commands
   during this preflight: those outputs can expose private paths, vault names, or secrets.
3. Check the configured source path and the standard local Obsidian locations, including
   `~/Library/Mobile Documents/iCloud~md~obsidian/Documents` and `~/Documents/Obsidian`, then the
   intended vault subdirectory. Test only the exact candidate path silently, without enumerating its
   contents. Use the result only as diagnostic evidence, never as a channel-binding selection.
4. Create or repair a bounded, reversible configuration Issue only when the non-emitting check
   independently proves a channel-owned canonical source and matching bindings for every
   write-capable service, or proves that the bounded repair will restore a single missing/divergent
   binding to that already-proven source. Generic iCloud/Obsidian discovery must never select or
   rewrite a dev/test/prod binding. If channel ownership or matching bindings remain unproven, retain
   only redacted boolean/path-class evidence and continue the Decision Quality workflow with that
   uncertainty explicit.

This preflight is inspection-only unless the governing Issue or source authority already permits the
bounded repair. It never authorizes a real-vault write, deployment, or disclosure of environment-file
contents. Issue, PR, BuilderOps, and maintenance receipts may contain only variable names and
redacted boolean/path-class results; never raw paths, vault names, environment values, DSNs, secrets,
or raw startup/Compose output.

## Owner-facing profile

When the diagnosis and ownership gate establish that the owner must decide, produce the proportionate
Decision Quality brief with these additional presentation constraints:

- Lead with the exact decision and why it belongs to the owner or which contractual gate requires it.
- Present one decision per brief and two or three genuine options, including deferral or the safe
  status quo when relevant.
- State each option's owner-visible consequence, then give one recommendation, confidence, material
  uncertainty, and the safe no-answer default.
- Keep the lead brief readable in under a minute. Link durable evidence instead of embedding paths,
  IDs, labels, internal codenames, or a reasoning trace.
- Use the owner's current language. Remove unexplained repository jargon and say what the owner will
  notice, gain, lose, pay, or risk.

Place the brief at the decision boundary: at the top of the chat or session summary, in the same
Issue comment that adds `agent:needs-human`, or in the PR body/top-level comment when the PR is
waiting on that decision. Never block unrelated reversible work while waiting.

After the decision, use the portable skill's activation handoff and route any longer-lived execution
to the existing domain or delivery workflow. Do not track it here.
