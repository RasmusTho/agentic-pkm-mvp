State: Research/design proposal (advisory, 2026-07-15). **This document is not a specification and enacts no runtime behavior, consent grant, schema, model choice, or threshold.** It proposes a buildable local-only direction under ADR-0060; Posture A remains operational until ADR-0060's activation gates pass.
Doc role: Research/design proposal — input to a later `feature-breakdown` pass
Authority: Advisory only. ADR-0060 owns the B-full and voiceprint consent-class decisions; `docs/HEIMDAL/OWNER_DECISIONS.md` retains R-CONSENT/R-PRIVACY/R-EXTERNAL; enacted event and runtime contracts remain with their existing owner surfaces.
Owner: Architecture / Heimdal attribution + Mimer identity seam
Temporal class: reference
Review cadence: event-driven (before voiceprint feature breakdown or when the local model bake-off runs)
Source of truth: ADR-0060, ADR-0049, `docs/HEIMDAL/FABLE_COMPANION.md`, `docs/HEIMDAL/CAPABILITY_CHARTER.md`, and `docs/HEIMDAL/ENTITY_IDENTIFICATION_RESEARCH.md`; external sources below support model feasibility only.

# Voiceprint attribution design proposal

This proposal closes a design gap, not a runtime gap. It keeps the existing Heimdal pipeline and
authority boundaries intact: A8 performs local ASR, A9 attributes and degrades, the published event
uses `attributions[].basis: voiceprint`, and Mimer's markdown-first entity register remains the
identity authority. No voiceprint vector or raw voice sample crosses the raw-to-published seam.

The non-negotiable default is unchanged: a speaker is publishable as a named person only when both
identity evidence and an applicable consent grant resolve. A weak match, an ambiguous match, a
revoked/missing grant, a stale profile, or a model/profile version mismatch all resolve to
`unresolved`; third-party content remains represented through `withheld[]`, never guessed or
silently upgraded.

## Recommended approach

### Recommendation: a local, staged verification pipeline

Use a three-part local pipeline rather than asking one model to perform segmentation, diarization,
and identity in one opaque decision:

1. **Silero VAD** proposes bounded speech regions from the continuous stream. It is small, supports
   local PyTorch/ONNX execution, and exposes the threshold, minimum speech, minimum silence, maximum
   speech duration, and padding controls this design needs. Its own documentation says thresholds
   should be tuned per dataset; the values in the stream strategy below are therefore bake-off
   seeds, not enacted constants.
2. **A local diarization/speaker-change stage** splits a region into speaker-homogeneous turns and
   marks overlap. Prefer `pyannote.audio` Community-1 for the first bake-off because it supplies
   local diarization primitives and accepts locally stored pipeline/model paths. Disable optional
   telemetry and fail loud if the pinned local artifact is absent. A Hugging Face token may be used
   during an explicit installation step to obtain an accepted model artifact; inference must never
   depend on Hugging Face, pyannoteAI, or another network service.
3. **SpeechBrain ECAPA-TDNN embeddings** are the primary voiceprint candidate. The published
   SpeechBrain model card provides local embedding extraction and cosine-distance verification,
   reports a VoxCeleb test result, and explicitly warns that performance does not transfer by
   warranty to other data. That combination fits HEIM-6: the mechanism is mature and local, but its
   score must be calibrated on this operator's devices, languages, rooms, and interlocutors before
   it can become an attribution policy.

Run a bounded bake-off before enactment:

- **Primary:** SpeechBrain `spkrec-ecapa-voxceleb`.
- **Comparator:** the embedding model shipped with the selected local pyannote pipeline, so
  diarization and verification can be evaluated with one model family.
- **Cheap baseline only:** Resemblyzer. It is local and Apache-2.0, but its own documentation says it
  works best in English and the project is materially older. Keep it only if it wins on the actual
  Swedish/English, far-field, wearable-device fixture set.
- **Fixture matrix:** operator and consented test speakers; clean/quiet, room-distance, outdoor,
  phone/pendant, Swedish/English, short/long turns, overlap, illness/hoarseness, and hard negatives
  with acoustically similar voices. Raw fixtures stay inside the Heimdal raw seam.
