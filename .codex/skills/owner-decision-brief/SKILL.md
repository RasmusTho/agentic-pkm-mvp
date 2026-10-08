---
name: owner-decision-brief
description: "Yggdrasil profile for owner escalations: use the repo-local decision-quality skill, preserve contractual operator gates and repo authority, and render one plain-language owner decision without creating another decision or task authority."
---

# Owner Decision Brief

An owner escalation applies exactly one compatible `action:human-*` label and the shared
`blocker_action.v1` receipt (`_shared/BLOCKER_ACTION_CONTRACT.md`); it is not a generic blocker.

This is a thin Yggdrasil profile for the repo-local `decision-quality` skill. It applies whenever a
repository workflow has established a material owner decision or required operator acknowledgment,
including an `agent:needs-human` escalation. Routine agent-owned technical work uses
`decision-quality :: Routine agent-owned work` and resumes its caller without entering this profile.
An ordinary fact request or acceptance observation alone does not require an owner-decision brief.

## Required method

For a material owner decision or required operator acknowledgment, load the complete
`.codex/skills/decision-quality/SKILL.md`. It owns the decision method; this profile supplies repo
constraints and placement only. `scripts/install_skills.sh` provisions it. If unavailable, report
the missing capability and continue only independently safe work; do not invent an owner ask.

Apply `decision-quality :: Yggdrasil profile` and these authorities:

- `AGENTS.md :: Agency default` owns escalation scope; `AGENTS.md :: Communicating with the owner`
  owns language and Problem -> Options -> Consequences.
- For system facts, current owner docs and live GitHub/Git/CI/dispatcher/BuilderOps evidence outrank
  screens, projections, plans, and memory. This does not override explicit user instructions; resolve
  them through `decision-quality :: Current mandate and delegated choices`.
- Keep observation, proposal, decision, command, and receipt distinct; create no decision/task store.

## Contractual operator gates

Never use the decision ownership gate to remove an unconditional operator gate that remains
applicable after current-mandate resolution. Promotion acknowledgment, consent-class changes, and
prod actions retain their owning workflow's exact human-acknowledgment requirements. Full Decision
Quality prepares the ask; this profile supplies its repository-safe form.

When no irreversible effect, external-facing consequence, material authority ambiguity, or
owner-reserved value remains, resume the authorized reversible action/review. A technical failure
alone does not justify escalation. Keep evidence in the existing authoritative record.

## Contract-dominance preflight

Before creating an owner ask, adding `agent:needs-human`, or presenting options, apply the
repo-local method's contract-dominance preflight, then delegate terminal routing to the canonical classifier:

1. Resolve the current mandate through the required method, then select the live contract that actually governs the work. For a governing Issue, read its current
   body, acceptance criteria, `Verify:` targets, and named owner authority. For Issue-free work,
   select the complete Direct Repair block, workflow contract, owner document, protected invariant,
   or operator gate that applies. Do not manufacture an Issue or acceptance-criterion dependency
   for work governed by another authority surface.
   For an apparent Issue-imposed technical choice or owner-approval step, apply
   `.codex/skills/_shared/ISSUE_CONTRACT.md :: Outcome and implementation discretion` first. Establish its source
   and purpose; its wording alone is not proof that the owner reserved the decision. Execute
   `issue-maintenance-change-control :: Repair technical constraints and resume` when the established
   mandate permits the repair, then return to the caller without sending an owner ask.
2. Keep an established contract dominant over implementation or integration drift. A missing
   implementation, integration or rebase conflict, source drift, or failed recovery is technical
   evidence, not proof that the intended value is undecided. Remove options that would silently
   weaken or supersede the contract unless an evidence-backed proposal to change the established
   contract identifies an owner-reserved value, mandate, or scope that genuinely requires the owner
   to decide. Do not require the owner to have already approved the change; the evidence establishes
   that the decision belongs to the owner, not what the answer must be.
3. After filtering the apparent options, apply
   `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Escalation Classifier` and do not
   copy or redefine its route table here. Technical drift remains `blocked_technical` only when no
   authority is missing. Contradictory source authority remains `needs_owner` when it is unresolved
   after instruction-priority and current-mandate resolution, as does every other
   explicit `needs_owner` authority category in that classifier. Every non-`needs_owner` route and
   every protected-finding, follow-up, or deferred disposition remains governed by its owning
   contract and must not be reclassified here. Retry exhaustion or technical uncertainty alone does
   not change that authority boundary.

Contractual operator gates still fire exactly as their owning workflows define when independently
applicable. This preflight does not waive them. Use the required method's delegated-choice handling
to distinguish a user's revised instruction from an unsatisfied gate; do not repeatedly request an
already authorized technical decision. Machine identities and evidence belong in the prepared
record, not in a technical questionnaire for the owner. A required exact-field acknowledgment must
still be complete and attributable to its authorized decision maker; agent preparation is not that
acknowledgment, and an unknown rollback baseline must not become an asserted absence.

## Local vault-binding preflight

When a missing local vault binding, mount, or path appears to be the blocker, resolve permitted
technical evidence through this preflight before adding `agent:needs-human` or asking the owner.
Use the full Decision Quality method if a material owner choice or operator gate remains.

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

For an established owner choice, present one plain-language decision in the owner's current language:

- why it belongs to the owner or which gate requires it;
- two or three genuine options, including safe deferral/status quo where relevant, with consequences;
- recommendation/confidence, material uncertainty, and safe no-answer default.

Keep the lead readable in under a minute. Link durable evidence; omit internal jargon, machine
fields, and reasoning traces. Place it at the decision boundary: chat/session lead, the same Issue
comment as `agent:needs-human`, or the waiting PR's body/top-level comment. Continue unrelated
reversible work, then resume the same owning workflow after the answer; do not track execution here.

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation`. When evidence establishes an agent-owned
action, return to the owning workflow and execute it. When a real owner decision remains, present
the concrete brief and preserve that gate; after the answer, resume the same workflow with its
authority and evidence. Do not replace operator gates with inferred approval or turn ordinary
technical recovery into an owner question.
