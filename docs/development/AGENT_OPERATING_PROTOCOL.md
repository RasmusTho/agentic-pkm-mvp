State: Development reference for builder-agent pre-implementation classification and routing.
Doc role: Governance
Authority: Defines the task-class taxonomy and required pre-implementation checks for builder agents in this repository.

# Agent Operating Protocol

Use this protocol before producing implementation guidance or touching code in this repository. It does not replace `AGENTS.md` or any repo-local skill — it is the pre-implementation classification step that ensures agents orient correctly before acting.

Read `AGENTS.md` first. Then use `.codex/skills/README.md` to confirm the matching skill. Then apply this protocol.

## Task classes

Before any implementation guidance or code change, identify which class the task falls into:

| Class | Description | Primary lane | First-read docs |
| --- | --- | --- | --- |
| **Architecture** | Target-state design, contract definition, capability specification, ADR, system-level decisions | Docs-authoring or governance | `docs/ARCHITECTURE.md`, `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`, `docs/DESIGN_PRINCIPLES.md`, relevant capability spec |
| **Implementation** | Bounded code, schema, or test change from a GitHub slice issue | Issue-first implementation | `AGENTS.md`, `.codex/skills/issue-to-code/SKILL.md`, owner doc, source anchors |
| **Operations** | Runtime health, promotion, rollback, environment, release-channel | Release-channel / ops skills | `docs/ENVIRONMENTS.md`, `docs/RELEASE_CHANNELS/README.md`, `docs/OPERATIONS.md`, `docs/HEALTH.md` |
| **Governance** | Skills, `AGENTS.md`, templates, enforcement scripts, delivery-system artifacts | Governance lane | `AGENTS.md`, `docs/development/AGENT_INSTRUCTION_GOVERNANCE.md`, `.codex/skills/README.md` |
| **Cost-control / quality-control** | Context efficiency, bounded outputs, acceptance verifiability, stop conditions, doc writeback discipline | Docs-authoring or governance | `docs/development/DEV_WORKFLOW.md`, this doc |

## Required pre-implementation checks

Before producing implementation guidance or code, answer each field:

| Field | Question to answer | Stop condition |
| --- | --- | --- |
| **Repo skill** | Which repo-local skill under `.codex/skills/` matches this task? | If no skill matches and the task is non-trivial, prefer `agentic-pkm` as the default context skill. |
| **Owner docs** | Which owner doc governs the area being touched? (Use `docs/DOCS_INDEX.md` to locate it.) | Stop if the owner doc cannot be identified and the task is non-trivial. |
| **Authority boundary** | Is the governing doc a current-state SoT, a plan/target-state doc, or a historical doc? | Stop if the authority boundary is unclear — do not implement from a plan doc as if it were shipped runtime. |
| **Artifact class** | Which artifact class does the change produce or mutate? (See table below.) | Stop if the class is unclear and the change touches vault paths, DSNs, outbox state, or watcher execution. |
| **Environment / channel risk** | Which environment or release channel does this touch? (See table below.) | Stop if the task touches `prod`, `stable`, migrations, vault paths, DSNs, or watcher execution without reading `docs/RELEASE_CHANNELS/README.md` and `docs/ENVIRONMENTS.md` first. |
| **Verification target** | What is the concrete `Verify:` target for each acceptance criterion? | Stop if any behavioral AC lacks a named test and any non-behavioral AC lacks a named doc anchor, roadmap diff, or runtime receipt. |
| **Docs writeback** | If behavior, contracts, or architecture changes, which owner doc must be updated in the same change? | Stop if the change will produce shipped reality and no doc writeback is planned. |
| **Stop conditions** | See the stop conditions section below. | Resolve before proceeding. |

### Artifact classes

