State: SoT v5.5 Reality-MVP baseline locked (v5.6 delivered, v6.0 seams shipped at capability-seam level); this document is target-state framing for the integration fabric and does not claim every integration class is uniformly implemented today.
Doc role: Core SoT
Authority: Contract spine for how external components attach to Yggdrasil. Owns the integration-class taxonomy and the per-class contract fields (allowed role, authority limits, persistence class, provenance requirement, event boundary, health/observability expectation, replacement strategy). Sits below `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` (Integration Fabric subsystem) and above the narrower adapter contracts (`docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`, `docs/contracts/A2A_CONTRACT_AND_TRACE.md`, `docs/LLM.md`, `docs/EMBEDDINGS.md`, `docs/CONCEPTS/CLOUD_CONNECTORS_DECISION.md`). Does not replace `docs/ARCHITECTURE.md` for current runtime behavior.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-14
Last verified against: docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, docs/PROJECT_KERNEL.md, docs/ARCHITECTURE.md, docs/COMPONENTS.md, docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md, docs/contracts/A2A_CONTRACT_AND_TRACE.md, docs/LLM.md, docs/LLM_ROUTING.md, docs/EMBEDDINGS.md, docs/CONCEPTS/CLOUD_CONNECTORS_DECISION.md, docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, docs/AGENTS.md, parent initiative #877, prerequisite phase issue #878, governing slice issue #879.

# Integration Fabric Contract

This document defines how internal and external components attach to Yggdrasil through the Integration Fabric subsystem named in `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`. It is a docs-only contract: it does not introduce a runtime integration registry, runtime enforcement, or new tests.

The contract has three purposes:

1. Name the **integration classes** Yggdrasil composes with, so attachment work is bounded and legible.
2. Define the **contract fields** every integration class must answer, so a new integration cannot quietly become semantic authority or a hidden source of truth.
3. State the **authority rule** that separates "external thing providing capability, transport, inference, or interface" from "external thing being promoted into Yggdrasil's semantic authority."

This document is target-state framing. Several integration classes already have shipped adapters and contracts; others are described here so later attachment work has a stable place to anchor.

## Reading rules

- The integration fabric is part of the extension fabric (see `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`). Integration components are expected to be added, replaced, or removed over time without changing the kernel.
- Every integration class below must respect every kernel constraint in `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` (`Kernel and extension fabric`): human-first authority, vault-first durability, provenance/receipts/write guards, local-first operation, event/outbox compatibility, authority separation, and the single-user/single-vault baseline.
- Current behavior for any specific adapter remains owned by its narrower contract doc (MCP/tools, A2A, LLM/embeddings, cloud connectors). This document does not restate those contracts; it gives them a common shape.
- Target-state language in this document is distinct from current runtime claims. Where an integration class is partially shipped, the per-class entry says so explicitly.

## Integration classes

Yggdrasil composes with ten integration classes. Each class is a category of external component that crosses a Yggdrasil boundary. A given concrete integration is typically an instance of one class (for example, a specific LLM vendor SDK is a Model provider).

A concrete integration may legitimately participate in **more than one class** when it plays more than one role at the same Yggdrasil boundary. Obsidian is the canonical example: it is both the **Human surface** the human writes in (the durable surface where vault Markdown is authored) and the **External UI shell** that hosts Yggdrasil's in-note Panel surface and consumes the runtime API. When an integration spans classes this way, every applicable class's contract fields (allowed role, authority limits, persistence class, provenance requirement, event boundary, health/observability expectation, replacement strategy) must be answered for the integration's behavior in that role. The classes do not blend; the integration answers each contract surface in turn.

The ten integration classes are:

1. **Human surface** — external editor, browser, terminal emulator, OS-level UI shell that the human uses to interact with the vault or with Yggdrasil interaction surfaces (Obsidian, OS shell, browser hosting the HTTP API, future companion-UI host).
2. **Model provider** — external chat/completion/reasoning model service or local model runtime (cloud LLM API, local model server, on-device model).
3. **Embedding provider** — external or local embedding model service or runtime that produces vector embeddings consumed by indexing/retrieval.
4. **Storage backend** — external durable store that holds runtime projections, not durable human meaning (Postgres/pgvector, future vector stores, future relation stores, future blob stores).
5. **Sync transport** — external mechanism that moves vault files or system-owned files between devices (iCloud, Dropbox, Git, future replication transports). Sync transports are operational plumbing only; they are never the semantic source of change.
6. **Parser / OCR** — external content-extraction service or library that converts non-Markdown source material into text or structured content (PDF parser, OCR, HTML-to-text, future structured extractors).
7. **Tool / MCP provider** — external tool surface invoked by agents through the descriptor registry and MCP adapter contract (built-in tools, governed real tools such as `mcp.vault.append_note`, remote MCP servers behind the flagged multiplex seam, future tool servers).
8. **External UI shell** — external interactive shell that hosts Yggdrasil surfaces or consumes its API (Obsidian as host, companion-UI implementations, future operator dashboards, third-party UIs). Distinct from "human surface" because the UI shell is the runtime container, not the human itself.
9. **Observer / telemetry source** — external observability or telemetry destination that consumes status, health, events, traces, or metrics (Prometheus, Grafana, log aggregators, future tracing backends).
10. **Agent runtime** — external agent process, A2A peer, or remote orchestrator that participates through governed contracts (currently bounded in-process A2A routing and future remote agent runtimes).