- **Measures:** false accept rate (the privacy-critical metric), false reject rate, equal-error rate,
  calibration error, `unknown` rate, overlap failure rate, real-time factor, peak memory, and impact
  on the shared production host. Results are stratified by device and acoustic condition, not
  collapsed into one flattering average.

Do not copy a library's demo threshold. Choose two locally calibrated decision boundaries for each
pinned `(embedding_model, preprocessing_version, profile_version)`:

- below `candidate_floor`: `unresolved`;
- between `candidate_floor` and `resolved_floor`: `ambiguous` with candidates retained only inside
  the protected attribution stage;
- at or above `resolved_floor`: identity evidence may be `matched`, but publication still requires
  an active grant applicable to that entity and capture context.

Require a margin over the second-best eligible profile as well as the absolute threshold. One strong
score against two nearly equal candidates is ambiguous, not resolved. Overlap, too little voiced
audio, a stale/revoked profile, or an out-of-calibration condition forces `unresolved` regardless of
score. The implementation must pin local artifacts by digest, record stage versions, disable network
fallback and telemetry, and leave the item queued/degraded if any local model is unavailable.

### Operator enrollment under `self_record`

Operator enrollment is an explicit, reversible owner action that extends the already-decided
standing `self_record` consent; it does not mint a new consent class.

1. The enrollment surface asks the operator to record several prompted and free-speech samples over
   multiple sessions and, ideally, at least two expected devices/conditions. A starting bake-off
   target is 60–120 seconds of accepted voiced audio in 5–10 samples; the later implementation spec
   sets the exact minimum from measured stability.
2. The same pinned VAD, preprocessing, overlap rejection, and embedding model used at inference
   validate each sample. Samples with insufficient speech, clipping, overlap, or excessive noise are
   rejected loudly. Enrollment never harvests ordinary recordings silently.
3. Store individual normalized embeddings plus a robust centroid/profile summary inside the
   encrypted, policy-gated Heimdal identity-profile store. Store only opaque profile refs in control
   notes or events. Raw enrollment audio follows the raw-layer retention/erasure policy; embeddings
   are biometric-class protected data even when raw audio is deleted.
4. Bind the profile to the operator's existing entity ref and the standing
   `grant-self-record-v1` lineage. The event-side attribution may become
   `resolution: resolved`, `basis: voiceprint` only after both the profile binding and active
   `self_record` grant resolve.
5. Every re-enrollment creates a new profile version. Old profiles become inactive; observations are
   not rewritten. Reprocessing, if authorized later, emits a revision/correction event under HEIM-1.

This can be built and exercised on deliberate Posture-A memos before B-full activation, as
ADR-0060 permits. It must not claim that B-full, place/session consent, or third-party enrollment is
operational.

### Per-person grant note and entity-register binding

The proposed durable human-readable surface is one markdown grant note per third-party voiceprint,
linked from `_heimdal/consent.md` and bound by stable refs to exactly one Mimer person entity and one
protected Heimdal voice profile. This is a proposal for later CES/ADR/spec enactment, not a schema
landed by this document.

Proposed path: `_heimdal/voiceprint-grants/{grant_ref}.md`.

Proposed shape:

```yaml
---
kind: heimdal_voiceprint_identity_grant
schema_version: proposed-v1
grant_ref: grant-voiceprint-<uuid>
entity_ref: ent:<uuid>
profile_ref: heimdal-voice-profile:<uuid>:<version>
status: active | revoked | expired
consent_class: per_person_voiceprint
consent_evidence_ref: <opaque governed evidence ref>
granted_at: <ISO-8601>
expires_at: <ISO-8601 or null>
revokes_grant_ref: null | grant-voiceprint-<uuid>
profile_model_ref: <pinned model + preprocessing version>
---
```

Field rules for a later contract:

- `entity_ref` resolves to one canonical/provisional **person** note in Mimer's markdown-first entity
  register. The grant note never duplicates the person's name as identity authority.
