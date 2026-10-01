State: Target-state feature specification; planned, not shipped.
Doc role: Feature specification
Authority: Owns the user-facing outcome, scope, flow, and subsystem composition for meeting context assistance. It is not itself a capability contract and does not claim that live capture, in-meeting context retrieval, or post-meeting note proposals are implemented.
Owner: Product / architecture; Agent/Orchestration owns feature composition, with subsystem responsibilities below.
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-09-27
Last verified against: docs/HUMAN-FLOWS.md, docs/HUMAN_FLOW_TO_RUNTIME_MAP.md, docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md, docs/MODULAR_ARCHITECTURE.md, docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/CAPABILITY_CONTRACT_MODEL.md, docs/INTEGRATION_FABRIC_CONTRACT.md, docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md, docs/CONCEPTS/ARTIFACT_RETENTION_POLICY_CONTRACT.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md

# Meeting Context Assistance

## Purpose

Meeting context assistance combines durable capture with in-the-moment cognitive support. It lets
the human stay present in a meeting while Yggdrasil transcribes the session, finds relevant context
in the vault, and presents concise, source-linked information privately. A meeting is not reduced
to a transcript or generic summary: its participants, project background, current discussion, and
the user's direct questions shape what context is retrieved and surfaced.

The human flow is anchored in `docs/HUMAN-FLOWS.md`; its user-outcome acceptance scenario is
`docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md` §13. This feature specification defines the target
system composition for that flow.

This document specifies a future user-facing feature composed from use-case flow(s), reusable
capabilities, integrations, and the eight existing subsystems. The feature crosses subsystem
boundaries; its components retain their subsystem owners. It changes no kernel authority boundary,
introduces no ninth subsystem, and makes no runtime claim.

## Scope

The first target covers:

- live desktop meetings and ad hoc desktop audio sessions;
- context from the existing vault and meeting metadata such as attendee identities, agenda, and
  calendar description;
- local-first audio capture, transcription, retrieval, and reasoning;
- optional remote ASR, LLM, or calendar providers only when explicitly configured and disclosed;
- a quiet, private sidecar that surfaces only relevant, high-confidence cards and answers direct
  questions from the user;
- a source-linked post-meeting note proposal that the human reviews before durable writeback.

The first target excludes mobile or in-person capture, prerecorded-meeting imports, email, CRM, and
general web search. The assistant does not speak to the meeting or expose its private sidecar to
other participants.

## Human flow

1. **Prepare.** The system receives meeting metadata from a configured calendar source or a local
   meeting description. It resolves attendee and project references against the existing vault.
   Ambiguous or unsupported identity matches remain unresolved; the system does not state a guess
   as fact.
2. **Start and control capture.** The user explicitly starts the session. The active capture state
   and input sources remain visible, and the user can pause or stop. The configured participant
   notice and provider-disclosure rules are shown before capture begins.
3. **Transcribe.** Local ASR produces time-aligned transcript segments. Speaker attribution carries
   confidence and may remain unknown. Audio, transcript, temporary stream state, and later notes
   remain distinct artifacts with explicit provenance links.
4. **Build meeting context.** As meaningful turns arrive, the orchestrator requests a scoped,
   inspectable context bundle from retrieval and context-assembly capabilities. The bundle records
   the meeting scope, included and excluded material, why each item was selected, freshness,
   authority flags, provenance, and expiry as required by
   `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`.
5. **Assist privately.** The sidecar shows short, source-linked cards when the evidence is relevant
   and confidence is sufficient. The user can ask a direct question at any time. A card that arrives
   after its discussion has moved on is marked stale or withheld rather than shown as live guidance.
6. **Review after the meeting.** The system may propose a transcript-linked note, decisions, and
   commitments. They remain proposals until the user reviews them and any write passes through the
   existing governed APPLY path. The durable note links to the transcript and supporting context;
   it does not replace them.
7. **Apply retention policy.** Audio, transcript, note, context bundle, session state, and derived
   projections each receive a separate value assessment under
   `docs/CONCEPTS/ARTIFACT_RETENTION_POLICY_CONTRACT.md`. A low score can mark an artifact as a
   deletion candidate; it remains until storage pressure requires space and the configured notice,
   hold, and authority checks pass. The retention agent tracks the estimated reclaimable space by
   storage pool.

