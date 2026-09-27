State: Target-state concept contract; shared policy semantics are specified here but are not enforced by the current runtime.
Doc role: Concept contract
Authority: Owns the value-aware assessment and physical retention/deletion policy across stored artifact classes. It does not replace class-specific lifecycle, persistence-surface, provenance, or authority contracts and does not prescribe a storage backend or schema.
Owner: Knowledge & Artifact owns retention semantics; Capability owns reusable AI-assisted assessment; Agent / Orchestration coordinates scheduled review; Integration Fabric supplies deterministic storage inventory and tier adapters; Governance / Authority owns deletion admission, garbage collection, and receipts.
Temporal class: timeless
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-09-27
Last verified against: docs/MODULAR_ARCHITECTURE.md, docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/CAPABILITY_CONTRACT_MODEL.md, docs/INTEGRATION_FABRIC_CONTRACT.md, docs/MEETING_CONTEXT_ASSISTANCE/README.md, docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md, docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md, docs/PRIVACY.md, data/context/retention.yaml, data/context/security.yaml, app/media/transcribe.py, scripts/rotate_storage.py

# Artifact Retention Policy Contract

## Purpose

This contract defines how Yggdrasil assesses artifact value, tracks storage use, and reclaims space
when a managed storage pool needs it. Available storage is a first-class input to the overall
retention decision: deterministic capacity checks determine when cleanup is needed and how much
space to reclaim, while AI-assisted assessment provides a reasoned relative priority for eligible
artifacts. The policy does not assign a fixed deletion date or delete material solely because it is
old, large, or a member of a particular artifact class.

The contract is target-state. It does not claim that the current runtime has a shared retention
service, value assessor, cold-storage implementation, or general artifact garbage collector.

## Scope and related contracts

The shared policy covers all stored artifact classes, including human knowledge artifacts, source
material, agentic memory, meeting audio and transcripts, context bundles, companion notes, receipts,
operational traces, indexes, caches, and other runtime projections. It does not collapse their
meaning or grant authority to edit or delete them.

This policy is distinct from:

| Concern | What it answers | Owner |
| --- | --- | --- |
| Semantic lifecycle | What developmental or lifecycle state an artifact is in | `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md` and class contracts |
| Persistence surface | Whether an artifact belongs to the writing, retention, or system surface | `docs/SEPARATING_PERSISTENCE_SURFACES/README.md` |
| Temporal validity | Whether claims may have become stale or drifted | `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md` |
| Retrieval relevance | Whether an artifact is useful for a current query or context | Retrieval and salience contracts |
| Physical retention | Which storage tier an artifact occupies, its relative retention priority, and when it may be reclaimed under storage pressure | This contract |

High retention value does not mean that an artifact is current or authoritative. Cold storage does
not mean that an artifact is semantically `archived`. Deletion eligibility is not a lifecycle
transition such as memory rejection, machine-mirror discard, or note archiving.

## Retention assessment

The assessment evaluates the artifact and its context. It produces a relative retention score or
band, a confidence signal, an explanation, the evidence considered, the policy-profile version,
and the assessment time. It may recommend that a low-value artifact enter the deletion-candidate
pool. It does not set an expiry date or authorize movement or deletion. The chosen score
representation and profile values must be human-adjustable; they must not be hidden only in a model
prompt or hard-coded as an age/size cutoff.

Evidence considered includes:

| Signal | Retention implication |
| --- | --- |
| Uniqueness and ability to find or recreate the material | Hard-to-recover material has greater retention value; readily replaceable material may have less. |
| Human effort and development | Highly worked, refined, or synthesized material receives a strong value increase. |
| Access frequency and recent use | Often accessed material receives greater retention priority. Use signals are evidence of value, not proof of meaning. |
| Evergreen or user-defined long-term retention | Evergreen status or frequent use increases retention priority. An explicit user or legal hold excludes an artifact from automatic deletion until released. |
| File size and available storage | File size estimates reclaimable space, and remaining capacity guides whether and how much to reclaim. Size alone never lowers importance or makes an artifact eligible for deletion. Any configured influence of storage scarcity on the AI assessment must remain explicit and explainable. |
| Source quality and verification need | Poor source quality may increase the value of retaining the original for later verification. |
| Transcript quality and raw-audio value | A high-quality transcript can lower the unique value of raw audio; poor audio or transcription quality raises the value of retaining audio for review. |
| Legal, evidentiary, or other user-stated need | Explicit holds and user-defined requirements override a low model assessment until released by the human or an authorized rule. |
| Relations and dependencies | Consider whether another retained artifact relies on this artifact or would become unintelligible if it were removed. |

