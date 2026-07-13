State: Advisory research synthesis (docs-only; no source integration, ingestion path, or product decision enacted).
Doc role: Research
Authority: Evidence and recommendation for issue #3195 under parent #3194. Provider facts are bounded to the cited primary sources as accessed on 2026-07-13; the Yggdrasil assessment is advisory and subordinate to current owner docs and contracts.
Owner: AI Conversation Intelligence research roadmap (#3194), downstream of EBF/SIP/HKA owner boundaries
Temporal class: snapshot
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-07-13
Last verified against: `docs/research/CHAT_SURFACE_BUILD_VS_BUY.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`, `docs/boundaries/EBF.md`, `docs/boundaries/SIP.md`, and the primary sources in the source register

# AI Conversation Intelligence: Input Source Options

## Executive answer

There is no single generally available, provider-neutral history API for personal AI conversations.
The workable inputs fall into three different lanes:

1. **Human-selected material** is the safest seed for discovery because consent, scope, and relevance
   are explicit, but it cannot establish completeness.
2. **Official account exports** are the best near-term source for retrospective feasibility work.
   OpenAI, Anthropic, and Google each document user-accessible exports that include conversation or
   chat activity, but none of those help pages promises a stable cross-provider record schema.
3. **Records captured at a caller-controlled API or CLI seam** are the best long-term source for new
   sessions because acquisition time, tool version, and request/response structure can be recorded
   when the interaction happens. They do not recover consumer-product history retroactively.

Enterprise compliance feeds solve a different, organization-governance problem and bring cost,
role, retention, and data-controller obligations that are disproportionate for the personal PKM
case. UI scraping and reverse-engineering private caches are not recommended acquisition seams.

This answer is about evidence availability, not ingestion authority. Every candidate remains an
external source observation. Import does not make a transcript, a model statement, or a derived
summary accepted knowledge, memory, or vault truth.

## Evaluation frame

The comparison uses these dimensions:

- **Access path** — the documented route by which the person or operator obtains the material.
- **Data unit / shape** — the strongest unit the source actually exposes, without inferring a
  stable schema where none is documented.
- **Provenance fidelity** — whether provider, account/workspace, native identifiers, order, role,
  time, attachments, tools, model/config, and acquisition facts can be preserved.
- **Stability** — whether the seam is a supported product/API contract, a user-facing export, or an
  undocumented implementation detail.
- **Cost** — qualitative acquisition and maintenance cost; this report does not make pricing claims.
- **Governance/privacy exposure** — who can authorize access, how much unrelated material is swept
  in, and whether the seam creates a new data copy or administrator power.
- **Feasibility** — suitability for a bounded research corpus, a repeatable prototype, or a later
  governed production adapter.

The repo boundary is decisive: EBF may observe and normalize provider material, but source identity
must survive into SIP and provider records never acquire HKA, MEM, or mutation authority merely by
crossing the adapter boundary.

## Source option matrix

| Source class | Access path | Data unit / shape | Provenance fidelity | Stability | Qualitative cost | Governance/privacy exposure | Feasibility verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Human-selected excerpt or file** | The user explicitly selects text, a file, or a bounded conversation export for one import | Exactly the selected payload plus a capture receipt supplied by Yggdrasil | **Medium** if provider, native locator, selection time, and surrounding-context limits are recorded; otherwise low | **High** as a product-independent workflow | Low engineering; recurring human selection cost | Lowest collection blast radius; explicit scope, but may contain third-party or sensitive content | **Use first for discovery and golden examples.** Not evidence of account completeness |
| **Official consumer account export** | Provider settings/privacy flow or provider privacy portal | Provider-created archive that the provider says includes chat/conversation activity; exact schema remains provider-specific and not publicly guaranteed by the cited help pages | **Medium-high** when native IDs, chronology, roles, attachments, and export metadata survive; must be measured on samples | **Medium.** Supported user right/product feature, but archive content and format can change | Low marginal access cost; medium parser and fixture maintenance | Broad historical copy with high sensitivity; requires explicit owner action, secure staging, minimization, and deletion policy | **Best near-term retrospective research source.** Build parsers only after sample-and-contract work |
| **Caller-controlled model/API capture** | Yggdrasil or another authorized client records the requests, responses, tool events, identifiers, and receipts it creates | Structured request/response items or provider conversation resources, plus caller-side context omitted by the provider | **High** for events captured at creation; incomplete for hidden provider state and pre-existing consumer chats | **High-medium** when pinned to a versioned public API; provider differences remain | Medium implementation and operations; ordinary model/API usage remains separate | Creates an intentional new record and requires purpose limitation, secrets handling, retention, and user notice | **Best long-term source for new governed sessions.** Does not solve historical import |
| **Machine-readable agent/CLI output captured at execution** | Supported non-interactive JSON/stream output or an explicit export hook | Turn/tool/event stream emitted by the tool invocation; scope depends on the command and flags | **High** for emitted events if tool version, working scope, session ID, and redaction state are recorded | **Medium-high** for documented output flags; schemas still need version fixtures | Low-medium for tools already used; normalization and secret filtering are non-trivial | Builder/operator sessions may contain code, credentials, third-party data, and chain-of-work details | **Good controlled pilot source for future sessions.** Treat as operator material until Product authority explicitly admits it |
| **Enterprise compliance or audit feed** | Workspace-admin product available only on qualifying organization plans | Append-only logs, state queries, audit events, or organization exports; coverage and retention are product-specific | **High** for workspace/audit origin; semantic completeness for personal knowledge is not guaranteed | **High-medium** as a supported enterprise surface, with deprecations and retention windows to monitor | High commercial, security, legal, and operational overhead | Administrator access over other users' material; controller/processor duties, least privilege, retention, deletion, and worker expectations dominate | **Do not use for the personal MVP.** Revisit only for an explicitly organizational product boundary |
| **Authorized portability API** | OAuth authorization followed by provider archive-job APIs where the desired product/resource is supported | Provider-defined portability archive, often asynchronous and delivered by expiring URLs | **Medium-high** if job, scope, subject, time window, and archive checksums are retained | **Medium.** Public API, but product/resource/region availability and policy verification are prerequisites | High initial verification/security work; repeatability can beat manual export | Restricted/sensitive scopes, verification, transparent disclosure, minimization, deletion, and revocation obligations | **Promising adapter class, not assumed available for every AI product.** Verify exact product scope in a later issue |
| **Documented local session state or private application cache** | Read files maintained for resume/history by a local client | Tool-private session representation; supported export semantics are usually weaker than resume semantics | Potentially **high**, but fields may mix UI state, internal events, secrets, and derived summaries | **Low** unless the vendor explicitly contracts the file format for external consumption | Low discovery cost; high breakage, migration, and sanitization cost | Bypasses the product's intentional export boundary and may collect hidden or unrelated local data | **Do not make this a primary adapter.** A supported export hook can promote the class later |
| **Browser automation, DOM scraping, or network interception** | Automate the consumer UI or inspect its private traffic | Rendered fragments or undocumented internal payloads | **Low-medium** and difficult to prove complete; edits, branches, tools, and hidden context are easy to lose | **Very low** | High maintenance and incident cost | Credential/session handling, consent, terms, anti-automation, and over-collection risks | **Reject as a planned source.** Use neither as production seam nor as completeness evidence |

### Provider examples verified in this pass

- OpenAI documents a consumer ChatGPT data export whose ZIP includes chat history and other account
  data; availability differs by account/workspace type, and delivery can be delayed.
- Anthropic documents Claude data export for individuals and qualifying workspace owners and states
  that exports include conversation and account/user data.
- Google documents Gemini Apps data download through Google Takeout, including Gemini chats,
  generated media, and uploads selected through Gemini Apps activity.
- OpenAI's API exposes durable Conversation resources and listable conversation items for API-side
  state created through that API. This is not documented as an endpoint for a consumer ChatGPT
  account's history.
- Anthropic's Messages API is explicitly usable for stateless multi-turn conversations: the caller
  supplies prior turns. Therefore the caller, not the Messages endpoint, is the natural source of a
  complete application-side transcript.
- Codex documents newline-delimited JSON events for non-interactive runs, while Claude Code
  documents `json` and `stream-json` output formats. Those are supported capture seams for runs
  launched under caller control; neither statement makes private session storage a public contract.
- OpenAI documents a separate Enterprise/Edu Compliance Platform with logs and metadata, qualifying
  access, retention limits, and an active history of endpoint migration. It should not be treated as
  the default path for a personal knowledge system.

## Cross-source provenance minimum

Any later feasibility fixture should preserve the following before normalization:

- `source_provider` and `source_product`;
- `source_account_or_workspace_ref` as a scoped/pseudonymous reference, not copied credentials;
- `source_native_conversation_id` and item/message IDs when present;
- `source_created_at`, `source_updated_at`, and the provider's precision/timezone posture when known;
- original role and content-block type without translating provider labels into authority;
- attachment/tool/media references and whether the referenced bytes are present, missing, or redacted;
- export/API/tool version, acquisition method, acquisition time, and archive checksum;
- declared scope, consent/authorization receipt, sensitivity posture, and deletion/retention status;
- gaps: missing timestamps, unavailable branches, omitted attachments, truncated content, or unknown
  model/config must remain explicit rather than synthesized.

This is a research fixture envelope, not a runtime contract. #3196 owns the conceptual model, and a
later adapter issue must reconcile any adopted fields with the metadata bundle and SIP/EBF contracts.

## Recommendation

Use a staged, reversible source strategy:

1. **Discovery corpus — explicit human selection.** Start with a small set of conversations the
   owner deliberately chooses across providers/tools. Record a capture receipt and known omissions.
   This produces useful model/taxonomy examples with the smallest privacy blast radius.
2. **Retrospective feasibility — official exports.** Obtain one owner-authorized export sample from
   each priority consumer provider. Profile structure, identifiers, timestamps, branches,
   attachments, edits, tool events, and deletions. Commit only synthetic fixtures; never commit real
   exported conversations to the repo.
3. **Forward feasibility — controlled API/CLI capture.** For newly created test sessions, capture
   versioned machine-readable events at the caller-controlled seam. Compare them to export-derived
   records and quantify information loss during normalization.
4. **Defer enterprise and portability adapters.** They require a named organizational use case,
   product/resource availability proof, and privacy/security authority that #3195 does not grant.
5. **Reject scraping and private-cache coupling.** They are too brittle and governance-heavy to
   justify as planned acquisition paths.

The decision criterion for a later prototype is not "can text be extracted?" It is whether a
source can produce a bounded, consented, provenance-complete fixture without making the provider's
conversation store semantically primary and without granting raw model output knowledge authority.

## Open questions and next bounded issues

### Open questions

1. Which provider/tool histories are actually in the owner's intended first corpus, and which are
   excluded because they mix personal, work, third-party, or regulated data?
2. What deletion promise applies to staging copies, extracted attachments, failed parses, logs, and
   derived fixtures after the import decision is complete?
3. What counts as proof that the requesting human owns or is authorized to process every participant's
   material in a conversation?
4. Which source facts must be retained verbatim for later correction or dispute, and which sensitive
   content may be reduced to a hash/locator after derivation?
5. How should edits, regenerated answers, branches, shared chats, temporary chats, voice, files,
   tools, citations, and missing/deleted items appear as absence rather than false linear history?
6. Which external source should be the first prototype target after #3196 and #3197 define the
   provider-neutral model and taxonomy?

### Recommended next bounded issues

- **Privacy, security, and data-ownership threat model for conversation imports.** Define lawful/user
  authority, minimization, sensitivity classes, staging/deletion, secrets scanning, third-party
  content, and fail-closed receipts. Deliver a decision checklist and abuse-case set; no adapter.
- **Provider-neutral acquisition manifest contract.** Reconcile the research provenance minimum
  with EBF/SIP and `docs/architecture/metadata-bundle.md`; define missing/unknown semantics and
  checksums. Deliver a contract proposal and synthetic examples; no runtime parser.
- **Official-export fixture characterization.** With explicit owner authorization, inspect one
  export per selected provider, publish only redacted structural manifests and synthetic fixtures,
  and report field coverage and drift risk.
- **Controlled capture bake-off.** Generate synthetic multi-turn/tool/attachment sessions through
  one OpenAI API path, one Anthropic API path, and documented CLI JSON modes; measure provenance
  coverage and normalization loss without importing personal history.
- **Adapter architecture options.** Compare per-provider parsers, a portability/archive adapter,
  and caller-side capture behind an EBF boundary; include versioning, idempotency, quarantine, and
  deletion behavior. Remain docs-only until a separate implementation issue is approved.

## Source register

All external sources below are primary provider or standards documentation. Accessed 2026-07-13.

| ID | Publisher | Primary source | Claim supported | Volatility note |
| --- | --- | --- | --- | --- |
| S1 | OpenAI | [How do I export my ChatGPT history and data?](https://help.openai.com/en/articles/7260999-how-do-i-export-my-data) | Consumer export route, eligibility caveats, delivery window, expiring download, and inclusion of chat history | Product help; re-check before adapter work |
| S2 | Anthropic | [How can I export my Claude data?](https://support.anthropic.com/en/articles/9450526-how-can-i-export-my-claude-data) | Individual/workspace export roles, conversation-data inclusion, and expiring download | Product help; re-check plan/role availability |
| S3 | Google | [Download your Gemini Apps data](https://support.google.com/gemini/answer/16920332?hl=en) | Takeout route and inclusion of Gemini chats, generated media, and uploads; archive timing and delivery choices | Product help; re-check activity/export settings |
| S4 | OpenAI | [Conversations API reference](https://developers.openai.com/api/reference/resources/conversations) | API Conversation resources and item operations for API-side state | Versioned public API; pin fixtures to observed schema |
| S5 | Anthropic | [Create a Message](https://platform.claude.com/docs/en/api/go/messages/create) | Messages API supports stateless multi-turn use and requires the caller to send prior turns | Versioned public API; new optional fields/variants can appear |
| S6 | Anthropic | [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) | Retention differs by API feature; Messages and stateful managed-agent sessions have different storage postures | Policy/feature matrix; re-check before data design |
| S7 | OpenAI | [Codex developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli) | `codex exec --json` emits newline-delimited JSON events and sessions can be resumed | CLI behavior; capture tool version and schema fixture |
| S8 | Anthropic | [Claude Code CLI reference](https://docs.anthropic.com/en/docs/claude-code/cli-usage) | Non-interactive `json` and `stream-json` output modes and resumable sessions | CLI behavior; capture tool version and schema fixture |
| S9 | OpenAI | [Compliance Platform for Enterprise and Edu](https://help.openai.com/en/articles/9261474-openai-compliance-platform-for-enterprise-customers) | Qualifying access, current append-only compliance logs, retention, and endpoint migration/removal risk; the deprecation notice says the old stateful route was removed on 2026-06-05 | Enterprise product; page retains legacy two-pattern prose, so check authenticated current API docs and deprecations before use |
| S10 | Google | [Data Portability API overview](https://developers.google.com/data-portability) and [user data policy](https://developers.google.com/data-portability/policy) | Authorized archive-job class, app verification, sensitive/restricted data duties, transparency, minimization, security, and deletion expectations | Product/resource/region scope must be verified separately |

### Repo authority used

- `docs/research/CHAT_SURFACE_BUILD_VS_BUY.md :: B. Framing` — conversation history must not become
  the semantic center or demote the vault to a RAG source.
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md :: The Chat contradiction this spec must address`
  — canvas thinking and governed mutation are distinct from ASK-style chat history.
- `docs/boundaries/EBF.md :: Provenance obligations` — preserve provider identity and source binding;
  external mechanisms do not acquire authority.
- `docs/boundaries/SIP.md :: Provenance obligations` — preserve derivation and source continuity
  across normalization.

## Non-claims

- This report does not assert that any provider export is complete, lossless, continuously
  available, or schema-stable.
- It does not assert that Google Data Portability currently exposes Gemini as a programmatic resource;
  the exact product/resource scope remains a prerequisite check.
- It does not conclude that processing exported conversations is lawful, ethical, consented, or
  secure for a specific corpus.
- It does not choose an adapter, parser, storage schema, provider, runtime path, or product feature.
- It does not treat a conversation, model answer, generated summary, CLI transcript, compliance log,
  or provider role label as accepted human knowledge or machine memory.