- `profile_ref` is opaque and resolves only inside the policy-gated Heimdal profile store. No voice
  embedding, raw path, or audio appears in markdown, event payloads, logs, receipts, or indexes.
- `consent_evidence_ref` points to governed evidence of consent; it is not free-text proof and the
  operator's act of enrollment is not silently treated as the other person's consent.
- An active grant is valid only when the grant, entity ref, profile version, model/preprocessing
  version, and capture-context applicability all resolve. Any broken join degrades closed.
- Revocation is append-only: create a revocation record/note that names `revokes_grant_ref`, make the
  profile ineligible immediately, and trigger the separately enacted raw/profile erasure and
  projection-suppression paths. Do not edit old observations or reuse a revoked profile version.
- Entity merges follow Mimer's redirect lineage. An ambiguous/split entity or a merge under review
  makes the voiceprint grant ineligible until the binding is explicitly reconciled; identity graph
  evolution must never broaden consent by accident.

At A9, diarization produces local speaker turns, the matcher compares each eligible turn only with
active, context-applicable profiles, and the consent resolver performs the second gate. The published
attribution contains the resulting entity resolution, `basis: voiceprint`, and honest confidence
metadata; it never exposes candidate lists or biometric vectors. A speaker with no applicable grant
remains `role: present, resolution: unresolved`, and their content remains in `withheld[]` with the
existing third-party reason.

### HEIM-6 confidence mapping

Treat similarity as model evidence, not as identity probability. Preserve the existing per-axis
confidence design:

| Evidence state | Published resolution | Attribution confidence | Publication consequence |
| --- | --- | --- | --- |
| insufficient/overlapped/out-of-calibration audio | `unresolved` | score retained internally; event records method/version and a degraded band | third-party content withheld |
| score below candidate floor | `unresolved` | calibrated band `low` | third-party content withheld |
| score in review band, or top-two margin too small | `ambiguous` | candidate-relative calibrated band; no canonical winner | third-party content withheld |
| score above resolved floor and margin, but grant missing/stale/revoked/inapplicable | `unresolved` | identity evidence may be recorded internally; consent does not become confidence | third-party content withheld |
| score and margin pass; active applicable grant resolves | `resolved` | numeric score + `method`, `model_ref`, `calibration`, profile version; human UI renders a band | named attribution may publish |
| explicit per-fragment human correction | new correction event with `basis: stated` | `by_construction` only for the corrected fragment | never upgrades unrelated turns/events |

The `attribution` axis is independent of transcription, temporal, entity-resolution, and consent
state. Consumers may pass through or downgrade it, never take a maximum with another axis. A new
model, preprocessing change, profile version, or calibration population creates a new method/version;
it never silently reinterprets old scores. Threshold changes affect new processing or explicit
revision events only.

### Primary feasibility sources

- SpeechBrain ECAPA-TDNN model card (local embeddings, cosine verification, transfer limitation):
  https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb
- ECAPA-TDNN paper (Interspeech 2020): https://arxiv.org/abs/2005.07143
- pyannote.audio (open-source diarization, segmentation, overlap, embeddings, local-path support):
  https://github.com/pyannote/pyannote-audio
- Silero VAD implementation and parameter semantics:
  https://github.com/snakers4/silero-vad/blob/master/src/silero_vad/utils_vad.py
- Resemblyzer baseline and stated language limitation:
  https://github.com/resemble-ai/Resemblyzer

## Open questions for the owner

The following are R-CONSENT/R-PRIVACY decisions. Feature breakdown must keep them blocked or route a
decision brief; an implementation agent may not answer them implicitly through defaults:

1. **What proves third-party consent?** Who must attest, what evidence is sufficient, and may the
   operator record that evidence alone, or must the subject participate in the enrollment flow?
2. **What is the grant's scope?** Is a per-person voiceprint grant usable everywhere, or must it be
   intersected with place/session/purpose/time? Does a grant authorize identity matching only, or
   also publication of that person's transcribed speech? ADR-0060 decides neither edge case.
3. **Expiry and renewal:** must every third-party grant expire, and what event requires renewed
   consent or a fresh voice profile?
