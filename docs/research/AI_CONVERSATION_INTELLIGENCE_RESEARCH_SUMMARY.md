State: Final advisory research synthesis (docs-only; no provider, acquisition path, adapter, schema, taxonomy, ADR, prototype result, or runtime behavior adopted).
Doc role: Research
Authority: Reconciles the seven-child research roadmap under #3194 and defines evidence gates for any future proposal. Current owner docs and accepted ADRs remain authoritative.
Owner: AI Conversation Intelligence research roadmap (#3194)
Temporal class: snapshot
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-07-13
Last verified against: all six preceding AI Conversation Intelligence research artifacts on `main`, their source specifications, current EBF/SIP/PDM/HKA/MEM/GOV owner boundaries, and the parent-closure contract

# AI Conversation Intelligence: Research Summary and Decision Gate

## Executive conclusion

The research supports a coherent **future evidence path**, not an architecture or product decision.
AI conversations could be treated as untrusted, provenance-bound source observations from which
rebuildable projections and review-only candidates are derived. They must not become HKA knowledge,
MEM records, or provider-neutral “truth” by acquisition, normalization, or model classification.

For retrospective research, a human-selected synthetic lane is the only currently justified starting
point. Official exports are the preferred later characterization seam; caller-controlled API or
machine-readable CLI capture is the preferred later forward-looking class. Each remains conditional on
a named provider/product, authority, purpose, supported contract, privacy decision, and bounded issue.
Browser scraping, traffic interception, and private-cache coupling are rejected as planned seams.

No feasibility experiment has run. No provider has been selected. No human owner has authorized an
acquisition or runtime architecture. Therefore this synthesis creates **no ADR** and no executable
implementation issue. It closes the research question at an honest advisory boundary and leaves each
possible next step deferred behind explicit evidence and authority gates.

## Recommended target posture

“Target” below means the recommended posture if the capability is revisited; it does not describe
current runtime support.

### End-to-end posture

1. **Purpose and authority first.** A named human-owned purpose, corpus boundary, participant/right
   posture, processor decision, expiry, and deletion plan must exist before bytes move.
2. **Provider-specific acquisition edge.** EBF-facing logic preserves provider/product/version,
   account/workspace binding, native IDs, pagination, branches, edits, tools, citations, attachments,
   errors, rate limits, and capability gaps. Unknowns remain unknown.
3. **Small neutral acquisition envelope.** Only durable cross-provider meanings—source scope, run and
   item identity, raw locator/hash, observed version/time, checkpoint, completeness/gap, lineage, and
   deletion posture—cross the conceptual boundary. Provider extensions stay namespaced.
4. **Persistence remains PDM-owned.** If later authorized, quarantine, raw observations, checkpoints,
   and receipts use governed PDM/`StorePort` bindings. EBF and SIP do not create shadow stores.
5. **Normalization is a rebuildable SIP projection.** Mapping versions, exact field/span lineage,
   missing/unsupported/loss reports, scoped identity, correction, and supersession remain explicit.
6. **Taxonomy outputs are candidates.** The proposed multi-label candidate functions and independent
   authority, provenance, temporal, confidence, lifecycle, and evidence/admissibility axes aid review;
   they are not an ontology, classifier contract, or accepted knowledge.
7. **Human authority remains unchanged.** HKA and MEM accept, reject, correct, supersede, or promote
   only through their current governed lifecycles. Provider “assistant” roles and model outputs carry
   no special standing.
8. **Lifecycle evidence is first-class.** Retries, duplicate/collision decisions, partial failure,
   correction, redaction, retention, and deletion propagate through a copy/derivation graph. Partial or
   unknown deletion is never reported as complete.
9. **Operations remain content-free.** OEF/GOV evidence may carry run IDs, counts, hashes/locators,
   status, cost, latency, and dispositions, never transcripts, secrets, attachment contents, or a
   competing source store.

### Evidence gates

| Gate | Minimum evidence and authority | Outcome allowed |
| --- | --- | --- |
| G0 research closure (this issue) | Six advisory inputs reconciled; conflicts, risks, and non-goals explicit; no invented result | Close #3194 research roadmap only |
| G1 synthetic conformance experiment | New strict-ready issue; human owner; frozen synthetic manifest/rubric; deny/audit controls; disposable sandbox; independent review; complete cleanup | Report pass/fail/inconclusive for the frozen conceptual model only |
| G2 named seam characterization | G1 evidence plus one named provider/product/version, current supported public contract, dated privacy/security/legal/processor approval, synthetic fixture reconstruction | Propose a bounded provider-specific research parser or reject the seam |
| G3 consented/minimized real-data experiment | G2 passes; explicit corpus/participant authority; purpose/retention/deletion/incident plan; no git/CI payload; human review | Characterize the approved corpus only; no production import |
| G4 runtime architecture decision | Product purpose/value, G1–G3 evidence as applicable, threat model, owner-doc impacts, persistence/operations/support design, owner authorization, accepted ADR | Create bounded implementation breakdown; still no implicit HKA/MEM promotion |

G1 does not automatically authorize G2; G2 does not authorize G3; and G3 does not imply G4. A later
owner may stop at any gate.

### Selected, rejected, and deferred alternatives

These are research dispositions, not shipped configuration:

| Alternative | Disposition | Rationale and boundary |
| --- | --- | --- |
| Newly authored synthetic human-selected material | **Selected for G1 only** | Narrowest scope and strongest control; proves only the frozen synthetic matrix |
| Official consumer/account export | **Deferred; preferred G2/G3 retrospective class** | Supported human-initiated seam with useful structure, but broad scope, unstable provider shape, rights, staging, retention, and deletion risks remain |
| Caller-controlled API capture | **Deferred; preferred future-session class** | Can bind provenance at creation; does not retrieve consumer history and introduces online/provider processing and retention semantics |
| Machine-readable CLI capture | **Deferred; controlled synthetic/operator class** | Better structure than terminal scraping; may contain code/secrets and must not couple to private session stores |
| Portability API | **Deferred** | Potentially authorized/repeatable, but resource coverage, OAuth scopes, verification, jobs, expiry, and provider support must be proven |
| Enterprise/compliance feed | **Deferred outside the personal MVP** | Requires a named organizational product, admin/member authority, commercial contract, controller, retention, and high-volume lifecycle design |
| Browser/DOM scraping or network interception | **Rejected** | Unstable/private seam, credential and scope exposure, ambiguous completeness, high maintenance |
| Private cache/session-file coupling | **Rejected as a normal seam** | Undocumented and unstable with uncontrolled secrets, migration, locking, and deletion behavior |
| One universal provider conversation schema/parser | **Rejected** | Erases provider capabilities and unknowns; neutral envelope plus provider-specific edge is safer |
| Direct provider material → HKA/MEM | **Rejected** | Violates source/derived/candidate/accepted-authority separation |
| Automatic taxonomy classification/promotion | **Rejected for this roadmap** | Taxonomy is advisory; disagreement and evidence roles require human review and owner decisions |

### Privacy, security, and data-ownership baseline

The #3595 baseline is a prerequisite, not a feature checklist that this repository currently enforces.
Any later lane must be synthetic-first, no-acquisition-by-default, previewable and minimized, hostile-input
safe, content-free in logs/receipts, local-first in controlled quarantine, and externally processed only
after an exact recipient/endpoint/retention/region/training/deletion decision. Attachments, shared/client/
employer material, special-context data, public links, and connected-app copies are deny-by-default.

“Ownership” must remain decomposed into account/workspace control, authorship, depicted participants,
work-product rights, export authority, new-use authority, confidentiality/contract duties, local-copy
control, and correction/restriction/deletion rights. Possession of an export proves none of these.

Deletion is a verified graph operation across provider, quarantine, extraction, normalization,
derivation, logs, caches, backups, public links, and connected apps. Each copy has an independent state;
unreachable, partial, excepted, or unknown is not deleted. Prompt injection, malicious archives,
secrets, over-collection, cross-scope identity, external disclosure, and false authority are hard-stop
risks rather than quality warnings.

### Conceptual model and taxonomy posture

The conceptual model is useful vocabulary for experiments, not a schema. It distinguishes source
binding, acquisition, conversation/item/content observations, projection, derivation activity,
candidate, and accepted HKA/MEM outcome. Identity is always source-scoped; chronology, branches, edits,
deletions, precision, and gaps are preserved rather than inferred. A conversation is a source container,
not automatically an Episode, Workspace, Context, knowledge object, or memory.

The taxonomy is a multi-label proposal for candidate functions such as decision, commitment, question,
claim, explanation, plan, preference, evidence reference, creative material, and reflective observation.
Function is independent from authority, provenance, time, confidence, lifecycle, and evidence/admissibility.
Zero, one, or several candidates may arise from a span. Disagreement is retained and measured; it is not
silently collapsed into consensus.

### Feasibility gate

The #3597 scope is the only approved description of G1, but it grants no execution authority. Its 14
synthetic fixtures cover manual/export/API/CLI-shaped records, branches/edits, tools, citations,
attachments-without-bytes, pagination, duplicates/collisions, correction, simulated deletion states,
malformed/unknown records, taxonomy disagreement, prompt injection, and secret canaries.

Go requires 100% explicit feature disposition, provenance, loss/unknown reporting, scoped identity,
authority separation, real-sandbox cleanup, and complete preflight-tested safety evidence; deterministic
replay must pass three times. Simulated failed/unreachable deletion states test truthful disposition and
must not be confused with actual undeleted payload. Missing evidence is inconclusive/stop, never zero.
Passing would demonstrate only conceptual implementability for the frozen synthetic matrix.

### Reconciliation of tensions and conflicts

| Tension across artifacts | Reconciliation |
| --- | --- |
| Input-source research names exports and API/CLI as preferred lanes, while privacy starts synthetic-only | “Preferred” is conditional by use case. G1 is synthetic only; export/API/CLI are deferred to later gates with separate authority |
| A neutral model improves comparison, but providers expose incompatible structures | Neutralize lineage/lifecycle/identity posture only; preserve provider-specific records and extensions at the EBF edge; never force a universal transcript |
| Raw preservation aids replay/audit, while minimization and deletion oppose extra copies | No preservation by default. If separately authorized, PDM owns a minimized quarantine copy with expiry/copy graph; hashes/locators replace payload duplication in receipts |
| Corrections need history, while deletion may require removal | Keep correction/supersession relations while authorized; on deletion remove semantic payload and retain only policy-authorized non-content tombstone evidence |
| Taxonomy enables discovery, but labels can acquire false authority | Labels remain rebuildable candidate annotations with exact spans and reviewers; HKA/MEM acceptance remains a separate human receipt |
| Provider citations/tools look actionable, but source content is untrusted | Preserve structure and availability only; never fetch citations, execute tools, or obey transcript instructions during characterization |
| Feasibility thresholds look decisive, but no experiment ran | Treat every threshold as a pre-registered proposal and every result as “not measured”; no feasibility or architecture claim follows |
| Research recommends an adapter posture, but no owner selected a provider/product | Keep the posture advisory and make G4 plus an authorized ADR the only route to runtime adoption |

### Non-goals

This roadmap does not acquire, import, parse, normalize, index, classify, summarize, embed, retrieve,
display, sync, retain, or delete a real AI conversation. It does not select a provider; implement an
adapter/port/schema/event/API/service/migration/UI; change HKA, MEM, Episode, Workspace, Context, or
evidence semantics; establish legal basis or compliance; approve an external processor; create a
production privacy/security control; or prove user value, accuracy, latency, cost, or feasibility.

## Residual risk and bounded backlog

### Residual risk after research closure

- **Authority cannot be inferred technically.** Participant rights, employment/client duties, purpose
  compatibility, and controller/processor allocation remain human/legal decisions.
- **Provider facts drift.** Product, plan, endpoint, retention, export, deletion, API, CLI, and policy
  behavior must be re-verified from current primary sources at the exact later gate.
- **Synthetic evidence is narrow.** It cannot reveal real frequency, hidden export omissions,
  re-identification, user value, production performance, or external deletion behavior.
- **Neutralization can still become lossy.** Extensions and gap reports reduce but cannot eliminate
  pressure to flatten provider semantics or invent chronology/identity.
- **Derived copies multiply risk.** Projections, summaries, annotations, embeddings, logs, backups,
  issue text, and CI artifacts can outlive their source unless explicitly inventoried and deleted.
- **Models and source text are adversarial boundaries.** Prompt injection, secret leakage, unsupported
  tools, citation fetching, and false confidence remain possible even with sandbox controls.
- **Human review can fail.** Disagreement, fatigue, confirmation bias, and authority confusion can turn
  candidates into unsupported knowledge without strong receipts and correction paths.
- **No current controls were implemented.** Every control described in the research is a future
  requirement, not evidence that Yggdrasil currently provides it for AI conversations.

### Bounded backlog dispositions

No executable issue is created by this synthesis because no later gate is authorized. The following
items are explicitly deferred or discarded; reopening one requires its trigger and a new strict-ready
issue with its own SBS/authority/verification contract.

| ID | Bounded question | Disposition | Trigger before an issue may become ready | Stop/closure outcome |
| --- | --- | --- | --- | --- |
| ACI-N1 | Execute the frozen synthetic conformance experiment from #3597 | **Deferred, not filed** | Human names owner/purpose/budget and approves exact no-network/no-runtime-write sandbox, manifest, rubric, cleanup, and independent review | Close inconclusive/failed without expanding data or privileges |
| ACI-N2 | Characterize one named official export or caller-controlled API/CLI shape using reconstructed synthetic fixtures | **Deferred, not filed** | N1 passes for relevant concepts; current public contract and permitted synthetic reconstruction are verified; provider/product/version is named | Reject/defer seam on unknown version, silent loss, or unsupported lifecycle |
| ACI-N3 | Run a consented/minimized real-data characterization | **Deferred, not filed** | N2 passes plus explicit human/legal/privacy/security/processor/corpus/participant/retention/deletion/incident approval | Delete all controlled copies and close on any authority, secret, scope, or cleanup failure |
| ACI-N4 | Adopt taxonomy terms or build classification/review tooling | **Deferred, not filed** | Synthetic reviewer evidence, owner semantic decision, correction/disagreement workflow, and affected HKA/MEM/HUMAN-FLOWS contracts exist | Keep taxonomy advisory or discard terms with poor agreement/value |
| ACI-N5 | Design and implement a production adapter/capability | **Discarded from #3194 scope** | New capability breakdown only after an authorized G4 decision/ADR and required earlier evidence | No implementation backlog if owner does not authorize G4 |
| ACI-N6 | Support portability or enterprise/compliance acquisition | **Deferred outside personal MVP** | Named organizational product, roles, plan/contract, controller, data subject/employee governance, retention, volume, and current API evidence | Reject if governance/contract/cost cannot be bounded |
| ACI-N7 | Reconsider scraping/interception/private-cache ingestion | **Discarded** | None under current posture; only a genuinely supported public vendor seam could be evaluated as a different alternative | Remains prohibited as described |

Open questions therefore remain bounded to later gates: actual provider shape and completeness; product
purpose/value; rights and processor posture; semantic agreement; storage/retention architecture;
operational cost/SLO; human review design; correction/deletion UX; and whether any capability should
exist at all. Research closure does not require answers because it does not authorize the work.

## Future owner-doc impact

No current-state owner doc is changed by this synthesis other than indexing and roadmap status. If a
later gate is explicitly authorized, the proposal must update the relevant owners rather than treating
this research as normative:

| Future change | Owner documents that would require review/update before claiming support |
| --- | --- |
| Provider acquisition/authentication/capability handling | `docs/boundaries/EBF.md`, `docs/COMPONENTS.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, and the then-current configuration/operations owner docs |
| Raw/quarantine/checkpoint persistence and deletion mechanics | `docs/boundaries/PDM.md`, persistence/storage contracts, `docs/SECURITY.md`, retention/deletion governance docs |
| Normalization, derivation, lineage, correction, or events | `docs/boundaries/SIP.md`, `docs/EVENTS.md`, concept/evidence contracts, `docs/TESTING.md` |
| Candidate review, HKA acceptance, or MEM lifecycle | `docs/boundaries/HKA.md`, `docs/boundaries/MEM.md`, `docs/HUMAN-FLOWS.md`, applicable GOV/receipt contracts |
| Product/UI behavior and user controls | `docs/HUMAN-FLOWS.md`, applicable product/surface owner docs, `docs/ROADMAP.md`, privacy/security user-facing contracts |
| Runtime architecture adoption | `docs/adr/INDEX.md` plus a new accepted ADR, then every affected boundary/current-state owner doc |

The exact set must be re-derived at that future time. Naming a document here neither changes it nor
claims that the capability exists.

Transition debt outcome: **no effect**. No old/new contract pair, temporary bridge, compatibility window,
or removal trigger is introduced. Fitness-rule outcome: **no effect**. The proposed experiment measures
future evidence but implements no enforced rule. A later runtime issue must create bounded debt/fitness
records if its actual design requires them.

## ADR readiness decision

**Decision: no ADR is authored.**

The evidence is not mature enough to record an architecture decision and no owner ruling exists to
authorize one. The single decision gate still missing is:

> A human owner must decide whether a named AI Conversation Intelligence product/acquisition capability
> should proceed to architecture selection after relevant feasibility, provider-contract, privacy,
> security, rights, operations, and user-value evidence is available.

Today that gate cannot be presented for decision: the G1 experiment has not run, no provider/product or
corpus is named, no purpose/value has been validated, and no processor/retention/deletion/operations
posture is approved. Writing an ADR for the conceptual neutral envelope, adapter posture, taxonomy, or
“no acquisition” would convert advisory constraints or temporary absence into a false durable decision.

If G4 is later reached, the ADR must state the exact capability and alternatives; evidence-gate results;
provider-specific versus neutral responsibilities; PDM/StorePort ownership; HKA/MEM authority;
privacy/security/rights/processor posture; retention/deletion/correction; operations and rollback;
owner-doc impacts; rejected paths; and why the decision is now authorized. Until then, current owner
docs win and this research remains non-normative.

## Parent closure handoff

### Delivered child chain

| Child | Artifact | Merged evidence | Standing |
| --- | --- | --- | --- |
| #3195 | Input-source options | PR #3587, `a73879b96654246dfa969b9af9759f987a5e16b3` | Advisory; closed |
| #3196 | Conceptual conversation data model | PR #3588, `f88c9e468685b9ec48e8fefdd63a396cd9c2c034` | Advisory; closed |
| #3197 | Knowledge taxonomy | PR #3590, `f79295f6f2eb41a8b202444ff99ba6d403633ae3` | Advisory; closed |
| #3595 | Privacy/security/data ownership | PR #3601, `9fcbf6e9debbfc6da7b474c09d60210220b3eecf` | Advisory baseline; closed |
| #3596 | Adapter architecture options | PR #3606, `0059ba4c5952119147e9e358bacfc1148f45ff4e` | Advisory posture; closed |
| #3597 | Feasibility prototype scope | PR #3615, `92ad23658ddc1d99fe55b7f63a4917d2120da7bb` | Scope only, not executed; closed |
| #3598 | This synthesis and ADR gate | This delivery PR/merge receipt | Advisory no-ADR outcome; close only post-merge |

### Required post-merge parent checks

This section is a pre-merge-verifiable checklist, not a claim that post-merge work has already happened.
After #3598 merges, the closer must:

1. verify the exact merge commit and that this artifact, `docs/DOCS_INDEX.md`, the source spec, and the
   roadmap status resolve on `origin/main`;
2. post #3598's owner-doc receipt and child delivery receipt on #3194, then verify #3598 is closed and
   its dispatcher lease/task is terminal;
3. re-read live parent #3194 and every formal sub-issue; verify all seven children are closed and their
   delivery/owner-doc/review/CI evidence is reachable;
4. confirm there are no unresolved review findings, open executable follow-ups, unhandled owner-doc
   outcomes, transition-debt rows, fitness-rule claims, or Project/label lifecycle mismatches;
5. update the local epic run state with all child PRs, merge SHAs, review/CI, receipts, no-ADR outcome,
   deferred/discarded backlog, and any upstream blocker-bug learnings;
6. apply `docs/development/PARENT_ISSUE_CLOSURE.md`: post one auditable parent closure receipt with
   acceptance/evidence mapping, bounded-future-work disposition, owner-doc/debt/fitness/run-state
   outcomes, and no-runtime-authority statement;
7. close #3194 only after those checks pass, remove stale `agent:*` labels, verify formal sub-issue
   closure and parent state, and emit the final TCD review.

Parent closure should state clearly that the research roadmap completed while the capability remains
unimplemented and unauthorized. Deferred/discarded ACI-N1–N7 are sufficient disposition for this
research parent; they are not hidden executable work and must not be reopened without a new owner gate.

## Traceability register

| Research artifact | Material contribution reconciled here |
| --- | --- |
| `AI_CONVERSATION_INTELLIGENCE_INPUT_SOURCES.md` | Acquisition alternatives, provenance minimum, preferred/deferred/rejected source classes |
| `AI_CONVERSATION_INTELLIGENCE_DATA_MODEL.md` | Source-scoped identity, conceptual entities/lifecycles, provenance, authority layers, conversation-not-Episode |
| `AI_CONVERSATION_INTELLIGENCE_KNOWLEDGE_TAXONOMY.md` | Multi-label candidate functions, orthogonal axes, examples, disagreement and non-adoption posture |
| `AI_CONVERSATION_INTELLIGENCE_PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md` | Lifecycle/threat model, rights/control decomposition, provider facts, controls, residual risk, prohibited/deferred paths |
| `AI_CONVERSATION_INTELLIGENCE_ADAPTER_ARCHITECTURE_OPTIONS.md` | Provider-specific edge, neutral envelope, PDM persistence boundary, failure/deletion/conformance posture |
| `AI_CONVERSATION_INTELLIGENCE_FEASIBILITY_PROTOTYPE_SCOPE.md` | Synthetic fixtures, no-authority experiment, measures, safety/cleanup evidence, stop/go/redirect gates |

## Limitations

This summary inherits the evidence limits and access dates of its sources. It does not independently
verify provider behavior, execute the proposed experiment, assess law/compliance, test real data, measure
value/quality/cost/latency, or prove that all future owner-doc impacts are known. Recommendations may be
superseded by provider drift, experiment evidence, owner decisions, or accepted architecture. Until an
authorized future gate says otherwise, current runtime and owner documentation remain the only truth.