These ten classes are deliberately broad. A new integration that does not fit one of them is a signal to revisit this taxonomy at the architecture level, not to invent a hidden eleventh class inside an adapter.

## Contract fields

For each integration class (and for each concrete integration within a class), the following fields must be answerable. If a field cannot be answered, the integration is not ready to attach.

- **Allowed role** — what this integration is permitted to do for Yggdrasil. Phrased in terms of capability, transport, inference, or interface. Never in terms of "owns this meaning."
- **Authority limits** — what this integration is explicitly not permitted to do. At minimum: it must not become semantic authority over the vault, it must not bypass governance/authority surfaces to mutate the durable surface, and it must not become a hidden source of truth.
- **Persistence class** — what this integration is allowed to persist, where, and under what durability claim. Answers must distinguish: durable human meaning (vault Markdown — almost never written directly by an integration), system-owned continuity (companion notes — only through governed paths), runtime projection (rebuildable from vault + companion set), and external durability (lives outside Yggdrasil, treated as opaque to the durable surface).
- **Provenance requirement** — what provenance must accompany any output or side effect from this integration so the result can be traced back through the event envelope, receipts, and governance layer. Includes integration identity, model/version where applicable, and trace correlation.
- **Event boundary** — how this integration crosses into the rest of Yggdrasil. Side effects that affect runtime state or the durable surface must cross through the event envelope (`app/events/schema.py`, `docs/EVENTS.md`, `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`) or through an explicit typed capability contract. Bespoke side channels are not allowed.
- **Health / observability expectation** — what the rest of the system must be able to see about this integration: liveness, error class, latency, failure mode, fallback posture, and provenance of fallback. Failures must degrade legibly per `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` (`How kernel and extension fabric compose`).
- **Replacement strategy** — how this integration can be replaced or removed without violating the kernel. Includes: deterministic fallback or local-first alternative where required, contract surface that lets a successor integration attach without rewriting callers, and migration posture for any external durability it owned.

These fields are the integration-fabric contract surface. A new integration adapter is not blocked on a new doc; it is blocked on answering these fields somewhere authoritative (typically the narrower adapter contract doc).

### Per-class summary

The table below is a target-state summary. Where a class already has a shipped adapter contract, the owner doc is named and remains authoritative for current behavior.

