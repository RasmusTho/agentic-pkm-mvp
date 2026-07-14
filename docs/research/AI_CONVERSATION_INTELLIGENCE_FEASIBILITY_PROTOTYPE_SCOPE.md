State: Advisory experiment specification (docs-only; no prototype execution, provider access, fixture corpus, runtime authority, or feasibility result enacted).
Doc role: Research
Authority: Evidence and a falsifiable future experiment gate for issue #3597 under parent #3194. It is subordinate to current EBF/SIP/PDM/HKA/MEM/GOV owner contracts and the privacy baseline in #3595.
Owner: AI Conversation Intelligence research roadmap (#3194)
Temporal class: snapshot
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-07-13
Last verified against: `docs/AI_CONVERSATION_INTELLIGENCE/FEASIBILITY_PROTOTYPE_SCOPE.md`, the five preceding AI Conversation Intelligence research artifacts, and the owner/boundary documents in the source register

# AI Conversation Intelligence: Feasibility Prototype Scope

## Executive answer

The next useful evidence is not a real-history import. It is a separately authorized, disposable
experiment that asks whether the provider-neutral concepts proposed by the research can represent
synthetic provider-diverse conversations without erasing source structure, provenance, loss,
disagreement, or deletion obligations.

This document specifies that experiment but does **not** run it. No fixtures, code, model calls,
credentials, exports, provider requests, local stores, embeddings, or measurements are created here.
Every threshold below is a proposed decision rule whose result remains **not measured**. A later
strict-ready issue must approve any execution and must preserve the zero-write/no-authority boundary.

## Hypotheses and fixture set

### Prototype question and non-authority contract

Primary question:

> Can a disposable implementation of the conceptual acquisition envelope, conversation projection,
> source-span lineage, candidate taxonomy, and deletion-copy graph represent a deliberately difficult
> synthetic fixture matrix deterministically while making unsupported, missing, ambiguous, and lossy
> cases explicit?

The experiment tests representation and conformance only. It does not test whether personal histories
should be acquired, whether a provider seam is legally or commercially usable, whether classification
is valuable, or whether the proposed adapter architecture should be adopted.

Hypotheses:

- **H1 — loss is legible:** every source feature is either preserved, mapped with exact lineage, or
  reported as missing, unsupported, ambiguous, redacted, or intentionally excluded; nothing is silently
  flattened or invented.
- **H2 — identity and replay are stable:** repeated processing of the same fixture and mapper version
  yields identical scoped identities, ordering, projections, gap reports, and deletion-copy edges.
- **H3 — provider diversity stays at the edge:** provider-shaped extensions survive without becoming
  required core fields or changing HKA/MEM/GOV authority semantics.
- **H4 — candidate standing remains separate:** multi-label taxonomy annotations, reviewer disagreement,
  and derived candidates retain exact source spans and never become accepted knowledge or memory.
- **H5 — lifecycle failure is observable:** pagination, duplicate delivery, interruption, correction,
  and deletion scenarios produce explicit resumable or terminal dispositions rather than partial success.
- **H6 — the experiment is operationally bounded:** a later execution can report content-free cost and
  latency by stage, destroy all temporary material, and prove that it made no durable/runtime write.

A failed hypothesis is useful evidence. The experiment must not relax a threshold mid-run to produce a
favourable outcome.

### Minimal synthetic fixture matrix

All content must be newly written synthetic text with fictitious people, organizations, identifiers,
URLs, files, and secrets. Provider names may label shape classes, but fixtures must not copy provider
exports, private schemas, real prompts, screenshots, or account metadata. “Consented fixture” is a
possible later expansion, not part of the minimum run; it requires separate human approval and the
same minimization/deletion controls before bytes move.

| Fixture | Synthetic source shape and feature | Deliberate challenge | Expected evidence, not expected answer |
| --- | --- | --- | --- |
| F01 manual selection | Plain text plus declared source locator and selection boundary | Missing native IDs/times and incomplete context | Explicit unknowns; no completeness claim |
| F02 export-shaped A | Nested conversation with stable native IDs and timestamps | Edited turn and regenerated sibling branch | Branch/version relations preserved or unsupported reported |
| F03 export-shaped B | Content-block messages and tool call/result pairs | Partial tool result and provider extension | Ordered blocks, opaque extension, terminal partial status |
| F04 export-shaped C | Citation and attachment metadata | Missing bytes, inaccessible citation, coarse timestamp | Availability and precision posture; no URL fetch |
| F05 API-stream-shaped | Incremental blocks with request and finish metadata | Interrupted stream followed by retry | Attempt identity, received blocks, gap, and replay disposition |
| F06 CLI-event-shaped | Machine-readable run/tool events | Process exit during tool execution | Tool input remains inert; terminal failure is explicit |
| F07 pagination | Three pages with opaque cursors | Repeated item, empty middle page, cursor loop | Page receipts, collision/dedup decision, safe stop |
| F08 identity collision | Same native item ID under two source bindings | Cross-account collision trap | Distinct scoped identities; no global-ID merge |
| F09 correction | Later observation changes one turn and retracts another | Chronology and provenance preservation | Supersession/retraction edges; earlier evidence not rewritten |
| F10 simulated deletion graph | Abstract content-free graph with raw, projection, and candidate nodes | Injected unreachable-copy and failed-deletion states; no actual undeletable payload | Correct per-node partial disposition is a conformance pass; never a false “deleted” claim |
| F11 malformed/unknown | Unknown item kind, invalid timestamp, oversized depth marker | Temptation to coerce or skip | Quarantine/reject with content-free reason |
| F12 taxonomy review | Same spans annotated independently by two reviewers | Multi-label and confidence disagreement | Both annotations, agreement measure, no forced consensus |
| F13 prompt injection | Source text instructs tools, network access, and writes | Data/instruction confusion | Text remains inert; attempted capability use stops run |
| F14 secret marker | Clearly synthetic canary token and sensitive-category marker | Logging and minimization leakage | Redaction/block receipt; canary absent from logs/reports |

Minimum provider diversity means at least three independently shaped synthetic source families plus the
manual, stream, and CLI classes above. Diversity is structural, not a claim that a current provider
actually emits the invented shape. Any later use of an observed public schema needs a dated, permitted,
synthetic reconstruction and a separate source/version register.

Features explicitly in scope are source bindings; acquisitions/pages/attempts; messages and ordered
content blocks; branches, edits, regenerations, tools, citations, attachment metadata, missing content,
partial streams, extensions, scoped identity, exact spans, taxonomy annotations, corrections,
supersession, duplicate/collision decisions, and deletion-copy edges.

Out of scope are real exports or transcripts; attachment bytes; audio/video/image processing; browser
or cache capture; provider authentication; semantic web retrieval; live model classification;
embeddings; durable persistence; HKA/MEM promotion; policy enforcement; production throughput; and
provider completeness claims.

## Experiment protocol and safety boundary

### Authorization and setup gate

A later execution issue must name an owner, reviewer, exact commit, fixture manifest, allowed commands,
temporary location, time/CPU/memory ceilings, retention deadline, and cleanup verifier. It must confirm:

1. every fixture is synthetic and approved by two-person inspection;
2. the environment has no provider or model credentials, network access, external tools, vault path,
   production configuration, or persistent service binding;
3. output is confined to a disposable non-synced temporary directory or memory filesystem;
4. telemetry, traces, test reports, and logs are content-free and use fixture IDs only;
5. the experiment has no `StorePort`, database, queue, outbox, HKA, MEM, vault, or runtime write path;
6. deny-by-default network and process/tool controls plus a filesystem/runtime-write allowlist produce
   content-free attempted-access and policy receipts, and an independent preflight proves that the
   receipts detect a blocked canary action in each class;
7. the deletion/cleanup command and evidence collector are tested before fixture processing; and
8. the run stops on scope drift, unexpected file/network access, secret/canary leakage, or an unknown
   fixture/version state.

This research delivery satisfies none of those execution prerequisites; it only makes them reviewable.

### Experiment steps

For a future, separately authorized implementation:

1. **Freeze inputs.** Hash the synthetic manifest, fixtures, mapper, taxonomy, expected-capability
   declarations, and decision rubric. Record no payload in the receipt.
2. **Declare capabilities.** For each source family, state which features are supported, unsupported,
   unknown, or intentionally excluded before processing.
3. **Plan only.** Produce the intended fixture/page/item counts, estimated bytes, allowed stages, and
   deletion plan. A reviewer approves or cancels without moving source bytes outside the sandbox.
4. **Parse at the provider-shaped edge.** Convert each fixture into immutable in-memory observations
   and page/attempt receipts. Never execute tools, render active content, or fetch citations.
5. **Project neutrally.** Create rebuildable conceptual records with provider-namespaced extensions,
   scoped identity, mapping version, exact field/span lineage, and a per-item loss/unknown report.
6. **Annotate candidates.** Two reviewers independently apply the proposed multi-label taxonomy to
   F12 spans. Store annotations only in the disposable run; authority remains candidate-only.
7. **Exercise lifecycle cases.** Replay all fixtures, reorder safe page delivery, retry interruption,
   present duplicates/collisions, apply correction/retraction, and traverse F10's abstract deletion-copy
   graph. Its injected failed/unreachable states test truthful disposition only and create no real copy.
8. **Measure.** Calculate the frozen metrics below by fixture, source family, and stage. Record numerator,
   denominator, unit, and excluded cases; never replace an unknown denominator with zero.
9. **Adversarial check.** Reconcile the preflight-tested deny/audit receipts and filesystem/runtime-write
   allowlist: injection text remained inert, canaries did not reach logs/reports, every attempted network
   or process/tool action was denied and reported, and no write occurred outside the sandbox. Missing or
   internally inconsistent evidence is terminal; absence of a receipt is not counted as zero events.
10. **Destroy and verify.** Delete sandbox inputs/outputs and verify the declared copy graph. Retain only
    content-free aggregate metrics, hashes, exact code/config revisions, failure categories, review
    receipts, and cleanup status if the later issue explicitly authorizes that receipt.

Run order is fixed: happy-path structure, ambiguity/loss, replay/identity, partial failure, correction,
taxonomy disagreement, adversarial safety, then deletion. A failure in safety, authority separation, or
cleanup stops later stages; it is not converted into a warning.

### Zero-write, privacy, and deletion boundary

“Zero-write” means no durable application or provider write and no retained semantic payload. A future
test process may need ephemeral files in its explicitly approved sandbox; those are controlled copies,
must appear in the copy graph, must never be committed or uploaded, and must be destroyed at run end.
CI is not the default execution environment because artifacts, logs, caches, and third-party runners
can create uncontrolled copies.

The experiment must use fake account/workspace bindings, content-free receipts, deny-by-default
extensions, size/depth limits, no active attachments, no URL resolution, no tool execution, and no
external model. F14 canaries test leakage but are not credentials. Discovery of real personal data,
credentials, or an unplanned path is an incident-style stop: isolate, do not paste into an issue/PR,
delete controlled copies, and invoke the repository's owned response path.

Actual sandbox cleanup is separate from simulated F10 disposition. Cleanup is successful only when every
real temporary input, raw observation, projection, candidate, annotation, log, report, cache, and backup
edge is verified `deleted`; an actual `partial`, unreachable, unknown, or failed payload copy blocks go.
F10 passes by reporting its abstract injected states correctly, not by leaving bytes behind. Hash-only
content-free run receipts may remain only if the later issue explicitly authorizes them.

## Metrics and decision criteria

No value in this section is a result. Thresholds are proposed before-run gates.

| Measure | Calculation / unit | Go threshold | Failure or stop interpretation |
| --- | --- | --- | --- |
| Feature disposition coverage | Fixture features with preserved/mapped/explicit-gap disposition ÷ declared features | 100% overall | Any silent drop or invented value: stop |
| Required-field validity | Valid conceptual records ÷ records expected valid by manifest | 100% | Any invalid happy-path record: fail H1 |
| Provenance completeness | Emitted fields/candidates with source object plus exact field/span lineage ÷ lineage-required outputs | 100% | Any orphan: stop; no candidate may proceed |
| Loss/unknown precision | Injected missing/unsupported/ambiguous cases reported with correct posture ÷ injected cases | 100% | Conflated or hidden state: fail H1/H3 |
| Replay determinism | Byte-identical canonical results and dispositions across three clean replays | 3/3 | Any unexplained drift: fail H2 |
| Scoped-identity correctness | Correct distinct/duplicate decisions ÷ F07/F08/F09 cases | 100%, zero cross-binding merges | Cross-source collision: stop |
| Partial-failure legibility | Injected interruption/page/tool/parser failures with terminal/resumable status, gap, and next safe action | 100% | Silent partial success or unsafe retry: stop |
| Taxonomy span traceability | Annotations with exact spans, labels, reviewer, confidence, and version ÷ annotations | 100% | Missing evidence/standing: fail H4 |
| Taxonomy disagreement | Per-label positive agreement and Jaccard overlap, reported with raw counts | Report all; no go minimum | Forced consensus or hidden denominator: stop; low agreement redirects taxonomy work |
| Authority separation | Candidate/projection outcomes that remain non-HKA/non-MEM ÷ all outcomes | 100% | Any automatic promotion/write: stop |
| Simulated deletion disposition | F10 abstract nodes with the expected deleted/failed/unreachable/partial status ÷ F10 nodes | 100%; injected failures are reported, never coerced to deleted | Wrong/hidden disposition: fail lifecycle conformance |
| Actual cleanup completeness | Real sandbox copy nodes verified deleted ÷ declared real copy nodes | 100% accounted and deleted | Any real unreachable/unknown/partial/failed payload copy: stop |
| Safety containment | Preflight-tested deny/audit and write-allowlist receipts reconciled; unexpected successful network/provider/model/process/tool action, out-of-sandbox or durable/runtime write, or canary leakage | Complete evidence; exactly 0 successful forbidden events and 0 leaks | Any violation, missing receipt, untested detector, or evidence mismatch: immediate stop/inconclusive, never zero |
| Stage latency | Monotonic elapsed milliseconds per fixture and stage; p50/p95 plus max | Reported, no adoption threshold | Missing instrumentation: inconclusive; this fixture set cannot prove production latency |
| Compute cost | CPU-seconds, peak memory MiB, temporary bytes, and any external charge | Reported; external charge = 0 | External charge/call: stop; otherwise informs later budget only |
| Reviewer effort | Minutes per fixture plus disagreement-resolution minutes, reported by reviewer | Reported, no adoption threshold | Missing/biased sample: inconclusive; high load redirects UI/taxonomy design |
| Quality disposition | Passed/failed/inconclusive hypotheses with linked fixture evidence | All H1–H6 pass for go | A safety/authority failure stops; other failures redirect or narrow scope |

Passing these thresholds would show only that the concepts are implementable for the frozen synthetic
matrix. It would not prove provider compatibility, real-data safety, user value, legal basis, production
performance, model quality, or architecture fitness.

## Runtime proposal gate and follow-ups

### Go, redirect, and stop outcomes

A later run may support a **bounded proposal**, never direct implementation, only when:

- H1–H6 pass on the frozen matrix with complete content-free evidence;
- every safety, authority, provenance, identity, and deletion hard gate is satisfied;
- independent reviewers reproduce the reported decisions from the manifest and aggregates;
- the final cleanup status is complete; and
- a human owner accepts that the narrow question warrants a new strict-ready issue.

That proposal must choose only one narrow next question, such as a disposable synthetic parser for one
publicly documented export-shape version or a provider-neutral envelope conformance harness. It must
repeat SBS impact, owner-doc, privacy, processor, lifecycle, rollback, evidence, and deletion analysis.

**Redirect** when representation works but taxonomy agreement, reviewer effort, provider-extension
pressure, or latency/cost is poor. The follow-up is more research or a smaller synthetic matrix, not a
runtime adapter.

**Stop** the roadmap lane when any result requires silent loss, invented chronology/identity, provider
fields in core authority logic, automatic HKA/MEM promotion, uncontrolled copies, real data to pass,
external processing to establish the baseline, unverifiable deletion, or write/network/tool authority.
Stop also when the proposed neutral model cannot distinguish unsupported from missing, or when scoped
identity cannot prevent cross-source collision.

### Findings still required before any runtime work

Even a fully passing synthetic run leaves these decisions open:

1. a human-owned product purpose and user value hypothesis;
2. a named provider/product/acquisition seam and current supported contract;
3. corpus authority, participant/right posture, data categories, retention, and deletion obligations;
4. controller/processor, region, model/provider, logging, incident, and external-processing decisions;
5. an accepted data/port contract and PDM-owned persistence design, if any persistence is proposed;
6. a real threat model, hostile-input controls, operational SLO/budget, rollback, and support owner;
7. a separately authorized consented/minimized characterization protocol before any real record moves;
8. owner decisions for taxonomy semantics, promotion, correction, contradiction, and human review; and
9. an ADR only if an architecture choice has become mature, consequential, and explicitly authorized.

Suggested bounded follow-ups are conditional, not filed implementation commitments:

- execute this exact synthetic conformance experiment under a new strict-ready issue;
- refine only the failed conceptual relation or taxonomy axis if results redirect;
- perform a current provider-contract/legal/privacy review for one named seam before real-data work;
- design a deletion/correction conformance suite through the owning PDM/GOV boundaries; or
- close the lane with no runtime backlog if hard-stop evidence appears.

This artifact contains no experiment result and does not satisfy an ADR gate. Issue #3598 must reconcile
the research honestly and record “no decision” if real execution and human authorization remain absent.

## Source register

Repo sources are authoritative only for their owned boundaries; the research artifacts remain advisory.
No mutable provider claim is necessary for this scope, so no provider documentation is used as evidence.

| ID | Source | Use in this specification |
| --- | --- | --- |
| R1 | `docs/AI_CONVERSATION_INTELLIGENCE/FEASIBILITY_PROTOTYPE_SCOPE.md` | Required hypotheses, protocol, measures, gates, and non-implementation boundary |
| R2 | `docs/research/AI_CONVERSATION_INTELLIGENCE_INPUT_SOURCES.md` | Acquisition classes and source-fidelity questions |
| R3 | `docs/research/AI_CONVERSATION_INTELLIGENCE_DATA_MODEL.md` | Conceptual identity, lineage, projection, and authority entities |
| R4 | `docs/research/AI_CONVERSATION_INTELLIGENCE_KNOWLEDGE_TAXONOMY.md` | Candidate labels, independent axes, disagreement, and human review |
| R5 | `docs/research/AI_CONVERSATION_INTELLIGENCE_PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md` | Synthetic-only, minimization, hostile-input, copy-graph, deletion, and stop baseline |
| R6 | `docs/research/AI_CONVERSATION_INTELLIGENCE_ADAPTER_ARCHITECTURE_OPTIONS.md` | Provider-shaped edge, neutral envelope, lifecycle/failure, and conformance questions |
| R7 | `docs/boundaries/EBF.md`; `docs/boundaries/SIP.md`; `docs/boundaries/PDM.md` | External-boundary, projection, and persistence ownership constraints |
| R8 | `docs/boundaries/HKA.md`; `docs/boundaries/MEM.md`; `docs/boundaries/GOV.md` | Human-knowledge, memory, and governance authority separation |
| R9 | `docs/TESTING.md`; `docs/development/DEV_WORKFLOW.md` | Distinction between deterministic slice verification, feature validation, and acceptance |

## Limitations

The matrix is intentionally invented and small. It cannot establish the shape or semantics of a current
provider export, frequency of edge cases, behaviour of real users, re-identification risk, production
capacity, classifier utility, or end-to-end deletion in external systems. The proposed thresholds may
themselves need human revision **before** a run, with that revision recorded; changing them after seeing
results would invalidate the decision evidence. This is research planning, not legal advice, a privacy
assessment, a shipped contract, or a claim that AI conversation ingestion is feasible.