## Surface and interaction rules

- The in-meeting sidecar is a private mode hosted by the existing Companion UI shell and an
  authorized Chat surface. It is not a fourth canonical interaction surface and does not acquire
  independent authority.
- The live experience is quiet and non-interruptive. It does not speak or inject content into the
  meeting. Only relevant, high-confidence cards appear without a direct question.
- Capture has an explicit user start, visible active state, and pause/stop controls. Participant
  notice and any configured remote-provider disclosure are prerequisites to starting capture.
- In-meeting cards and answers are read-only. The post-meeting note is a proposal. Neither an agent
  nor a capability writes directly to the durable surface.
- Context is presented with source links and enough explanation to inspect why it was surfaced.
  Model-generated interpretation is marked as interpretation, not as source fact.

## Subsystem ownership

The feature is an emergent composition across the eight existing subsystems in
`docs/MODULAR_ARCHITECTURE.md`. The longer-horizon subsystem decomposition and change-impact model
remain in `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`:

| Subsystem | Responsibility in this feature |
| --- | --- |
| Human Surface | Hosts the private sidecar, start/pause/stop controls, direct questions, corrections, and note review. |
| Knowledge & Artifact | Owns durable meeting artifacts, source links, artifact classification, and retention semantics. |
| Runtime Projection | Stores transient session projections and rebuildable transcript indexes, context projections, and search projections. It does not own unique captured audio or the canonical finalized transcript. |
| Capability | Provides reusable identity resolution, retrieval/context assembly, turn synthesis, citation, and note-proposal functions. The shared retention contract also places reusable AI-assisted value assessment in this subsystem. |
| Agent / Orchestration | Coordinates the meeting session, decides when to invoke capabilities, handles timing and state, and returns bounded results to the surface. This is the feature-composition owner. It also owns the scheduled retention-agent workflow, not the assessment meaning or deletion authority. |
| Governance / Authority | Admits meeting scope and provider use, governs proposals and deletion, and requires policy checks and receipts for durable effects. |
| Integration Fabric | Adapts desktop audio inputs, local or configured remote ASR/LLM providers, configured calendar metadata, and storage inventory/tier operations. It provides access, transport, inference, physical measurements, and governed copy movement; it does not own canonical artifact identity or decide meaning. |
| Observability / Fitness | Measures capture and transcript quality, identity-resolution uncertainty, context latency and freshness, fallback behavior, card use, storage pressure, candidate inventory, estimated versus actual reclaimed space, and GC outcomes without logging full transcript content by default. |

Knowledge & Artifact remains the semantic owner of what is retained. Governance / Authority owns
admissibility and destructive-effect control. Agent / Orchestration does not absorb either role.

## Capability reuse and ownership

The feature is not a capability. It composes capabilities whose primary owner is the Capability
subsystem, while the other subsystems retain their own responsibilities. The standard contract
shape is defined in `docs/CAPABILITY_CONTRACT_MODEL.md`; this feature spec does not duplicate those
contracts.

| Meeting function | Owner and treatment |
| --- | --- |
| Resolve participants and project references | Planned meeting-specific read-only capability, `resolve_meeting_context`, owned by the Capability subsystem. Its eventual contract must return confidence, source references, and explicit unresolved/ambiguous results. |
| Retrieve and assemble project context | Reuse Retrieval, Context building, and the context-bundle contract. Meeting-specific scope, freshness, and transcript cues are a profile over those capabilities; do not create a duplicate `assemble_meeting_context` capability. |
| Answer questions and surface timely cards | Compose retrieval, resurfacing, synthesis/review, and citation-checking capabilities under meeting-session orchestration. Create a standalone meeting-turn capability only if later scenarios establish an independently reusable contract. |
| Capture, transcribe, and read calendar metadata | Integration Fabric adapters for desktop audio, ASR, and configured calendar providers. These are integrations, not cognitive capabilities; session control belongs to Agent / Orchestration and visible controls to Human Surface. |
| Propose notes, decisions, and commitments | Reuse the existing note-patch/proposal and governed APPLY contracts. Keep commitment creation tied to its own artifact and authority contracts; do not create a catch-all `propose_meeting_artifacts` capability. |
| Assess and reclaim meeting artifacts | Reuse the shared retention assessment and pressure-triggered cleanup defined in `docs/CONCEPTS/ARTIFACT_RETENTION_POLICY_CONTRACT.md`; do not create a meeting-only retention capability or timer. |