The AI assessor makes a reasoned trade-off across available evidence. It is not a deterministic
formula that mechanically sums these signals. Retention priority is relative and can change as an
artifact is used, linked, revised, better understood, or as a configured storage-scarcity signal
changes. Deterministic inventory independently measures available capacity, and storage pressure
sets the cleanup trigger and reclaim target. Pressure alone never mechanically downgrades importance
or widens low-score deletion eligibility. Time since creation may be evidence, but there is no
fixed age-based expiry or class-level deletion clock.

If evidence is missing, conflicting, low-confidence, or unavailable, the artifact does not enter
the deletion-candidate pool on that assessment. Keep its current placement and retry later. The
system does not substitute a blind age/size fallback for an uncertain value assessment. Routine
reassessment and cleanup run quietly; the human does not decide each artifact's fate one at a time.

## Assessment cadence and value bands

A target-state retention agent combines periodic, agentic reassessment with deterministic storage
measurement and cleanup controls. A review every few weeks is a reasonable initial cadence for
reassessing artifact value; the cadence remains configurable. Deterministic inventory and capacity
checks run more frequently. Low-capacity signals, substantive artifact changes, or other important
events may trigger an earlier targeted reassessment. The policy profile defines when a score is too
stale to support deletion; a pressure-triggered cleanup must refresh stale candidate assessments
before destructive action.

The policy interprets its configurable assessment into relative priority bands. These bands affect
tiering and deletion eligibility; they are not retention durations:

| Band | Required consequence |
| --- | --- |
| **High** | Keep in active storage and out of the deletion-candidate pool while the current assessment remains high. If active storage pressure cannot be relieved by eligible lower-priority material, report the capacity shortfall rather than moving or deleting high-priority material. |
| **Medium** | Keep out of the deletion-candidate pool while the current assessment remains medium. The policy may place it in a lower-cost tier when that relieves pressure on a particular storage pool. |
| **Low** | May enter the deletion-candidate pool when confidence and policy checks pass. It is not deleted merely because it was marked; it becomes eligible for reclamation only when storage pressure requires space and notice/authority checks pass. |

An artifact may remain in the candidate pool while storage is available; time in that pool is not a
deletion trigger. When space is needed, eligible candidates are considered in ascending retention
priority. If the available low-priority candidates cannot meet the reclaim target, surface the
shortfall instead of silently expanding deletion eligibility.

An explicit user or legal hold excludes an artifact from automatic deletion until released. A user
`Keep` action removes or postpones candidate status for a configurable number of review cycles, after
which the item is assessed again; an explicit `Hold` remains in effect until released. These
controls must be visible and easy to apply to a batch. Score interpretation, confidence
requirements, tiering, reassessment cadence and triggers, storage-pressure thresholds, candidate
notice behavior, and user controls belong in a documented, versioned, human-editable policy profile.
This contract owns the policy meaning; runtime binding and numeric calibration are follow-on
implementation decisions. `data/context/retention.yaml` is not that profile today; its current
relevance-ranking semantics are documented in the crosswalk below.

### Raw audio and transcript timing

For meeting audio, a usable completed transcript and its quality are evidence in the assessment of
the raw recording. Audio and transcript are assessed separately; retaining the transcript does not
automatically make the audio valuable to keep, and a poor or incomplete transcript can increase the
recording's value for verification. The assessment may mark audio as a low-priority candidate, but
the recording remains until storage pressure calls for reclaiming space and the notice and authority
checks pass. If transcription fails or is delayed, do not infer low value from the absence of a
transcript; reassess when better evidence is available.

## Physical retention and garbage-collection path

The physical retention state is separate from each artifact class's semantic lifecycle. A possible
path is hot storage → cold archive → deletion candidate → notice-cleared candidate → garbage
collection. These are placement and authority states, not age-based lifecycle deadlines:

1. **Inventory.** Maintain a machine-readable inventory of managed artifacts and copies, their
   storage pools/locations, latest retention score and confidence, assessment time/freshness,
   candidate and notice status, holds/dependencies, and estimated reclaimable bytes. Reconcile the
   inventory regularly against actual storage. Count deduplicated/shared physical data only once. Estimates
   should be shown by storage pool so operators can see how much space candidates could free there.
