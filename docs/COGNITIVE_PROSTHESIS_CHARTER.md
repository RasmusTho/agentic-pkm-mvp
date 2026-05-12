State: SoT v5.5 baseline; v6 active planning direction. Charter document; describes product-level thesis, not shipped implementation.
Doc role: Core SoT
Authority: Product-level thesis for Yggdrasil as a local-first cognitive prosthesis, second-brain environment, and governed memory/runtime substrate for agents. Other docs should remain compatible with this charter; where they diverge, this charter wins on intent and they win on current implementation truth.
Owner: Product / kernel
Temporal class: timeless
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-12
Last verified against: docs/PROJECT_KERNEL.md, docs/HUMAN-FLOWS.md, docs/ARCHITECTURE.md, docs/CONCEPTS/COGNITIVE_ONTOLOGY.md, docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md, docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md

# Cognitive Prosthesis Charter — Yggdrasil / agentic-pkm-mvp

> Audience: product, architecture, and builder-agent readers who need a single page that explains *what Yggdrasil is for* before reading the kernel, architecture, or concept contracts.

This document is the product-level thesis for Yggdrasil. It does not redefine the kernel
(`docs/PROJECT_KERNEL.md`), the human flows (`docs/HUMAN-FLOWS.md`), or the runtime architecture
(`docs/ARCHITECTURE.md`). It frames them.

It also does not claim that all target-state capabilities are implemented today. Where this
charter describes a capability as a product property, current implementation truth is owned by
`docs/STATUS.md`, `docs/ROADMAP.md`, and the owner docs they reference.

## 1. Product thesis

Yggdrasil is three things at once, and the design only works when all three are held together:

1. **A local-first cognitive prosthesis for the human.** It supports cognitive functions a human
   cannot reliably do unaided — durable capture, reorientation, retrieval, commitment tracking,
   reflection, source-anchored interpretation — without taking authorship away.
2. **A second-brain environment.** Human-authored Markdown artifacts in the vault are the
   primary durable knowledge surface. They are meant to be read, edited, and trusted by the human
   directly, on disk, with or without the system running.
3. **A governed memory and runtime substrate for agents.** System agents operate as bounded
   delegates over that vault and over supporting machine surfaces (databases, indexes, event
   streams, receipts), under explicit authority contracts. Their memory, context, and writes are
   first-class objects — not hidden state in a model.

These three roles are nested, not separate products. The prosthesis is the purpose; the
second-brain environment is the human-facing shape it takes; the agent substrate is what makes
the prosthesis active rather than passive.

## 2. Human cognitive burdens the system supports

The system exists because unaided cognition leaks. The cognitive burdens Yggdrasil is meant to
absorb or share with the human include:

- **Holding too much in working memory.** Open loops, in-flight projects, unfinished thoughts,
  and waiting states should be externalizable without ceremony.
- **Losing fleeting thought.** Captured fragments must reach a stable, locatable, provenance-bearing
  place before the moment passes.
- **Reorienting after time away.** After hours, days, or months, the human should be able to find
  the right surface to resume work without manually reconstructing context.
- **Trusting sources later.** Imported material, quoted passages, and external references must
  remain attributable and inspectable long after the originating context is forgotten.
- **Turning intent into bounded action.** Vague intentions become next actions, projects, waiting
  states, and review cycles — visible structures, not memorized obligations.
- **Maintaining contextual integrity across life spheres.** Work, private, creative, and hobby
  contexts must remain distinct in default behavior, with explicit and auditable bridges rather
  than silent leakage.
- **Reflecting and consolidating.** Past notes, decisions, and reviews must remain available for
  revisiting, not be flattened into a passive archive.
- **Auditing what the system did on the human's behalf.** Every meaningful machine action should
  leave a receipt the human can read.

For the canonical inventory of human needs, see `docs/CONCEPTS/USER_NEEDS_MODEL.md`.

## 3. Distinguishing the kinds of state in the system

The charter relies on keeping the following kinds of state ontologically separate. Conflating
them is the most common failure mode the system is designed to avoid.

- **Human memory.** Lives in the human. Not stored in the system. The system supports it.
- **Human-authored knowledge artifacts.** Markdown notes, source-rich captures, project material,
  reflections, world-building. The vault is their canonical home. Their identity and provenance
  must survive any one runtime stack.
- **Agent memory.** Bounded, inspectable state that a system agent uses to act over time:
  delegations, prior receipts, working scratch, agent-scoped knowledge. It is owned by the
  agent's role and authority boundary, not by the human's knowledge surface.
- **Runtime state.** Ephemeral coordination state of the running system: queues, locks,
  in-flight events, watcher cursors, session state. It is rebuildable and never authoritative
  for human knowledge.
- **Machine mirrors and derived projections.** Databases, search indexes, embeddings, graph
  views, catalog projections. They exist to make the vault and agent activity addressable at
  runtime. They are disposable in principle; the canonical artifact wins on identity and content.

Concept-level contracts that anchor these distinctions:
`docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`, `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`,
`docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md`, `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`,
`docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`.