4. **Revocation depth:** beyond making future matches ineligible and deleting raw/profile material,
   what must happen to already-published attributed content and derived Mimer artifacts? The
   append-only-versus-erasure tension remains owner territory.
5. **Special subjects:** are minors, people unable to consent, household members, and incidental
   recurring speakers categorically excluded or governed by distinct rules?
6. **Human correction authority:** may the operator correct one turn to a known person without an
   active voiceprint grant, and if so must the result remain `basis: stated` and withheld rather than
   becoming reusable enrollment evidence?
7. **Profile retention and portability:** how long may inactive/revoked biometric templates remain,
   may they ever leave the Heimdal raw/private boundary for backup, and what deletion receipt is
   required?

Until these are decided, the narrow buildable posture is operator enrollment under `self_record`, a
synthetic/explicitly consented local bake-off, and fail-closed third-party degradation. There is no
cloud fallback and no inferred consent from familiarity, frequency, co-occurrence, entity presence,
or a high voice similarity score.

## Recommended slice breakdown

This ordering is suitable input to `feature-breakdown`; it deliberately separates owner decisions,
measurement, protected storage, matching, and publication so no slice can smuggle consent through a
model score.

1. **VOICE-01 — Consent/authority decision and contract enactment.** Resolve the owner questions
   needed for the first third-party path; update ADR/CES and the consent-control owner surfaces.
   Verify with exact doc anchors and no runtime claim.
2. **VOICE-02 — Local model + segmentation bake-off.** Build an offline harness and private fixture
   matrix comparing ECAPA-TDNN, the selected pyannote embedding, and the Resemblyzer baseline plus
   Silero/diarization settings. Produce FAR/FRR/calibration/RTF/memory receipts and a pinned artifact
   recommendation. No production enrollment or attribution.
3. **VOICE-03 — Continuous-stream segmentation stage.** Implement the stream contract below,
   deterministic timestamp lineage, crash/restart overlap handling, bounded buffers, and A8-compatible
   ASR units. Verify silence, short utterance, long monologue, overlap, and restart fixtures.
4. **VOICE-04 — Protected voice-profile store.** Add encrypted/policy-gated profiles, versioning,
   model/preprocessing refs, revocation eligibility, deletion receipts, and a hard prohibition on
   embeddings in events/markdown/logs. Include producer migration/preflight if a runtime invariant is
   introduced.
5. **VOICE-05 — Operator enrollment under `self_record`.** Explicit capture/quality/re-enrollment
   flow, operator entity binding, and Posture-A memo verification. Keep B-full inactive.
6. **VOICE-06 — Calibrated matcher and HEIM-6 policy.** Implement absolute + top-two-margin gates,
   unknown/ambiguous/resolved states, out-of-calibration fail-closed behavior, stage-version lineage,
   and replay-as-revision.
7. **VOICE-07 — Per-person grant note + entity binding.** Only after VOICE-01: enact the markdown
   note schema, ledger/event linkage, entity redirect/split behavior, explicit enrollment, expiry,
   revocation, and erasure/suppression effects.
8. **VOICE-08 — A9 attribution/degradation integration.** Compose diarized turns, matcher evidence,
   grant resolution, `basis: voiceprint`, and `withheld[]`; prove an ungranted, revoked, ambiguous,
   overlapping, or low-confidence third party never publishes as a named speaker.
9. **VOICE-09 — G2 capacity + adversarial UAT.** Run many-hour continuous workloads on the target
   host, measure production-runtime impact, spoof/replay/noise/overlap failures, and produce the
   durable ADR-0060 G2 evidence. Passing VOICE-09 alone does not activate B-full; all ADR-0060 gates
   still apply.

The later feature parent should own end-to-end acceptance: continuous audio → VAD segment →
speaker turn → local ASR/voiceprint → grant gate → published resolved or withheld observation, plus
revocation and restart recovery. Each child remains one bounded PR with its own `Verify:` targets.

## Stream segmentation strategy

### Proposed continuous-stream contract

