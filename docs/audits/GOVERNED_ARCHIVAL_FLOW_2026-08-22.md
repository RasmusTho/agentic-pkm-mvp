# Governed Archival Flow Across Durable Artifacts — Architecture Audit

State: Advisory architecture-research snapshot (2026-08-22), followed by an explicitly accepted
promotion into `docs/GOVERNED_ARCHIVAL_FLOW/`. Non-normative and subordinate to
`docs/DOCS_INDEX.md`, current-state owner documents, accepted contracts, implementation evidence,
and live GitHub delivery state. The audit itself authorizes no runtime, schema, or storage change;
the post-snapshot PromotionIntent authorizes only the governed specification/backlog handoff.

Doc role: Reference (audit snapshot)

Authority: Evidence-based structural analysis. Repository anchors below reflect the immutable local
`origin/main` snapshot `2364936fe37800d25e130c9eb31a1cea4de4b676`, retrieved 2026-08-22 at
`12:22:44Z` (`14:22:44+02:00`). Owner documents and shipped code/tests win on conflict.

Owner: Architecture research; proposed future ownership is allocated to existing Product/Runtime,
Platform/Operations, and Builder System boundaries only.

Temporal class: snapshot

Review cadence: event-driven (HAR completion, owner-contract change, retention/revocation change,
new durable artifact class, or accepted promotion)

Source of truth: mixed — local repository contracts/current-state docs, tests, and commit history.
Remote/live GitHub Issue/PR bodies and current remote freshness are unavailable for this audit and
are not used to assert local code truth. The local checkout is the evidence fallback requested for
this pass.

Promotion state: accepted after the immutable research snapshot. PromotionIntent
`prom_20260822201148_cc5214d7` was accepted at `2026-08-22T20:11:51Z` by BuilderOpsReceipt
`receipt_20260822201151_94c61ba1`. Its authorized result is the target-state specification at
`docs/GOVERNED_ARCHIVAL_FLOW/`; runtime delivery remains unclaimed.

## Post-snapshot promotion and current-main reconciliation

The causal/evidence analysis below remains bound to immutable local snapshot
`2364936fe37800d25e130c9eb31a1cea4de4b676`. Before promotion, the breakdown lane fetched and read
`origin/main` `f568e457f2bad7e15997fc405615f3deffda8abb` (commit time
`2026-08-22T19:57:03+02:00`) and reconciled these changes without rewriting the historical audit:

- PR #5061 delivered HAR-05; parent #3842 and children #3847–#3851 are closed. Current
  `docs/EVENTS.md` and the focused tests now carry gated cold restore, consent-revocation
  propagation, durable cleanup, `erasure_pending`, and all-copy terminal-liveness behavior. The
  snapshot-specific HAR-05 and early-erasure gaps below are therefore superseded for current-main
  implementation truth.
- `app/heimdal/media_ingress.py` admits audio, image, video, and document raw representations, and
  the delivered archive selector is modality-neutral. The promoted breakdown treats Heimdal as the
  first raw-media adapter and requires a production-path four-modality proof instead of four new
  archive pipelines.
- The accepted handoff resolves the broad capability as a shared contract plus verified transition
  kernel over owner-native adapters. It explicitly rejects a central archive registry or a new SBS
  subsystem.

Remote freshness was used only for this post-snapshot filing reconciliation. Historical causal
claims remain limited to the local evidence boundary documented in §1.

## Executive finding

The repository already contains most of a safe archival mechanism, but only for one concrete source
class: Heimdal raw audio. HAR-01 through HAR-04 are represented in this snapshot as a measured
capacity report, a location-aware raw representation, a verified encrypted cold-volume boundary,
and a receipt-gated hot-to-cold relocation. HAR-05 is present as a task specification but remains
future-state in this snapshot. The existing mechanism is strong enough to generalize, but the
general capability is not yet named or contracted.

The correct generalization is not “put every file in the Heimdal archive.” It is a governed archival
flow over durable source artifacts, with adapters for raw evidence, media originals, documents, and
human-authored artifacts, plus explicit exclusions for rebuildable derivatives, embeddings, and
caches. Identity, provenance, access policy, representation registration, retention/revocation,
restore, deletion receipts, and liveness must be common contracts; storage format, capture seam,
retention policy, consent class, and restore presentation remain adapter-specific.

The narrow implementation was rational and then self-reinforcing. The initiating spec named a
Heimdal raw-audio problem, its task anchors all pointed back to that audio-specific directory, its
acceptance tests exercised only raw-store paths, and the delivery skills correctly constrained
builders to bounded child Issues. The missing step was an upstream capability-discovery gate that
would have asked whether the same identity/representation/access/retention problem already applied
to images, video, documents, and human artifacts before the bounded feature was accepted.

## 1. Evidence boundary and research charter

### 1.1 Immutable authority snapshot

| Field | Value |
| --- | --- |
| Local authority ref | `origin/main` |
| Exact SHA | `2364936fe37800d25e130c9eb31a1cea4de4b676` |
| Commit time | `2026-08-22T12:22:44Z` |
| Retrieval time | `2026-08-22T12:22:44Z` (local commit metadata; filesystem audit began afterward) |
| Remote/live GitHub freshness | unavailable/not used for claims in this audit |
| Working copy | `/private/tmp/agentic-pkm-archival-flow-research` |
| Mutation boundary | local advisory audit and index row only; no implementation, Issue, PR, label, Project, or BuilderOps lifecycle mutation |

### 1.2 Bounded research questions

- RQ-1: What common governed archival flow can cover raw audio, images, video, documents, and
  other durable source artifacts without collapsing authority classes?
- RQ-2: Which artifacts are durable archival sources, and which are exceptions or rebuildable
  derivatives that must not be treated as archive authority?
- RQ-3: Which identity, representation, gated-access, restore, retention, revocation, deletion-
  receipt, and liveness invariants already exist, and which are absent or audio-local?