| Class | Examples | Notes |
| --- | --- | --- |
| Human Knowledge Artifact | Vault notes, plans, project docs, research memos | Human authority; do not overwrite without human-first write guard. |
| Agentic Memory Artifact | Memory candidates, promoted memory, recall records | Requires review + promotion governance before write authority. |
| Machine Mirror Artifact | Embeddings, index projections, retrieval chunks | Derived; must not become semantic authority. |
| Bridge / Assembly Artifact | Context bundles, composite panels | Governed composition; must record provenance. |
| Companion Metadata Note | `.meta.md` companions, frontmatter sidecar files | Linked to primary artifact; must not diverge from primary. |
| Runtime state | Outbox rows, dispatcher DB, heartbeats, watcher tick state | Prod/stable channel risk — treat with extra care. |
| Governance-bearing state | GitHub label mutations, Project status mutations, release pointer moves | Shared signal; must execute via explicit commands, not prose descriptions. |

### Environment and channel risk levels

| Level | Description |
| --- | --- |
| `none / docs-only` | No runtime change; docs-authoring or governance lane. |
| `dev` | Local development environment; changes to `app_dev` DB, local vault-test, or alpha path. |
| `test` | Test environment; local test bootstrap path, `app_test` DB, vault-test. |
| `prod` | Production runtime; `app` DB, real vault, watcher execution, panel actions. |
| `stable promotion` | Moving the `stable` pointer, applying irreversible migrations, restarting the prod process. |

## Behavioral rules

**Do not treat design/spec docs as shipped runtime.** A capability spec, plan doc, roadmap entry, or ADR describes intent or target state. Do not implement against it as if the described behavior already exists unless code, tests, and owner doc truth confirm the behavior is shipped.

**Do not propose or implement LLM-mediated mutation without governance, receipts, and human authority.** Any change that routes through a language model and results in vault writes, memory promotion, outbox emission, or watcher action must carry: explicit trust tier, write guard, provenance receipt, and human-first review path. Do not shortcut this for performance or convenience.

**Prefer bounded, issue-ready outputs over broad advice.** A concrete acceptance criterion with a `Verify:` target is worth more than three paragraphs of general guidance. Optimize for:
- small context packets
- owner-doc routing (point to the canonical doc, do not re-explain it)
- concrete `Verify:` targets
- explicit stop conditions
- verifiable delivery at merge time

## Stop conditions

Stop and route to Issue maintenance, human review, or docs repair when any of the following is true:

- **Authority boundary unclear**: the governing doc is ambiguous, a plan doc has not been cross-checked against current-state SoT truth, or the source anchor points to a stale or archived doc.
- **Prod/stable/migration/vault/DSN/watcher execution without ops docs**: the task touches these surfaces and `docs/RELEASE_CHANNELS/README.md`, `docs/ENVIRONMENTS.md`, or the relevant runbook has not been read.
- **Target-state/spec docs without code/test evidence**: the task depends on a capability spec, plan doc, or roadmap entry as if it were shipped runtime behavior, but no code path, passing test, or owner-doc acceptance record confirms the behavior is live.
- **Acceptance criteria lack `Verify:` targets**: any behavioral AC is missing a test pointer, or any non-behavioral AC is missing a doc anchor, roadmap diff, or runtime receipt. Route through `issue-maintenance-change-control` before coding.
- **Scope exceeds the governing Issue**: the task has expanded beyond the bounded slice contract. Update the Issue contract first; do not silently expand scope.
- **Governance-bearing mutation without explicit command execution**: any GitHub label, Project status, or release-pointer change was described rather than executed. Execute and verify before continuing.

## Related docs

- `AGENTS.md` — canonical builder-agent entrypoint and repo-wide rules
- `.codex/skills/README.md` — skill routing map
- `docs/development/DEV_WORKFLOW.md` — working loop, validation, acceptance verifiability
- `docs/DOCS_INDEX.md` — canonical doc role map and agent quick routing
- `docs/ENVIRONMENTS.md` — environment contract
- `docs/RELEASE_CHANNELS/README.md` — release-channel contract
- `docs/development/AGENT_INSTRUCTION_GOVERNANCE.md` — instruction maintenance rules
