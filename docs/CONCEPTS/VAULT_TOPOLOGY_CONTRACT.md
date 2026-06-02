State: SoT v5.5 baseline; v6 active planning direction. Names which vault layouts the system tolerates as legitimate topologies; not a current-state claim that every topology described here is operationally exercised.
Doc role: Concept contract
Authority: SoT for the topology rules a vault layout must satisfy to remain compatible with human authority, vault-first durability, provenance, and orientation. Does not prescribe a default topology, does not mandate multi-vault setups, and does not change runtime paths.
Owner: Architecture / product
Temporal class: strategic
Review cadence: event-driven
Source of truth: SoT
Last reviewed: 2026-06-02
Last verified against: docs/HUMAN-FLOWS.md, docs/HUMAN_FLOW_TO_RUNTIME_MAP.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, docs/COMPANION_UI_PRODUCT_SPEC.md, docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md, docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md, docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md, docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md, #1488

# Vault Topology Contract

> Audience: readers shaping how human-authored material, retained source material, and system bookkeeping are physically laid out on disk. Read `docs/SEPARATING_PERSISTENCE_SURFACES/README.md` first for the writing / retention / system surface vocabulary; this contract is about which **vault layouts** are legitimate carriers of those surfaces, not about renaming the surfaces themselves.

This contract names the vault topologies the system treats as legitimate, and the rules every topology must satisfy. It does not move folders, change runtime paths, or migrate artifacts. It does not prescribe a default. The current shipped baseline is a single human vault; the topologies below are the layouts the architecture is allowed to evolve toward without losing human authority, provenance, or orientation.

## What a vault is here

In this contract, a **vault** is a human-addressable, vault-first, Markdown/attachment-bearing tree that the human can open, read, and edit without the runtime. It is the durable human surface defined by `docs/PROJECT_KERNEL.md` and `docs/HUMAN-FLOWS.md`. Databases, indexes, mirrors, receipts, and runtime caches are not vaults; they are system-surface artifacts that may live inside a vault tree or alongside it, governed by `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`.

A **topology** is the choice of how many such vaults exist, which surfaces (writing, retention, system) each one carries, and how they relate to each other for the same human.

## Runtime topology authority decision (#1488)

The current runtime default for Vault Browser reads is **active-vault only**. The active vault filesystem is the enumeration source, Markdown/frontmatter remains the human-readable authority surface, and current `zone` projection is frontmatter-preferred with a vault-relative path fallback. No configured topology registry, multi-vault selector, graph projection, or semantic neighborhood source is authoritative for browser reads today.

The current `zone` field is a cognitive-distance overlay. Its authority order is:

1. Frontmatter `zone`, when present, as durable vault metadata under the human/vault authority model.
2. First vault-relative path segment as deterministic browser fallback when frontmatter `zone` is absent.

The path-derived fallback is runtime projection, not durable topology authority. It must not rewrite frontmatter, define artifact lifecycle, imply maturity, imply review posture, imply trust, or become a hidden source of semantic ranking. Runtime consumers may read it only as the current browser-compatible fallback for orientation and deterministic filtering.

Future topology-derived browser fields are allowed only as explicit projections over a named source. Each field must carry, or be accompanied by, all of the following:

- `source`: the configured topology source or vault-derived source used to derive the field.
- `authority_role`: whether the field is durable vault metadata, runtime projection, generated mirror, or unavailable.
- `provenance`: the concrete path, frontmatter key, registry entry, receipt, or mirror record used to derive it.
- `degradation`: explicit unavailable/stale/conflict/missing-source state when the topology source cannot be trusted.

When a future topology source is missing, stale, conflicting, or not configured, runtime consumers must degrade to the current active-vault frontmatter/path posture and expose that degradation. They must not fabricate topology, silently prefer a machine mirror, or mutate vault/frontmatter authority to make a projection complete.

Topology-derived zones may be used as explanatory metadata only until a later bounded implementation issue defines their source, fields, UI treatment, and tests. Any future use for ordering, overlays, or filters must surface the contributing topology signal, weight or deterministic rule, provenance, and degradation state in the browser response or UI. Opaque semantic ranking remains out of scope.

#1473 remains deferred after this decision. It may be rewritten or split only into bounded implementation issues that name the concrete topology source, the projection fields, the degradation behavior, and the visible ranking/filter/overlay signals. Until then, the shipped Vault Browser posture remains frontmatter-preferred/path-derived zone projection over the active vault.

## Allowed topologies

The system recognizes three legitimate topologies. Each is allowed; none is mandatory.

### 1. Single vault with internal surfaces

One human vault. The writing, retention, and system surfaces are distinguished **inside** that vault — by folder convention, frontmatter, companion notes, and naming — rather than by separate trees.

- Writing surface: human-authored notes at the root of the human-organized folder structure.
- Retention surface: source-rich material kept inside the same vault under retention-marked folders or frontmatter classes.
- System surface: companion notes, receipts, and indexes co-located with the artifact they describe, or under a clearly system-marked subtree, never silently shadowing human-authored material.