- RQ-4: Why did the delivered capability become Heimdal/audio-specific, where should breadth
  discovery have happened, and which signals were missing from the process?
- RQ-5: Which adapters and dependency-ordered slices would make a broad capability feature-breakdown
  ready without creating a second ontology, storage authority, or BuilderOps authority?

### 1.3 Explorer receipts

The pass was cut into three read-only evidence briefs on the same snapshot: HAR implementation and
tests; artifact/media/persistence/SBS contracts; and causal delivery-process tracing. Findings enter
this synthesis only when they carry a repository path plus line, test, document, or commit anchor.
No external Issue body is treated as verified local evidence.

Evidence receipts: Explorer A completed 2026-08-22T19:21:48Z with a clean checkout and classified
HAR/runtime findings as conforms, diverges, or unavailable; Explorer B completed 2026-08-22T19:16:12Z
with the cross-class artifact/media/SBS inventory; Explorer C completed 2026-08-22T19:17:07Z with the
causal process trace. All three were read-only and used no GitHub lifecycle operation. Their shared
authority SHA was `2364936fe37800d25e130c9eb31a1cea4de4b676`.

## 2. What exists in the snapshot: HAR-01..05

### 2.1 Capability boundary already encoded

`docs/HEIMDAL_LOCAL_ARCHIVE/README.md:1-8` explicitly describes a local encrypted cold tier for
Heimdal raw audio, subordinate to Heimdal owner decisions, the raw-store boundary, and `EVENTS.md`.
Its outcome is seven hot days followed by a verified cold copy on an encrypted APFS sparsebundle,
with no unencrypted external volume or iCloud archive (`README.md:12-23`). The seven-day value is
tiering, not a retention extension; all raw copies must be removed at expiry or revocation
(`README.md:24-35`).

The directory's task order is a flat chain — HAR-01 measure volume, HAR-02 migrate the raw store,
HAR-03 provision the encrypted volume, HAR-04 archive with receipts, HAR-05 prove restore/expiry —
with no parallel task (`README.md:40-51`). Its cross-task invariants explicitly name raw audio,
raw identity, raw-read gating, all-copy deletion, and non-authority of the archive manifest
(`README.md:53-81`). This is a coherent local capability contract, not an accidental code leak.

### 2.2 Delivered and missing posture at this SHA

- HAR-01 is an aggregate-only capacity report. `docs/EVENTS.md:550-569` says it reads only ingest
  time and encrypted byte length, partitions hot/archive-eligible/expired totals, and does not
  mount, move audio, alter retention, or claim a supported cold tier.
- HAR-02's identity/representation migration is delivered in the snapshot. The raw contract keeps
  immutable identity/provenance separate from registered ciphertext locations and verifies the
  immutable content identity before activation or gated read (`docs/EVENTS.md:395-417`).
- HAR-03's volume boundary is delivered. The host-only boundary validates channel, external-parent
  volume identity, sparsebundle/image/APFS identity, mount, capacity, and locked metadata before
  archive work (`docs/HEIMDAL_LOCAL_ARCHIVE/PROVISION_ENCRYPTED_COLD_VOLUME.md:30-100`).
- HAR-04's relocation producer is delivered. It reserves an opaque location before external bytes,
  verifies bytes and identity, writes a redacted manifest/receipt, then activates cold and retires
  hot; failures retain hot data (`docs/HEIMDAL_LOCAL_ARCHIVE/ARCHIVE_WITH_VERIFIED_RECEIPTS.md:20-36`,
  `:38-64`). The local implementation is `app/heimdal/local_archive.py:1-36`.
- HAR-05 is not delivered at this snapshot. Its spec requires a gated cold read, a restore drill,
  all-copy expiry/revocation, and retryable cold-delete failure (`docs/HEIMDAL_LOCAL_ARCHIVE/PROVE_RESTORE_AND_EXPIRY.md:11-49`),
  while the capability README still marks that acceptance unchecked (`README.md:83-110`).

### 2.3 Existing audio safety kernel

The raw-evidence owner document already contains strong partial invariants:

- Admission encrypts before durable write, stamps identity/provenance/consent and the initial
  representation atomically, and refuses missing keys (`docs/EVENTS.md:369-417`).
- `raw_ref` is opaque; only the gated read path resolves it to an active registered
  representation, and callers cannot provide a filesystem path (`docs/EVENTS.md:435-461`).
- Successful reads emit an append-only receipt in the same call; refused reads emit none
  (`docs/EVENTS.md:462-470`).
- Hard retention is settings-bound, generation-bound, receipt-bearing, and reports honest no-ops
  (`docs/EVENTS.md:478-521`). Every registered representation must be removed before success; a
  copy failure rolls back the attempt (`docs/EVENTS.md:522-536`).
- Missing raw state without an exact tombstone is `unavailable`, not inferred `erased`; an
  identical reinsert creates a new generation (`docs/EVENTS.md:508-513`).
- The focused tests exercise these claims, including crash ordering and retryability
  (`tests/heimdal/test_raw_liveness.py:235-296`,
  `tests/heimdal/test_local_archive_migration.py:350-430`).

These are excellent source-class primitives. They are not yet a cross-artifact archival contract:
the capture adapter, raw store, consent ledger, content hash, and audio retention settings are
Heimdal-specific seams. The current governed media-ingress contract is already broader than HAR:
it records durable raw writes plus committed outbox receipts, capture identity/content hash, and
retention outcomes for audio, image, video, and document modalities
(`docs/EVENTS.md:618-713`; implementation/test anchors include
`app/heimdal/media_ingress.py:472-531` and `tests/heimdal/test_media_ingress.py:166,940,970,1043`).
That breadth is an ingress capability, not evidence that the HAR cold-tier/restore/revocation
capability is cross-class.

## 3. General governed archival capability

### 3.1 Capability definition

**Governed archival flow** means moving or preserving a durable source artifact across one or more
registered storage representations while preserving source identity, provenance, policy authority,
and recoverability. It is a lifecycle overlay, not a new artifact ontology and not a single physical
archive volume.

