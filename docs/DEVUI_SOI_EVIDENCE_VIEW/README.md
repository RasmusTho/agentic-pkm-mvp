State: Accepted target-state Builder System specification (2026-08-09). The bounded SoI Evidence
View proof composer and immutable proof fixture are delivered by issue #4710; no UI, durable
hierarchy, or owner-outcome writer is delivered by this document.
Doc role: Read-model/view specification and implementation boundary for a read-only devUI SoI
Evidence View v0.
Authority: `docs/DEVUI.md` owns the owner experience. Product and architecture owner documents
retain the facts this view reads: SoI boundary and intent, SBS, capabilities, requirements,
contracts, implementation, tests, operations, and owner outcomes. This document owns only the
target read-model boundary, its terminology, and its proof gate.
Owner: Builder System governance
Temporal class: strategic
Review cadence: event-driven
Source of truth: This document for the target projection contract; the linked source owners for
every projected fact. `ARCHITECTURE.md` and `STATUS.md` win for shipped current reality.
Last reviewed: 2026-08-09
Last verified against: `origin/main` `87e137aad63d2c0858801c05e443ef5fa2d5c35b`,
`docs/DEVUI.md`, `docs/architecture/system-context-overlay.md`,
`docs/architecture/SBS_OPERATING_MODEL.md`, `docs/REQUIREMENTS_INDEX.md`,
`docs/CAPABILITY_CONTRACT_MODEL.md`, and `docs/DEVUI_BUILDER_SYSTEM_CONTROL/README.md`

# devUI SoI Evidence View v0

## Purpose and scope

The SoI Evidence View helps the Product Owner understand the evidence posture of the **Mimer
Product/Runtime System of Interest (SoI)** without reconstructing it from documents, code, tests,
delivery systems, and receipts. It is an Overview lens in devUI: a read-time, rebuildable
composition and navigation surface, not a second system model.

This v0 scope is intentionally narrower than the phrase “the whole Yggdrasil ecosystem”. The
current owner-declared SoI is Mimer Product/Runtime in
`docs/architecture/system-context-overlay.md`. The Builder System is an enabling system outside
that Product/Runtime SoI. A future Yggdrasil constituent or system-of-systems denominator needs
its own owner-declared boundary and must not be inferred from this view.

The view supports a complete *account* only relative to a named denominator; it does not claim
that all possible capabilities, requirements, or constituents are known.

## Responsibilities and source ownership

The view reads a federated chain. It does not centralize the source material in a new graph,
registry, lifecycle, or maturity store.

| Responsibility | Owning source class | View responsibility |
| --- | --- | --- |
| SoI intent and boundary | Product/kernel and system-context owner docs | Cite the named SoI scope, exclusions, and horizon. |
| System/SBS decomposition | SBS and architecture owner docs | Preserve typed boundaries, allocation, and current/target status. |
| Capability/sub-capability | Capability owner/specification | Preserve the source-owned identity and explicit parent/child relation. |
| Requirements, NFRs, assumptions, constraints | Product or capability owner docs | Show coverage or its absence; `REQUIREMENTS_INDEX` routes but never becomes requirement authority. |
| Architecture and contracts | Architecture, contract, and ADR owners | Link only explicit, source-owned allocations and contracts. |
| Implementation | Exact Git/configuration revision | Bind realization claims to a revision, never a filename or name match alone. |
| Verification and evidence | Test contracts, CI, and verification receipts | Keep evidence identity, result, watermark, and limitation visible. |
| Delivery and operations | GitHub, Git, CI, release, and operations receipts | Keep merge, delivery, availability, and health as distinct facts. |
| Owner outcome | A future owner-receipt authority | Render `tried` and `accepted` as unsupported or missing until that authority exists. |

The chain rendered by the view is:

```text
SoI intent
→ system/SBS decomposition
→ system capability/sub-capability
→ requirements/NFRs/assumptions
→ architecture/contracts
→ implementation
→ tests/evidence
→ delivery/operations
→ owner validation/acceptance
```