The segmentation stage turns an unbroken B-full audio stream into deterministic, replayable
**processing segments**. A processing segment is not an Episode, consent grant, speaker identity, or
published observation. It is an internal boundary proposal under one capture stream/consent context;
Mimer's Episode Resolution Engine retains multi-stream Episode ownership.

Input assumptions:

- resample locally to 16 kHz mono PCM for VAD/ASR while preserving source-time offsets;
- keep a bounded ring buffer so onset padding and crash-safe replay do not lose speech;
- stamp `stream_ref`, source start/end offsets, VAD model digest, parameter-set version, and
  consent-context ref on every proposed segment;
- a grant must already authorize capture admission; VAD is not the consent gate.

Starting parameters for the bake-off (not enacted defaults):

| Parameter | Seed value | Reason / failure posture |
| --- | --- | --- |
| speech probability threshold | `0.50`, with hysteresis/negative threshold | Silero's documented general starting point; tune per device/room |
| minimum voiced duration | `500 ms` | reject clicks/breath/noise while retaining short acknowledgements; rejected audio remains raw-seam evidence, not silently published |
| close/merge silence | `< 500 ms` merges; `>= 800 ms` finalizes | closely spaced clauses stay together; a meaningful pause bounds latency |
| edge padding | `200 ms` before/after | protect clipped phonemes; timestamps distinguish padded audio from voiced interval |
| target segment length | `5–20 s` | enough speech for Whisper context and speaker embeddings without long latency |
| hard maximum | `30 s` | bounds ASR/memory/latency; cut at the best `>= 200 ms` silence in the last 5 s |
| no usable silence before max | split with `1 s` overlap | avoid dropping words; downstream timestamp reconciliation removes duplicate transcript content |
| voiceprint turn minimum | `1.5 s` voiced, otherwise `insufficient` | short turns must not be force-matched |

Boundary algorithm:

1. VAD opens a candidate on sustained speech and prepends the ring-buffer padding.
2. Speech spans separated by less than 500 ms merge into one candidate. Gaps from 500–800 ms remain
   timing breaks inside the candidate; at 800 ms the candidate finalizes. Silence itself is never
   sent as semantic content.
3. At 30 seconds, split on the best recent silence; if none exists, use a one-second overlap and
   preserve exact offsets for deterministic de-duplication. A long monologue therefore cannot create
   an unbounded ASR call.
4. Run local diarization/speaker-change and overlap detection inside each processing segment.
   Voiceprint matching consumes each non-overlapped, speaker-homogeneous **turn**, not the mixed
   processing segment. Turns shorter than the calibrated minimum remain unresolved.
5. A8 receives the bounded processing segment plus timestamped turn hints and returns its existing
   `TranscriptResult`/segments. A9 joins transcript spans to diarized turns, performs voiceprint and
   grant resolution, and applies the existing degradation rule before publication. The local raw-seam
   transcript may exist for processing/review, but ungranted third-party text must not appear in
   published `content`.
6. Consecutive segments may share one capture stream and later one Episode, but are independently
   idempotent by source offsets + parameter/model version. Reprocessing with changed segmentation or
   models creates versioned revision output, never an in-place rewrite.

### Required failure behavior

- VAD/model missing, decode error, buffer overrun, clock discontinuity, or uncertain overlap: fail
  loud, preserve a gap/error receipt, and do not substitute cloud VAD/ASR/diarization.
- Speaker change near a hard cut: retain overlap and mark the turn boundary uncertain; never average
  two speakers into one profile match.
- No speech: emit no ASR unit, but keep capture/gap telemetry according to the existing durable-vs-live
  telemetry boundary.
- Unknown or ungranted speech: retain timing/presence as the current contract allows and emit
  `withheld[]`; do not leak candidate identities, similarity scores, embeddings, or transcript text.
- Parameter tuning: version every parameter set and evaluate boundary precision/recall, false merges,
  false splits, end-to-end latency, ASR word error impact, voiceprint FAR/FRR, and host capacity. A
  lower segmentation error rate is not acceptable if it raises false voice attribution or weakens
  withholding.