The common flow is:

```text
classify source
  -> admit identity + provenance + initial representation
  -> register representations and opaque resolver refs
  -> gate access and issue receipts
  -> reserve destination authority before bytes
  -> copy/verify identity + representation metadata
  -> commit manifest/receipt and activate destination
  -> retire only superseded representation
  -> restore through the same gate when needed
  -> retain/revoke by generation and enumerate every representation
  -> tombstone/receipt + durable retryable cleanup
  -> doctor liveness, orphan, mismatch, and stale-queue states
```

The flow preserves the existing separation: HKA owns durable human meaning, SIP owns semantic
identity/provenance continuity, GOV owns admissibility and authority receipts, and PDM owns storage,
migration, backup/restore, and physical lifecycle (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1256-1290`,
`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1506-1541`). The archival capability composes these owners; it
does not become a new authority layer.

### 3.2 Artifact-class matrix

| Class | Archive posture | Authority | Required adapter | Explicit exception |
| --- | --- | --- | --- | --- |
| Heimdal raw audio / raw sensor evidence | durable source until consent/retention erasure | raw evidence + consent/provenance; no Mimer knowledge authority | existing raw-store, consent, liveness, cold-volume and relocation adapters | audio-specific capture and retention policy remain local |
| Image/video/document original | durable source when the human intends record/evidence retention | original is source-authoritative | media/document admission, content identity, format inspection, storage resolver, gated read | no assumption that all media is permanent; policy selects retention class |
| Human-authored note / accepted artifact | durable human artifact; export/recovery is first-class | HKA artifact and governed mutation path | HKA ArtifactContract representation/export/recovery adapter | not a raw-evidence deletion job; owner authority and human-readable form remain primary |
| Companion note / human navigation surface | durable according to the source artifact and human intent | human-authored note; original source remains authoritative for media | companion linkage and HKA write adapter | must not replace or silently absorb the original |
| Transcript, OCR, thumbnail, crop, translation, analysis | retain only when explicitly non-rebuildable or human-accepted | derived from source; non-authoritative by default | DRI lineage/invalidation adapter and optional durable derivative marker | rebuildable by default; never substitute for the original |
| Embedding, vector index, lexical index, cache | rebuildable support structure, not archival source | DRI/system mirror | rebuild/reconciliation adapter | do not pay archive cost as if meaning were lost when it is rebuildable |
| Governance/retention/deletion receipt | durable accountability evidence | GOV receipt/tombstone authority | receipt export/backup adapter | not product content and not a replacement for the source artifact |

The media contract already distinguishes original, derivative, companion note, index, and navigation
map (`docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md:34-89`). Portability separately says
central human artifacts must remain comprehensible and that mirrors, indexes, embeddings, projections,
and caches are usually not central artifacts (`docs/CONCEPTS/PORTABILITY_CONTRACT.md:7-14`,
`:16-47`). HKA and PDM make the same distinction at the SBS level (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:556-607`,
`:772-810`). The general flow should reuse these distinctions rather than archive every byte class
uniformly.

### 3.3 Necessary adapters

1. **Artifact identity adapter** — stable artifact/source identity, content identity, origin facts,
   ownership, generation, and provenance. It must map into HKA/SIP/GOV primitives, not invent an
   archive identity.
2. **Capture/admission adapters** — Heimdal raw evidence, media originals, document import, and HKA
   artifact creation. Each names its consent/authority and initial representation producer.
3. **Representation adapter** — immutable or governed representation rows containing format, byte
   identity, encryption/key reference, storage kind, opaque location, active state, and lineage.
4. **Policy/access adapter** — consent, sensitivity, scope, retention class, revocation, and the
   existing gated-read/receipt contract. A mounted volume never grants access by itself.
5. **Archive backend adapter** — hot store, local encrypted cold store, future backup/object store,
   or portable export. Backend identity is checked by capability/proof, not path text.
6. **Restore/verifier adapter** — authorized read, byte/content identity check, format validity,
   provenance preservation, redacted restore receipt, and operator-visible failure.
7. **Retention/revocation adapter** — generation claim, lease drain, all-representation traversal,
   tombstone, deletion receipt, and retryable external cleanup.
8. **Doctor/reconciliation adapter** — read-only detection of orphan bytes, missing registration,
   identity mismatch, stale active representation, missing tombstone, stale cleanup queue, dead
   resolver, and non-rebuildable derivative without declared source.

## 4. Common invariants

These names are proposed extensions to the existing invariant registry semantics, not a second
registry. The current registry must be extended only after an accepted owner/promotion decision.

### 4.1 Minimal correctness kernel

The smallest kernel carrying the archival claim is:

- **ARCHIVE-MUST-01 — Identity is not location.** A representation move preserves stable source/
  artifact identity, content identity, origin provenance, generation, and opaque resolver reference;
  location text never becomes authority. Partial enforcement exists for raw audio in
  `docs/EVENTS.md:402-417` and for the SBS in `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:629-660`.
- **ARCHIVE-MUST-02 — Access is gated at the read seam.** Restore and ordinary reads use the same
  policy/allowlist/receipt gate; a mount, path, or manifest cannot authorize access. Partial
  enforcement exists in `docs/EVENTS.md:446-467`.
- **ARCHIVE-MUST-03 — No authority fork.** An archive manifest/receipt records storage custody and
  verification; it does not publish observation, create knowledge, or replace HKA/GOV/SIP authority.
  Partial enforcement exists in `docs/HEIMDAL_LOCAL_ARCHIVE/README.md:53-71` and
  `app/heimdal/local_archive.py:1-6`.
- **ARCHIVE-MUST-04 — Verify before representation retirement.** Destination reservation, durable
  copy, byte/content identity verification, manifest/receipt durability, and activation precede
  retirement of the superseded representation; failure retains a readable source and retry
  authority. Partial enforcement exists in `docs/HEIMDAL_LOCAL_ARCHIVE/ARCHIVE_WITH_VERIFIED_RECEIPTS.md:20-64`.
