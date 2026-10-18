---
name: secret-management
description: "Maintain Yggdrasil's cross-system credential architecture, access routes, and lifecycle without adding unnecessary stores, services, permissions, or operator work."
---

# Secret Management

Use for a cross-owner audit or change to credential architecture, agent/tool access, consumer
bindings, storage, rotation, revocation, or qualification. For one credential or one operation,
start with `.codex/skills/secret-routing/SKILL.md` and continue through the named owner procedure.

This skill coordinates existing authority. It does not make every store uniform, grant access,
perform live credential operations, or replace the owner documents for Product, Builder, Heimdal,
MARR, platform, or infrastructure consumers.

## Architecture rule

The credential owner contract binds a logical credential to its consumer, execution host, channel,
store, scope, binding, and lifecycle. An agent identity or task assignment does not itself grant
credential access. Agents use an authorized tool or consumer boundary; raw values remain in the
approved store and authorized process. A consumer gets only the declared credential and scope it
needs. Missing or ambiguous ownership or binding fails closed.

Keep existing owner stores and handoff interfaces. Do not introduce a global broker, second
registry, copied credential, broad fallback, or new host account just to make routing appear uniform.
Keep Product/Runtime, Builder, and infrastructure authority separate. State explicitly when a route
is implemented, live-qualified, pending, or only specified.

## Procedure

1. Read `docs/SECURITY.md :: System-wide credential access` and route through the existing
   `secret-routing` skill. Use the narrowest current owner documents; use `docs/DOCS_INDEX.md` as a
   grep-only index.
2. Bound the work by credential owner, consumers, channels, hosts, and authorized effects. Read
   current Issue, PR, owner receipt, or runtime evidence only when it can change the decision.
3. Build a value-free route matrix with one row per consumer and credential: owner, store, host and
   channel, scope, binding/tool, agent interaction boundary, lifecycle owner, and evidence state.
   Distinguish a declared route from actual access and from live qualification.
4. Inspect for leaks or excess authority across code/config, bootstrap, CI, logs, receipts, docs,
   Builder Vault, memory, and agent tools. Record only identifiers and metadata, never values.
5. Reuse the existing contract and stores. Where the checkout implements the metadata helper, use
   `scripts/secrets route <channel> --consumer <consumer>`. It reads the local host-secret contract
   only; it does not contact BWS, read credentials, grant access, or verify live state. Check the
   implementation status before recommending it. An unsupported consumer or command is a metadata
   gap, never permission to run a value-reading substitute. In particular, file-secret consumers
   require explicit support; do not infer it from environment-binding consumers.
6. Make the smallest change that closes the evidenced gap. Use existing deterministic helpers and
   skills. Do not add a paid dependency, service, account, subscription, recurring human action, or
   duplicate check unless the owner contract requires it and an authorized decision accepts the
   cost. Minimize model context and user interaction while preserving required evidence and gates.
7. If behavior, grants, credential identity, external access, or live state must change, use its
   governing Issue and owner procedure. This skill does not authorize external writes, secret
   provisioning, rotation, revocation, deployment, or permission changes.
8. Update the existing owner document and `docs/DOCS_INDEX.md` when its role, current truth, or
   canonical route changes. Add or update a bounded Issue for unresolved implementation work; do
   not claim a repository change proves live access.
9. Report the route matrix, changes, evidence state, minimum next action, and exact blocker, if any.
   Use one row per credential, consumer, physical host (or explicit missing host binding), and
   channel; separate administration, runtime use, and break-glass. Record unreviewed repositories,
   owners, hosts, tool sessions, and evidence surfaces. Never label the whole system complete while
   any requested scope remains unreviewed. Use the statuses implementerad, live-kvalificerad,
   väntande, and enbart specificerad; qualify live status only for the exact observed action,
   target, identity, and time. Dated receipts remain dated component evidence.
   Never include values or ask the user to paste them.

## Reusable update prompt

Use `.codex/skills/secret-management/UPDATE_PROMPT.md` for a system-wide refresh. Fill in the
requested scope and current authority; do not paste credentials or tokens into the prompt.

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation`. For docs-only policy work, continue
through `docs-governance` and `docs-authoring`. For executable behavior, use the governing Issue and
`issue-to-code`; for live provisioning or access, continue only through the credential owner's
authorized runtime procedure.