Before implementation issues are created, any genuinely new capability must name its primary
subsystem owner, answer the standard capability contract, and show how it fits the existing
capability set. Logs contain operational metadata rather than full transcript text by default; any
change to that privacy posture requires an explicit contract update.

## Artifact and authority boundaries

| Artifact | Role | Authority and linkage |
| --- | --- | --- |
| Raw audio | Unique captured source artifact | The retained recording is a managed source artifact with provenance and retention assessment; it is not a rebuildable runtime projection. A usable transcript and its quality inform whether the recording remains valuable for verification. A low score can make audio a deletion candidate, but storage pressure and the configured notice/hold/authority checks govern copy removal. |
| Transcript | Finalized, time-aligned, source-derived artifact | Links to the audio and meeting metadata; transcription errors and uncertain speaker labels remain inspectable. Partial streaming text, transcript search indexes, and context projections are separate disposable or rebuildable runtime projections. |
| Context bundle | Bridge / assembly artifact | Carries selected and excluded context, scope, provenance, freshness, authority flags, and expiry; never becomes memory by itself. |
| Meeting note after approval | Human-canonical knowledge artifact | Accepted through governed writeback; links to transcript spans and source notes. |
| Live session state and indexes | Orchestration state plus runtime projection | Agent / Orchestration owns the session flow; Runtime Projection may store transient session state and rebuildable indexes. These do not replace unique captured audio or the canonical finalized transcript. |
| Note proposal and cards | Proposal or read-only output | Carry evidence and confidence; do not silently mutate durable artifacts. |

Retention and physical hot/cold placement do not change an artifact's semantic class or its
lifecycle state. The shared retention contract governs those physical decisions.

## Local-first operation, privacy, and degradation

- Local capture, ASR, vault retrieval, and local reasoning are the default path. Remote providers
  run only when explicitly configured; the user sees which data will be sent before the session
  starts.
- Calendar access is limited to configured meeting metadata. Existing vault artifacts are the only
  knowledge source for the first target. Email, CRM, and web data are out of scope.
- If a remote provider is unavailable, continue with local capabilities where available and report
  the reduced capability. If local ASR or capture is unavailable, show that recording/transcription
  is not active; do not imply otherwise.
- If retrieval, identity resolution, or model reasoning is unavailable, capture may continue while
  context cards are withheld or marked unavailable. Never show stale delayed output as real-time
  advice.
- Unknown speaker identity, incomplete transcript spans, and conflicting sources remain explicit.
  An uncertain assessment does not silently become a confident fact.
- An implementation issue must define measurable latency and freshness limits before runtime work
  begins. Outputs that miss those limits are marked stale or withheld.

## Dependencies and sequencing

The roadmap sequences the shared retention contract before this feature. The context-bundle
contract and production ContextBundle route are shipped foundations; meeting-specific refresh and
low-latency routing remain future work. Runtime work also depends on:

- a local-first live desktop audio capture and streaming ASR path;
- participant/project resolution against configured meeting metadata and vault references;
- measurable freshness and latency bounds for meeting-specific context refresh and card delivery;
- a private sidecar hosted within an existing interaction-surface authority model;
- policy-governed artifact retention and deletion receipts.

The work remains spec-first. After these contracts are accepted, use `docs-to-issue` or
`feature-breakdown` to create bounded implementation work; this document does not create GitHub
backlog items.

## Out of scope

- Mobile, room/in-person, and prerecorded-meeting capture.
- Email, CRM, and general web context.
- A bot that speaks in the meeting or exposes private assistance to participants.
- Automatic durable note writes or autonomous deletion based only on model output.
- A new interaction surface or a ninth system subsystem.
- A runtime integration registry, storage schema, or claim that the feature is shipped.

## Related documents

- `docs/HUMAN-FLOWS.md`, `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`, and `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md` §13
- `docs/MODULAR_ARCHITECTURE.md` and `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/CAPABILITY_CONTRACT_MODEL.md` and `docs/INTEGRATION_FABRIC_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`
- `docs/CONCEPTS/ARTIFACT_RETENTION_POLICY_CONTRACT.md`