- **ARCHIVE-MUST-05 — All-copy deletion precedes terminal erasure.** Retention or revocation reports
  success only after every registered representation is handled, with a durable tombstone/receipt
  and retryable cleanup for external bytes. The owner contract states this at
  `docs/EVENTS.md:522-536`, but the current runtime diverges: the liveness path can commit the
  database erasure state before pending external cold cleanup completes
  (`app/heimdal/raw_liveness.py:1256`, `tests/heimdal/test_local_archive.py:719-768`).
  Consent-revocation propagation is explicitly still a gap at `docs/EVENTS.md:545-548`.

Everything else is defense in depth: volume identity, lock ordering, path redaction, receipt queue
monotonicity, batch bounds, and per-adapter format tests make the kernel safer but do not replace it.

### 4.2 MUST / GATE / DOCTOR extension set

| ID | Category | Invariant | Snapshot posture |
| --- | --- | --- | --- |
| ARCHIVE-MUST-06 | MUST | Every admitted durable source has identity, origin/provenance, policy/consent class, generation, and one registered initial representation atomically or fails closed. | Exists partially for raw audio (`docs/EVENTS.md:395-401`); new for generalized adapters. |
| ARCHIVE-MUST-07 | MUST | A representation is readable only through a registered resolver that verifies encryption/key, byte/content identity, and active generation. | Exists partially for raw audio (`docs/EVENTS.md:402-417`); new cross-class contract. |
| ARCHIVE-GATE-01 | GATE | Every adapter proves restore through the production gated-read seam, preserves provenance, and emits a redacted receipt. | HAR-05 target is not delivered at this SHA (`docs/HEIMDAL_LOCAL_ARCHIVE/PROVE_RESTORE_AND_EXPIRY.md:29-41`). |
| ARCHIVE-GATE-02 | GATE | A representative matrix covers raw audio, image, video, document, human-authored note, and one rebuildable derivative, with explicit excluded classes. | New; no current cross-class Verify target was found. |
| ARCHIVE-GATE-03 | GATE | Retention and revocation chaos tests prove all-copy deletion, no false success, generation non-resurrection, and retryable cleanup for each durable adapter. | Raw-audio partial proof exists (`tests/heimdal/test_raw_liveness.py:261-296`); generalized gate new. |
| ARCHIVE-GATE-04 | GATE | The capability's parent acceptance receipt proves scope coverage and owner-doc promotion only after all mandatory adapter gates pass. | New; current HAR README has only raw-audio parent acceptance (`README.md:104-110`). |
| ARCHIVE-DOCTOR-01 | DOCTOR | Detect an external object without a registered representation, a registered representation without bytes, or a manifest/hash/content mismatch. | HAR-04 health covers selected failures; cross-class doctor new. |
| ARCHIVE-DOCTOR-02 | DOCTOR | Detect an absent identity without tombstone, a stale generation receipt, a cleanup queue that cannot resolve, and a cold resolver bound to the wrong archive identity. | Raw liveness is explicit (`docs/EVENTS.md:508-513`); generalized doctor new. |
| ARCHIVE-DOCTOR-03 | DOCTOR | Detect a derivative/index/cache treated as source authority or a human artifact whose identity/origin is only in a rebuildable projection. | The rule exists in SBS/portability (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1282-1290`; `docs/CONCEPTS/PORTABILITY_CONTRACT.md:49-63`); reconciliation tooling new. |

## 5. Research-question resolutions

### RQ-1 — Can one capability cover audio, image, video, and documents?

Yes, at the lifecycle/authority layer, not as one capture implementation. The common kernel is
identity → registered representation → gated access → verified transition → all-copy retention /
revocation → receipts/liveness. Raw audio already demonstrates the mechanism (`docs/EVENTS.md:395-417`,
`:446-467`, `:522-536`). Images, video, and documents need admission, format, consent/privacy, and
restore adapters; the media contract explicitly keeps those semantics distinct from notes and
indexes (`docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md:34-89`). The present media-ingress
path confirms a shared durable-ingress receipt seam for those modalities, while not proving shared
archival lifecycle semantics (`docs/EVENTS.md:618-713`).

### RQ-2 — What is excluded or treated differently?

User-authored and human-accepted notes are HKA durable artifacts with human-readable/exportable
representations, not raw-evidence rows (`docs/contracts/ARTIFACT_CONTRACT.md:12-29`,
`:54-85`). Derivatives, embeddings, indexes, and caches are rebuildable support structures unless
explicitly marked non-rebuildable or human-accepted (`docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md:49-80`,
`docs/CONCEPTS/PORTABILITY_CONTRACT.md:34-47`). Receipts and tombstones are durable governance
evidence, but not user content. A broad archive must record these classes explicitly instead of
silently applying one deletion policy to all of them.

### RQ-3 — Which common invariants already exist?

Identity/location separation, opaque refs, gated reads, receipt-on-success, encrypted-at-rest,
generation-bound liveness, and fail-loud retention already exist in the Heimdal raw path
(`docs/EVENTS.md:390-417`, `:446-467`, `:488-536`). The all-copy deletion rule exists in the owner
contract, but is not fully conformant in the current implementation because terminal erasure can be
projected while external cold cleanup remains pending (`app/heimdal/raw_liveness.py:1256`,
`tests/heimdal/test_local_archive.py:719-768`). HKA/SIP/PDM already supply the
cross-system authority split (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1262-1290`). What is missing is a
single cross-class contract and adapter-conformance gate; restore/expiry itself is incomplete in
this local snapshot (`docs/HEIMDAL_LOCAL_ARCHIVE/PROVE_RESTORE_AND_EXPIRY.md:29-41`).

### RQ-4 — Why did the delivery become narrow?

