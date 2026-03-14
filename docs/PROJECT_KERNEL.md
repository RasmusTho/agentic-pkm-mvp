State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Core SoT
Authority: Product-kernel contract for purpose, principles, and long-lived stability constraints across the system; implementation docs must align with it without redefining it.

# PROJECT_KERNEL — agentic-pkm-mvp

## 1. North Star

**Purpose.** Build a local-first, cross-platform (macOS + Windows) personal knowledge system that helps a human capture, recall, curate, and ship work across distinct life domains without giving up authorship, privacy, or control. The human writing surface stays canonical; automation operates through explicit, auditable intents and produces reversible changes. The system treats both the warm vault and the cold “archive brain” (media, docs, projects) as first-class sources, with clear boundaries for trust and exposure.

**Non-goals.**
- A cloud-first product, or a system that requires network access to be useful.
- A “black box” assistant that acts without traceability, consent, or reversibility.
- A single undifferentiated memory where work/private/creative contexts freely mix by default.
- A prescriptive methodology for note-taking, taxonomy, or writing style.
- A platform-specific solution (must remain viable on macOS and Windows).
- An implementation tied to one model vendor, one agent framework, or one retrieval stack.
- A collaboration/multi-user knowledge platform before single-user trust and stability are proven.

## 2. Human Flows (product-level)

### Capture
Capture should feel effortless: drop a thought, a note, or an artifact into the right domain and trust bucket without “setting up the system”. Good looks like: the original content is preserved with provenance and a stable identity; the system may propose structure, but it never silently rewrites the human’s words.

### Recall / Ask
Recall should answer real questions with evidence: find the best sources, show what was used, and keep uncertainty visible. Good looks like: fast, source-grounded responses that respect domain boundaries (work stays work; private stays private) and allow the human to open the original warm note or cold object that informed the response.

### Curate
Curation should reduce entropy, not create chores: make it easy to accept, reject, or defer suggestions that improve findability and coherence. Good looks like: proposed tags/links/summaries are reversible and attributable; human intent stays authoritative; the system learns through explicit feedback and stable artifacts, not hidden state.

### Create / Ship
Creation should turn memory into output while keeping boundaries intact: drafts, briefs, plans, and artifacts emerge from grounded inputs. Good looks like: outputs are assembled in the target domain with provenance; the system does not “launder” archive material into untraceable claims; and it does not overwrite the source materials that fed the work.

### Archive & Retrieve (cold brain)
Archive should be a first-class brain, not a dumping ground: store and later retrieve from media, PDFs, emails, and project artifacts without forcing them into the note surface. Good looks like: cold objects remain immutable and portable; indexes are rebuildable; retrieval can cite cold sources safely; and exposure is constrained by domain and trust so sensitive private archives never bleed into work recall.

### Audit / Explain
Audit should make the system legible: the human can see what happened, why it happened, and what data it used. Good looks like: every answer has sources; every action has an intent and a receipt; and there is a coherent trail from outputs back to inputs, including which domain/trust rules were in effect.

## 3. System Principles (must always hold)

- **Human-first** — The system assists; it does not replace authorship. The default posture is “propose and explain”, not “decide and overwrite”.
- **Domain-first (domain separation)** — Every artifact and interaction is scoped to a domain (e.g., work vs creative/RPG vs private). Default retrieval, suggestions, and writes occur within the active domain; crossing domains requires explicit user intent and is recorded as such.
- **Warm/Cold separation** — Warm notes are human-edited and meant to be read/linked; cold objects are archived sources meant to be searched/cited. Derived artifacts (indexes, summaries, other machine views) are rebuildable and never become the source of truth.
- **Separation of trust** — Distinguish user-authored content, imported content, and machine-generated content. Lower-trust material can inform suggestions, but higher-impact actions and “claims” require evidence and, when appropriate, human confirmation.
- **Local-first + cross-platform** — The system works offline and stores user data in portable formats. Core behaviors and contracts must not depend on OS-specific quirks; portability is treated as a product requirement.
- **Observable by default** — Actions and runs emit structured traces and human-readable receipts. When something fails or surprises, diagnosis should be possible without guesswork.
- **Evolvable / modular** — Components can be swapped without rewriting the product philosophy. The kernel defines boundaries and contracts so the system can improve while remaining stable to the human.

Canonical layering story: the system uses four orthogonal dimensions — Domain, Plane, Trust, Zone — to describe boundaries without conflating them. See `docs/CONCEPTS/LAYERING_MODEL.md` for definitions and the cross-domain “bridge” concept.

Cross-platform constraints are defined in `docs/CONCEPTS/PORTABILITY_CONTRACT.md`. Archive exposure and safety (discovery → materialization) are defined in `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`.

## 4. Stability Contracts (what must remain stable over time)

