# Design Brief — Companion UI for Agentic PKM

## What this is
A user-facing module for a personal agentic PKM system. The system already exists: vault-backed (markdown + frontmatter), FastAPI runtime, agents, ingestion, companion notes, receipts. Obsidian is the canonical human writing surface. This module is a new client onto the existing runtime — it does not replace or modify core components.

## Who uses it
One user: a senior software architect who lives in the vault daily across iPhone, iPad, and Mac. Thinks at system level. Uses the vault for capture, synthesis, decision tracking, and long-running thought. Already fluent with Obsidian, markdown, and agent tooling. Not a consumer; not a novice.

## Why it exists
Obsidian is excellent for durable writing and reading but structurally weak for certain cognitive acts: externalized thinking with an agent, orienting within one's own active cognition, agent-assisted synthesis with staged suggestions, and lightweight mobile interaction with the vault. This module is the *assisted-thinking surface* where those acts happen. The vault remains the source of truth; this module renders, manipulates, and contributes to vault artifacts through documented contracts.

## Cognitive surfaces in scope
The module is expected to eventually support these distinct cognitive acts. Each one names a mode of thought, not a UI pattern:

- **Capture** — getting material into the system with minimal friction, especially from mobile.
- **Orient** — situating oneself in active cognition: open loops, active threads, commitments to future-self, stale decisions. Pulled by the user when sitting down to think.
- **Triage** — converting captured material into usable knowledge artifacts.
- **Resurface** — bringing relevant forgotten material back into view, interest-following rather than review-scheduled.
- **Synthesize** — producing higher-order artifacts (essays, specs, plans) from vault material with agent assistance.
- **Converse** — externalizing thought with one or more agents, exploring and manipulating ideas in place, optionally producing durable artifacts.

Not all surfaces ship in v0. The taxonomy exists so design decisions don't foreclose future surfaces.

## Hard constraints

**Vault compatibility is non-negotiable.**
- Markdown must open cleanly in Obsidian without this module present.
- Frontmatter remains human-legible.
- Wikilinks remain standard Obsidian wikilinks.
- Semantic truth lives in markdown body + frontmatter. Sidecar/JSON-in-markdown is allowed only for bounded layout/control state that is recoverable if deleted.
- Removing this module must not damage the vault.

**Architectural constraints.**
- This module is a client of the existing FastAPI runtime. It does not own vault I/O directly; the runtime does.
- Must run on iPhone, iPad, and Mac. Desktop can be primary; mobile can be a thinner subset.
- The runtime is reachable on a personal network (Tailscale or equivalent). This is not a cloud-hosted multi-tenant product.
- Existing artifact classes must be respected: human notes, companion notes, control artifacts, receipts, runtime projections. Control artifacts and chat transcripts must not be indexed as knowledge by default.

**Agent interaction constraints.**
- The system distinguishes ASSERT / SUGGEST / APPLY verbs with receipts. In v0 the module may propose and stage changes; direct APPLY mutation from chat is out of scope until receipt/governance plumbing is complete.
- Canvas-shaped conversation is not ASK-style query/answer. The module should support externalizing thought and manipulating ideas in place, not only question-answering.

**Single user, intentionally.**
- Design for one known user. Do not import patterns that assume unknown-user product usage (onboarding flows, trust-calibration UI for strangers, engagement mechanics, growth loops).
- Architecture must not structurally block a future multi-user variant, but multi-user is not a design driver.

## v0 scope

**Build:** the Converse surface as the first UI-bound surface. It is the surface that cannot be prototyped vault-natively and therefore is the correct forcing function for this module's existence.

**Do not build in v0:**
- A shell abstraction spanning multiple surfaces. Extract that only when a second UI-bound surface is built.
- Triage, Resurface, or Synthesize as distinct surfaces.
- Direct APPLY mutation from chat into arbitrary vault notes.
- Multi-agent orchestration as a UI concern.

**Orient is prototyped vault-natively first** (as a generated markdown dashboard note rendered in Obsidian). It enters this module only after its markdown contract is validated.

## What the design should produce

1. An interaction design for the Converse surface that fits a senior user's actual thinking process — exploratory, branching, sometimes producing a durable artifact, sometimes not. The designer decides how exploration vs. artifact-production is expressed; both cases must be supported.
2. A mobile-appropriate form that acknowledges the iPhone/iPad/Mac spread without forcing one form factor to mimic another.
3. A clear visual and interaction language for agent contributions (suggestions, staged outputs, provenance) that is legible without being ceremonial.
4. Navigation that works for v0 (one surface) but does not actively obstruct adding further surfaces later. The designer decides the shape; the brief does not prescribe shells, sidebars, or palettes.
5. A treatment of session persistence that reflects the vault contract: sessions are durable markdown artifacts, not ephemeral app state.

## Vault contract reference (for designers who need it)

Chat sessions, staged suggestions, and any derived artifacts will be persisted as markdown files in the vault with documented frontmatter schemas. Designers do not need to specify these schemas; they will be provided alongside the brief. The relevant fact for design is that every visible object in the UI maps to, or derives from, a vault-readable file.

## Open questions the design process should resolve

- How Converse expresses exploratory-thinking vs. artifact-producing modes of work without making users feel they've picked wrong.
- How agent contributions are visually distinguished from human content and from system state, across desktop and mobile.
- How the mobile surface handles the subset of Converse that makes sense on a phone (likely: reading, lightweight continuation, new session capture) without pretending to be the desktop.
- How session history, context, and sources are surfaced during a session without dominating the thinking surface.
- How the module communicates that it is a client of a separate runtime (e.g. when the runtime is unreachable) without leaking infrastructure concerns into the thinking experience.

## Non-goals

This brief does not prescribe: shell structure, sidebar presence, command palette, spatial vs. linear layout, artifact-pane placement, whether modes are toggles or separate views, color, type, or component library. Those are design decisions.
