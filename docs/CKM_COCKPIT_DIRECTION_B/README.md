State: ACCEPTED/DELIVERED CKM Cockpit Direction B foundation with the owner-readable portfolio amendment implemented by #4395 on 2026-07-30. Owner Gate A authorized the bounded design on 2026-07-24; Evidence Profile, children #4081–#4086, completion #4222, and parent #4080 are closed. Independent parent acceptance and closure were recorded on 2026-07-28. Direction A remains the script-free default; Direction B is the supported opt-in `ckm overview --cockpit` mode.
Doc role: Specification directory (capability breakdown)
Authority: Owns the target-state Direction B cockpit boundary, task decomposition, interaction-safety invariants, and acceptance path. Subordinate to ADR-0057, the delivered CKM MVP and Measurement & Access contracts, the ratified CKM Evidence Profile Phase 1 contract, and the Builder System authority boundary.
Owner: BuilderOps governance / Capability Knowledge Model
Temporal class: snapshot (accepted/closed contract and delivery history)
Review cadence: event-driven
Source of truth: this directory for Direction B implementation-task shape; ADR-0057 for CKM authority posture; `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md` for the delivered presentation contract being amended; `docs/CKM_MEASUREMENT_AND_ACCESS/README.md` for retained-observation semantics.
Last reviewed: 2026-07-30

# CKM Cockpit Direction B

## Capability boundary

Direction B enhances the existing generated local CKM Development Overview into an opt-in cockpit
mode. It remains one self-contained HTML artifact produced by the existing `ckm overview` command
and `render_overview_html` pipeline. It is not a second dashboard, a local service, a hosted UI, or
a control plane.

The cockpit answers four fixed owner questions:

1. Is this projection fresh and complete enough to inspect?
2. What differs between the two newest active retained observation records, when O1b says they are
   compatible?
3. Where is evidence weakest?
4. What should not be taken at face value?

The capability adds:

- a portfolio-first trust strip and fixed information architecture;
- descriptive interpretation hazards and explicit degraded/refusal states;
- an O1b-backed pairwise comparison with the fixed disclaimer
  **“Difference between two snapshots. Not a trend, cause, or forecast.”**;
- one bounded progressive-enhancement script that filters already-rendered capability rows only;
- deterministic proposal draft text for manual review and copy;
- deterministic print CSS and a manual PDF validation receipt.

The page remains a non-authoritative BuilderOps projection. All source data is captured before
rendering, content and ordering are deterministic for the same bound inputs, and no cockpit
affordance can mutate CKM, GitHub, repo docs, Product/Runtime state, or BuilderOps authority.

## Explicitly out of scope

- automatic ranking, gating, prioritization, agent scoring, prediction, causal diagnosis, trend
  claims, drift alerts, or automated action;
- clipboard APIs, GitHub URLs/prefill, network requests, fetch, cookies, local/session storage, or
  any write from the generated artifact;
- arbitrary historical reconstruction, a timeline, silent fallback to an older comparison pair, or
  a new observation cadence;
- a parallel renderer, dashboard, server, Companion UI integration, hosted/multi-user surface, or
  Product/Runtime authority;
- repairing evidence linkage, changing scorers, retaining observations automatically, or changing
  the accepted 365-day retention policy;
- implementing the already-ratified CKM Evidence Profile Phase 1 work inside Direction B.

## Design provenance and authority

