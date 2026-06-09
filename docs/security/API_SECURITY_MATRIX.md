State: Initial API security matrix for security foundation wave (#1587).
Doc role: Security review input
Authority: Route-by-route security classification for current FastAPI route modules. Consumes route code and security architecture docs; does not change runtime behavior or define new controls.
Owner: Security architecture / runtime API
Temporal class: operational
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-04
Last verified against: app/api/routes/*, docs/SECURITY_ARCHITECTURE.md, docs/SECURITY_TRUST_BOUNDARIES.md, docs/SECURITY_DATA_FLOWS.md, companion-ui/docs/LOCAL_ACCESS_MODEL.md

# API Security Matrix

## Purpose

This matrix inventories the current FastAPI route surface as input to future security review. It
classifies exposure assumptions, mutation posture, authority implications, receipt/audit
expectations, and the proportionate review level from `docs/SECURITY_REVIEW_METHOD.md`.

This is an analysis artifact only. It records current assumptions and gaps; it does not implement
auth, rate limiting, CSRF protection, receipts, or route behavior changes.

## Classification legend

| Field | Values |
| --- | --- |
| Exposure assumption | `trusted-device server default`, `loopback opt-out`, `unsupported public`, `external outbound optional` |
| Mutation class | `read`, `runtime-only`, `mirror write`, `body co-authoring`, `governance-bearing`, `BuilderOps operational`, `diagnostic` |
| Auth/rate-limit posture | Current docs assume no auth for trusted-device personal server use; no per-route rate limit is recorded unless noted. |
| Receipt/audit expectation | `none`, `trace`, `session-log provenance`, `pending intent`, `receipt-supporting event`, `BuilderOps receipt`, `governance receipt` |
| Review level | Level 1 for simple local read/status surfaces; Level 2 for writes, provider/tool influence, debug/event exposure, BuilderOps, memory/context, or governance-bearing surfaces. |

## Route inventory

Routes below use reachable mounted paths from `app/api/app.py` plus each route module's
`APIRouter` prefix and decorator path.

| Route/module | Method | Purpose | Exposure assumption | Mutation class | Auth/rate-limit posture | Receipt/audit expectation | Touches | Review level |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `app/api/routes/artifacts.py` | `GET /api/artifacts/note` | Read one vault note body and metadata by vault-relative path. | Trusted-device server default; loopback opt-out; public unsupported. | read | No auth/rate-limit in route; path traversal rejected. | none | vault content | Level 2 |
| `app/api/routes/ask.py` | `POST /api/ask` | Run Ask graph over retrieval/object store and optional LLM route. | Trusted-device server default; outbound provider possible through configured Ask/LLM path. | read/inference | No route auth/rate-limit; provider posture governed by LLM/privacy docs. | trace/status counters | DB mirror, retrieval, prompts/model outputs, external providers | Level 2 |
| `app/api/routes/builderops.py` | `GET /api/builderops/health` | Report BuilderOps boundary health. | Trusted-device server default; public unsupported. | read | No route auth/rate-limit. | none | BuilderOps store | Level 1 |
| `app/api/routes/builderops.py` | `GET /api/builderops/records` | List BuilderOps records, optionally by type. | Trusted-device server default; public unsupported. | read | No route auth/rate-limit. | none | BuilderOps operational records | Level 2 |
| `app/api/routes/builderops.py` | `GET /api/builderops/records/{record_id}` | Read one BuilderOps record. | Trusted-device server default; public unsupported. | read | No route auth/rate-limit. | none | BuilderOps operational records | Level 2 |
| `app/api/routes/builderops.py` | `POST /api/builderops/worklogs` | Create `AgentWorklog` through BuilderOps boundary. | Trusted-device server default; public unsupported. | BuilderOps operational | Boundary validates payload/source refs; no route auth/rate-limit. | BuilderOps record/receipt semantics where applicable | BuilderOps operational records | Level 2 |
| `app/api/routes/builderops.py` | `POST /api/builderops/learning-signals` | Create `LearningSignal` through BuilderOps boundary. | Trusted-device server default; public unsupported. | BuilderOps operational | Boundary validates payload/source refs; no route auth/rate-limit. | BuilderOps record/receipt semantics where applicable | BuilderOps operational records | Level 2 |
| `app/api/routes/builderops.py` | `POST /api/builderops/promotion-intents` | Create staged `PromotionIntent`; does not execute promotion. | Trusted-device server default; public unsupported. | BuilderOps operational | Boundary validates payload/source refs; no route auth/rate-limit. | BuilderOps record; promotion remains proposal only | BuilderOps operational records, GitHub/repo proposal path | Level 2 |
| `app/api/routes/builderops.py` | `POST /api/builderops/receipts` | Append BuilderOps receipt to the operational store. | Trusted-device server default; public unsupported. | BuilderOps operational | Boundary validates payload/source refs; no route auth/rate-limit. | BuilderOps receipt | BuilderOps receipts | Level 2 |
| `app/api/routes/canvas.py` | `POST /api/canvas/sessions` | Open in-memory Canvas session and durable session log. | Trusted-device server default; disabled unless `CANVAS_ENABLED` truthy. | runtime-only plus provenance setup | No route auth/rate-limit; feature flag gates surface. | session-log provenance | vault note path, session log, leave-point trace | Level 2 |
| `app/api/routes/canvas.py` | `POST /api/canvas/sessions/{session_id}/edits` | Apply Canvas body co-authoring edit. | Trusted-device server default; disabled unless `CANVAS_ENABLED` truthy. | body co-authoring | Feature flag, note path validation, content hash option, governance-bearing mutation rejection. | session-log provenance, not Panel governance receipt | vault body, session log | Level 2 |
| `app/api/routes/canvas.py` | `DELETE /api/canvas/sessions/{session_id}/edits/last` | Undo last Canvas body edit if body has not diverged. | Trusted-device server default; disabled unless `CANVAS_ENABLED` truthy. | body co-authoring | Feature flag, in-memory history, divergence check; no route auth/rate-limit. | session-log provenance | vault body, session log | Level 2 |
| `app/api/routes/canvas.py` | `POST /api/canvas/sessions/{session_id}/governance` | Route Canvas governance-bearing intent to Panel proposal pipeline. | Trusted-device server default; disabled unless `CANVAS_ENABLED` truthy. | governance-bearing | Feature flag, action type validation, artifact identity resolution; no route auth/rate-limit. | pending intent; later governance receipt on confirmation | Panel proposal store, vault identity, session log | Level 2 |
| `app/api/routes/canvas.py` | `DELETE /api/canvas/sessions/{session_id}` | Close in-memory Canvas session and session log. | Trusted-device server default; disabled unless `CANVAS_ENABLED` truthy. | runtime-only plus provenance | Feature flag; no route auth/rate-limit. | session-log provenance | session log, leave-point trace | Level 1 |
| `app/api/routes/companion.py` | `GET /api/companion/vault/notes` | List active vault note paths/titles. | Trusted-device server default; loopback opt-out; public unsupported. | read | No route auth/rate-limit; browse cap applies. | none | vault content metadata | Level 2 |
| `app/api/routes/companion.py` | `GET /api/companion/vault-browser` | Read Vault Browser projection with filters, receipts, memory posture. | Trusted-device server default; loopback opt-out; public unsupported. | read/projection | No route auth/rate-limit; limit/cursor caps apply. | receipt projection only | vault metadata, receipt projection, memory posture | Level 2 |
| `app/api/routes/companion.py` | `GET /api/companion/vault-link-index` | Read note-path index for wikilink resolver. | Trusted-device server default; loopback opt-out; public unsupported. | read/projection | No route auth/rate-limit; environment max cap applies. | none | vault paths | Level 2 |
| `app/api/routes/companion.py` | `GET /api/companion/vault-related` | Return deterministic related artifacts for Find scope. | Trusted-device server default; loopback opt-out; public unsupported. | read/projection | No route auth/rate-limit; limit cap and scope validation apply. | none | vault metadata/relations | Level 2 |
| `app/api/routes/companion.py` | `POST /api/companion/vault-browser/actions/queue-review` | Stage pending Panel governance proposal for review queue. | Trusted-device server default; loopback opt-out; public unsupported. | governance-bearing staging | WriteGuard check, scope validation; no route auth/rate-limit. | pending intent, not durable receipt | vault metadata, Panel proposal store | Level 2 |
| `app/api/routes/companion.py` | `GET /api/companion/orientation` | Return note-independent orientation projection with memory handoff intents and governance summary. | Trusted-device server default; loopback opt-out; public unsupported. | read/projection plus trace-backed handoff intent | No route auth/rate-limit; degraded states reported. | trace for memory intent, not candidate creation | memory posture, runtime signals, context/projections, receipts summary | Level 2 |
| `app/api/routes/companion.py` | `GET /api/companion/workspace` | Return active note workspace aggregate, body, Canvas/Panel/guard state. | Trusted-device server default; loopback opt-out; public unsupported. | read/projection | No route auth/rate-limit; note path validation. | none | vault content, UI projection, guard state, Panel state | Level 2 |
| `app/api/routes/companion.py` | `POST /api/companion/workspace/update` | Update active note body through workspace update flow. | Trusted-device server default; enabled only when Canvas/writeguard posture permits. | body co-authoring | Active/target scope match, WriteGuard, content hash option, frontmatter block rejection. | accountability evidence via body-edit/update path; not governance receipt | vault body | Level 2 |
| `app/api/routes/companion.py` | `POST /api/companion/workspace/body` | Update workspace note body through flagged flow. | Trusted-device server default; disabled unless `WORKSPACE_UPDATE_FLOW_ENABLED`. | body co-authoring | Feature flag, WriteGuard, markdown note path validation, frontmatter rejection. | accountability evidence via update response; no governance receipt | vault body | Level 2 |
| `app/api/routes/companion.py` | `POST /api/companion/note/save` | Human-initiated direct note body save. | Trusted-device server default; loopback opt-out; public unsupported. | human body edit | WriteGuard health guard only, hash option, markdown path validation, frontmatter preservation. | human edit accountability via response/current content; no governance receipt | vault body | Level 2 |
| `app/api/routes/context_bundles.py` | `GET /api/context-bundles/{bundle_id}` | Return inspectable context bundle; optional query emits bundle from retrieval. | Trusted-device server default; optional provider exposure through retrieval stack. | read/projection | No route auth/rate-limit. | context-bundle receipt/provenance where retrieval emits it | context bundles, retrieval, DB/index mirrors | Level 2 |
| `app/api/routes/debug.py` | `GET /api/debug/panel` | Parse Panel state for a vault note and return diagnostics. | Localhost/dev diagnostic; public unsupported. | diagnostic read | No route auth/rate-limit; path containment validation. | none | vault content, panel diagnostics | Level 2 |
| `app/api/routes/events_tail.py` | `GET /api/events/tail` | Return recent outbox JSONL events with filters. | Localhost diagnostic; public unsupported. | diagnostic read | No route auth/rate-limit; limit cap applies. | trace exposure | outbox traces/audit-supporting records | Level 2 |
| `app/api/routes/health.py` | `GET /api/health` | Return sanitized CLI health output. | Trusted-device server default; public unsupported. | diagnostic read | No route auth/rate-limit; sanitizer redacts sensitive details. | none | health/status metadata | Level 1 |
| `app/api/routes/health_contract.py` | `GET /healthz` | Simple liveness. | Trusted-device server default; public unsupported. | read | No route auth/rate-limit. | none | status metadata | Level 1 |
| `app/api/routes/health_contract.py` | `GET /readyz` | Read readiness snapshot, 503 outside ready states. | Trusted-device server default; public unsupported. | read | No route auth/rate-limit. | none | status metadata | Level 1 |
| `app/api/routes/health_contract.py` | `GET /status` | Read health-contract status snapshot. | Trusted-device server default; public unsupported. | read | No route auth/rate-limit. | none | status metadata | Level 1 |
| `app/api/routes/ingest.py` | `POST /ingest` | Insert normalized object and outbox event. | Trusted-device server default; public unsupported. | mirror write | No route auth/rate-limit; normalizes state axes. | outbox trace, not receipt | DB mirror, outbox | Level 2 |
| `app/api/routes/orientation.py` | `GET /api/orientation` | Return read-only orientation frame. | Trusted-device server default. | read/projection | No route auth/rate-limit. | none | orientation runtime projection | Level 1 |
| `app/api/routes/orientation.py` | `GET /api/orientation/bundle/{bundle_id}` | Consume orientation-scoped bundle into read-only frame. | Trusted-device server default. | read/projection | No route auth/rate-limit; rejects mis-scoped or `may_write=true` bundles. | context-bundle provenance | context bundle | Level 2 |
| `app/api/routes/panel.py` | `POST /api/panel/confirm` | Confirm/reject staged Panel proposal. | Trusted-device server default; loopback opt-out; public unsupported. | governance-bearing | Service owns policy, WriteGuard, idempotency, execution, receipts; no route auth/rate-limit. | governance receipt or blocked/logged outcome | Panel proposal, vault mutation when admitted, receipts/events | Level 2 |
| `app/api/routes/panel.py` | `POST /api/panel/checkbox-projection` | Source-backed read-mode projection to checked Markdown state. | Trusted-device server default; loopback opt-out; public unsupported. | projection/writeback support | Service validates source-backed projection; no route auth/rate-limit. | transport response may carry receipt/null per contract | Panel state, receipt projection, possible vault-visible projection | Level 2 |
| `app/api/routes/resurfacing.py` | `GET /api/resurfacing/bundle/{bundle_id}` | Consume resurface-scoped bundle into suggestion-only frame. | Trusted-device server default. | read/projection | No route auth/rate-limit; rejects mis-scoped or write-capable bundles. | context-bundle provenance | context bundle | Level 2 |
| `app/api/routes/search.py` | `GET /search` | Query embeddings/DB mirror and fallback recent objects. | Trusted-device server default; external outbound if embedding provider configured. | read/projection | No route auth/rate-limit; DB query parameterized. | trace if supplied | DB mirror, embeddings/provider payload | Level 2 |
| `app/api/routes/settings_validate.py` | `GET /api/settings/validate` | Return settings validation issues. | Trusted-device server default; public unsupported. | diagnostic read | No route auth/rate-limit. | none | settings metadata, possible config posture | Level 1 |
| `app/api/routes/status.py` | `GET /api/status` | Return observability status model. | Trusted-device server default; public unsupported. | diagnostic read | No route auth/rate-limit. | none | status metadata | Level 1 |

## Cross-route observations and gaps

| Gap / observation | Current proportionate interpretation | Follow-up posture |
| --- | --- | --- |
| Auth is not route-specific in the current matrix. | Acceptable for trusted-device personal server use, but not sufficient for supported LAN/Tailscale/public exposure. | Companion UI exposure profile defines non-loopback posture; implementation remains out of scope. |
| No explicit per-route rate limit contract is recorded. | Low current local risk; relevant for accidental broader network or future public/multi-user use. | Record as future hardening gap, not current emergency. |
| CSRF/CORS posture is exposure-dependent. | Lower for trusted-device personal server use with non-cookie auth absent; important if cookie/session auth or non-loopback exposure is added. | Review with Companion UI exposure changes. |
| Diagnostic routes expose traces, status, paths, or outbox records. | Useful for local development; unsuitable for public exposure. | Keep diagnostic routes Level 2 when exposure changes. |
| Body co-authoring and governance-bearing writes are separate lanes. | Canvas/workspace body writes need provenance/accountability but do not produce Panel governance receipts. | Preserve this distinction in future review and issue contracts. |
| Context bundle `may_write` flags do not authorize writes. | Existing bundle consumers reject write-capable bundles for read-only orientation/resurfacing paths. | Keep as architectural invariant. |
| BuilderOps routes are operational-plane writes, not product/runtime truth. | Records and PromotionIntents can support proposals; they do not cross repo/product authority by themselves. | Review any automatic promotion or GitHub mutation separately. |