The evidence-backed causal chain is in §7. In short, the initiating problem, spec name, source
anchors, task tests, linear dependency graph, and child-agent selection rule all optimized for a
bounded raw-audio slice. No artifact census or breadth challenge was required before the boundary
was treated as authoritative. The narrow result is therefore a process outcome, not evidence of a
bad HAR implementation.

### RQ-5 — What adapters are required?

The eight adapters in §3.3 are the minimum decomposition. The raw-audio adapter can retain its
current seam. Media/document and HKA adapters should share representation, policy, restore, cleanup,
and doctor contracts without sharing capture assumptions. Derived artifacts require an explicit
rebuildability adapter, not a disguised archive writer.

## 6. Structural weaknesses ranked by systemic impact

Ranking is blast radius × silence of failure, not likelihood.

### W1 — No cross-artifact capability-discovery gate before breakdown

The feature-breakdown procedure begins by identifying “one concrete capability boundary” and then
defines intent, tasks, verification, and acceptance (`.codex/skills/feature-breakdown/SKILL.md:197-213`).
It does not require a life-wide artifact census, a cross-class non-goal decision, or a search for
existing media/HKA/PDM contracts before accepting the boundary. The HAR source tree anchors only to
its own README (`docs/HEIMDAL_LOCAL_ARCHIVE/*.md` frontmatter, e.g. `ARCHIVE_WITH_VERIFIED_RECEIPTS.md:1-8`).
This can silently turn a reusable substrate problem into a source-specific capability.

Disposition: accepted for advisory handoff; promotion pending.

### W2 — Broad owner contracts were not in the HAR source-anchor set