No row above requires a new document by itself. A missing responsibility is a gap to render and
route to its owner; it is not permission for the view to copy or invent that responsibility.

## Identity, denominator, and claim rules

### Source-owned subjects and links

Every displayed subject and claim must carry the stable identity, category, source reference, source
revision or watermark, and authority class supplied by its owning source. This View defines no
repository-wide subject-kind enumeration. Its explanatory language — SoI scope, SBS boundary,
runtime capability, requirement, contract, implementation, evidence, delivery receipt, and owner
outcome — never renames, normalizes, or gives an identifier to an owner artifact.

`capability` is not a universal implicit type. An SBS boundary, CKM registry entry, and callable
runtime capability retain their source-specific meaning. Name, path, temporal proximity, or prose
similarity never creates a relation. A parent/child or allocation relation is usable only when an
existing owner source asserts it explicitly; it neither transfers evidence nor implies parent
maturity.

### Completeness denominator

Any use of **complete**, **partial**, or a count must name:

- `scope_ref` and owner;
- `denominator_source_ref`, revision/watermark, and observation time;
- expected subject/child set and required responsibility set;
- claim horizon; and
- excluded, unknown, unread, unavailable, refused, and not-applicable material.

`complete` is illegal when the denominator or expected child set is unknown. An unknown or omitted
required child prevents a parent-completeness claim. Document-index coverage proves discoverability
only; it does not satisfy a missing responsibility.

### Claim horizon and source state

Each claim independently records one horizon: `current`, `target`, `advisory`, or `historical`.
Target evidence never satisfies a current-state claim. The view carries the existing independent
source-state axes:

| Axis | Required semantics |
| --- | --- |
| Availability | `available`, `unavailable`, `refused`, or `unsupported` |
| Freshness | `fresh`, `stale`, or `unknown` |
| Coverage | `complete`, `partial`, `unread`, `missing`, or `not_applicable` |
| Cardinality | `nonempty`, `measured_empty`, `not_measured`, or `not_countable` |
| Linkage | `linked`, `unlinked`, `not_assessed`, or `not_applicable` |

`missing` means required material was successfully checked and absent. `unavailable`, `refused`,
and `unread` cannot be rendered as zero, empty, or missing. `measured_empty` requires a successful
bounded read with its scope and watermark. A provider withdrawal withdraws only the claims it owns;
it must remain visible rather than being replaced by an inferred value.

## Evidence vector, not a score

The owner sees an evidence vector across the responsibility chain: intent, allocation,
requirements, design/contracts, realization, verification, delivery, operational availability,
ready-to-try, owner-tried, and owner-accepted. Each dimension exposes its sources, source states,
limitations, and explicit links.

There is no scalar SOI maturity score, arithmetic parent roll-up, traffic-light summary, ranking,
or score-derived work selection. CKM may be one cited evidence provider, but its aggregate cannot
control the View’s scope, order, colour, priority, or next action. A displayed aggregate from any
source is progressive diagnostic detail only and never replaces the vector.

## devUI experience mapping

The SoI Evidence View is a lens in **Overview**, not a fourth top-level mode, Focus subject, or
Builder System Control scope.

| devUI zone | SoI Evidence View contribution |
| --- | --- |
| Now | The selected SoI scope, source health, evidence vector, explicit gaps, and work that existing authorities show as safely continuing or blocked. No score chooses the order. |
| Needs you | Only a named owner authority and an existing lawful decision route can surface here. Missing requirements or owner acceptance are gaps, not automatically owner actions. |
| Ready to try | Only receipt-backed delivered results that the owning delivery path says are ready for evaluation. Neither merge nor evidence coverage implies trial or acceptance. |

Drill-down preserves the selected typed subject and its sources. A selected capability may link to
Focus. Builder System concerns navigate to the separate Builder System Control lens. Navigation is
not a data join: Product/Runtime SoI and Builder System Control do not share denominator, primary
identity, ownership, or maturity semantics.

