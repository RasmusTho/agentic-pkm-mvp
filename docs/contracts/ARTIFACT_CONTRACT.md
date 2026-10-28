State: Partial implementation: dormant versioned semantic edits are shipped; broader artifact lifecycle and representation generalization remain target state.
Doc role: Contract
Authority: Owns human artifact identity, origin, survivability, and the bounded semantic source representation; broader lifecycle expectations remain target state.
Owner subsystem: HKA - Human Knowledge & Artifact Substrate
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-10-28

# ArtifactContract

## Purpose

Protect durable human-authored and human-accepted knowledge artifacts so human knowledge survives loss of machine-generated artifacts.

## Inputs

- Human-authored artifact content.
- Human-accepted machine contribution.
- Source-at-entry and artifact-origin facts.
- Ownership markers: human, system, imported, agent-promoted.
- Durability class and lifecycle state.

## Outputs

- Human artifact identity.
- Portable representation.
- Artifact-origin provenance carried with or recoverable from the artifact.
- Lifecycle state and migration status.
- Source references for SIP/DRI/RCA/MEM projections.

## Commands

- Create artifact.
- Apply governed mutation.
- Accept machine contribution.
- Migrate representation.
- Export or recover artifact.

The dormant AUTOOPS-08 versioned local body-edit path may pass an optional original
`admission_deadline` through KnowledgePort and the existing absolute writer. The FS adapter checks
it after native admission at actual CAS/conflict publication. A deadline cannot authorize a write
or extend a native token/context; unsupported non-CAS and Obsidian CLI routes refuse that opt-in
before effects. Existing callers without it retain their behavior.
The shared initially-stale conflict publisher invokes the FS owner's existing final guard after
candidate persistence and at every actual public-link attempt. This includes semantic owned
approval/selection checks when present, as well as the optional original deadline. Already-public
evidence is preserved for native receipt/accountability even when later work crosses expiry.

### Dormant semantic commands (AUTOOPS-06)

`app.knowledge.semantic.KnowledgeSemanticOwner` owns the source semantics for the directly
composable `artifact.classify`, `artifact.tags.add`, `artifact.tags.remove`, and
`collection.reorder` handlers in `app/operations/semantic_operations.py`. They are not installed
in HTTP, GUI, MCP, or a runtime singleton. Authenticated installation belongs to #5352;
capability acceptance belongs to #5329.

Each command targets one existing human note by its frontmatter `uuid`, with a caller-supplied
SHA-256 version over the exact raw bytes read by `read_note_text_with_version`. UUID resolution
uses the actual source notes within the server-selected vault binding, without UUID healing or
registry initialization. Duplicate, unresolved, aliased, system/companion, nested-vault, and
out-of-binding identities refuse admission. Retained Sources and the capture append artifact
cannot be semantic write targets. The selected Sources directory comes from its existing layout
resolver. These restrictions apply only to these admitted writes; ordinary render/ingest/read
paths gain no UUID or frontmatter migration requirement.

Classification admits only `artifact_class` and `artifact_type`. Class values are
`human_knowledge`, `fleeting_capture`, `daily_log`, `shopping_list`, `checklist`, `project_note`,
`area_dashboard`, `source_note`, `literature_note`, `media_note`, `screenshot_note`,
`scan_or_receipt_note`, `email_summary`, `youtube_source_note`, `contact_note`, `decision_record`,
`reflection_note`, `evergreen_note`, and `synthesis_note`, from the existing human-knowledge
vocabulary in `ARTIFACT_METADATA_CONTRACT.md` §5. The admitted subtype values in this bounded
implementation are the already documented `concept_note` and `photo`; it does not invent a
subtype vocabulary. Requested classification values are stripped and lowercased, then checked
against those sets. Existing unrelated fields are preserved. Agentic memory, bridge, mirror,
companion, and unaccepted proposal artifacts cannot become human knowledge through these
commands. Classification cannot implicitly change lifecycle, maturity, review, trust, or authority.