The media contract names photos, screenshots, scans, receipts, manuals, contracts, and reference
images as distinct media semantics (`docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md:7-21`),
while HKA/PDM define durable artifacts versus storage mechanics (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:556-607`,
`:772-810`). The HAR README's related sources instead point to Heimdal retention, Fable capture,
events, and local secret provisioning (`docs/HEIMDAL_LOCAL_ARCHIVE/README.md:118-123`). No local
evidence shows a deliberate “not applicable after cross-contract review” decision for images,
video, documents, or HKA notes.

Disposition: accepted for advisory handoff; promotion pending.

### W3 — Verification proves a mechanism, not capability breadth

HAR acceptance targets are raw-audio capacity, encrypted volume, raw-ref migration, raw relocation,
and raw restore/expiry (`docs/HEIMDAL_LOCAL_ARCHIVE/README.md:83-110`). The current `EVENTS.md`
explicitly says HAR-01 does not claim a supported cold tier (`docs/EVENTS.md:550-569`), and HAR-05's
restore/expiry tests are not present as delivered in this snapshot. There is no cross-class adapter
matrix, representation taxonomy test, or scope-coverage receipt.

Disposition: accepted for advisory handoff; promotion pending.

The implementation review also exposed two safety divergences that a cross-class gate must catch:
HAR-04 activation marks the old hot representation inactive but does not by itself prove physical
hot ciphertext removal (`app/heimdal/raw_store.py:915,1968`, `app/heimdal/local_archive.py:357`,
`tests/heimdal/test_local_archive.py:368`); and the liveness path may expose `erased` before external
cold cleanup has completed (`app/heimdal/raw_liveness.py:1256`,
`tests/heimdal/test_local_archive.py:719-768`). These are implementation-level convergence items,
not arguments for broadening the live HAR slice in this audit.

The broader persistence inventory also remains unresolved: current media ingress covers image,
video, and document modalities, while the target media-original policy says durable originals are
not automatically deleted and a separate classification task is still future
(`docs/EVENTS.md:618-713`, `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md:71-79,105-109`,
`docs/SEPARATING_PERSISTENCE_SURFACES/CLASSIFY_CURRENT_ARTIFACTS.md:12-20,103-118,162`). A generic
archival capability therefore needs an explicit retention-class decision before attaching that
ingress to HAR semantics.

### W4 — Delivery gates correctly protect bounded work but do not reopen architecture scope

`issue-to-code` requires work from bounded ready child Issues and stops when a chosen Issue is
feature-level or references multiple slices (`.codex/skills/issue-to-code/SKILL.md:155-169`).
`deliver-issue-set` coordinates the parent/child contract, dependency order, and readiness but
forbids implementation in planning mode (`.codex/skills/deliver-issue-set/SKILL.md:85-110`). These
are good anti-scope-creep controls after the boundary is chosen; they are not a discovery gate.

Disposition: accepted for advisory handoff; promotion pending.

### W5 — Promotion/learning evidence for the breadth question is not locally visible

Current architecture-research and feature-breakdown rules require an accepted `PromotionIntent` and
`BuilderOpsReceipt` before research becomes a new specification/backlog, and a promoted result after
materialization (`.codex/skills/architecture-research/SKILL.md:107-128`,
`.codex/skills/feature-breakdown/SKILL.md:43-49`). No such local receipt binding a broader archival
capability, a deliberate audio-only decision, or a post-delivery generalization was found in the
snapshot. This is an evidence gap, not proof that no remote record ever existed.

Disposition: unavailable for historical causal attribution; accepted as a prevention requirement.

## 7. Why the narrow implementation happened

This section separates causes evidenced in the repository from prevention proposals in §9.

### 7.1 Direct cause: the initiating capability was already audio-specific

The local history commit `67ba2a2476c091abdf1389a8250d30e0b226d060` (“Add local archive and secret
provisioning specs”, 2026-07-16) added the complete `HEIMDAL_LOCAL_ARCHIVE` directory. The added
README defines a local cold tier for Heimdal raw audio and explicitly keeps Mimer from receiving
recordings (`docs/HEIMDAL_LOCAL_ARCHIVE/README.md:12-23`). The initial task files repeat the parent
capability `Heimdal Local Archive`, a `source_anchor` into that README, and `can_parallelize_with: []`
(`docs/HEIMDAL_LOCAL_ARCHIVE/ARCHIVE_WITH_VERIFIED_RECEIPTS.md:1-8`). A later breakdown cannot infer
an omitted modality from a source document that never names the broader problem.

### 7.2 Rational narrowing: a concrete retention/storage failure already existed

The raw audio path already had a hot store, a seven-day tier threshold, settings-governed hard
retention, opaque `raw_ref`, gated reads, and all-copy deletion semantics (`docs/EVENTS.md:362-476`,
`:478-548`). HAR-01 therefore measured a real non-content capacity problem and HAR-02 supplied the
identity/representation seam needed before moving bytes. This made a raw-audio slice an efficient,
low-ambiguity first delivery rather than an arbitrary choice.

### 7.3 Locking mechanism: source anchors and acceptance targets were closed over the slice

Every HAR child anchors to the local capability README and verifies named `tests/heimdal/**` paths.
The parent/feature-breakdown contract requires each child to be bounded, independently verifiable,
and ordered (`.codex/skills/feature-breakdown/SKILL.md:252-275`). This prevents a child agent from
silently widening a migration or deletion mechanism into a media platform. The same mechanism that
protected correctness also made scope expansion illegitimate after pickup.

The source-anchor validator reinforces existence and syntax, not semantic breadth: it validates the
anchor shape and referenced file (`scripts/validate_source_anchors.py:68-71,153-185`), and its tests
accept descriptive existing-file anchors (`tests/scripts/test_validate_source_anchors.py:8-21`).
Nothing in that gate requires an adjacent artifact-class census or a representative adapter matrix.

### 7.4 Locking mechanism: linear dependency order made the chain intentionally serial

HAR-01 → HAR-02 → HAR-03 → HAR-04 → HAR-05 is explicitly declared (`README.md:40-51`), and each
task says it cannot parallelize. This was sensible because identity/representation, volume authority,
and retention cleanup share state. It also meant no independent image/video/document exploration was
scheduled as a sibling workstream.

### 7.5 Locking mechanism: issue-to-code and delivery gates are downstream guards

The canonical hot path is Docs → Feature issue → Slice issue → Agent → PR → CI → Slice verification
→ Merge → Feature validation → Owner Doc (`.codex/skills/issue-to-code/SKILL.md:113-119`). The
implementation agent must stop on feature-level work and use the bounded Issue contract
(`.codex/skills/issue-to-code/SKILL.md:155-169`). `deliver-issue-set` similarly requires dependency
and readiness planning but forbids code/PR/merge mutation in planning mode
(`.codex/skills/deliver-issue-set/SKILL.md:85-110`). Nothing in these downstream gates asks “what
other artifact classes share this mechanism?” because that is upstream architecture work.

### 7.6 Missing or unproven signals

The local snapshot provides no evidence of:

- a pre-breakdown inventory mapping raw audio, images, video, documents, notes, derivatives, caches,
  and embeddings to existing HKA/PDM/SIP/GOV owners;
- a Source Anchor to `MEDIA_ARTIFACT_CONTRACT.md`, `ARTIFACT_CONTRACT.md`, or the persistence-surface
  taxonomy in the HAR capability contract;
- a breadth row in the parent acceptance/verification path;
- a TCD plan field that priced a capability census against a narrow first slice;
- an accepted PromotionIntent/BuilderOpsReceipt deciding “audio-only now, generic substrate later”; or
- a retrospective signal tying the narrow scope to an upstream discovery improvement.

The absence claims above are bounded to the local snapshot and its checked-in artifacts. Historical
GitHub comments, Issue bodies, and BuilderOps stores are remote/live evidence and remain unavailable
for this audit.

The parent/child Issue contract is therefore only partially reconstructable: live Issue #3842 and
the HAR child bodies are unavailable, while the local checkout contains no `PARENT_FEATURE_ISSUE.md`
hub and the HAR task frontmatter has no `github_issue:` binding; the task files instead repeat the
same local parent capability/source anchor (`docs/HEIMDAL_LOCAL_ARCHIVE/ARCHIVE_WITH_VERIFIED_RECEIPTS.md:1-8`).
That is evidence of a local traceability gap, not proof about what the remote Issues said. The current
feature-breakdown contract expects parent/child traceability and bounded task metadata
(`.codex/skills/feature-breakdown/SKILL.md:98-119,148-160`), so the missing local bindings are a
prevention target rather than a retroactive attribution of intent.

TCD is not evidenced as a direct cause. The current policy chooses capability, model, reasoning,
context, tools, parallelization, and verification according to total cost (`AGENTS.md:306-366`),
but no HAR-specific checked-in `tcd_plan` or `tcd_review` was found. Likewise, the checked-in
BuilderOps promotion gateway is proposal-level (`docs/builderops/BUILDEROPS_PROMOTION_GATEWAY.md:13-45`),
and the mandatory accepted-research-promotion rule appears in the later architecture-research and
feature-breakdown contracts (`.codex/skills/architecture-research/SKILL.md:107-128`,
`.codex/skills/feature-breakdown/SKILL.md:43-49`). No HAR-bound PromotionIntent or BuilderOpsReceipt
was locally available. These facts explain why breadth was not durably surfaced; they do not prove
that a particular model, effort setting, or reviewer consciously chose audio-only scope.

### 7.7 Where breadth discovery should have happened

1. **Architecture-research intake:** when the question changed from “how do we cold-tier raw audio?”
   to “what is the governed archival capability?”, the architecture-research charter should have
   been opened before another feature breakdown.
2. **Repo skill routing:** the repo routing table sends architecture research to the architecture-
   research skill and separates docs governance, feature breakdown, deliver-issue-set, issue-to-code,
   and verification/closure paths (`.codex/skills/README.md:28-36,140-143,198-213,230-235`). The
   routing correctly separated workflow responsibilities but contained no mandatory cross-class
   discovery handoff at the boundary between them.
3. **Docs-governance routing:** the source set should have been classified against existing owner
   docs and anti-sprawl rules before creating a new capability directory
   (`.codex/skills/docs-governance/SKILL.md:37-45`, `:59-89`).
4. **Feature-breakdown step 1:** “one concrete capability boundary” should have required a bounded
   capability census and explicit reasons for excluding adjacent classes, not just a task list
   (`.codex/skills/feature-breakdown/SKILL.md:197-213`).
5. **Parent contract:** Source Anchors and SBS Impact should have named HKA, PDM, SIP, GOV, and the
   media contract even if the first implementation slice remained audio-only.
6. **Verification/acceptance:** parent validation should have required either a representative
   cross-class adapter matrix or an explicit owner decision that the capability is intentionally
   audio-only and not a generic archival substrate.
7. **Retrospective:** after the first bounded delivery, the result should have produced a terminal
   BuilderOps learning/promotion outcome rather than leaving generalization only in chat or memory.

## 8. SBS reconciliation

| Structural claim | Relation to SBS | Evidence and boundary |
| --- | --- | --- |
| Archival flow composes identity/meaning/storage/authority instead of owning all four. | Conforms | HKA/SIP/PDM/GOV separation at `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1262-1290`; stable contracts at `:1512-1541`. |
| Raw audio capture and media/document admission remain source adapters. | Conforms | EBF/source-adapter rule in `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1538-1541`; current raw capture boundary `docs/EVENTS.md:369-385`. |
| Physical archive volume, mount, backup/restore, encryption, and store health belong to PDM/Platform boundary, not HKA. | Conforms | PDM responsibilities `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:772-810`; HAR-03 host boundary `docs/HEIMDAL_LOCAL_ARCHIVE/PROVISION_ENCRYPTED_COLD_VOLUME.md:30-100`. |
| Gated access, revocation, and deletion receipts are GOV/retention authority over PDM mechanics. | Extends | Existing raw contract `docs/EVENTS.md:478-536`; cross-class adapter contract is not yet named. |
| A generic archival capability should be a cross-boundary overlay, not a new SBS subsystem. | Conforms | SBS says Level 2 entries are control boundaries, not necessarily services, and names HKA/SIP/PDM/GOV interfaces (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1256-1275`, `:1506-1541`). |
| A new archival SBS subsystem or “archive authority” should be created. | Proposes reshaping — rejected for this audit | No evidence requires a new subsystem. Any future reshape would need CES/ADR/owner decision through `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`; this audit enacts none. |
| BuilderOps/PromotionIntent is a Product artifact store for archive state. | Conforms against | Builder System is enabling, not Product/Runtime, and its artifacts do not become runtime/HKA truth (`docs/architecture/SBS_OPERATING_MODEL.md:119-159`, `:202-223`). |

## 9. Dependency-ordered feature-breakdown handoff (snapshot proposal; now promoted)

The following table preserves the candidate handoff as it existed at the immutable audit snapshot.
The required explicit disposition now exists as PromotionIntent `prom_20260822201148_cc5214d7` and
receipt `receipt_20260822201151_94c61ba1`. Its executable successor is
`docs/GOVERNED_ARCHIVAL_FLOW/README.md`, which reconciles delivered HAR-05, maps the proposal into
GAF-01..07, and keeps existing HAR work as prior evidence rather than duplicate backlog.

| Order | Candidate slice | Dependency | Acceptance kernel / Verify target |
| --- | --- | --- | --- |
| A0 | Establish governed archival capability boundary and artifact-class census | none | Owner-approved boundary maps audio, image, video, document, HKA note, derivative, embedding, cache, and receipt classes; Verify: doc writeback at `docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md` plus `docs/contracts/ARTIFACT_CONTRACT.md`. |
| A1 | Define shared identity/representation/receipt contract | A0 | Stable identity, provenance, generation, opaque location, active representation, key/format metadata, and receipt joins are defined without changing HKA/PDM ownership; Verify: doc writeback at `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`. |
| A2 | Extract raw-audio adapter and finish HAR-05 | A1; reconcile HAR-01..04 | Cold restore and retention/revocation exercise production gated read, all-copy deletion, liveness, and retry; Verify: `tests/heimdal/test_local_archive_retention.py::test_restore_then_delete_all_raw_copies` (target named by current HAR-05 spec). |
| A3 | Add media-original adapter for image/video/document sources | A1 | One representative original per class preserves source identity, provenance, gated read, verified relocation, restore, and deletion; Verify: `tests/<new-media-archive-path>::test_media_original_archive_restore_and_revoke`. |
| A4 | Add HKA human-artifact export/recovery adapter | A1; HKA owner decision | Human-readable representation and minimum identity/origin survive storage migration; Verify: doc writeback at `docs/contracts/ARTIFACT_CONTRACT.md :: Outputs` plus a named recovery test. |
| A5 | Add derived/rebuildable adapter and source-authority doctor | A1 | Derivatives/embeddings/caches are rebuildable or explicitly marked non-rebuildable and never become source authority; Verify: `tests/<new-archive-governance-path>::test_rebuildable_derivative_is_not_archive_authority`. |
| A6 | Add cross-class retention/revocation/restore matrix and doctor | A2-A5 | Parent validation receipt proves all mandatory classes, false-success refusal, cleanup retry, liveness, and no orphan/mismatch state; `Verify: runtime receipt: governed-archival-validation.v1`. |
| A7 | Promote owner docs and close the capability | A6 | Only after validation, current-state docs describe supported classes and exclusions; Verify: doc writeback at `docs/EVENTS.md` and the selected HKA/media/PDM owner docs. |

Reconciliation notes: the promoted cut does not reopen A2/HAR-05 because current main already
delivers it. GAF-03 instead conforms that implementation as the raw-media adapter; GAF-04 and GAF-05
provide retained-source and HKA policy adapters; GAF-06 owns derivative refusal/doctor behavior;
GAF-07 is the final validation child and parent-closure handoff. The parent hub itself remains
non-pickup work.

## 10. Prevention backlog

These are upstream prevention changes identified from evidence, not filed backlog items.

| ID | Upstream change | Why it prevents recurrence | Verify target |
| --- | --- | --- | --- |
| PREV-01 | Add an architecture-research trigger/checklist for capability requests touching identity, storage, retention, restore, or deletion. | Forces a cross-artifact and owner-contract census before a source-specific breakdown. | Verify: `.codex/skills/architecture-research/SKILL.md` contains the archival/capability-discovery gate; governance test or lint target to be named at promotion. |
| PREV-02 | Extend `feature-breakdown` intake with “shared substrate vs source adapter” and explicit adjacent-class exclusions. | Prevents step 1 from treating the first concrete symptom as the whole capability. | Verify: doc writeback at `.codex/skills/feature-breakdown/SKILL.md :: Working procedure`. |
| PREV-03 | Add a capability-boundary template section for artifact census, owner map, and “why not broader” evidence. | Makes omitted images/video/documents/notes visible before parent creation. | Verify: `docs/<capability>/README.md` contains the census and exclusion ledger. |
| PREV-04 | Add a parent-contract gate requiring Source Anchors to every affected owner contract and a representative adapter matrix when the substrate is cross-class. | Stops audio-only Verify targets from being mistaken for capability acceptance. | Verify: `tests/governance/<new-capability-boundary-test>::test_parent_contract_covers_declared_artifact_classes`. |
| PREV-05 | Make non-trivial TCD planning price breadth discovery and review depth, not just child parallelization. | Records when a cheap architecture pass is lower TCD than rework after a narrow delivery. | Verify: the `tcd_plan` block in the breakdown receipt names breadth risk, context cost, and review gate. |
| PREV-06 | Add a review/verification prompt for “scope is bounded by evidence or merely by first producer”. | Gives reviewers a concrete causal question without authorizing scope creep in implementation. | Verify: doc writeback at `.codex/skills/verification-and-closure/SKILL.md` or its governing review contract. |
| PREV-07 | Route post-delivery narrowness discoveries through `LearningSignal` and, when a normative generalization is accepted, `PromotionIntent`. | Prevents the general capability from remaining an informal retrospective insight. | `Verify: runtime receipt: builderops.learning-signal.v1` and `runtime receipt: builderops.promotion-intent.v1`. |
| PREV-08 | Add a docs-governance reconciliation rule for target-state artifact/media contracts before a new lifecycle spec is indexed. | Reuses existing owner docs and avoids parallel artifact/archive ontologies. | Verify: `tests/architecture/<new-doc-governance-test>::test_archival_spec_indexes_owner_contracts`. |

## 11. Disposition and promotion gate

| Finding family | Disposition | Authority consequence |
| --- | --- | --- |
| Existing HAR raw-audio mechanism | accepted as current evidence | Keep current owner docs/code/tests authoritative; do not rewrite shipped claims from this audit. |
| General governed archival flow | accepted and promoted to target-state specification | PromotionIntent `prom_20260822201148_cc5214d7` and receipt `receipt_20260822201151_94c61ba1` authorize `docs/GOVERNED_ARCHIVAL_FLOW/`; runtime support still requires child delivery and parent acceptance. |
| Cross-class MUST/GATE/DOCTOR names | accepted as proposed invariant extension | Extend `docs/testing/invariant-tests.md` only through the normal owner/CES/promotion path; no parallel registry. |
| Historical causal explanation | accepted where anchored; unavailable where historical Issue/BuilderOps evidence is remote | Do not claim reviewer intent or absent remote records; preserve the local-snapshot boundary. |
| New archival Issue/spec set | promotion accepted; materialization delegated to `feature-breakdown` | The feature-breakdown receipt, live Issues, and PR become the authoritative materialization evidence; this historical audit remains advisory. |
| New SBS subsystem | rejected for this audit | Any future reshape must use CES/ADR/owner decision. |

## 12. Compact evidence receipt

```yaml
architecture_research_receipt:
  topic: governed_archival_flow
  authority_ref: origin/main
  authority_sha: 2364936fe37800d25e130c9eb31a1cea4de4b676
  retrieved_utc: 2026-08-22T12:22:44Z
  remote_freshness: unavailable_not_used
  working_copy: /private/tmp/agentic-pkm-archival-flow-research
  boundary:
    - Heimdal HAR-01..05 contract/code/test chain
    - durable artifact/media/HKA/PDM/SIP/GOV owner surfaces
    - Builder feature-breakdown and delivery-process causality
  result_classes:
    - conforms: raw identity/location, gated read, receipt, liveness, SBS separation
    - diverges: broad archival capability is not yet one cross-class contract
    - unavailable: remote/live Issue bodies, historical BuilderOps/PromotionIntent receipts,
      and post-snapshot HAR-05 delivery claims
  key_findings:
    - HAR is a coherent raw-audio capability, not a generic archival capability.
    - Existing contracts support generalization through adapters without a new SBS subsystem.
    - Narrow scope was caused by an audio-specific source boundary plus downstream bounded-delivery gates.
    - Capability census and breadth acceptance were missing upstream signals.
  dispositions:
    - accepted_advisory: general flow, invariant kernel, prevention backlog
    - promoted_after_snapshot: docs/GOVERNED_ARCHIVAL_FLOW via prom_20260822201148_cc5214d7
    - rejected: new archive SBS subsystem
  mutations:
    - immutable snapshot phase: local audit file and DOCS_INDEX row only
    - post_snapshot: accepted PromotionIntent and governed feature-breakdown handoff
  post_snapshot_receipt:
    reconciled_main_sha: f568e457f2bad7e15997fc405615f3deffda8abb
    har05: delivered_by_pr_5061
    promotion_intent: prom_20260822201148_cc5214d7
    accepted_receipt: receipt_20260822201151_94c61ba1
    target_spec: docs/GOVERNED_ARCHIVAL_FLOW/README.md
```
