State: Advisory architecture research (docs-only; no adapter, port, schema, provider selection, acquisition authority, or runtime behavior enacted).
Doc role: Research
Authority: Evidence and recommendations for issue #3596 under parent #3194. Provider facts are bounded to the cited primary sources as accessed on 2026-07-13; the architecture is conceptual and subordinate to current EBF/SIP/HKA/MEM/GOV owner contracts.
Owner: AI Conversation Intelligence research roadmap (#3194), downstream of EBF/SIP/PDM and the privacy baseline delivered by #3595
Temporal class: snapshot
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-07-13
Last verified against: `docs/AI_CONVERSATION_INTELLIGENCE/ADAPTER_ARCHITECTURE_OPTIONS.md`, the four preceding AI Conversation Intelligence research artifacts, EBF/SIP/HKA/MEM/GOV boundary docs, and the primary sources in the source register

# AI Conversation Intelligence: Adapter Architecture Options

## Executive answer

No single adapter class can safely cover retrospective consumer history, newly generated API/CLI
sessions, and organization compliance data. They expose different authority, shape, lifecycle, and
failure semantics. The recommended architecture is therefore a **provider-specific acquisition edge
behind a small provider-neutral conceptual boundary**, not one universal parser and not a provider
conversation model promoted into the core.

Use three staged lanes:

1. **Human-selected material** for synthetic/discovery fixtures and the narrowest explicit scope.
2. **Official account exports** for a later, separately authorized retrospective characterization.
3. **Caller-side API or machine-readable CLI capture** for future sessions created under caller
   control, where provenance can be recorded at creation.

Defer portability APIs and enterprise/compliance feeds until an actual organizational use case and
authority exist. Reject browser scraping and private-cache coupling as planned paths. Every lane
must preserve provider records as immutable source evidence, build rebuildable normalized
projections, keep derived candidates separate, and propagate correction/deletion through a
copy/derivation graph. This recommendation is research only; it does not adopt an interface,
schema, event, endpoint, provider, or implementation backlog.

## Evaluation frame

Each option is evaluated against:

- **Authority and scope:** who can request it and whether the requested corpus is previewable and bounded;
- **source fidelity:** preservation of account/workspace scope, native IDs, order, branches, edits,
  roles, timestamps, tools, attachments, citations, and explicit omissions;
- **contract stability:** supported public seam, version/schema posture, drift discoverability, and deprecation path;
- **lifecycle control:** pagination/checkpointing, retry/replay, idempotency/deduplication, partial
  failure, rate limiting, cancellation, and deletion/redaction propagation;
- **security/privacy:** credentials, secrets, broad-copy exposure, external processing, and the #3595 baseline;
- **conformance:** whether synthetic fixtures and deterministic tests can distinguish success,
  partial success, unsupported capability, and unsafe unknowns;
- **boundary fit:** provider details stop at EBF while SIP lineage and HKA/MEM/GOV authority remain intact.

Ratings are qualitative research judgments, not procurement scores or shipped design decisions.

## Option matrix

| Acquisition class | Authority/scope | Fidelity and drift | Lifecycle/failure posture | Boundary/cost posture | Recommendation |
| --- | --- | --- | --- | --- | --- |
| **Human-selected text/file** | Strongest explicit selection and smallest blast radius; cannot prove completeness or third-party rights | Shape is caller-defined; provenance is weak unless provider, source locator, selection time, context limit, and hash are captured | Simple one-shot acquisition; cancellation and local deletion are tractable; manual transcription can omit branches/metadata | Provider-neutral at the edge and cheap; recurring human effort; easy to keep synthetic | **Use first** for synthetic golden examples and discovery. Never claim account completeness |
| **Official consumer/account export** | Human initiates a supported privacy/product flow, but archives can span broad history and account data; workspace availability varies | Highest retrospective potential, but help pages do not promise a stable cross-provider schema. OpenAI documents chat history plus other account data [S1]; Anthropic and Google document provider-specific exports [S2, S3] | Usually asynchronous, coarse-grained, expiring-download, and archive-oriented. Replays create new copies; parser must detect version/shape and fail on unknowns | Per-provider archive adapter at EBF; medium parser/fixture maintenance; high privacy/staging burden | **Preferred retrospective characterization seam** after separate real-data authority. Never normalize directly from an assumed universal export format |
| **Caller-side model/API capture** | Covers only sessions the authorized caller creates; does not retrieve consumer history | High fidelity for caller-visible requests/responses/tool events if recorded at creation; provider-internal state remains unknown. OpenAI Conversation resources are API-side state [S4]; Anthropic Messages supports caller-supplied history [S5] | Online errors, rate limits, streaming interruption, retries, duplicate requests, and endpoint retention require explicit receipts. Capture before semantic processing | Versioned provider client at EBF plus provider-neutral acquisition manifest; medium implementation/operations | **Preferred forward-looking seam** for new governed sessions, only after a bounded runtime issue and processor decision |
| **Machine-readable CLI capture** | Covers commands launched through an authorized tool boundary; operator/developer scope can contain code and secrets | Supported JSON/event modes can preserve run/tool structure better than terminal scraping. Codex and Claude Code document machine-readable output modes [S6, S7] | Process exit, partial streams, resumable sessions, tool version, working scope, redaction status, and interrupted writes must be explicit | Thin tool-specific collector at EBF; useful for controlled synthetic runs; never read private session stores | **Good controlled pilot source** for future synthetic sessions. Treat as operator material, not Product/HKA truth |
| **Enterprise/compliance feed** | Workspace administrator and qualifying plan; authority over members and employment context is material | High audit/workspace provenance but optimized for compliance/eDiscovery rather than personal-knowledge semantics. OpenAI documents the append-only Compliance Logs Platform; its help page's deprecation notice says the old stateful route was removed on 2026-06-05 [S8] | Pagination, retention windows, endpoint migration/removal, admin roles, high volume, immutable audit events, and unavailable/expired objects complicate replay; no state-query capability is assumed | Dedicated organization adapter and governance lane; high commercial/security/legal/operational cost | **Defer for personal MVP.** Revisit only for a named organizational product, controller, role, current authenticated API contract, and retention boundary |
| **Authorized portability API** | OAuth user authorization plus provider verification and restricted/sensitive-scope obligations | Public machine-readable job contract and provider-specific resource schemas; exact product/resource coverage must be proven. Google documents archive jobs and capability-specific resources [S9, S10] | Asynchronous initiate/status/signed-download, cancel, retry, authorization reset, one-time/time-based access, and expiring artifacts are first-class [S10, S11] | Provider-specific OAuth/job adapter; high verification/security overhead; repeatable once authorized | **Defer but preserve as an adapter class.** Do not claim Gemini or another AI product is supported until the resource schema proves it |
| **Private local cache/session files** | Local possession may bypass intended export controls and mix accounts/scopes | Potentially rich but tool-private, undocumented, unstable, and prone to internal/derived/secret fields | File races, migration, corruption, lock/state semantics, silent version drift, and incomplete deletion are uncontrolled | Tight implementation coupling and high breakage/sanitization cost | **Reject as a normal seam.** A vendor-supported export hook may later qualify independently |
| **Browser/DOM scraping or network interception** | Relies on session credentials and UI/private traffic; scope and terms are hard to bound | Rendered fragments or private payloads are not completeness/stability contracts; branches, tools, attachments, and hidden context can disappear | Anti-automation, pagination/infinite scroll, UI experiments, token expiry, retries, duplicate capture, and partial pages fail ambiguously | Highest maintenance and credential/incident exposure; provider implementation leaks into core | **Reject.** Neither a production adapter nor valid completeness evidence |

### Decision drivers by use case

- **Taxonomy/data-model discovery:** synthetic human-selected examples win because breadth of real
  history is unnecessary and privacy blast radius dominates.
- **Retrospective structure measurement:** official exports are the only recommended consumer-history
  class, but the output should be structural manifests and synthetic fixtures, not committed content.
- **Repeatable future capture:** caller-side API/CLI seams win because version, scope, request ID,
  tool events, and acquisition time can be observed when the record is created.
- **Organization governance:** compliance/portability paths may be appropriate only when the product,
  admin/user roles, controller, contract, and deletion/retention duties are explicit.

## Boundary and responsibility model

### Conceptual layers

The terms below describe responsibility boundaries, not a proposed class hierarchy or schema.

| Layer | Responsibility | May contain | Must not do |
| --- | --- | --- | --- |
| **Source authority** | Provider/user/workspace remains authority for what the source exposed and its native lifecycle | Provider records, export archive, API/CLI event, source deletion/retention state | Become Yggdrasil truth merely because acquired |
| **Provider acquisition edge (EBF)** | Authenticate through an approved seam; discover capabilities; enumerate/fetch; produce source observations and acquisition receipts; expose provider failures faithfully | Provider-specific IDs, cursors, archive/job states, versions, rate-limit/request IDs, feature flags | Own durable/quarantine storage or checkpoints; translate provider roles into HKA/MEM authority; hide unsupported fields/failures; retain credentials in payloads |
| **Provider-neutral acquisition envelope (EBF-facing)** | Describe source binding, declared scope, acquisition/run identity, capability snapshot, raw artifact locator/hash, item locators, checkpoint, completeness/gaps, and deletion posture | Opaque provider locators and bounded common metadata | Promise a universal conversation schema or erase provider identity |
| **Storage mechanics (PDM)** | If separately authorized, persist quarantine/raw observations, receipts, and checkpoints through governed `StorePort` bindings; carry source/provenance/sensitivity metadata; apply storage lifecycle mechanics | Encrypted staging, durable or rebuildable classification, storage locators, checkpoint commits, deletion/tombstone mechanics | Define source meaning/authority/retention policy; let EBF/SIP construct a private store or DSN; treat persistence as acceptance |
| **Normalization projection (SIP)** | Produce rebuildable conversation/item representations with explicit mapping/version, unknowns, loss notes, and exact lineage | Provider-neutral conceptual records plus provider-extension references | Mutate raw evidence; invent timestamps/order/identity; own acquisition/authentication |
| **Derivation/candidate layer (SIP → review)** | Chunk, classify, summarize, or propose knowledge/memory candidates with source-span and transformation lineage | Rebuildable outputs, confidence/evidence roles, correction/supersession relations | Promote to HKA/MEM, execute transcript instructions, or obscure source standing |
| **Human authority lifecycles (HKA/MEM/GOV)** | Accept/reject/correct/promote under existing owner contracts and receipts | Governed accepted knowledge or memory only after explicit authority | Treat provider content, normalized records, or model output as implicitly accepted |
| **Operations/evidence (OEF/GOV as owned)** | Observe run status, counts, latency, failures, drift, deletion progress, and conformance without payload duplication | Content-free metrics, request/run IDs, hashes/locators, dispositions | Log transcripts, secrets, attachment contents, or create a shadow source store |

### Provider-specific versus provider-neutral responsibility

Keep provider-specific:

- authentication/authorization method, token scopes, account/workspace binding, endpoint/product/plan;
- export archive/job structure, pagination cursor, request ID, rate-limit headers, and retry guidance;
- native conversation/item IDs, roles, item/content-block kinds, branch/edit/regeneration semantics;
- tool calls/results, citations, attachments/media, model/config metadata, and provider deletion states;
- version/deprecation/capability discovery and raw error/status payload classification.

Keep provider-neutral only where semantics survive without invention:

- acquisition/run identity, declared source scope and authorization receipt;
- raw artifact locator/hash, media type, observed version, capture time, and immutable lineage;
- source-scoped object identity and explicit present/missing/unknown/redacted/unsupported posture;
- checkpoint/cursor as opaque provider state, item processing disposition, and gap/completeness report;
- transformation version, exact inputs/spans, derived-copy inventory, correction/deletion status;
- independent source role, evidence role, authority state, sensitivity, and human review receipt.

The neutral boundary must support extensions rather than a “miscellaneous JSON” escape hatch that
silently becomes required. An extension is provider-namespaced, preserved at the edge, included in
fixture/conformance coverage, and never interpreted by core authority logic.

### Conceptual port operations

A future architecture might need operations equivalent to the following, but this memo deliberately
does not name or adopt an interface:

1. **Describe source/capabilities** — identify provider/product/version/account/workspace posture and
   supported enumeration, item kinds, attachment/citation/tool/branch/edit/deletion features.
2. **Plan acquisition** — resolve a human-approved bounded scope into a dry-run manifest and estimated counts/bytes.
3. **Acquire page/artifact** — return immutable source observations plus an opaque proposed next checkpoint and request receipt; any authorized persistence/commit is performed through PDM/`StorePort`.
4. **Normalize selected observation** — produce a versioned projection and loss/unknown report with exact lineage.
5. **Reconcile/correct/delete** — observe source changes where supported and propagate explicit statuses through controlled copies.
6. **Diagnose/conform** — expose capability drift, unsupported variants, fixture version, and content-free failure evidence.

Separating planning from acquisition is critical: a human must be able to inspect scope before bytes
move. Separating acquisition from normalization makes authorized raw preservation and parser replay
possible without another provider call, while PDM/`StorePort`—not EBF or SIP—owns any durable or
quarantine storage mechanism.

## Adapter lifecycle and failure semantics

### Lifecycle states and receipts

| Phase | Required behavior | Receipt/gap evidence |
| --- | --- | --- |
| Register | Bind provider/product/account or workspace pseudonym, acquisition class, and approved scope | Source binding, authority receipt, privacy-baseline version; no secret |
| Discover | Read supported endpoint/export/tool version and capability posture without content where possible | Dated capability snapshot with supported/unsupported/unknown fields |
| Plan | Enumerate or preview intended range/count/bytes and exclusions | Human-readable manifest, approval, limits, expiry; no wildcard default |
| Acquire | EBF fetches one archive/page/event stream and emits source observations; when separately authorized, PDM places bytes/records in quarantine through `StorePort` | Run/page ID, raw hash/locator, provider request/job ID, time, proposed cursor, item count, storage receipt if persisted |
| Validate | EBF/SIP checks media/schema/version, integrity, archive safety, scope, duplicates, and required identifiers; PDM applies storage mechanics without interpreting meaning | Accepted/quarantined/rejected disposition and structured non-content errors |
| Normalize | Apply pinned mapping to selected observations | Mapper version, per-item result, exact lineage, loss/unknown report |
| Reconcile | Compare repeated source observations without rewriting history | New acquisition, equivalence/supersession/correction relations, drift report |
| Derive/review | Create candidates/projections under no-write analysis and human review | Derivation receipt, exact spans, authority remains candidate-only |
| Retain/delete | Apply per-copy TTL/deletion plan and propagate correction/deletion | Copy-graph statuses, retries, partial/unknown state, minimal tombstone |
| Retire | Stop unsupported/deprecated adapter version without erasing evidence | Retirement reason, last supported source version, migration/re-acquisition decision |

### Complex conversation features

An adapter must report capabilities before mapping. It must never flatten an unsupported structure
and call the result complete.

| Feature | Safe conceptual treatment |
| --- | --- |
| Pagination and ordering | Preserve provider cursor as opaque; record page request/result IDs and stable source ordering only when documented/observed; detect loops and cursor drift |
| Branches/regenerations | Represent explicit parent/alternate relations when supplied; otherwise mark branch posture unknown, never invent one linear “canonical” history |
| Edits/deletions | Keep observations/acquisitions distinct; relate versions or tombstones; do not overwrite earlier source evidence or infer deletion from absence alone |
| Streaming/partial responses | Record terminal/aborted/truncated posture, received blocks, provider request ID, and gaps; never synthesize missing completion |
| Tools/functions | Preserve call/result identity, order, provider type, and availability; treat arguments/results as untrusted sensitive source content, not executable instructions |
| Attachments/media | Inventory locator, media type, size/hash and available/missing/redacted status; bytes are separately authorized and deny-by-default |
| Citations/web results | Preserve provider-supplied citation/source relation and access posture; never auto-fetch or claim cited content was verified |
| Roles/system/config | Preserve original labels/config where exposed; do not translate provider “assistant/system” roles into Yggdrasil authority |
| Usage/model metadata | Preserve observed model/version/token/finish/request facts only; missing remains unknown and aliases are not immutable model identity |

### Retry, replay, idempotency, and deduplication

- **Read retries:** retry only classified transient transport/429/5xx failures with bounded
  exponential backoff, jitter, provider `retry-after` where documented, cancellation, and a run
  deadline. Anthropic documents 429/`retry-after` and default SDK retries for transient failures
  [S12, S13]. Treat exact numeric limits as runtime discovery, not constants.
- **Write-like provider operations:** export/archive initiation, authorization reset, and any future
  server-side conversation creation are not assumed idempotent. Persist the provider job/request ID
  before retry, query status first, and require provider-documented idempotency semantics. Google
  portability explicitly models initiate, status, cancel, retry, and authorization reset [S10, S11].
- **Replay:** normalize from preserved raw observations with a pinned mapper version; never re-fetch
  merely to rerun a parser. A replay creates a new projection/derivation receipt, not a new source fact.
- **Identity:** use provider+product+account/workspace scope+native object ID when present. If absent,
  use acquisition-local locator plus content hash; never promote a hash alone to semantic identity.
- **Deduplication:** distinguish byte equality, source-object equality, repeated observation, and
  semantic similarity. Only the first two can support deterministic collapse, while retaining all
  acquisition receipts. Similarity produces a review relation, not deletion.
- **Checkpoint commit:** advance a cursor only after any authorized raw preservation and per-page
  receipt have committed through PDM/`StorePort`. EBF proposes opaque provider checkpoint state; it
  does not own the durable checkpoint. Normalization failure must not lose the committed acquisition
  checkpoint or silently skip the item.

### Partial failure and legible completeness

An acquisition result is one of `complete within declared scope`, `partial`, `cancelled`, `failed`,
or `unknown`; “success” alone is insufficient. A partial result lists requested and observed scope,
pages/artifacts/items accepted or quarantined, missing/unsupported variants, last PDM-committed checkpoint,
retry safety, and whether deletion/cleanup is complete. One malformed item must not corrupt other raw
records, but it blocks a completeness claim.

Fail closed on wrong account/workspace, broader-than-approved scope, unsupported archive/schema,
cursor loop, active attachment, secret detection, integrity mismatch, ambiguous retry of a
write-like operation, external-call attempt, or incomplete required deletion. Errors and telemetry
carry codes/counts/hashes/locators, not source content.

### Rate limits and backpressure

Rate limits are provider-, organization-, workspace-, model-, endpoint-, and time-dependent.
Adapters should expose observed limit class and reset/retry hints, not normalize provider headers
into one assumed universal quota. A scheduler owns bounded concurrency and backpressure; the adapter
reports provider facts. Checkpointing must make delayed retry safe without duplicating accepted
observations. Cancellation must stop new provider work while preserving enough receipt state to
delete already-created local copies.

### Authentication and secrets

- Use the least-privileged documented user/admin/OAuth/API credential for the exact source class.
- Bind credentials to provider, product, account/workspace, environment, scopes, and expiry outside
  source payloads; never put tokens, cookies, keys, signed URLs, or raw headers in logs/receipts/git.
- Do not use browser session cookies or intercepted traffic as adapter credentials.
- Separate admin/compliance credentials from member content access and from ordinary model API keys.
- Signed export/download URLs are secrets; redact them and retain job/artifact identifiers only.
- Rotation/revocation, auth failure, scope mismatch, and tenant mismatch are terminal until human repair.

### Deletion, redaction, and correction propagation

The source provider, acquisition archive, extracted raw records, normalized projection, derived
chunks/embeddings/summaries, logs, backups, public links, and accepted HKA/MEM objects are independent
copies or authority states. A provider deletion signal does not prove local deletion, and local
deletion does not prove provider deletion. OpenAI and Google document separate chat/file/service or
connected-copy behavior [S14, S15].

A later implementation needs a derivation/copy graph where every controlled node has owner,
location, purpose, sensitivity, expiry, source, transformation, and deletion/correction status.
Deletion propagates from derivatives toward raw staging while preserving only a policy-authorized,
content-free tombstone. Accepted HKA/MEM material cannot be silently erased or rewritten through an
adapter; it follows its owner lifecycle for retraction/correction with source-deletion evidence.
Partial/failed/unknown deletion remains visible and blocks a “deleted” receipt.

### Drift discovery and retirement

Detect drift through documented version/deprecation feeds, capability snapshots, archive/schema
fingerprints, unknown field/item counters, fixture failures, and sampled structural manifests. New
fields are preserved as opaque provider extensions where safe but are not silently normalized.
Removed/changed required semantics stop that adapter version. Drift remediation creates a new
mapper/fixture version and replay report; it never rewrites old receipts. Provider docs and fixtures
are re-checked before each real experiment and on any observed shape or policy change.

## Recommendation, conformance, and follow-ups

### Recommended conceptual architecture

Recommend a future **EBF acquisition edge, PDM storage seam, and SIP projection**:

1. A provider/acquisition-class-specific EBF edge performs capability discovery, scope planning,
   authenticated acquisition, source-observation production, and provider-faithful lifecycle/failure reporting.
2. A small provider-neutral acquisition envelope carries source binding, raw locator/hash,
   capability/version snapshot, checkpoint, gaps, and copy/deletion posture without claiming a
   universal transcript schema.
3. When separately authorized, PDM persists quarantine/raw observations, receipts, and committed
   checkpoints only through governed `StorePort` bindings; neither EBF nor SIP owns a private store.
4. SIP builds a pinned, rebuildable normalized projection and exact derivation lineage. HKA/MEM/GOV
   remain human-authorized destinations, never adapter outputs.

For sequencing, use synthetic human-selected fixtures first; characterize official exports only
under a later authority gate; prototype forward capture through one caller-controlled API/CLI seam
only after conformance criteria exist. Do not select a provider yet. Evidence is insufficient to
choose an adopted interface or production adapter because no real/synthetic bake-off has measured
field coverage, drift, failure recovery, or deletion propagation.

### Conformance strategy

Every future adapter version should run the same provider-neutral behavioral suite plus its own
provider fixtures. All committed fixtures must be synthetic.

| Suite | Required synthetic cases and assertions |
| --- | --- |
| Source/scope | correct and wrong account/workspace; bounded time/item range; over-broad archive; explicit cancellation; no credential leakage |
| Shape/capability | known and unknown version; text; branches; edits; regenerations; tools; citations; missing/redacted attachments; unknown item type; absent timestamps/IDs |
| Integrity/safety | path traversal; decompression bomb; malformed encoding/JSON; duplicate entry; active content; secret patterns; hash mismatch |
| Pagination/checkpoint | empty/single/multiple pages; repeated/looping/expired cursor; insert/update during pagination; crash before/after PDM raw/checkpoint commit; resumable checkpoint; no EBF/SIP private store |
| Retry/rate limit | timeout, connection failure, 429 with/without retry hint, 5xx, auth/scope/tenant failure, cancellation during backoff, bounded retry exhaustion |
| Identity/dedup | same bytes/new acquisition; same native ID/changed version; missing native ID; content collision fixture; semantically similar but distinct records |
| Partial failure | one bad item among valid items; lost attachment; truncated stream; unsupported field; status/count/gap receipt; no false completeness |
| Replay/drift | old raw fixture through old/new mapper; additive unknown field; breaking required-field change; deterministic output and explicit migration/loss report |
| Deletion/correction | source deleted/local retained, local deleted/source retained, derived-copy cascade, partial failure/retry, HKA/MEM correction handoff, minimal tombstone |
| Authority | provider roles/model output stay source evidence; no HKA/MEM/GOV write; transcript instructions cannot invoke tools or widen scope |

Minimum go evidence for a later implementation proposal: deterministic fixture results; zero silent
loss; explicit unsupported/gap states; raw replay through an authorized PDM-backed locator without
provider access; safe retry/checkpoint
behavior; no secrets/content in logs; verified synthetic deletion cascade; and human review of
authority boundaries. Any false completeness, cross-tenant access, ambiguous write retry, content
leak, or authority escalation is a stop condition.

### Deferred alternatives

- A single universal “conversation adapter” that parses every source directly into one canonical
  schema: deferred/rejected because it erases provider capability and lifecycle differences.
- Event-stream-first ingestion for every source: deferred because exports are archive/job based and
  event semantics would be invented.
- Full raw payload storage as the durable system of record: deferred because privacy/copy/deletion
  obligations and storage authority are unresolved.
- Portability/compliance integration: deferred until exact product coverage, organizational
  authority, verification, cost, retention, and incident ownership are proven.
- Embeddings or model-based normalization at the edge: rejected as a required adapter step; it adds
  derived copies, external processing, nondeterminism, and authority confusion before source parsing.

### Open questions

1. Which one acquisition class and synthetic provider shape should #3597 use to test the conceptual
   boundary without real data or runtime writes?
2. What is the minimum acquisition-envelope information already owned by EBF/SIP metadata contracts,
   and which candidate fields would require an owner-doc change rather than a local adapter detail?
3. Which source capabilities are mandatory for a useful conversation representation versus safely
   optional/unsupported (branches, edits, tools, attachments, citations, model/config)?
4. What provider documentation or observable artifact identifies export/schema version reliably?
5. How is account/workspace scope pseudonymized while still detecting cross-tenant mistakes?
6. Which raw evidence, if any, may persist after normalization, and who owns its retention/deletion policy?
7. How should provider source deletion or correction be detected when no change feed exists and
   absence from a later export is not reliable deletion proof?
8. Which retry/idempotency semantics are documented for each selected provider operation, and what
   must be treated as human-recoverable rather than automated?
9. What conformance fixture licensing/provenance is acceptable for provider-shaped synthetic archives?
10. What evidence threshold would justify an ADR or adopted adapter port rather than continued research?

### Recommended bounded follow-ups

- **Zero-write adapter protocol spike (#3597 input).** Define synthetic in-memory examples for
  capability discovery, dry-run manifest, raw observation receipt, normalized projection/loss
  report, and deletion plan. Measure only paper/fixture behavior; no runtime port or provider call.
- **Official-export structural characterization.** After separate owner/privacy authority, inspect
  one selected export in quarantined local staging and publish only structural field/capability
  counts plus synthetic fixtures. No real payload in repo, logs, issues, or CI.
- **Acquisition-envelope owner-boundary review.** Map each candidate datum to existing EBF/SIP
  metadata ownership and propose the smallest explicit contract change only if the feasibility
  evidence demonstrates a gap.
- **Synthetic conformance harness.** Implement hostile/complex provider-shaped fixtures and
  deterministic checks for pagination, drift, retry, dedup, partial failure, authority, and deletion.
  Keep it provider-call-free.
- **Provider lifecycle decision.** For one future seam, record current auth scopes, versioning,
  rate-limit/retry/idempotency behavior, retention/deletion, deprecations, and operational ownership.
- **Copy-graph/deletion contract.** Coordinate with the privacy follow-up before any persistent raw,
  normalized, embedding, or summary layer exists.

## Source register

All external sources are primary provider documentation. Accessed 2026-07-13. Product/API facts
are volatile and must be re-checked before feasibility or implementation. These sources establish
specific available seams and failure/lifecycle facts, not Yggdrasil authority or universal schemas.

| ID | Publisher | Primary source | Claim supported | Volatility / limit |
| --- | --- | --- | --- | --- |
| S1 | OpenAI | [Exporting your ChatGPT history and data](https://help.openai.com/en/articles/7260999-how-do-i-export-my-data) | Supported consumer export flow, availability distinctions, asynchronous delivery/expiring link, ZIP includes chat history and other account data | Help/product behavior; re-check account/workspace eligibility and archive shape |
| S2 | Anthropic | [How can I export my Claude data?](https://support.anthropic.com/en/articles/9450526-how-can-i-export-my-claude-data) | Individual/workspace roles and conversation/account data export | Re-check plan, workspace role, contents, delivery, and expiration |
| S3 | Google | [Download your Gemini Apps data](https://support.google.com/gemini/answer/16920332?hl=en) | Takeout export includes selected Gemini activity such as chats/media/uploads and does not delete provider data | Settings, account type, export contents, and retention can change |
| S4 | OpenAI | [Conversations API reference](https://developers.openai.com/api/reference/resources/conversations) | API-side Conversation resources and item operations | Not evidence of consumer ChatGPT history access; pin endpoint/schema fixtures |
| S5 | Anthropic | [Create a Message](https://platform.claude.com/docs/en/api/go/messages/create) | Stateless multi-turn Messages use where prior turns are supplied by caller | API/version/content-block variants can change |
| S6 | OpenAI | [Codex developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli) | Supported `codex exec --json` newline-delimited event output and resume behavior | Capture tool version; CLI event shapes can evolve |
| S7 | Anthropic | [Claude Code CLI reference](https://docs.anthropic.com/en/docs/claude-code/cli-usage) | Supported non-interactive JSON/stream-JSON output and session options | Capture CLI version and documented output mode |
| S8 | OpenAI | [Compliance Platform for Enterprise and Edu](https://help.openai.com/en/articles/9261474-openai-compliance-platform-for-enterprise-customers) | Qualifying workspace access and current append-only Compliance Logs Platform for audit/eDiscovery/DLP/SIEM; deprecation notice says the old stateful route was removed on 2026-06-05 | The page still contains legacy prose describing two patterns, so the dated removal notice controls this memo; authenticated current API docs must be checked before design |
| S9 | Google | [Data Portability API overview](https://developers.google.com/data-portability) | OAuth portability class, supported product/resource schemas, app verification and sensitive/restricted scope posture | Does not establish Gemini resource availability |
| S10 | Google | [Data Portability API reference](https://developers.google.com/data-portability/reference/rest) | Archive-job, access-type, authorization, initiate, status, retry, cancel, and reset resources | API/resource/region/policy availability must be verified |
| S11 | Google | [Call Data Portability API methods](https://developers.google.com/data-portability/user-guide/methods) | Job IDs, status/signed URLs, cancel/retry, and authorization reset lifecycle | Signed URLs/tokens are secrets; exact resource semantics differ |
| S12 | Anthropic | [Rate limits](https://platform.claude.com/docs/en/api/rate-limits) | Organization/workspace/endpoint limit classes, 429 and retry/reset headers, dynamic tier posture | Never hardcode current numeric examples; exact account limits vary |
| S13 | Anthropic | [Errors](https://platform.claude.com/docs/en/api/errors) | Structured errors/request IDs and documented SDK retry behavior for transient failures | Adapter must pin SDK/version and bound retries itself |
| S14 | OpenAI | [Chat and File Retention Policies in ChatGPT](https://help.openai.com/en/articles/8983778) | Chat, file/Library, project/GPT, compliance visibility, and deletion paths are distinct | Current policy includes exceptions; feature/workspace behavior can change |
| S15 | Google | [Gemini Apps Privacy Hub](https://support.google.com/gemini/answer/13594961?hl=en) | Activity, connected-app/other-service copies, retention, and deletion controls can be independent | Consumer/workspace/settings/region behavior differs |
| S16 | Anthropic | [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) | Feature-specific API storage/retention posture | Re-check exact endpoint, feature, agreement, and platform |

### Repo authority used

- `docs/research/AI_CONVERSATION_INTELLIGENCE_INPUT_SOURCES.md` — source-class evidence and staged source recommendation.
- `docs/research/AI_CONVERSATION_INTELLIGENCE_DATA_MODEL.md` — source-scoped identity, acquisition, projection, derivation, and candidate concepts.
- `docs/research/AI_CONVERSATION_INTELLIGENCE_KNOWLEDGE_TAXONOMY.md` — candidate functions remain independent of authority and provenance axes.
- `docs/research/AI_CONVERSATION_INTELLIGENCE_PRIVACY_SECURITY_AND_DATA_OWNERSHIP.md` — explicit selection, local-first staging, minimization, copy/deletion graph, and external-processing gates.
- `docs/boundaries/EBF.md` and `docs/boundaries/SIP.md` — provider/source binding at the edge and provenance-preserving normalization.
- `docs/boundaries/PDM.md` and `docs/contracts/STORE_PORT.md` — storage mechanics, quarantine/raw/checkpoint persistence, and store resolution stay behind PDM-owned ports without defining meaning or authority.
- `docs/boundaries/HKA.md`, `docs/boundaries/MEM.md`, and `docs/boundaries/GOV.md` — human knowledge, memory, and governance authority remain owner-controlled.

## Non-claims

- This memo does not adopt an adapter interface, envelope, schema, state machine, event, service,
  persistence layer, provider SDK, endpoint, auth flow, retry policy, or conformance harness.
- It does not select OpenAI, Anthropic, Google, a CLI, an export, a portability API, or a compliance feed.
- It does not authorize credentials, provider calls, real exports, attachments, external processing,
  storage, normalization, deletion, or HKA/MEM/GOV mutation.
- It does not claim any provider export/API is complete, stable, lossless, idempotent, or available
  for a specific account/product/region beyond the cited documentation.
- It does not turn provider roles, native IDs, model output, normalized records, or derived candidates
  into accepted Yggdrasil knowledge or memory.