Tag arguments and the existing `tags` value must be lists of strings. Names are stripped, leading
`#` characters are removed, and names are lowercased, deduplicated, and sorted. Empty names,
whitespace/control characters within names, malformed lists, and the ambiguous legacy `tag`
field refuse the write. These are human navigation tags; relation/provenance tags and model
classifier output supply no mutation authority.

`collection.reorder(container_id, ordered_ids, expected_version)` uses the envelope's sole
`artifact_id` target as `container_id`. Its source representation is a top-level frontmatter
`member_order` list of stable artifact UUID strings on that existing note. The existing list is
the complete authored membership snapshot. The requested list must contain each member exactly
once and no other members. UUID spelling is normalized to lowercase hyphenated form before
duplicate and set comparisons. Every member must resolve uniquely to a human note in the same
selected binding. An explicitly authored `member_order: []` permits the empty permutation.
Missing/null/uninitialized/malformed lists, duplicates, omissions, extra members, and unresolved
or out-of-context members refuse before source mutation. The operation never initializes the list,
changes membership, creates a container, edits member notes, synthesizes inverse relations, or
uses DB/search/Panel/folder order as membership evidence. Source membership and order share one
raw-byte version and one HKA CAS; a concurrent edit conflicts.

The frontmatter must be a complete block mapping with unique string keys; malformed YAML,
merges, anchors, and aliases require explicit repair. Only selected field values are spliced,
preserving source body bytes, UUID, provenance, and unrelated frontmatter bytes/comments. There
is no arbitrary metadata writer.