- **Canonical artifacts (portable representations)** — Warm notes and cold objects have stable identities, provenance, domain, trust, and timestamps. Their canonical forms are portable and readable without the system; derived representations are disposable and rebuildable.
- **Exposure rules (domain + trust as contracts)** — Domain and trust classification are first-class, consistently applied constraints on retrieval, suggestion, and write targets. Cross-domain exposure requires explicit intent and must be auditable.
- **Event/intent schema discipline (versioned contracts)** — System coordination uses versioned, append-only event/intent envelopes with stable semantics and idempotence expectations. Producers and consumers must tolerate forwards-compatible evolution (new fields, new event types) without breaking older artifacts.
- **Store boundaries (interfaces, not implementations)** — Object storage, search indexing, and relation/graph storage are separate responsibilities with explicit interfaces. Indexes and caches are treated as derivative; objects and their provenance remain authoritative.
- **Config-as-product** — Configuration is user-facing, validated, versioned, and portable. Changes are observable and safe by default; invalid configuration degrades gracefully and predictably.
- **Evaluation gates (regression protection)** — The system maintains explicit fitness checks for key invariants: source-grounded recall, no cross-domain leakage, idempotent re-runs, rebuildable indexes, and “no silent edits”. Gates exist to protect trust, not to optimize a single metric.

Trust semantics (ASSERT vs SUGGEST vs APPLY) are defined in `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`. Event/intent versioning and backward/forward compatibility are defined in `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`. Config-as-product constraints are defined in `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md`.

## 5. Agentic AI Positioning (cutting-edge, but disciplined)

This project supports modern agentic patterns as *architectural families*, not framework choices:

- **Plan → Act → Reflect loops** for bounded, stepwise work where each step is inspectable and failures are recoverable.
- **Plan-and-execute variants** where planning outputs are explicit artifacts and execution happens through constrained tool actions with receipts.
- **Reflection/reflexion-style improvement loops** where outcomes and feedback refine prompts/policies/evaluations as versioned artifacts, rather than hidden adaptation.
- **Memory tiers / external memory principle** where durable knowledge lives in inspectable stores (warm notes, cold archive, relations), and model context is treated as a temporary view over those stores.
- **AgentOps / observability discipline** where every run produces traces, counters, and audit records sufficient to debug behavior, compare changes, and enforce safety boundaries.

## 6. Tensions / Follow-ups

- Planes/zones are discussed widely, but the canonical Domain/Plane/Trust/Zone model now lives in `docs/CONCEPTS/LAYERING_MODEL.md`; follow-up is to reference it consistently where boundaries are explained.
- We are running an experiment policy: default scope = active domain + global evergreens, with domain excludes (work excludes rpg) and one-shot explicit includes; validate UX before hardening.
- Several “human flow” and “components” docs embed implementation details (flags, endpoints, tool names) that the kernel intentionally avoids; we should decide which docs are kernel-level contracts vs implementation manuals.
- Some documents describe specific agent framework choices by name; the kernel describes framework-agnostic pattern families, so we should later de-framework the top-level architectural phrasing where appropriate.
- Archive exposure safety is now defined in `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`; follow-up is to reference it consistently where cold archive behavior is described.
- Cross-platform portability is now defined in `docs/CONCEPTS/PORTABILITY_CONTRACT.md`; follow-up is to reference it consistently where portable artifacts and path-like references are described.
- Trust semantics and gating expectations are now anchored in `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`; follow-up is to reference it consistently where flows describe assertions, suggestions, and durable changes.
- Event/intent versioning and backward/forward compatibility are now anchored in `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`; follow-up is to reference it consistently where event/intent contracts are described.
- Config-as-product constraints are now anchored in `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md`; follow-up is to reference it consistently where configuration is described.
- Component maturity language is not always consistent (e.g., “planned” vs “baseline/stable” in the same catalog); we should reconcile maturity taxonomy against the kernel’s stability contracts.

## 7. Doc Boundary (Kernel/Contracts vs Implementation Manuals)

Kernel/contract docs define product intent, invariants, and stability contracts. They must avoid operational specifics and remain valid even when components are swapped or upgraded.

Implementation manuals describe current wiring, operations, and “how it works today”. They may change frequently; when they do, they must reference the relevant contract(s) and clearly distinguish what is stable vs merely current.

If a document needs both, split it (or separate “Contract” from “Current Implementation”) so contract statements remain easy to find and hard to accidentally dilute.

## 8. Sources

- docs/ARCHITECTURE.md
- docs/ROADMAP.md
- docs/STATUS.md
- docs/COMPONENTS.md
- docs/AGENTS.md
- docs/EVENTS.md
- docs/HUMAN-FLOWS.md
- docs/DOCS_INDEX.md