This is the current shipped baseline. It is the simplest topology and the one against which every other topology must remain reversible.

### 2. Human vault plus retention/system surfaces in adjacent vaults

One primary human vault for the writing surface, with one or more adjacent vault trees that carry the retention surface, the system surface, or both. Each adjacent vault is still vault-first (human-readable, openable without the runtime), but is operationally separated from the writing surface to reduce noise in the human's primary working surface.

- Writing surface: the primary human vault.
- Retention surface: may live in the primary vault or in a dedicated retained-artifact vault (e.g. an archive/source brain layout per `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md`).
- System surface: may live in the primary vault or in a dedicated system-surface vault containing companion notes, receipts, traces, and indexes.

This topology is allowed when separating the surfaces into adjacent vaults makes the human's primary working surface easier to orient in, not harder. It must not turn the system-surface vault into a hidden source of meaning.

### 3. Master / satellite vaults

A master vault plus one or more satellite vaults belonging to the same human, each carrying a bounded scope (for example, a role, a project, a domain). Each satellite is a full vault on its own terms; the master vault remains the orientation surface across satellites.

- Writing surface: distributed across master and satellites, with each satellite carrying its own bounded writing surface.
- Retention surface: per satellite, with cross-satellite retention either centralized in the master or explicitly shared.
- System surface: per satellite, with cross-satellite receipts and indexes either centralized or explicitly federated.

This topology is allowed when satellite boundaries match real cognitive or authority boundaries (role identity, organizational separation, confidentiality scope) per `docs/CONCEPTS/USER_NEEDS_MODEL.md`. It must not be used as a workaround for missing scope, retrieval, or context-bundle behavior in a single vault.

## Topology rules

Multiple vaults are allowed when, and only when, they preserve the cognitive and authority boundaries the system already commits to. Every topology — single, adjacent, or master/satellite — must satisfy all of the following.

1. **No hidden source of truth.** No vault in the topology may carry meaning that is not also discoverable from the human-addressable surface. The system surface, wherever it lives, must remain a mirror/receipt/index layer per `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` and `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`. A retention vault may hold source-rich material the human did not author, but its retained-artifact status must be legible from the artifact itself, not only from runtime state.
2. **No split artifact identity.** A given artifact has one identity across the topology. Two vaults may hold a mirror, a companion note, or a projection of the same artifact, but they must not each present themselves as the primary artifact. Identity is governed by `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` and `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`; topology must not silently fork it.
3. **No harder orientation.** A topology must make the human's `Retrieve -> orient -> act` flow (per `docs/HUMAN-FLOWS.md` and `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`) easier or at worst neutral. If adding a vault forces the human to remember which vault to look in before they can re-enter their own material, the topology has failed this rule.
4. **Cognitive and authority boundaries are real.** A satellite or adjacent vault is only justified when it matches a real boundary — a role identity, a confidentiality scope, a separable operational scope, or a separable retention/system surface. Vaults must not be introduced to model arbitrary categories the human could express inside one vault.
5. **Human authority and provenance survive the split.** Every topology must preserve human authority over machine edits, provenance for retained material, receipts for executed intents, and write guards on machine-touched artifacts, per `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`, `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`, and `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`. A topology that weakens any of these is not a legitimate topology.
6. **Reversibility to single vault.** Every multi-vault topology must remain reducible to a single-vault topology without loss of meaning, attribution, or receipts. The single-vault layout is the floor of the contract.

## What this contract does not do

This contract does not:

- prescribe a default topology, or claim multi-vault is the target;
- move files, rename folders, or change runtime paths;
- change ingest, retrieval, or write-guard behavior;
- define companion-ui implementation, onboarding flow, or any UI surface;
- change context-bundle, memory, or sync semantics;
- replace `docs/SEPARATING_PERSISTENCE_SURFACES/README.md` as the SoT for the persistence surface trichotomy; this contract is the topology layer on top of that vocabulary.

## Relationship to neighbouring contracts

- `docs/SEPARATING_PERSISTENCE_SURFACES/README.md` — names the three persistence surfaces this contract distributes across vaults.
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` — governs artifact identity across mirrors and projections, including across vaults.
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` — governs per-note system-surface co-location, including the case where companion notes live in a separate system-surface vault.
- `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md` — governs retention-surface behavior, including the case where retained source material lives in a dedicated retention vault.
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — the product/UI shell that hosts surfaces over whatever topology the human has chosen; companion-ui must work across all allowed topologies without preferring one.
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` — bridges human flows to the runtime; topology choices must keep this mapping legible.

## Acceptance reading

A topology is compatible with this contract when a reviewer can answer all of the following without consulting runtime state:

- Which vault carries the writing surface for this human?
- Where does the retention surface live, and is its retained-artifact status legible from the artifact itself?
- Where does the system surface live, and is it clearly a mirror/receipt/index layer rather than a source of meaning?
- For any given artifact, which vault holds its primary identity?
- Does removing every non-primary vault still leave the human with a coherent, attributable, receipt-bearing record of their work?

If any of those answers requires runtime state to resolve, the topology has drifted out of this contract and needs repair before it is treated as legitimate.