The trusted composition must supply the exact normalized `SemanticIntent`'s applicable explicit
human semantic approval as an existing GOV `GovernedWriteGrant`, plus a mandatory held
`semantic_authority_window(intent, grant)`. Construction refuses missing approval/window ports;
point-check-only booleans and a no-op window are not supported producers. The grant must carry a human-review
decision and match actor, action (`operation.<operation_id>`), `vault_semantic_edit`, source
resource, complete immutable `ActiveContextSetV1`, and selected target binding. A generic body-edit
grant, machine suggestion, kernel policy allow, or relation edge cannot substitute for this
approval. Human-present Canvas keeps its accepted body-only policy (#4932).

The existing context-bound GOV write window holds principal, ownership, and binding leases. Inside
it, the trusted producer holds WSP's opt-in `ContextSelectionStore.read_effect_window` over the
captured immutable selection record, then the exact approval owner's read/effect fence. Every
approval mutation must use that same owner's lock and copy-on-write record. The producer binds
the raw record to the exact resolved snapshot and original grant; resolver-adjusted snapshot
generation is not compared directly with the raw selection generation. Raw bearers remain in the
server closure and never enter source or receipts. No new approval store, issuer, TTL, or token
refresh is supplied here.

The yielded final guard reads the captured approval record, then the captured selection record,
under their held locks. It is owned, nonblocking, and performs no resolver, clock/prune,
filesystem, or arbitrary port callback. Concurrent selection/approval changes wait for the window;
same-thread reentrant clear, replacement, or revocation invalidates this guard before publication.
This is an opt-in semantic current-selection requirement; ordinary WSP consumers retain their
existing frozen in-flight snapshots. Resolve before taking the selection-store lock: resolver
resolution can invalidate a selection and therefore already takes locks in resolver-to-store order.
Approval mutations must not hold their lock while entering selection/resolver/binding operations.

Both windows span the HKA CAS and durable source/authority receipt event. At the rewritten-note
seam, health, registry and locator admission precede the final source census: every semantic
family revalidates its target UUID, and reorder also revalidates its complete member UUIDs.
Target ambiguity or locator drift therefore refuses after preceding owner/CAS waits. This source
validation and all approval lookup work finish before the final owned guards;
only static exact GOV token/context validation and immutable expiry checking follow them,
immediately before exchange or staged-conflict publication. An entry-time approval or held lock
never extends the lifetime. A typed state-owner pre-publication refusal is distinct from an
unproven receiptless effect. A window exit failure preserves any prior committed/unknown effect
and original receipts for recovery. `write_note_from_absolute` routes the selected
binding explicitly into its locator; the existing adapter owns filesystem mechanics.

Identity discovery retains decoded YAML nodes, including duplicate declarations and completed
UUID/merge children inside a later failing collection. A later syntax error cannot hide an earlier
decoded requested UUID through quoted escapes. Partial nodes identify candidates for refusal;
they never supply authorized identity, membership, or mutation content. Matching candidates still
require complete strict metadata. UUID-looking prose or unrelated nested fields do not make an
unrelated malformed note a matching candidate or impose a whole-vault repair requirement.

Source `WriteReceipt`, policy/token, immutable `AuthorityReceipt`, operation/actor/context/target,
input/result versions, and normalized changes are preserved in the existing durable outbox event
before success can be acknowledged. The execution kernel persists its existing reservation and
receipt/recovery outcome. A stale read returns `conflicted`; a later CAS conflict preserves the
HKA staged proposal and failed AuthorityReceipt with canonical source `not_applied`. Missing or
mismatched approval returns `rejected`; invalid metadata/membership returns `invalid`.
Receiptless source failures retain `unknown` effect truth; a known applied source with incomplete
accountability returns `recovery_required` and retains its original source receipt. Neither state
is blindly retried. With durable receipts and unavailable/failed Store/index/link repair, the
result is `convergence_pending` with source `committed`; it never claims rollback. A successful
explicit DRI reconciliation may return `succeeded`. Kernel replay after restart returns the
original operation outcome and receipts without invoking another source effect. Indeterminate
reservations require receipt reconciliation, never source inference or a fresh operation identity
as a retry shortcut.

AUTOOPS-08 adds `KnowledgeSemanticOwner.reconcile` and
`semantic_operations.reconcile_semantic_operation` as explicit read/verify-first seams. Newly
recorded semantic receipts bind the original request, arguments, context, identity and version by
intent digest. Reconciliation reads the exact durable owner event and verifies that chain and its
source result. It never repeats semantic mutation or manufactures missing accountability. Absent,
malformed, mismatched or historical receipts without that binding remain recoverable; later human
source edits are preserved. Current kernel admission and all existing mutation-time WSP/GOV and
human-approval windows retain their meanings. Native single-operation replay remains historical.
Semantic mutation receives the same optional per-call original deadline and checks it after its
owned final approval/selection guard; no arbitrary kernel callback runs inside those locks.

## Queries

- What is the human artifact identity?
- What origin facts must survive?
- Which representation is portable?
- Which projections can be rebuilt from this artifact?

## Events

- `artifact.created`
- `artifact.governed_mutation_applied`
- `artifact.machine_contribution_accepted`
- `artifact.representation_migrated`

## Invariants

- Human knowledge remains usable if machine artifacts disappear.
- Artifact-origin facts that must survive do not live only in SIP/DRI.
- HKA owns durable human artifact lifecycle, not storage backend mechanics.
- Human/system ownership markers are explicit.
- Semantic mutation preserves the independent classification, lifecycle, trust, review, and authority axes.
- Authored order and its complete member list live together on the human source; projections cannot supply missing meaning or permission.

## Allowed Producers

- HIX human creation/acceptance flows.
- GOV-approved mutation paths.
- EBF import/source adapters under HKA rules.

## Allowed Consumers

- SIP, DRI, RCA, MEM, CAO, HIX, GOV, SFC, OEF.

## Forbidden Use

- Do not store only derived semantic meaning in HKA without a human-readable/exportable representation.
- Do not let RCA, MEM, CAO, EXE, EBF, or HIX directly mutate HKA without GOV/HKA path.
- Do not use storage schema as artifact ontology.

## Failure Modes

- Derived representations contain non-rebuildable meaning.
- SIP becomes irreplaceable shadow store.
- UI state becomes authoritative.

## Transitional Implementation Notes

Current vault notes and companion notes are the main durable artifact surface. This target contract generalizes the artifact boundary beyond vault/Markdown while preserving human readability/exportability.

## Open Questions

- What minimum ArtifactContract supports no-vault operation while preserving human comprehensibility?
- Which artifact-origin facts must live inside the artifact versus in adjacent durable receipts?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md`
- `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`
