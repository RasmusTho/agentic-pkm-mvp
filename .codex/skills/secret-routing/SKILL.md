---
name: secret-routing
description: "Choose the existing Yggdrasil secret path and owner for a concrete credential. Use whenever a user or agent mentions secrets, passwords, API keys, tokens, Bitwarden/BWS, macOS Keychain, Jev credentials, VM credentials, secret rotation, Proxmox/OpenTofu credentials, or asks where a value belongs. This skill routes work; it does not create a new secret store or secret policy."
---

# Secret Routing

Use this as the single entry point when it is unclear which credential path applies. Choose by
consumer, operation, and execution host. Do not choose a store just because it is already unlocked or
available in the current session.

This skill only routes. The cited owner documents and skills own credential meaning, grants,
provisioning, handoff, rotation, and live qualification. Follow their current status and operator
gates; a target-state plan or a successful local read does not prove live qualification.

## First identify the request

Establish these facts from the request and repository state:

1. **Consumer:** Which process or service needs the credential?
2. **Operation:** Is the agent making one authenticated call, administering a secret store, starting
   a runtime consumer, or preparing infrastructure?
3. **Execution host and scope:** Where will the process run, and which channel/environment does it
   serve?
4. **Current evidence:** Is the path implemented, live-qualified, or only specified? Read the owner
   source below and the linked issue or receipt when live status matters.

If a fact is missing, inspect the named owner source before asking the user. Ask only when that source
contains a genuine owner decision or the requested effect is outside its authority.

## Route to the existing owner

| Request | Use this path | Boundary to preserve |
| --- | --- | --- |
| Make one bounded Jev judgment during local development on the current Mac | Load the existing jev-direct skill for the active agent. | This is the local TSO-06 development tool. It does not configure Product, Builder, MARR, VM, or production routes. |
| Use Jev from a Product or Builder runtime consumer | `docs/TYPESAFE_SYSTEM_ONE/README.md :: Initial Consumers` and `:: Data and Credential Boundary`, plus the consumer's owner contract. | Product and Builder call through MARR under separate caller policy and credentials; only the MARR server resolves the provider key. Runtime routes remain subject to their host-binding and acceptance gates. |
| Read or provision a secret for a Mac-hosted Yggdrasil process | `docs/LOCAL_SECRET_PROVISIONING/README.md` and its declared consumer contract. | macOS Keychain is the current Mac-hosted source. Use the documented consumer binding and handoff; do not invent a second Keychain naming or lookup convention. |
| Read Linux channel secrets, administer BWS, install VM reader credentials, or deploy database secrets | `docs/CLOUD_SECRET_PROVISIONING/README.md` and live validation hub [#5667](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667). | Keep Linux BWS and Mac Keychain roles distinct. Separate repository implementation evidence from live account, token, permission, and VM qualification. BWS administration must satisfy the issue's current writer/fencing gate. |
| Operate an external helper credential such as a webhook or provider identity | `docs/HEIMDAL/EXTERNAL_SYSTEMS_CONTROL_PLANE.md :: Credential boundary`. | Heimdal owns helper lifecycle. Secret values stay in the execution host's approved secure store; the repository and Builder Vault hold references and scope, not values. Follow the document's current enactment status. |
| Use a Proxmox/OpenTofu provider credential or protect infrastructure state | The current Platform and Operations owner document and preparation issue [#5856](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5856), plus the current infrastructure implementation issue if one exists. | The preparation issue is not proof that a repository, provider token, backend, state object, or access path exists. Do not invent or provision one from the plan. Keep credentials out of Git and state outside Git under the selected, qualified backend and locking contract. |
| Any other credential | Locate its owner through `docs/DOCS_INDEX.md` and the consumer's current owner contract. | Do not reuse or copy a credential across consumers or stores unless the owner contract explicitly declares that exact shared identity and scope. If no owner or approved path exists, report that exact gap and stop before handling the value. |

## Handle the value safely

- Never ask the user to paste a secret into chat. Do not put secret values in command arguments or
  echo them in output, logs, screenshots, receipts, issues, pull requests, BuilderOps records, or Git.
- Use only the owner-approved lookup and consumer handoff. Do not improvise `security`, `bw`, `bws`,
  shell export, or provider commands when the owner contract supplies a governed path.
- Do not assume that one credential can serve another consumer, environment, provider, or operation.
  In particular, Jev-call access, BWS read access, and BWS write access are separate authorities.
- For a change to secret identity, scope, storage, rotation, or exposure, follow the owning issue and
  its approval/qualification gates before making a durable or external change.
- For infrastructure work, read the current repo and issue state first. A plan, an unlocked vault, or
  a local credential does not authorize `apply`, destroy, access expansion, or application deploy.

## Report the route clearly

For secret-routing work, tell the user in plain language:

1. which consumer and operation you identified;
2. which owner document, skill, and credential path apply;
3. what is verified as implemented or live versus specified or pending;
4. the next allowed action, including the exact gate if work must stop.

If one request concerns several credentials, list one route per credential. Do not compress distinct
credentials into a generic “Bitwarden secret” or “API key” label.

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation`.

After routing, execute the workflow that owns the requested work. Use `issue-to-code` for
issue-backed repository implementation, `docs-governance` for owner-document changes, the named
runtime/operator procedure for live secret operations, or the existing Jev direct-call skill for a
Jev judgment. Do not stop after naming a route when the existing request already authorizes the next
safe step. Preserve all explicit scope and live-operation gates from the owner contract.