Normal, empty, and degraded states are first-class. The empty state must state the selected scope
and whether it is measured empty, not measured, or unavailable. The degraded state keeps valid
claims visible, withdraws invalid dependent claims, names the failed source and watermark, and
never redirects the owner to a raw provider UI as the normal recovery path.

## Non-authority boundary

This View MUST NOT:

- persist a hierarchy, capability registry, evidence graph, maturity value, task, session, or
  lifecycle state;
- infer relations, create work, write source documents, or alter delivery/owner outcomes;
- conflate Product/Runtime SoI scope with Builder System Control scope;
- treat indexed documentation, code presence, merge, deployment, or Ready to try as owner
  acceptance; or
- use an aggregate to prioritize, colour, sort, scope, or recommend work.

It may link to the existing governed route that owns a gap or decision. That link is not command
admission and does not add a devUI authority.

## Read-only proof gate before implementation breakdown

Before broad feature breakdown or visual work, one bounded proof issue must define an immutable
source manifest and run against its exact source revisions. The manifest must name:

- one existing owner-declared Mimer Product/Runtime SoI scope;
- one current claim and one target claim, each with an owning source and revision;
- two contrasting source-owned capability specifications, one current/delivered and one
  target/planned, only when their owner docs expose the necessary identity and horizon; and
- every explicit relation used by the proof, or an explicit `unlinked` result where no source owns
  that relation.

The proof MUST NOT assume that a SoI scope, SBS boundary, CKM entry, and capability specification
form a hierarchy. Its first positive result is allowed to be an honestly **unlinked** comparison;
no source relation means no joined maturity claim. It creates no UI, persistence, generalized
hierarchy, or owner-outcome writer.

The proof PR must retain the manifest, exact source revisions, expected read result, and test
output as its evidence artifact. Its governing Issue must name executable `Verify:` targets
equivalent to the following; tests may use fixtures but must exercise the production read composer:

The proof must demonstrate at least these falsification cases:

1. `test_unknown_denominator_cannot_render_complete`;
2. `test_indexed_document_does_not_satisfy_missing_nfr_responsibility`;
3. `test_target_claim_never_counts_as_current_evidence`;
4. `test_unavailable_refused_stale_or_unread_never_renders_as_zero_or_measured_empty`;
5. `test_unknown_expected_child_prevents_complete_parent_coverage`;
6. `test_unowned_relation_remains_unlinked`;
7. `test_aggregate_cannot_control_order_color_scope_priority_or_next_action`;
8. `test_delivery_availability_ready_to_try_trial_and_acceptance_remain_distinct`; and
9. `test_read_has_no_task_graph_lifecycle_registry_or_persistence_write`.

Only a proof with the named manifest, expected result, and passing `Verify:` targets may be
promoted to broader feature breakdown. Owner-tried and owner-accepted remain deliberately
unsupported until a separately authorized receipt model exists.

## Current-to-target status

This target contract is accepted documentation only. The delivered `devui.composition.v1` remains a
per-request projection over its existing providers; it does not provide whole-SoI coverage. The
bounded SoI Evidence View proof composer, source manifest, and proof fixtures are delivered through
the governing implementation lane for issue #4710. A UI, visual handoff, generalized hierarchy, and
any owner-outcome receipt authority are not delivered.

## Sources and routing

- `docs/DEVUI.md` — owner experience, three zones, delivery-fact separation, and projection boundary.
- `docs/architecture/system-context-overlay.md` — current Mimer SoI boundary and Builder System
  enabling-system separation.
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` and `docs/architecture/SBS_OPERATING_MODEL.md` — target SBS
  and Builder/Product boundary.
- `docs/CAPABILITY_CONTRACT_MODEL.md` — runtime capability contract meaning.
- `docs/REQUIREMENTS_INDEX.md` — requirements coverage routing and declared gaps.
- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md` and
  `docs/DEVUI_BUILDER_SYSTEM_CONTROL/README.md` — source-state semantics and sibling-lens boundary.
- BuilderOps handoff `awl_20260809190530_fbe61638` and accepted promotion
  `prom_20260809190541_add4a40b` — research provenance only, not source authority.