The owner Gate A receipt is
[#3972 comment 5066973510](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3972#issuecomment-5066973510).
It authorizes bounded Direction B design and feature breakdown only.

The Claude Design Direction B export supplied to the coordinator on 2026-07-24 is supporting design
input. The prototype HTML and generated `support.js` are not production dependencies and must not
be copied. This merged specification, current owner contracts, and the live Issue/PR chain are
authoritative when design prose and repo truth differ.

On 2026-07-30 the owner rejected the delivered portfolio page as a cockpit because its raw
measurement, evidence, and hazard detail created information overload. The owner directed the
implementation to follow the Claude Design handoff for visual hierarchy and interaction decisions,
while allowing the repo-owned measurement semantics to differ. This is an owner-authorized
presentation correction, not a new CKM authority class or measurement redesign.

## Owner-readable portfolio amendment (CKM-DB-OWNER-READABLE)

The cockpit start page is a decision-overview surface for one owner. Its first screen must make four
things understandable without requiring the owner to learn CKM field names:

1. whether the projection is usable now;
2. where the available evidence shows progress or change;
3. where evidence is missing, stale, incomplete, or otherwise needs attention;
4. which caveats materially limit the overview.

“Progress” means a descriptive change in retained CKM evidence or assessment coverage. It never
means product quality, delivery velocity, priority, causal improvement, or a CKM-authored judgment.
When no compatible comparison exists, the cockpit says that no change view is available and still
renders the current overview.

### Portfolio information budget

The portfolio start page follows the Claude Design handoff's hierarchy:

1. one short non-authority banner;
2. one human-readable trust summary, with technical generation identity behind disclosure;
3. three compact cards in one responsive grid:
   - **What changed** — at most five plain-language comparison facts;
   - **Where evidence needs attention** — at most five capability or portfolio facts, selected
     without an authoritative rank and ordered deterministically;
   - **Read with care** — at most three material caveats;
4. compact filters;
5. a collapsed capability overview;
6. optional detail, provenance, legend, current gaps, proposal drafts, and raw evidence.

No portfolio card may contain a raw digest, public ID, database/schema term, command line, full
watermark set, citation list, proposal body, seven-dimension vector, or unbounded findings list.
Those values remain available in the generated artifact through native disclosure or capability
detail so auditability is preserved.

The “Where evidence needs attention” card is not a leaderboard. If more than five capabilities
match, the card reports the total and shows the first five in stable capability-tree order with an
explicit “not ranked” label and a disclosure to all matching rows. Color may reinforce a state but
must never be its only label.

### Human-readable vocabulary

Level-zero copy uses owner language first. Internal codes may appear only in expanded technical
detail.

| Internal state | Portfolio wording |
| --- | --- |
| complete, fresh projection | Ready to inspect |
| usable projection with stale or missing assessment evidence | Usable with limitations |
| capture refused or incomplete | Overview unavailable |
| compatible retained pair | Changes since the previous observation |
| `insufficient_retained_samples` | No previous comparable observation yet |
| incompatible or unavailable comparison input | Change view unavailable; current overview unaffected |
| evidence gap | Evidence missing |
| stale assessment | Assessment older than its evidence |
| low confidence | Limited supporting evidence |
| unassessed | Not assessed |

Typed codes, exact timestamps, digests, watermarks, and recovery commands remain in the expanded
technical details and deterministic source HTML. Refusal states stay explicit and fail closed; only
their first-line explanation is translated into owner language.

### Portfolio versus capability detail

Each collapsed capability row shows:

- the capability name;
- one short descriptive status sentence;
- zero or more text labels for changed, stale, missing-evidence, limited-evidence, or not-assessed
  states;
- a disclosure control for the existing measurement vector and evidence.

The collapsed row does not show the seven-cell metric matrix, raw scalar values, maturity-like
bands, public IDs, node-state fields, citation counts, or proposal drafts. Expanded capability
detail retains the complete deterministic evidence and measurement content required by
`INV-DB-7`.

The existing subsystem evidence-count section, full interpretation-hazard list, current-gaps list,
proposal drafts, legend, and provenance footer are supporting detail. They must not precede or
visually compete with the three owner cards.

### Owner-readable amendment acceptance

- [x] The first viewport follows the handoff hierarchy and presents the trust summary, three compact
  owner cards, filters, and the beginning of the collapsed capability overview without a raw-detail
  section intervening.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_prioritizes_owner_readable_portfolio_over_raw_detail`
- [x] Each owner card obeys its bounded information budget, uses plain-language state copy, and
  exposes overflow or technical identity only through disclosure.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_owner_cards_are_bounded_and_human_readable`
- [x] Collapsed capability rows omit raw metrics and identifiers while expanded source content
  preserves the complete vector, evidence, findings, comparison slice, and proposal draft.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_progressive_disclosure_preserves_audit_detail`
- [x] Comparison-unavailable, stale, incomplete, empty, and source-unavailable states have concise
  owner wording without weakening the existing typed refusal or deterministic rendering contracts.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_owner_copy_preserves_refusal_semantics`
- [x] A generated real-store artifact is visually checked at desktop, narrow viewport, 200% zoom,
  JavaScript-off, and print/PDF against the Claude Design portfolio/detail hierarchy.
  Verify: durable screenshots plus a manual visual receipt on the governing implementation Issue

## Live reconciliation ledger

| Claude decision | Current source anchor | Resolution | Reason |
| --- | --- | --- | --- |
| Enhanced local generated HTML | `app/builderops/ckm/overview_html.py :: render_overview_html`; `app/builderops/cli.py :: ckm_overview` | Keep, refine | Add opt-in `ckm overview --cockpit`; extend `render_overview_html(..., cockpit=...)` and `write_overview_html(..., cockpit=...)`. Do not add a sibling cockpit renderer. The default call remains Direction A compatible. |
| Preserve Direction A visual language and scalar | `docs/CKM_EVIDENCE_PROFILE/README.md :: INV-EP-2`; `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md` | Refine | Preserve the layout language, but sequence behind Evidence Profile Phase 1 and never restore or contractually depend on `min`, maturity bands, or aggregate colour. |
| Newest compatible retained pair | `app/builderops/ckm/metrics.py :: MetricRetentionStore`; `app/builderops/ckm/comparison.py :: compare_retained_observations` | Refine | Select exactly the newest two active records by `(retained_at DESC, sample_id DESC)`, then reverse that selected pair to chronological `(older, newer)` order for O1b so a signed delta is newer minus older. Compare those IDs once. Fewer than two, unavailable input, expiry/tamper, or incompatibility produces a typed visible refusal. Never search older rows. |
| Pairwise delta copy | `docs/CKM_MEASUREMENT_AND_ACCESS/COMPARE_COMPATIBLE_OBSERVATIONS.md` | Keep | Render only O1b component-wise deltas and the exact non-trend disclaimer; preserve input IDs/digests, provenance, freshness, limitations, and tagged state transitions. |
| Broad banned-language scan | Existing Direction A prose, exact disclaimer, and cited source text | Refine | Test only new renderer-authored interpretation/proposal regions. Exempt the exact required disclaimer. Never scan citations, capability definitions, finding statements, or legacy Direction A copy as if they were generated claims. |
| “Scorer blind spot” dead-dimension diagnosis | ADR-0057 projection posture; Evidence Profile known substrate defects | Reject as diagnosis | Render only: “Snapshot-wide zero: this dimension is 0.00 for every assessed capability in this snapshot. CKM cannot determine whether that reflects missing evidence, current metric coverage, or portfolio state.” |
| Progressive filters | `tests/builderops/ckm/test_overview_html.py :: test_no_scripts_or_external_references`; Direction A static contract | Keep, narrow | Cockpit mode may contain exactly one inline script. Full rows and trust/gap content are server-rendered. Controls begin disabled; the script enables controls and toggles row `hidden` state/count text only. JS-off leaves all content usable and explains why filtering is unavailable. |
| Print expands disclosure content | Native `<details>` in `overview_html.py` | Refine | `@media print` overrides the user-agent closed-details rule with `details > :not(summary) { display:block !important; }`, forces filtered rows visible with `[hidden] { display:block !important; }`, and hides controls. CSS does not claim to mutate `open`. |
| Draft proposal actions | ADR-0057; `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: I-MA8` | Keep, narrow | Emit inert deterministic text only, bound to capability public ID, snapshot digest, exact watermarks, and verbatim finding/evidence source. Include “Draft only — not an Issue contract, priority, decision, or ready work.” No clipboard/network/write/prefill. |
| Recovery commands from prototype | Current Click commands `ckm overview`, `ckm measure --retain`, `ckm compare --sample-id` | Refine | User-facing recovery text may name only commands proven by CLI tests. `--cockpit` is a future contract owned by the framing slice. Invented `ckm observe`/capture-limit commands are forbidden. |
| Exactly one script | Direction A no-script acceptance; owner Gate A | Keep as smallest amendment | The default overview stays script-free. Cockpit mode amends the presentation contract once, solely for local filtering, without changing CKM authority or adding persistence/network behavior. |

## Information architecture

The output order is fixed. The owner-readable amendment supersedes the earlier placement of
unbounded hazards, gaps, proposals, and raw capability measurements on the portfolio level:

1. projection/non-authority banner;
2. cockpit header and human-readable trust summary;
3. bounded “What changed”, “Where evidence needs attention”, and “Read with care” cards;
4. disabled-by-default filter controls and disclosure count;
5. collapsed capability overview;
6. disclosed capability measurements and evidence;
7. supporting interpretation hazards and unfiltered current gaps;
8. inert proposal drafts;
9. technical provenance with generation time, state identity, digest, and sorted watermarks.

Capability detail order remains the deterministic `_forest` order: case-folded capability name and
stable ID within each parent, with damaged cycles/orphans rendered as additional roots. Findings,
evidence, watermarks, proposal drafts, comparison components, and refusal detail keys use explicit
stable sort keys; SQLite row order and mapping insertion order are never accepted as UI order.

## Refusal, degraded, and empty states

| State | Required presentation |
| --- | --- |
| CKM store missing, old, unsupported, over-bound, or changes during capture | CLI fails closed before writing output, using the current projection-capture refusal; no partial cockpit file is eligible. |
| Complete snapshot with zero capabilities | Render the full shell, trust strip, “No capabilities in the CKM store”, empty gaps/proposals, and provenance footer. |
| Assessment unavailable or stale | Preserve unavailable-vs-zero and stale markers; no generated diagnosis or numeric coercion. |
| Retention database absent/incomplete | Render comparison unavailable with typed code `source_unavailable`; do not create or initialize the sidecar. |
| Fewer than two active retained samples | Render `insufficient_retained_samples` with observed count; no comparison. |
| Newest two records incompatible | Render the exact O1b incompatibility code and sorted mismatched fields; state that older rows were not searched. |
| Selected input expired, pruned, deleted, corrupt, or tampered | Render the typed O1b refusal without partial deltas; do not search older rows. |
| Compatible pair with tagged state transition | Render both tagged states and no numeric delta unless both endpoints are measured numbers. |
| No findings / no proposals | Render explicit empty text; do not invent generic work. |
| JavaScript unavailable or blocked | All rows, details source content, trust, comparison/refusal, gaps, proposals, and footer remain in HTML. Controls remain disabled and `<noscript>` explains that all rows are shown. |
| Print while rows are filtered or details are closed | Print CSS makes every row and disclosure body visible; interactive controls are omitted; trust/refusal/provenance remain. |

## Cross-Task Invariants / Interaction Safety

- **INV-DB-1 — projection-only authority.** Every cockpit output says it is derived and
  non-authoritative. Nothing in the renderer, script, proposal text, or print path can rank, gate,
  prioritize, decide, score agents, predict, or write to an authority surface.
- **INV-DB-2 — one captured snapshot.** Trust, hazards, map, gaps, and proposals derive from the same
  bounded `CkmProjectionBatch` and state identity. No section re-queries mutable CKM state.
- **INV-DB-3 — Evidence Profile precedence.** Direction B begins only after CKM Evidence Profile
  Phase 1 is delivered. It consumes the per-dimension vector/tri-state/count view and never reads the
  cross-dimension aggregate into a render surface.
- **INV-DB-4 — exact pair, chronological comparison, no fallback.** Comparison selects exactly the
  newest two active retained records, orders that selected pair as `(older, newer)` for O1b, then
  invokes O1b once so a signed delta is newer minus older. Any refusal is rendered honestly; no
  older compatible pair is searched.
- **INV-DB-5 — no interpretive laundering.** New renderer-authored interpretation is descriptive and
  caveated. Source text is labeled/cited, not rewritten into a stronger claim.
- **INV-DB-6 — one bounded script.** Cockpit HTML contains exactly one inline script, used only to
  enable controls, evaluate already-rendered filter tokens, toggle capability-row `hidden`, and
  update disclosure counts. It cannot fetch, persist, generate content, mutate gaps/trust/proposals,
  or attach inline event handlers.
- **INV-DB-7 — JS-off and print completeness.** Filtering is optional enhancement. The source HTML
  and printed artifact always contain every capability, detail body, gap, refusal, and draft.
- **INV-DB-8 — proposal non-decision.** Every draft binds the snapshot digest/state identity, exact
  sorted watermarks, capability public ID, and verbatim source finding/evidence. Every draft carries
  the non-decision disclaimer and no closing keywords, labels, priority, or GitHub URL.
- **INV-DB-9 — deterministic bytes.** Identical explicit generation time, projection batch,
  comparison/refusal, and renderer version produce byte-identical HTML. Volatile current time is
  never read inside helpers after the render context is built.
- **INV-DB-10 — real command honesty.** Recovery copy is centralized and tested against Click help;
  future flags appear only in the slice that implements and tests them.

### Partial-failure paths

- Evidence Profile is not delivered: every Direction B child remains dependency-blocked; no agent
  may claim a cockpit slice against the contradictory scalar/band surface.
- Trust/framing merges but hazards do not: cockpit mode still renders a complete non-authoritative
  page with no invented hazard block; the parent remains open.
- Hazards merge but comparison does not: the page states comparison is not yet supported rather than
  deriving deltas locally.
- Comparison inputs exist but O1b refuses: the typed refusal is the whole comparison result; map,
  gaps, and trust remain usable.
- Filtering script is blocked: all rows remain visible, controls remain disabled, and the gaps panel
  is unchanged.
- Proposal generation has no eligible finding: the section is explicitly empty; it never drafts
  work from a score alone.
- Print support lands before later content changes: the terminal print slice is last and must be
  rerun after every preceding child; parent acceptance rejects a PDF missing any final section.
- A later child fails after earlier merges: prior outputs stay inert and non-authoritative; no task
  marks the parent accepted or promotes owner docs independently.

## Implementation tasks and execution order

Live file ownership proves a serial chain is cheaper than parallel delivery: all six slices integrate
through `app/builderops/ckm/overview_html.py` and
`tests/builderops/ckm/test_overview_html.py`.

0. External prerequisite — deliver CKM Evidence Profile Phase 1.
1. [Establish Trust and Portfolio Framing](ESTABLISH_TRUST_AND_PORTFOLIO_FRAMING.md)
2. [Surface Interpretation Hazards Honestly](SURFACE_INTERPRETATION_HAZARDS_HONESTLY.md)
3. [Render Compatible Observation Comparisons](RENDER_COMPATIBLE_OBSERVATION_COMPARISONS.md)
4. [Filter the Capability Map Honestly](FILTER_CAPABILITY_MAP_HONESTLY.md)
5. [Generate Governed Proposal Drafts](GENERATE_GOVERNED_PROPOSAL_DRAFTS.md)
6. [Support Deterministic Print Output](SUPPORT_DETERMINISTIC_PRINT_OUTPUT.md)

## Capability acceptance ledger

- [x] Owner Gate A records GO for bounded Direction B design and feature breakdown.
  Verify: [#3972 comment 5066973510](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3972#issuecomment-5066973510)
- [x] CKM Evidence Profile Phase 1 is delivered before Direction B implementation begins.
  Verify: closed Evidence Profile parent/children plus a terminal real-store receipt at `docs/CKM_EVIDENCE_PROFILE/README.md :: Verification and acceptance path`
- [x] All six child contracts pass their named tests, current-SHA CI, and local review gate.
  Verify: child PR delivery receipts linked from parent [#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080)
- [x] The finished cockpit answers the four fixed questions without ranking, causality, authority, or mutation.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_answers_fixed_owner_questions_without_authority`
- [x] O1b comparison and all refusal states are exercised through the production CLI/render call site.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_cli_renders_comparison_and_refusal_states`
  in completion issue [#4222](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4222), then its
  merged delivery receipt on parent [#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080)
- [x] JS-off and print receipts prove full-content preservation.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_progressive_enhancement_keeps_full_source_content`; manual PDF receipt on parent [#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080)
- [x] No owner doc claimed Direction B was supported before all child and parent acceptance checks
  passed; this reconciliation now records the accepted truth.
  Verify: post-merge owner-doc receipts on every child, independent parent acceptance, and final
  promotion diff at `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`

## Verification, validation, and owner-doc promotion

Each child ran its exact `Verify:` targets, the full focused CKM suite, `ruff check app tests`,
`mypy app`, current-head CI, and the independent local review gate. Completion issue
[#4222](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4222) and
[PR #4224](https://github.com/RasmusTho/agentic-pkm-mvp/pull/4224) added the protected
production-CLI comparison/refusal proof. Parent
[#4080 acceptance](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080#issuecomment-5102696743)
verified the child ledger, deterministic artifact/print evidence, exact merged-main authority, and
owner-doc posture. Its
[closure receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080#issuecomment-5102745391)
is the terminal acceptance boundary.

## Relationship to GitHub issues

The serial execution chain is terminal:

1. Parent validation hub [#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080) —
   accepted and closed; never a pickup Issue.
2. CKM-DB-01 [#4081](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4081) —
   delivered and closed.
3. CKM-DB-02 [#4082](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4082) —
   delivered and closed.
4. CKM-DB-03 [#4083](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4083) —
   delivered and closed.
5. CKM-DB-04 [#4084](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4084) —
   delivered and closed.
6. CKM-DB-05 [#4085](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4085) —
   delivered and closed.
7. CKM-DB-06 [#4086](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4086) —
   delivered and closed.

GitHub is the live backlog and validation surface. These docs own stable target-state intent,
invariants, and task shape; Issue labels and receipts own current pickup/delivery truth.

## Source docs

- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_HTML_PROJECTION.md`
- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/CKM_MEASUREMENT_AND_ACCESS/COMPARE_COMPATIBLE_OBSERVATIONS.md`
- `docs/CKM_EVIDENCE_PROFILE/README.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`