2. **Assessment.** On the configured cadence (initially, every few weeks is reasonable), the
   retention agent reviews value signals and proposes updated scores and candidate status. The
   deterministic inventory process measures usage and available capacity more frequently. Pressure
   or substantive changes may trigger a targeted reassessment; the model never directly changes
   files or storage state.
3. **Tiering.** When a specific pool is under pressure, the policy may move eligible lower-priority
   artifacts to a configured cold pool if that frees enough space in the pressured pool and
   preserves required access. High-priority material stays in active storage. Verify a copy before
   treating a move as complete. Track source and destination footprint separately; cold placement
   does not free total storage if the cold pool is also constrained.
4. **Deletion candidate and notice.** Low-priority, sufficiently assessed artifacts may be marked
   as candidates and listed in a low-noise batch notice or digest. Send a notice when an artifact
   first becomes a candidate or materially changes; do not repeat notices for unchanged candidates.
   The delivered notice is the final notice for that artifact version and starts its response
   deadline. Marking an artifact does not
   delete it. The notice is bound to the listed artifact version and assessment and includes
   identity, rationale, score/confidence, location/archive status, estimated reclaimable space,
   and the response deadline. A substantive content or scope change invalidates that notice and
   requires reassessment and a new notice before deletion. A batch `Keep` action removes or
   postpones candidate status under the configured policy; `Hold` excludes an artifact until
   released. A class contract may designate a rebuildable cache or index as eligible for class-level
   notice rather than a per-object notice. That class-level notice/profile satisfies the notice
   clearance check only for its enumerated artifact class; object identity, low-score eligibility,
   pool pressure, holds, and per-copy deletion receipts still apply. No action is required for
   routine background operation.
5. **Pressure-triggered reclamation.** A deterministic monitor detects when a storage pool reaches
   its configured pressure threshold and calculates a reclaim target. A deterministic selector
   chooses only notice-cleared, low-priority candidates that are eligible for that pool, beginning
   with the lowest current retention score and using their estimated physical reclaimable bytes to
   meet the target. No response to a successfully delivered final notice by its deadline counts as
   acceptance under the user's preconfigured policy. Failed delivery disqualifies that item from
   automatic deletion; use bounded retries and surface one consolidated exception. Immediately
   before deletion, Governance rechecks artifact identity/version, current assessment, policy,
   capacity need, location, and holds. A score change that makes an artifact ineligible, a
   substantive content/scope change, resolved pressure, or a hold cancels that deletion attempt.
6. **Insufficient candidates and receipt.** If eligible low-priority candidates cannot meet the
   reclaim target, do not silently lower the priority threshold or delete higher-priority material.
   Report the amount safely reclaimable and the remaining shortfall. Record a receipt for each
   completed copy-removal operation with artifact identity/version, assessment rationale and
   confidence, policy version, hold/notice checks, locations removed, estimated and actual bytes
   reclaimed, and GC result. A pool-level reclaim operation is complete when its requested copy set
   has been verified removed. Report an artifact as fully deleted only when no known managed copy
   remains; otherwise report remaining locations and the partial result. Receipts are stored
   artifacts and follow their own retention policy; related receipts may be consolidated so deletion
   records do not create an endless chain.

Reclamation may be copy-scoped. For example, a hot-pool pressure request may remove the hot copy
while retaining a verified cold archive; this frees space in the pressured pool without fully
deleting the logical artifact. A request for full artifact deletion must enumerate and address all
known managed copies. If a copy cannot be removed, report a partial result and do not report the
logical artifact as deleted. A failed or partial removal does not produce a successful receipt for
the affected copy set. Actual freed bytes are reconciled after the operation; predicted reclaimable
bytes are planning estimates, not proof of successful reclamation.

Policy configuration must make assessment factors, score bands, confidence requirements, review
cadence and triggers, per-pool pressure thresholds and reclaim targets, tiering, notice timing,
candidate eligibility, and user controls changeable without code changes. This contract does not
prescribe numeric defaults; the implementation must expose those defaults explicitly before
enabling deletion.

## Subsystem ownership

The retention policy composes existing subsystems; it does not create a retention subsystem or a
new deletion authority:

| Subsystem | Responsibility |
| --- | --- |
| Human Surface | Shows batched candidate notices and storage summaries; accepts `Keep`, `Hold`, and policy-control intent from the user. |
| Knowledge & Artifact | Owns retention-policy meaning, artifact identity/class semantics, evidence interpretation rules, and candidate meaning. |
| Runtime Projection | May maintain rebuildable indexes or views over artifact locations, scores, and reclaimable-space estimates; those projections do not decide value or authorize deletion. |
| Capability | Provides the reusable AI-assisted retention assessment as a typed, provenance-bearing function. It returns a score/rationale and never manages files or authorizes an effect. Its exact contract is a follow-on capability specification. |
| Agent / Orchestration | Schedules the periodic review (every few weeks is a reasonable initial target), gathers assessment inputs, coordinates deterministic checks, and prepares candidate batches. It does not own policy meaning or deletion authority. |
| Governance / Authority | Applies holds, notice, pressure, eligibility, and policy checks; admits tier moves and destructive cleanup; records receipts. |
| Integration Fabric | Supplies filesystem/storage adapters and deterministic measurements for available, used, and reclaimable bytes by storage pool. |
| Observability / Fitness | Reports assessment quality, storage pressure, estimated versus actual recovered space, cleanup failures, and policy outcomes without logging artifact contents by default. |

## Authority, provenance, and lifecycle boundaries

- The retention agent coordinates periodic review, deterministic capacity measurement, and
  candidate preparation. The assessor returns a relative score and rationale; it never moves,
  archives, or deletes an artifact.
- Knowledge & Artifact owns assessment meaning and candidate semantics. Integration Fabric
  supplies storage inventory and storage-tier adapters. Runtime Projection may maintain rebuildable
  inventory views but does not become the authority for artifact value or deletion.
- Governance / Authority admits a tier move or pressure-triggered deletion under the current policy
  profile and records the receipt. A model-generated assessment does not override a hold or
  authorize an effect.
- The policy does not relabel an artifact's semantic class, imply that cold placement is
  `archived`, or use `discarded` as a universal artifact lifecycle state.
- Physical deletion is an explicit destructive effect authorized by the user's configured policy
  and a storage-pressure request. A delivered batch notice is the last chance to apply Keep or Hold
  to listed candidates; no response by the stated deadline is acceptance as specified above.
- Deletion must preserve enough non-content provenance to explain what policy decision occurred,
  while that receipt remains subject to this same policy.
- Copy locations and deletion outcomes must be inspectable. Replication delay, disconnected
  devices, or unavailable archive targets cannot be represented as completed deletion of all
  managed copies.

## Current-repository crosswalk

These existing rules have narrower roles and are not a unified physical retention policy:

| Existing surface | Current role | Boundary for this contract |
| --- | --- | --- |
| `data/context/retention.yaml` | Declares `keep_if` and `downrank_if` relevance signals, including provenance, answerability, age, and context links. Repository search found no runtime consumer. | Keep its ranking meaning distinct; do not treat it as deletion permission or as the shared retention profile. |
| `data/context/security.yaml` | Lists embedding retention durations for external seed, curated, and evergreen content, plus security settings. | These are embedding/security-specific declarations, not cross-artifact deletion authority. |
| `docs/PRIVACY.md` | Describes local execution/logging posture and specific temporary media/outbox retention behavior. | Existing per-surface behaviors require reconciliation when a shared policy is implemented; this contract does not claim they are currently enforced uniformly. |
| `app/media/transcribe.py` | Provides a local/file-or-URL transcription path and writes transcript output; it is not live stream capture. | Raw-audio cleanup is specific to that path and is not a general media lifecycle manager. |
| `scripts/rotate_storage.py` | Rotates selected DuckDB/provenance files with operational count/age controls. | Operational database rotation is not artifact-value assessment or general garbage collection. |
| Canvas/session retention docs | Describe session-log retention and pinning questions for a particular interaction surface. | Session logs participate in the shared policy but keep their own artifact identity and provenance. |
| `ARTIFACT_LIFECYCLE_MODEL.md` | Defines class-specific semantic lifecycle states and transitions. | The retention policy governs physical placement and removal without borrowing or redefining those states. |

The crosswalk is a current-state snapshot for contract design. Before runtime implementation, audit
the affected owner docs and code paths again and align their local settings with the shared policy
without implying behavior that has not shipped.

## Related documents

- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/MEETING_CONTEXT_ASSISTANCE/README.md`
- `docs/PRIVACY.md`