## 4. Why Markdown / vault artifacts are the primary durable surface

The human-facing knowledge surface is plain Markdown on the local filesystem, organized by a
catalog projection the human can read and walk without the system.

This is not a stylistic choice. It is a stability contract:

- **Comprehensibility beyond any one runtime.** If the runtime, model vendor, or framework
  changes — or disappears — the human's central artifacts remain readable and editable in any
  text editor.
- **Authorship and reversibility.** Human edits are the authoritative version of any human
  artifact. Machine edits to the vault go through write guards and produce receipts so they can
  be reviewed, reverted, or refused.
- **Portability.** Markdown plus metadata frontmatter is portable across OS, editor, and sync
  tooling without re-encoding meaning.
- **Local-first guarantee.** The human can use, read, and grow the vault offline; cloud services
  are optional additive surfaces, not load-bearing dependencies.

See `docs/CONCEPTS/PORTABILITY_CONTRACT.md` and `docs/FRONTMATTER.md`.

## 5. Why runtime surfaces exist (and remain subordinate)

Databases, search indexes, embedding stores, watchers, event buses, agents, and APIs exist
because a pure file tree is not enough to deliver a cognitive prosthesis. They provide:

- fast retrieval across a growing vault,
- structural views the file tree cannot express,
- coordination for asynchronous work,
- a substrate agents can act through safely,
- the audit and receipt trail that makes machine action legible.

These surfaces are *supporting* surfaces. They must remain:

- **Rebuildable from canonical artifacts** — never the source of truth for human knowledge.
- **Bounded by authority contracts** — agents act through receipts and intents, not by directly
  mutating human artifacts without trace.
- **Observable** — runs produce traces and receipts sufficient to explain what happened.

## 6. Why provenance, source authority, write guards, events, and receipts are mandatory

A cognitive prosthesis only works if the human can trust it. Trust requires:

- **Provenance** — every artifact and machine claim is traceable to its source.
- **Source authority** — imports retain attribution; the system does not launder external
  material into untraceable claims.
- **Write guards** — machine writes to human surfaces require explicit intent and produce
  reversible, auditable changes; "no silent edits" is an invariant, not a preference.
- **Events** — coordination uses versioned, append-only event/intent envelopes so behavior is
  reconstructable.
- **Receipts** — every meaningful machine action leaves a human-readable record of what
  happened, why, and on whose authority.

Without these, the system is a cloud-shaped assistant that happens to run locally. With them, it
is a prosthesis whose actions remain the human's actions.

## 7. What the system is not

To keep the charter honest, the system is explicitly **not**:

- A cloud-first product or a network-required assistant.
- A black-box agent that acts without traceability, consent, or reversibility.
- A single undifferentiated memory where work, private, creative, and hobby contexts freely mix.
- A prescriptive note-taking methodology or imposed taxonomy.
- A collaboration / multi-user knowledge platform. Single-user trust and stability come first;
  the architecture must not foreclose later multi-user evolution, but no multi-user work is
  scheduled.
- A platform-specific tool. macOS and Windows portability are product requirements.
- A vendor-locked stack. Model, framework, and retrieval choices are swappable; the kernel and
  contracts are not.

## 8. Failure modes that would violate the cognitive prosthesis purpose

Any of the following would mean the system has stopped being a cognitive prosthesis, regardless
of how well it performs on isolated metrics:

- **Silent machine edits to human artifacts.** Writes without intent, without receipts, or
  without reversibility.
- **Loss of provenance.** Answers, summaries, or proposed structure that cannot be traced back
  to the artifact or source that produced them.
- **Cross-domain leakage by default.** Private, work, creative, or hobby context bleeding into
  retrieval, suggestion, or write surfaces without explicit allowance.
- **Runtime becoming the source of truth.** The database, index, or agent memory diverging from
  the vault and being treated as authoritative for human knowledge.
- **Opaque agent state.** Agents accumulating durable behavior or memory that is not legible,
  bounded, or inspectable by the human.
- **Cloud dependence creeping into core flows.** Capture, retrieval, or commitment handling
  becoming inoperable without network or a specific vendor.
- **Artifact lock-in.** Central human artifacts becoming unreadable or unusable outside the
  current implementation.
- **Receipt rot.** Receipts that exist nominally but no longer reflect what actually changed.

These failure modes are the invariants that the architecture, contracts, gates, and review
cadence in the rest of the documentation exist to protect.

## 9. Relationship to the rest of the docs

- The **kernel** (`docs/PROJECT_KERNEL.md`) holds the long-lived stability contracts implied by
  this charter.
- **Human flows** (`docs/HUMAN-FLOWS.md`) describe the human-facing functions the prosthesis
  must support.
- **Architecture** (`docs/ARCHITECTURE.md`) describes the runtime substrate.
- **Concept contracts** (`docs/CONCEPTS/*.md`) define the ontological and semantic boundaries
  the charter depends on.
- **STATUS / ROADMAP** describe what is shipped today and what is planned next; this charter
  describes what the product is *for*.
