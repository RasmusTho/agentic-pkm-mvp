State: Research analysis — architectural decision brief. Not a roadmap commitment; does not override `docs/ARCHITECTURE.md` or `docs/STATUS.md`. Authored against repo state 2026-04-20.
Doc role: Research
Authority: Framing and recommendation for the Chat-surface build-vs-buy question. Binding only if promoted into an ADR or owner-doc edit via a separate lane.
Owner: `docs/ROADMAP.md` (Interaction Model Evolution)
Last reviewed: 2026-04-20
Last verified against: docs/plans/V60_ARCHITECTURE_TARGET.md, docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md, docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md, docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md, docs/plans/COMPANION_NOTE_AND_AGENT_CONTEXT_PLAN.md, docs/plans/AUTONOMY_AND_SYNC_VALIDATION.md, docs/research/pattern-harvest-agentic-architecture.md, docs/settings/panel-actions.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/** (README, RECONCILE_CHAT_MUTATION_AUTHORITY, DEFINE_CHAT_AUTHORITY_BOUNDARY, DEFINE_CANVAS_COEDITING_MODEL, STATE_EXECUTION_AUTHORITY_REMAINS_GATED)

Downstream companion spec: the concrete co-editing posture, co-authoring vs governance-bearing split, one-to-many note↔session model, `.chats/` file-system convention, and `type:` frontmatter classification for Phase 2 are specified in `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md`. Read that spec for the shape the Phase 2 surface must implement.

# Chat Surface: Build vs Buy vs External Tool

## A. Executive answer

**Phased hybrid, anchored to external agent tooling for now, with a custom thin Chat surface later.**

Concretely:

1. Phase 1 (now): keep using **Claude Code / Codex CLI** as the *builder-and-operator* surface they already are. Do not elevate them to a user-facing Chat surface.
2. Phase 1 (now, in parallel): continue the v6.0 priority stack — operationalize salience/staleness, finish receipt + SUGGEST/APPLY gating, extract retrieval as a capability (`docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md` Priorities 1, 3, 4). Chat has no home until those land; putting a UI in front of them earlier would harden the wrong semantics.
3. Phase 2: stand up a **thin, custom canvas-shaped Chat surface** — a UI over the capability contracts, not a new cognition stack. Explicitly reject adopting Open WebUI or LibreChat as the primary Chat surface.
4. Phase 3: governed canvas-commit path through the same gated-execution pipeline Panel uses.

The justification is architectural, not taste. "Chat" in this system is a *governed-capability-entry-point on top of a canvas-shaped interaction posture*, not a thin LLM frontend. OSS chat UIs are built around a different primitive — model-invocation-as-the-product — and would push the architecture toward exactly the failure mode `DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER.md` names. The v6.0 invariant from `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` (LLM reasoning alone never triggers execution) makes the UI layer's job narrow, which in turn makes "build small" cheaper than "adopt-and-constrain large". Governance readiness — receipts, scope/sphere split, retrieval capability — is the gating variable, not UI polish.

## B. Framing

"Chat surface" is doing too much work in casual conversation. This system has at least seven candidate meanings, and the build-vs-buy answer changes by which one you pick:

| Framing | What it implies | Relevant to us? |
| --- | --- | --- |
| **Chat-as-Q&A** | ASK-style receive-query → return-answer | **No.** Explicitly rejected by `docs/FINDING_AND_REORIENTING/DEPRECATE_ASK_AS_ARCHITECTURAL_CENTER.md` and by `DEFINE_CHAT_AUTHORITY_BOUNDARY.md` ("Chat is canvas, not ASK"). Any OSS chat UI whose native metaphor is Q&A is a misleading comparison. |
| **Chat-as-canvas** | Externalize and manipulate thought across existing vault context; state is transient until commit | **Yes — this is the target.** Recorded as Candidate A in `RECONCILE_CHAT_MUTATION_AUTHORITY.md`. |
| **Chat-as-agent-console** | Operator-side surface for running/inspecting agent workflows | **Partially.** Claude Code and Codex CLI already do this well for builder/operator tasks. Not the user-facing goal. |
| **Chat-as-orchestration** | Workflow editor / agent graph canvas | **Not here.** Would collapse interaction and orchestration layers — explicitly against `V60_ARCHITECTURE_TARGET.md` operating layers. |
| **Chat-as-mutation-capable-interface** | Third governed mutation path alongside Panel and Automation | **Phase 3.** Allowed by Candidate A but gated behind receipts and canvas-commit pipeline. |
| **Chat-as-dev-tool** | Where engineers write code, change settings, run migrations | **Already covered by Claude Code / Codex CLI.** Not the user-facing Chat question. |
| **Chat-as-thin-LLM-frontend** | "ChatGPT clone for my stack" | **No.** Adopting this framing is the single largest architectural risk: it re-centers the system on model invocation and silently re-enthrones the ASK loop. |
| **Chat-as-governed-capability-entry-point** | A surface whose commands/thoughts dispatch *capability contracts* (retrieve, rerank, orient, propose, commit), not raw model calls | **Yes — this is the shape.** The UI is thin; capabilities and governance carry the weight. |

The relevant comparisons are therefore: canvas + governed-capability-entry-point. Everything else is a category error in this decision.

A second disambiguation: "build vs buy" is not binary. The real question is *where the seam is*. Three candidate seams:

- **Seam A — UI only**: we build/buy only rendering + input; capability contracts, retrieval, governance, note-writer remain ours.
- **Seam B — UI + conversation store + RAG**: we adopt an OSS stack's conversation history, thread model, vector/RAG layer, and tool-calling format.
- **Seam C — UI + cognition**: we adopt an OSS or external stack's entire agent runtime (e.g., use Claude Code as the user-facing surface).

Adopting Seam B or C binds our architecture to a vendor's model of what a chat is. Seam A is the only honest answer for a vault-first, capability-based, governance-gated system. The rest of this document treats Seam A as the live option when it says "buy".

## C. Option analysis

### Option A — Build custom Chat surface (Seam A, thin UI over our capabilities)

**Strengths.**
- UI maps directly to our capability contracts (`retrieve`, `rerank`, `orient`, `resurface`, `propose`, `commit`); no translation layer.
- Canvas semantics (externalize / manipulate / optionally-commit) have no off-the-shelf equivalent — they are not the chat primitive OSS tools optimize for.
- Receipts, scope/sphere, staleness, salience, admission gate render natively. No fighting a host application's assumptions about what "a message" is.
- Governance-gated mutation path (per `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`) is simpler to enforce when we own the commit button.
- Multi-user-neutral by construction; instance/device/replica provenance can live in the UI's authority model rather than being bolted on.

**Weaknesses.**
- Real UI work: editor, diff view, commit affordance, receipt rendering, thread/canvas state. Non-trivial even as "thin".
- Risk of mission creep: every generic chat feature (search, export, branching) is a temptation that doesn't serve cognitive support.
- Opportunity cost versus shipping the signals underneath (`V60_COGNITIVE_SUPPORT_PRIORITIES.md` Priorities 1–4).

**Architectural fit.** Highest. Interaction is primary (`V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Fixed Decisions), and a custom surface keeps interaction separate from cognition/execution/governance/memory.

**Near-term fit.** Low. The priorities that would make a Chat surface non-trivially useful have not landed yet.

**Long-term fit.** Highest. Canvas-commit through gated execution is only reachable from a UI we control.

**Key risks.**
- Building the UI before the capability contracts exist hardens heuristics into durable affordances (`V60_COGNITIVE_SUPPORT_PRIORITIES.md` §Sequencing Principles: "surfaces built on absent signals become heuristics that silently become truth").
- Temptation to build "a ChatGPT clone, but ours" instead of a canvas.

### Option B — Adopt OSS chat UI (Open WebUI / LibreChat)

**Strengths.**
- Authentication, conversation history, multi-provider model routing, streaming, RAG wiring are already solved.
- Tool-calling / MCP plumbing exists (stronger in LibreChat per its docs; present in Open WebUI via Pipelines).
- Visibly productive demo in days, not weeks.

**Weaknesses.**
- Both are built around chat-as-Q&A / chat-as-thin-LLM-frontend primitives. Neither is a canvas. Retrofitting canvas semantics onto a thread-of-messages UI is not a feature add — it's a fight with the framework's world model.
- The "conversation" is the primary persistent artifact. In our architecture, **the vault is**. Adopting a system whose data model centers the chat log silently demotes the vault to "RAG source" and re-introduces the exact failure mode `V60_ARCHITECTURE_TARGET.md` warns against ("v6.0 does not make ... derived runtime DB/index state semantically primary").
- Authority boundaries are invisible in these UIs. Neither tool has a concept of receipts, SUGGEST/APPLY verbs, scope/sphere, admission, or instance provenance. We would have to ship all of that as either (a) patches/forks or (b) a sidecar backend the UI can't render.
- **Open WebUI license (v0.6.6+, April 2025): non-OSI, branding-preservation required above a 50-user / 30-day threshold, CLA required for new contributions.** This is decisive for a project whose design principles include human-first governance and long-term architecture reversibility. Sources: [Open WebUI license docs](https://docs.openwebui.com/license/), [HN discussion](https://news.ycombinator.com/item?id=43901575), [BigGo coverage](https://finance.biggo.com/news/202511041923_open-webui-license-change-backlash). For a single-user system this is legally workable, but depending on a project that has relicensed multiple times (Apache → MIT → CC BY-NC-SA → MIT → BSD-3 → custom) is a structural risk, not a compliance footnote.
- LibreChat remains MIT and has stronger MCP/Agents shape, but the same vault-demotion issue applies.

**Architectural fit.** Low. Adoption collapses the interaction / cognition separation because the tool owns both.

**Near-term fit.** Superficially high (fast demo), actually low (re-centers the architecture wrong).

**Long-term fit.** Low. Reversibility at the docs layer is lost the moment users accumulate conversation history in the adopted tool's store.

**Key risks.**
- The chat log becomes the de facto source of truth (Red Flag #1 below).
- Branding lock-in (Open WebUI) or governance boundary drift.
- "Just use its RAG / tool layer" silently re-introduces ASK semantics.

### Option C — Use external agent/coding tool as the Chat surface (Claude Code / Codex CLI / ChatGPT-Codex)

**Strengths.**
- Already in use by the builder agents. MCP, hooks, skills, sub-agents, plugins are all first-class. Headless SDK exists (Claude Code Agent SDK; Codex CLI as MCP server) per [Claude Code overview](https://code.claude.com/docs/en/overview) and [Codex MCP docs](https://developers.openai.com/codex/mcp).
- Operator-grade: diffs, receipts, permissions, allow-lists, sandboxing. These are well-fit to *governance and execution*.
- Zero UI build cost for the operator surface.

**Weaknesses.**
- These are **developer/operator surfaces**, not user-facing cognitive-support surfaces. Their primary metaphor is "agent acts on repo" — the repo is the object, and the user is the operator. For our user (a thinker with a vault), that inversion does not hold: the vault is not a repo being acted on, it is a canvas being thought-with.
- Conflating dev tooling with user-facing interaction is Red Flag #4 below — the inverse failure of Red Flag #1.
- Vendor lock-in: Claude Code binds to Anthropic subscription / console; Codex CLI binds to a ChatGPT plan or OpenAI API. Both send user thought to a remote service by default. Our stated posture is local-first; this is structurally contrary.
- No native canvas metaphor. "Plan mode" is close, but the surface still thinks in terms of tasks and diffs, not thought-manipulation.
- Receipts are coding-shaped (file diffs, PR descriptions), not cognition-shaped (SUGGEST/APPLY, scope-aware proposals).

**Architectural fit.** Low for the *user-facing Chat surface* question. **High** for the *builder/operator* question — which is already the status quo.

**Near-term fit.** Keep as operator surface. Do not promote.

**Long-term fit.** Stays operator-side.

**Key risks.**
- Accidental scope creep: "Claude Code is our agent UI" would collapse user and operator authority into the same surface.
- Vendor / license / pricing coupling to Anthropic or OpenAI.

### Option D — Hybrid / phased

**Strengths.**
- Lets external tooling carry Phase 1 (builder-agent work, operator tasks) while the v6.0 capability contracts that would underpin a real Chat surface are being built.
- Defers the custom UI build until there are actual capabilities for it to render — which is when the UI is cheap to scope.
- Keeps the decision reversible at each phase boundary.

**Weaknesses.**
- Requires discipline to *not* let Phase 1 tooling drift into Phase 2 territory ("we're already typing into Claude Code, let's just put users in there").
- Two surfaces coexisting (operator CLI + eventual canvas) means the docs must keep the authority lanes sharp.

**Architectural fit.** Highest of the four, because it matches the separation `V60_ARCHITECTURE_TARGET.md` already describes: observation, contract, admission, execution are distinct stages with distinct tooling appropriate to each stage.

**Near-term fit.** High — it's essentially the status quo plus a commitment not to promote the operator surface.

**Long-term fit.** High — ends in Option A (thin custom canvas) with governance-grade signals underneath.

**Key risks.**
- Indefinite deferral: "we'll build the custom UI later" becoming "we never build it and just keep widening Claude Code's role".
- Exit criteria for each phase must be explicit and verifiable (see §G).

## D. Tool-by-tool evaluation

Dimensions for each tool: *what it is → self-hostable → extensibility → local-model support → tool calling → custom API → context injection → identity/session → auditability → role separation → suitable as*.

### Open WebUI

- **What it is.** Self-hostable web UI for LLM chat + RAG, originally a ChatGPT-alternative frontend for Ollama. Pipelines, Tools, Functions extensibility. Latest release noted as v0.8.12 (March 2026). ([GitHub](https://github.com/open-webui/open-webui))
- **Self-hostable.** Yes — Docker / pip / compose / Kustomize / Helm.
- **Extensibility.** Pipelines framework (Python), native Python Tools, Functions. Mature plugin surface.
- **Local-model support.** Strong (Ollama-native; any OpenAI-compatible endpoint).
- **Tool calling.** Yes, via Pipelines; tool-calling in the OpenAI-compatible idiom.
- **Custom API.** OpenAI-compatible endpoint configurable.
- **Context injection.** RAG-shaped (vector DB + document upload + web search). Not vault-native.
- **Identity/session.** RBAC, LDAP/AD, SCIM, SSO, OAuth. Enterprise-capable.
- **Auditability.** OpenTelemetry traces/metrics/logs. Audit trail is infrastructure-shaped, not governance-shaped.
- **Role separation.** Admin/user via RBAC.
- **Critical fact.** License changed April 2025 (v0.6.6+) to non-OSI custom license with branding-preservation clauses and a CLA. Enterprise license required above 50 users / 30 days for white-labeling. ([license docs](https://docs.openwebui.com/license/))
- **Suitable as.** Operator/admin LLM gateway for teams. **Not suitable** as our user-facing canvas-Chat surface because (a) conversation-centric data model demotes the vault, (b) license volatility, (c) no canvas primitive.

### LibreChat

- **What it is.** MIT-licensed self-hostable multi-provider chat app with Agents, MCP, Code Interpreter, Artifacts, custom endpoints via `librechat.yaml`. ([GitHub](https://github.com/danny-avila/LibreChat), [MCP docs](https://www.librechat.ai/docs/features/mcp))
- **Self-hostable.** Yes — Docker / Railway / Zeabur / Sealos.
- **Extensibility.** Custom endpoints, tool/plugin system, Agents marketplace, MCP servers configured via YAML.
- **Local-model support.** Yes via Ollama and other OpenAI-compatible endpoints.
- **Tool calling.** Strong. MCP servers with deferred-tool loading and Tool Search.
- **Custom API.** First-class custom endpoints.
- **Context injection.** RAG as separate service with Meilisearch + vector hybrid.
- **Identity/session.** OAuth2, LDAP, email, Azure AD, AWS Cognito. Enterprise-shaped auth.
- **Auditability.** Recommends comprehensive logging; no built-in receipt/verb contract.
- **Role separation.** Multi-user with token-spend tracking.
- **Suitable as.** Strong team chatops / multi-provider gateway. **Not suitable** as our canvas-Chat surface for the same structural reason as Open WebUI: chat-thread is the durable primary, vault would be relegated to RAG source. But MIT + MCP maturity makes it the *least bad* Seam-B fallback if we are ever forced to adopt.

### Claude Code

- **What it is.** Anthropic's terminal / IDE / desktop / web agentic coding tool with MCP, Skills, Plugins, Hooks, Sub-Agents, Agent SDK, headless CLI. ([overview](https://code.claude.com/docs/en/overview))
- **Self-hostable.** No — model runs via Anthropic API / Bedrock / Vertex / Foundry. The CLI itself runs locally.
- **Extensibility.** Skills (filesystem), Plugins (public beta since Oct 2025), Hooks, CLAUDE.md, MCP. High for coding and agent workflows.
- **Local-model support.** No (binds to Claude).
- **Tool calling.** First-class MCP.
- **Custom API.** Not a generic hosted API surface; can act as MCP server via Agent SDK.
- **Context injection.** CLAUDE.md, Skills, auto-memory, MCP.
- **Identity/session.** Tied to Anthropic account / third-party provider credentials.
- **Auditability.** Session transcripts; diffs; hook logs. Operator-grade, not governance-grade.
- **Role separation.** Assumes a developer operator.
- **Suitable as.** **Builder-agent surface (current use, keep).** Inference: operator surface for running maintenance, doc-authoring, and repo work. **Not suitable** as user-facing canvas because (a) coding-shaped metaphor, (b) vendor/model lock-in contrary to local-first posture, (c) receipts are file-shaped, not cognition-shaped.

### Codex CLI / ChatGPT-Codex

- **What it is.** OpenAI's agentic coding CLI (Apache-2.0), with ChatGPT-account auth preferred, plus a web surface at chatgpt.com/codex. MCP support in CLI and IDE extension; can act as MCP server. ([Codex changelog](https://developers.openai.com/codex/changelog), [MCP](https://developers.openai.com/codex/mcp))
- **Self-hostable.** CLI is local; model inference is cloud (OpenAI).
- **Extensibility.** MCP (STDIO / streamable HTTP), slash commands, config.toml.
- **Local-model support.** No (cloud OpenAI).
- **Tool calling.** MCP first-class.
- **Custom API.** Can expose as MCP server.
- **Context injection.** Agents-style; repo-focused.
- **Identity/session.** ChatGPT plan / OpenAI API.
- **Auditability.** Command approval flows; network domain restriction in cloud mode.
- **Role separation.** Developer operator.
- **Suitable as.** Alternative to Claude Code in the builder/operator lane. Same verdict: **not a user-facing Chat surface**. Useful as a parallel agent if workload needs redundancy or if a task benefits from a different model lineage.

### Brief notes on other contenders (one-line each)

- **AnythingLLM** — MIT, workspace-centric ("documents-plus-chat"); closer to "PKM chat" than Open WebUI, but workspace model still centers the conversation, and its agent framework is its own — adopting means adopting their agent metaphor.
- **Msty** — Offline-first desktop app with knowledge stacks, chat branching; polished but closed-ish; not extensible enough to host our capability contracts.
- **Jan** — Open-source local-first desktop LLM client; too consumer-shaped, not a platform.
- **Cherry Studio** — Multi-model desktop client; same category as Msty/Jan.
- **Continue** — IDE-integrated coding assistant; same category as Claude Code/Codex for our purposes.
- **Big-AGI** — Open-source chat UI; same conversation-as-primary issue as Open WebUI.
- **assistant-ui** / **Vercel AI SDK UI kits** — React component libraries (inferred: MIT). If we ever build custom Chat, these are the right-sized building blocks for Seam A, not competitors to it. They are UI primitives, not chat applications.

The practical implication of the brief survey: there is no OSS chat app whose data model puts the vault first. There is a category of UI-kit libraries (assistant-ui, Vercel AI SDK UI) that could accelerate a custom build.

## E. Comparison matrix

Scale: **H** = high / strong fit, **M** = medium / partial fit, **L** = low / weak fit. "Fit" means fit to *our* stated architecture, not general quality.

| Option / tool | Arch. fit | Governance fit | OSS / local-first fit | Extensibility | Integration complexity | Time to value | Long-term maintainability | UX fit (canvas) | Observability / audit | Mutation safety |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A. Build custom (thin canvas)** | H | H | H | H | M (we own it) | L (months) | H | H | H (we define) | H |
| **B. Adopt OSS chat UI (generic)** | L | L | M | H | M-H (fork/patch) | H | L | L | M | L |
| **C. External agent tool as Chat** | L (user-facing) / H (operator) | M (operator only) | L (cloud model) | H | L (status quo) | H | M | L | M (operator-shaped) | M |
| **D. Hybrid / phased** | H | H | H | H | M | M | H | H (phase 2+) | H | H |
| Open WebUI | L | L | L (non-OSI since v0.6.6) | H | M | H | L (license volatility) | L | M | L |
| LibreChat | L | L | M (MIT) | H | M | H | M | L | M | L |
| Claude Code | L (user) / H (operator) | M (operator) | L (cloud model) | H | L | H | M | L | M | M |
| Codex CLI | L (user) / H (operator) | M (operator) | L (cloud model) | H | L | H | M | L | M | M |
| AnythingLLM | L-M | L | M (MIT) | M | M | H | M | L-M | L-M | L |
| assistant-ui / Vercel AI SDK UI | n/a (building block) | n/a | H (inferred MIT) | H | M | M | H | H (when used in A) | n/a | n/a |

## F. Recommended path

**Do now (Phase 1).**

1. **Keep Claude Code / Codex CLI as builder-agent and operator surfaces.** Do not promote them. They carry the Phase 1 load correctly. (Principle: interaction / cognition / execution / memory / governance are separate subsystems — `V60_ARCHITECTURE_TARGET.md`.)
2. **Finish the signal layer before any UI move.** Priorities 1 (salience/staleness), 3 (receipts + SUGGEST/APPLY), and 4 (retrieval as capability) from `V60_COGNITIVE_SUPPORT_PRIORITIES.md`. (Principle: signal before surface.)
3. **Do not adopt Open WebUI.** License trajectory (non-OSI, branding clauses, CLA, enterprise gating) is structurally incompatible with a long-lived, vault-first, single-user-now-but-reversible system.
4. **Do not adopt LibreChat as the primary Chat surface.** MIT is fine, MCP is good, but its data model centers the conversation — which silently demotes the vault. (Principle: vault is canonical human writing/reading surface — `V60_ARCHITECTURE_TARGET.md` operating layers.)
5. **Keep the Panel proposal surface as the live mutation-capable interaction baseline.** Do not widen it into Chat work (`docs/plans/AUTONOMY_AND_SYNC_VALIDATION.md`).

**Do not do now.**

- Do not stand up *any* persistent user-facing chat UI. Not a forked OSS app, not a custom prototype, not Obsidian plugin UI. A Chat surface without receipts is architecturally unsafe.
- Do not let Claude Code / Codex become the end-user's primary surface by default. It is a builder surface for this project and must stay that way.
- Do not wire vault into an OSS chat app's RAG layer "to evaluate". That evaluation is the thing that silently demotes the vault.

**Revisit later.**

- When Priorities 1, 3, 4 have landed: reopen Phase 2 (build thin custom Chat).
- When the first canvas-commit receipt shape is specified: reopen Phase 3 (governed Chat mutation).
- If Anthropic or OpenAI change auth / pricing / data-retention policies unfavorably: reopen Phase 1 (builder surface choice), fall back to the other.
- If a new OSS project emerges whose primitive is *canvas*, not *chat-thread*, re-evaluate Option B with honest criteria.

Justification references by principle:

| Recommendation | Principle invoked |
| --- | --- |
| No chat UI before signals | `V60_COGNITIVE_SUPPORT_PRIORITIES.md` §Sequencing Principles |
| Thin custom UI in Phase 2 | `DEFINE_CHAT_AUTHORITY_BOUNDARY.md` "Chat is canvas, not ASK" |
| Keep external tools as operator-only | `V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §System-of-systems framing |
| Reject Open WebUI | OSS / local-first posture in `V60_ARCHITECTURE_TARGET.md`; reversibility principle in `RECONCILE_CHAT_MUTATION_AUTHORITY.md` |
| Receipts before Chat mutation | `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` |

## G. Suggested phased strategy

### Phase 1 — Months 1–3: keep the status quo, finish the signal layer

**Surfaces used.**
- **Vault (Obsidian)** — primary human writing/reading surface. Unchanged.
- **Panel** — primary mutation-capable interaction surface with low-risk autonomy proposals (already delivered per `AUTONOMY_AND_SYNC_VALIDATION.md`).
- **Claude Code / Codex CLI** — builder/operator surface for engineering work.
- **No user-facing Chat surface.**

**What's governed.** Panel mutation path (existing). Watcher policy. Companion-note ingest.
**What's exploratory.** Claude Code / Codex sessions, as operator side-channels.
**Exit criterion to Phase 2.**
- `V60_COGNITIVE_SUPPORT_PRIORITIES.md` Priorities 1, 3, and 4 shipped (or at minimum: receipt artifact fields defined + retrieval capability contract defined).
- A receipt shape exists that Chat-originated mutations *could* pass through without redesigning it.
- One end-to-end Panel proposal flow produces a receipt that the owner-doc describes as the canonical example.

### Phase 2 — Months 3–6: thin custom canvas Chat (read-only, Deep-Agent-hosting)

**Surfaces used.**
- Vault, Panel as Phase 1.
- **New: a custom canvas Chat surface.** Location decision (inside/outside Obsidian) is deferred per `RECONCILE_CHAT_MUTATION_AUTHORITY.md`.
- Thin UI built on UI primitives (assistant-ui or Vercel AI SDK UI kits; final choice at Phase-2 start).
- Binds to capability contracts (retrieve, rerank, orient, resurface, propose). Does *not* mutate durable state.
- Hosts the first Deep Agent rollout in **read-only mode** (`V60_CAPABILITY_AND_AGENT_EVOLUTION.md` §Deep Agents start in Chat before Panel).

**What's governed.** Retrieval capability inputs/outputs; salience/staleness flags are surfaced; conversation transcript is transient, not durable.
**What's exploratory.** Canvas interaction model (how drafts/arrangements/annotations behave visually); salience-driven resurfacing surface.
**Exit criterion to Phase 3.**
- A canvas-commit proposal shape exists on paper, with a receipt target, scoped to the Priority 3 gating verbs.
- One Deep Agent has completed a read-only slice with acceptance receipts.
- The canvas-vs-ASK distinction remains verifiable: nothing in the UI rewards turn-based Q&A over thought-manipulation.

### Phase 3 — Months 6–18: governed canvas-commit

**Surfaces used.**
- Vault, Panel, Chat (now mutation-capable through the gated-execution pipeline).

**What's governed.** Canvas-commit actions flow through the same policy + validation + event pipeline Panel uses. No separate Chat receipt store. ("Receipts live where Panel mutation receipts already live." — `RECONCILE_CHAT_MUTATION_AUTHORITY.md` §Decision.)
**What's exploratory.** Richer Deep Agent cognition in Chat; selective cognition in Panel planning (`V60_CAPABILITY_AND_AGENT_EVOLUTION.md` Phase 3).
**Exit criterion.** Reversibility budget: if within one-to-two releases canvas-commit cannot be made to satisfy `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` *and* Governance Before Autonomy simultaneously, Phase 3 is rolled back at the docs layer. (Per `RECONCILE_CHAT_MUTATION_AUTHORITY.md` §Re-evaluation trigger.)

## H. Decision criteria

The choice is driven by the following hard criteria, in order. If a criterion fails, the choice must be revisited.

1. **Vault stays canonical.** Any option whose data model centers the conversation (Open WebUI, LibreChat, generic OSS chat UIs) fails. The vault must remain the primary durable artifact. If we can't state "the chat log is not where meaning lives" in one sentence, the option is wrong.
2. **Governance must be expressible in the surface.** Receipts, SUGGEST/APPLY verbs, scope/sphere, admission must be representable. Surfaces that cannot render these fail. This rules out all OSS chat apps at the user-facing layer.
3. **LLM reasoning alone never triggers execution.** The surface must not allow a model-decided mutation that bypasses the gated pipeline. External agent tools (Claude Code, Codex) *can* bypass it when given shell access — which is why they are operator surfaces, not user surfaces.
4. **Local-first and license-stable.** Surfaces whose licenses have shifted multiple times (Open WebUI) or whose inference requires a specific cloud vendor (Claude Code, Codex) fail this criterion for the user-facing role. They are acceptable for the *builder* role because builders can accept vendor coupling that users should not be forced into.
5. **Reversible at the docs layer until first commit.** If canvas-Chat cannot be rolled back without unwinding shipped code, stop. This is the `RECONCILE_CHAT_MUTATION_AUTHORITY.md` re-evaluation trigger.
6. **Cognitive-support fit, not chatbot fit.** The surface should help the user externalize and manipulate thought (USER_NEEDS_MODEL Need #3, #4, #5). A surface optimized for "answer my question" fails this criterion, regardless of how nice its UX is.
7. **Hard fallbacks.**
   - If Claude Code changes license / pricing / data policy unfavorably → fall back to Codex CLI as operator surface, and vice versa.
   - If Open WebUI's license drifts further → not a fallback candidate at all (was already rejected).
   - If LibreChat changes license → drop from the Seam-B fallback list.
   - If we cannot ship receipts by Phase-2 start → Phase 2 does not start. Build no UI until the gate exists.

## I. Red flags

These are the high-probability failure modes for this decision. Most of them look reasonable in the moment.

1. **The chat tool becomes the semantic center.** The highest-severity failure. An OSS chat UI is adopted "just for the interface"; users start treating the conversation history as memory; the vault becomes RAG source material; the entire cognitive-prosthetic framing inverts. Triggering condition to watch: anyone says "we can use the chat logs as context for the next thing" without flinching.
2. **Bypassing governance through "temporary" integrations.** An external tool is given direct write access to the vault for a demo; the demo ships; the governance path is quietly skipped. `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` exists precisely to forbid this. Triggering condition: any PR that wires an LLM response into a file-write without passing through the admission pipeline.
3. **Building a large custom UI too early.** The custom surface ships before the signals (salience, staleness, scope, receipt) exist. The UI then hardens the wrong semantics (cf. `V60_COGNITIVE_SUPPORT_PRIORITIES.md` §Sequencing Principles). Triggering condition: a Chat UI PR that predates the receipt-artifact PR.
4. **Conflating dev tooling with user-facing interaction surface.** Claude Code or Codex silently becomes "the chat" because we're already living in it. The operator metaphor takes over the user metaphor. Triggering condition: the user-facing docs start mentioning CLI commands or shell-like semantics as normal cognitive interaction.
5. **ASK semantics re-introduced under a new name.** Canvas becomes query-and-response over time because query-and-response is easier to build. Explicitly guarded against in `DEFINE_CHAT_AUTHORITY_BOUNDARY.md`. Triggering condition: the primary verb in the Chat UI is "send" rather than something like "lay down / arrange / commit".
6. **License ratchet in the UI substrate.** Adopting an OSS UI whose license trajectory has included relicensing moves (Open WebUI: Apache → MIT → CC BY-NC-SA → MIT → BSD-3 → custom-non-OSI). Even if today's license is usable, the ratchet risk alone is architecturally disqualifying for a multi-year project.
7. **Vault demotion via "RAG plumbing".** Wiring vault notes through a vector-DB-centric RAG layer provided by a chat app makes the app's retrieval path authoritative and hides retrieval-as-capability behind a vendor's framing. This is the same failure as #1, one layer down.
8. **Instance/replica assumptions baked into a borrowed UI.** OSS chat apps assume a single-server truth. Our v6.0 stance explicitly models multi-device/replica posture as normal (`V60_ARCHITECTURE_TARGET.md` §Multi-device / replica migration). A borrowed UI will silently foreclose this.
9. **"Let's just prototype it in Open WebUI."** Even a throwaway prototype creates conversation history that users rely on; removing it later is politically expensive. Prototyping on a structurally wrong surface produces structurally wrong feedback.
10. **Forgetting that Panel is not Chat.** Panel is command-oriented with in-note receipts; Chat is canvas-shaped with pipeline-local receipts. Merging them "to simplify" collapses two different authority lanes.

---

## Sources

Internal (repo):
- `docs/plans/V60_ARCHITECTURE_TARGET.md`
- `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`
- `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md`
- `docs/plans/COMPANION_NOTE_AND_NOTE_CONTEXT.md`
- `docs/plans/COMPANION_NOTE_AND_AGENT_CONTEXT_PLAN.md`
- `docs/plans/AUTONOMY_AND_SYNC_VALIDATION.md`
- `docs/research/pattern-harvest-agentic-architecture.md`
- `docs/settings/panel-actions.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/RECONCILE_CHAT_MUTATION_AUTHORITY.md` (Decision: Candidate A, 2026-04-11)
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CHAT_AUTHORITY_BOUNDARY.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`

External (verified):
- Open WebUI repository: https://github.com/open-webui/open-webui
- Open WebUI license (v0.6.6+, non-OSI, branding clause, CLA): https://docs.openwebui.com/license/
- Open WebUI license-change community discussion: https://news.ycombinator.com/item?id=43901575
- Open WebUI license-change coverage: https://finance.biggo.com/news/202511041923_open-webui-license-change-backlash
- LibreChat repository (MIT): https://github.com/danny-avila/LibreChat
- LibreChat MCP docs: https://www.librechat.ai/docs/features/mcp
- LibreChat Agents docs: https://www.librechat.ai/docs/features/agents
- LibreChat custom endpoints: https://www.librechat.ai/docs/configuration/librechat_yaml
- Claude Code overview: https://code.claude.com/docs/en/overview
- Claude Code Agent SDK: https://platform.claude.com/docs/en/agent-sdk/overview
- Claude Code Skills: https://code.claude.com/docs/en/skills
- OpenAI Codex CLI changelog: https://developers.openai.com/codex/changelog
- OpenAI Codex MCP: https://developers.openai.com/codex/mcp
- OpenAI Codex CLI: https://developers.openai.com/codex/cli
- Comparison surveys consulted (not authoritative): https://portkey.ai/blog/librechat-vs-openwebui/, https://blog.elest.io/the-best-open-source-chatgpt-interfaces-lobechat-vs-open-webui-vs-librechat/, https://www.helicone.ai/blog/open-webui-alternatives

Inferences explicitly marked in the text include: Open WebUI v0.8.12 release date (per README excerpt, March 2026, not independently re-verified); assistant-ui / Vercel AI SDK UI kits license (stated as "inferred MIT"); LibreChat audit-log specifics (search results summarized the feature area but did not produce a fielded spec — treated as "recommended by community, not fielded").