| Integration class | Allowed role (typical) | Authority limit (kernel-binding) | Persistence class | Event boundary | Owner contract doc(s) |
| --- | --- | --- | --- | --- | --- |
| Human surface | Interface | Not semantic authority; never bypasses governance | Durable human meaning (vault); the human writes, not the surface | Through user-originated events and Panel/Chat/CLI/API actions | `docs/HUMAN-FLOWS.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md` |
| Model provider | Inference | Not semantic authority; outputs are proposals under governance | None inside Yggdrasil (external durability is opaque) | Through capability/agent contracts that wrap model calls; receipts on any APPLY | `docs/LLM.md`, `docs/LLM_ROUTING.md` |
| Embedding provider | Inference (vector projection) | Not semantic authority; embeddings are derived and rebuildable | Runtime projection only (VectorIndex) | Through embedding-related events and rebuild commands | `docs/EMBEDDINGS.md` |
| Storage backend | Transport / durability for runtime projections | Never owns durable human meaning; vault + companion set must remain sufficient for rebuild | Runtime projection (ObjectStore, VectorIndex, RelationIndex, outbox) | Through the DB outbox envelope; direct store reads are allowed for rebuildable projections | `docs/ARCHITECTURE.md` (`Component Catalog`, `Concurrency & Idempotency`), `docs/COMPONENTS.md` |
| Sync transport | Transport | Never semantic source of change; file-based eventual consistency is the architectural truth | None (moves files; persistence is the vault filesystem) | Through watcher/worker reactions to changed files | `docs/ARCHITECTURE.md` (`Operational topology`), `docs/CONCEPTS/CLOUD_CONNECTORS_DECISION.md` |
| Parser / OCR | Capability (content extraction) | Not semantic authority; produces ingestible content with provenance | Runtime projection (external corpus plane) or staged input; durable human meaning only through governed promotion | Through ingestion events and provenance metadata | `docs/ARCHITECTURE.md` (`Current Runtime Surfaces` — external corpus ingest), `docs/COMPONENTS.md` (`Optional extension points`) |
| Tool / MCP provider | Capability (effectors) | Not semantic authority; all tool calls under tool policy + governance | Depends on tool; vault-touching tools (e.g., `mcp.vault.append_note`) only via governed real tools | Through descriptor registry, tool policy, and event envelope; trace correlation required | `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md` |
| External UI shell | Interface (runtime container) | Not semantic authority; container does not decide meaning | None inside Yggdrasil (shell-local state is opaque) | Through the HTTP API and event envelope | `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`, `docs/COMPANION_UI_PRODUCT_SPEC.md` |
| Observer / telemetry source | Interface (read-only) | Read-only; never writes back to vault or runtime state | None inside Yggdrasil (telemetry destination owns its own storage) | Through status/health endpoints and emitted observability events | `docs/OBSERVABILITY.md`, `docs/HEALTH.md`, `docs/STATUS.md` |
| Agent runtime | Capability / orchestration | Not semantic authority; agents propose under governance and respect authority separation | None directly; mutations go through governance/authority and event envelope | Through A2A contract and event envelope; trace correlation required | `docs/contracts/A2A_CONTRACT_AND_TRACE.md`, `docs/AGENTS.md` |

The table is a summary, not a substitute for the per-integration contract. Health/observability and replacement strategy details belong in the owner contract doc for each integration class.

## Authority rule

The authority rule is the kernel-level constraint that distinguishes the integration fabric from the rest of Yggdrasil.

- External components may provide **capability** (a reusable function such as retrieval reranking or content extraction), **transport** (moving bytes, files, or events between places), **inference** (model outputs over inputs), or **interface** (a surface the human or another system interacts with).
- External components must **not** become **semantic authority** over the durable surface unless they are promoted through Yggdrasil contracts. "Semantic authority" means: deciding what a vault note means, owning the canonical value of a Core-6 field, originating a write to the durable surface without governance, or being treated as the source of truth for any human-facing concept.
- "Promoted through Yggdrasil contracts" means: an explicit, named, authoritative contract document (typically an owner doc under `docs/`) describes the promotion, names the governance path, names the provenance and receipt requirements, and names the kernel constraints it must continue to respect. A code change is not a promotion. A new adapter is not a promotion. A new vendor relationship is not a promotion.
- Any integration that would weaken human-first authority, vault-first durability, provenance/receipts/write guards, local-first operation, event/outbox compatibility, or authority separation is a kernel change. It must be argued for at the kernel level, not introduced inside an adapter.
- An integration that fails or is unavailable must degrade legibly. It must not silently take over authority, hide the failure from the human, or invent a fallback that violates governance.

This rule is the load-bearing line of this document. Everything else in this contract serves it.

## Out of scope for this document

This is the integration-fabric **contract**, not the integration-fabric **runtime**. The following are intentionally not defined here:

- A runtime integration registry, runtime enforcement, capability registry, or runtime contract validator. Those are implementation lanes opened from initiative #877, not docs-only contracts.
- Per-adapter behavior, retry/backoff, timeout, and SLA detail. Those are owned by the narrower contract docs (`docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`, `docs/contracts/A2A_CONTRACT_AND_TRACE.md`, `docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md`, `docs/LLM.md`, `docs/EMBEDDINGS.md`).
- The capability contract model itself — defined separately in `docs/CAPABILITY_CONTRACT_MODEL.md`.
- Current runtime contracts and current-vs-planned status — owned by `docs/ARCHITECTURE.md`.
- Kernel constraints and the subsystem map — owned by `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`.

## Verification path

This document is verified by the existence of:

- an `Integration classes` section that names the ten classes (human surface, model provider, embedding provider, storage backend, sync transport, parser/OCR, tool/MCP provider, external UI shell, observer/telemetry source, agent runtime),
- a `Contract fields` section that defines, for each class, allowed role, authority limits, persistence class, provenance requirement, event boundary, health/observability expectation, and replacement strategy, and
- an `Authority rule` section that states external components may provide capability, transport, inference, or interface but must not become semantic authority unless promoted through Yggdrasil contracts.

`docs/ARCHITECTURE.md`, `docs/COMPONENTS.md`, and `docs/DOCS_INDEX.md` point to this document without duplicating its content.
