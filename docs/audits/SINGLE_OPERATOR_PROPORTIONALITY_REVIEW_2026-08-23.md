# Single-Operator Proportionality Review

State: Advisory architecture/process review (2026-08-23). Non-normative and subordinate to
`docs/DOCS_INDEX.md`, `docs/DESIGN_PRINCIPLES.md`, current owner contracts, implementation evidence,
and live GitHub state. This review authorizes no product implementation, feature breakdown, Issue,
PR, label, Project, branch, reset, cleanup, or lifecycle mutation.

Doc role: Reference (audit snapshot)

Authority: Evidence-based review of repository skills, process contracts, current `origin/main`,
read-only GitHub state, and preserved GAF-05 local repair evidence.

Owner: Architecture research / Builder System process stewardship. Product/runtime authority remains
with the existing owner documents and contracts.

Temporal class: snapshot

Source-of-truth boundary: `origin/main` at `f85011fd0a8d2fc86dced8a0c7c1c95a916d58b4`, verified by
`git ls-remote origin refs/heads/main` at `2026-08-23T19:32:01Z`. Local time was Europe/Stockholm.

## tcd_plan

```yaml
tcd_plan:
  task_summary: "Review skills and delivery process for proportionate single-user note-management design"
  assumptions:
    - "P1 single-operator is the default product profile unless evidence establishes another profile"
    - "The GAF-05 local repair line is evidence only and is not PR or main authority"
    - "GitHub and worktree state remain read-only"
  complexity: very_high
  risk: high
  verification_difficulty: hard
  human_review_burden: high
  defect_blast_radius: high
  budget_pressure: medium
  execution_context: coordinator_only
  issue_local_helper_budget: 0
  context_cost:
    measurement: proxy
    input_tokens: "unknown(no runtime telemetry)"
    agent_starts: 0
    context_pack_bytes: "unknown"
    compactions: 1
  recommended_capability:
    workflow_or_skill: "learning-retrospective -> architecture-research"
    model_family: "architecture-grade"
    reasoning_effort: high
    tools: "git, gh REST, rg, read-only worktree inspection"
    github_context_required: true
  cheapest_acceptable_path: "one sequential coordinator with bounded evidence reads and a single audit artifact"
  escalation_triggers: "new authority store, durable journal, multi-writer state, exact-once cross-store claim, adversarial threat, or regulated RPO/RTO requirement"
  deescalation_triggers: "single writer, local storage, checksum/readback, manual recovery, and a bounded failure cost"
  review_gate: "recheck exact origin/main SHA, retain file/doc/Issue/PR anchors, and confirm no mutation"
```

## Executive conclusion

The reasonable design level now is **P1: a single-operator, local-first note system with one
serialized writer and explicit, inspectable recovery**. For cold-tier archival, the capability is:

```text
hot note -> atomic local write -> owner-native locator -> copy to cheap HDD
          -> checksum/readback -> durable receipt -> retire hot copy only after proof
          -> on-demand restore by locator and checksum
```

This is enough to protect one person's data against ordinary local failures and operator mistakes.
It needs a real atomic write, a checksummed copy, readback before source retirement, a fail-loud
last-copy rule, a simple backup/restore path, and a recovery procedure a human can understand.

HKA in-place disaster recovery is a separate capability. It should not be silently imported into a
cold-tier move merely because both mention recovery, receipts, or governed writes. The P1 cold-tier
kernel should not acquire multi-writer conflict reconstruction, distributed authority, exact-once
semantics across stores, enterprise disaster recovery, or adversarial journal-tamper resistance
without concrete evidence that the product profile changed.

The HKA review findings on PR #5094 were locally correct against the HKA contract. The process
failure was upstream: the capability was allowed to cross from a simple local archival operation
into an authority/replay/recovery mechanism without a profile and complexity-budget checkpoint.
The preserved GAF-05 line is therefore strong evidence for rescoping, not a reason to publish the
unpublished repair line.

## Evidence boundary

| Evidence | Fresh fact and anchor |
|---|---|
| Current main | `f85011fd0a8d2fc86dced8a0c7c1c95a916d58b4`; remote ref read at `2026-08-23T19:32:01Z`; latest commit describes verified delivery after PR #5093. |
| Product posture | `docs/DESIGN_PRINCIPLES.md:124-137` names “Single-Operator Scale”, one human on trusted personal infrastructure, and says enterprise HA, horizontal scaling, multi-tenancy, zero-trust internal auth, and pluggable providers require explicit demand. |
| Archival owner contract | `docs/GOVERNED_ARCHIVAL_FLOW/README.md:104-126` requires identity independent of location, no authority fork, verification before retirement, access/restore gates, liveness, additive rollout, and no derived authority. |
| Existing causal audit | `docs/audits/GOVERNED_ARCHIVAL_FLOW_2026-08-22.md:430-540` explains how audio-specific source anchors and bounded decomposition produced a narrow implementation; it identifies the missing capability-discovery gate. |
| Parent/task scope | Issue #5062 is open with the cross-class validation contract; Issue #5067 is open and asks for HKA recovery over the governed-write seam. Both were read through GitHub REST. |
| Review head | PR #5094 is open at `015c34b57537d0de57f7c85bdf39e10b58f4e1f3`, base `f85011fd...`, 649 additions and 6 deletions across 5 files. It remains non-authoritative for main. |
| Review findings | PR #5094 review `5001994105` has three P1 findings and one P2: constructible GOV binding, lost-receipt replay, missing production instantiation, and a second public adapter protocol. |
| Unpublished repair evidence | Preserved worktree `/Users/rasmusthornberg/code/.worktrees/agentic-pkm-mvp-5067` has PR head plus 14 local repair commits; `origin/main..local` is 19 files, 10,624 additions, 65 deletions. It was inspected read-only and not cleaned or reset. |
| Convergence packet | The local `docs/audits/2026-08-23-hka-recovery-convergence.md` records repeated mechanism-level P1 races across GOV authority, journals, aliases, receipts, generations, path identity, and crash ordering. Its local repair head is not PR/main authority. |
| Prior small-capability precedent | `.codex/skills/_shared/BUILDER_THREAD_CONTRACT.md:7-31` deliberately defines one serialized writer and explicitly excludes distributed locks, slot reservation, iCloud convergence, and filesystem recovery. `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md:15-27` shows multi-writer as an explicit later decision. |

## Product/scale profile and complexity budget

The profile is an admission control, not a claim that a future profile is impossible. Unknown
evidence is not permission to select the largest profile.

| Profile | Default facts | Escalation evidence | Design posture |
|---|---|---|---|
| **P1: single-user/local** | One owner; one serialized writer; trusted local host; hot storage plus cheap HDD; short outage acceptable; ordinary accidental loss and hardware failure are the main concerns; manual recovery is acceptable. | This is the current product posture in `DESIGN_PRINCIPLES.md`. | Simple local authority, atomic writes, checksum/readback, explicit receipts, fail-loud retirement, manual/on-demand restore. |
| **P2: small-team/local-sync** | Two or more independent writers, shared or synced vault, observed collision risk, or a recovery objective that requires stale detection. | A concrete second writer, collision incident, shared sync requirement, or measured RPO/RTO need. | Add stale detection, conflict copies, ownership of resolution, and bounded sync semantics. Do not infer distributed consensus. |
| **P3: multi-tenant/regulated/distributed** | Untrusted tenants, remote authority, legal retention, contractual RPO/RTO, high availability, adversarial tamper model, or multiple independent authority stores. | A named product requirement, incident, contract, or owner decision with measurable obligations. | Separate capability and contract for tenant isolation, distributed authority, immutable audit/DR, or adversarial integrity. |

### P1 complexity budget

P1 permits one local state owner, one writer boundary, one manifest/receipt representation, one
verified copy path, one retirement gate, and one human-readable restore procedure. A new authority
store, durable operation journal, distributed lock, cross-store exact-once claim, automatic conflict
reconstructor, or adversarial filesystem protocol consumes the budget and requires a profile review.

The budget is not an implementation prohibition. It is a stop signal when the mechanism grows faster
than the failure cost it protects against.

## Essential, optional, and future-scale

| Capability | P1 status | Reason |
|---|---|---|
| Atomic local write/rename | **Essential** | Prevents torn note files and is cheap to verify. |
| One serialized writer boundary | **Essential** | Makes local ordering and recovery understandable. |
| Owner-native locator | **Essential** | Location can change without changing note identity. |
| Copy to cheap HDD | **Essential** | Delivers the actual cold-tier value. |
| Checksum and readback | **Essential** | Detects incomplete or corrupt copies before retirement. |
| Durable manifest/receipt | **Essential** | Records locator, checksum, generation, and copy status; it is evidence, not a second authority. |
| Fail-loud last-copy retirement | **Essential** | Never delete the only verified copy. |
| On-demand restore and manual recovery runbook | **Essential** | Recovery must work without an autonomous recovery engine. |
| Periodic backup snapshot and restore drill | **Essential** | A backup that has never been restored is only an assumption. |
| Encryption at rest | **Optional P1** | Use when the actual host/storage threat justifies it; keep key ownership simple. |
| Pending-state doctor/read-only inspection | **Optional P1** | Useful operator ergonomics, but not a second recovery authority. |
| Multi-writer conflict copies and stale detection | **Future P2** | Requires a real second writer or sync collision. |
| HKA in-place recovery | **Separate optional capability** | Valuable only for a concrete HKA recovery requirement; not a cold-tier prerequisite. |
| Distributed authority and exact-once across stores | **Future P3** | Requires multiple authority stores and a measured obligation. |
| Automatic conflict reconstruction/AI merge | **Future P2/P3** | Manual owner resolution is safer until collision volume proves otherwise. |
| Enterprise DR/HA, multi-tenancy, regulated retention | **Future P3** | No current product evidence makes these defaults. |
| Adversarial journal-tamper protocol | **Future P3** | Ordinary checksums and backup integrity are enough for the current threat model. |

## Proportionate reference architecture

```text
human note
   |
   v
one local serialized writer
   |
   +--> atomic hot-file write + owner-native locator
   |
   +--> select eligible old representation
          |
          +--> write small manifest/status record
          +--> copy to HDD temporary path
          +--> checksum source and destination
          +--> read back destination and verify checksum
          +--> mark verified cold copy
          +--> retire hot copy only when another verified copy exists

restore: locator -> verified cold copy -> atomic hot restore -> checksum/readback -> receipt
         if proof is absent: stop, preserve copies, show a human-readable recovery action
```

The manifest may contain note identity, representation, locator, generation, checksum, source and
destination, status, and timestamps. It is a durable evidence record, not a new semantic authority.
The owner-native note store remains authoritative for note meaning. A failed copy remains pending or
failed and is visible; it is not silently retried through a hidden transaction engine.

Intentionally not built in P1: a central archive database, multiple authority stores, operation-token
issuance, replay journals, automatic conflict promotion, a distributed lock service, no-follow path
proof machinery, cross-store exactly-once guarantees, or a generalized HKA recovery state machine.

## GAF-01..04 disposition and HKA separation

| Area | Keep | Simplify or defer |
|---|---|---|
| GAF-01 | Contract boundary, opaque references, owner-native identity, no central archive authority. | Keep the vocabulary narrow; do not imply every future artifact needs a new kernel. |
| GAF-02 | Copy, verify, receipt, retirement gate, truthful pending/unavailable states, terminal liveness. | Prefer one local writer and a small manifest over a replay-safe transaction journal. |
| GAF-03 | Adapter/conformance shape where multiple real representations exist; modality neutrality. | Do not create adapters or four-way proof obligations without a second concrete source class. |
| GAF-04 | Separate source-class policy where consent/retention actually differs. | Keep it out of a simple note cold-tier path unless that policy is present. |
| GAF-05 | Treat HKA recovery as its own capability with its own contract, threat model, and budget. | Do not make in-place disaster recovery a hidden requirement of cold-tier archival. |
| GAF-06/07 | Optional compatibility and acceptance surfaces if the broad capability is deliberately retained. | Defer until a concrete P2/P3 trigger or an explicit owner decision exists. |

## Why the skills produced an enterprise solution

This was not caused by one careless implementation decision. The process composed several locally
reasonable safeguards without a product-profile gate.

1. `docs/DESIGN_PRINCIPLES.md` states the single-operator posture, but the intake contract did not
   require each capability to restate users, writers, failure cost, recovery objective, or threat
   model.
2. The GAF parent contract named a cross-class kernel, HKA/PDM/SIP/GOV seams, recovery, authority,
   and several future artifact classes. That wording made a general transaction mechanism look like
   the safe interpretation of a cold-tier need.
3. `feature-breakdown` correctly required independent child tasks, cross-task invariants, and
   per-task Verify targets. It did not require a first-producer/adjacent-capability census or a
   complexity budget before creating the child graph.
4. `issue-to-code` classifies system boundary, artifact, and environment, and elevates auth,
   security, data, migration, concurrency, and external APIs. It does not ask whether those risks
   are actually in the current product profile. Generic “governed write” language therefore made
   HKA replay and tamper concerns look mandatory.
5. `verification-and-closure` correctly protects data loss, authority, replay, concurrency, and
   false-green findings as P1-class risks. It has a low-convergence mechanism breaker, but after the
   breaker it routes to more mechanism analysis rather than a profile-boundary rescope.
6. The fresh-review rule and “no valid blocking P2” rule preserve correctness, but they also create
   a ratchet: every correct P1 requires a stronger mechanism unless a separate rule permits stopping
   the capability itself.
7. Source anchors and acceptance targets closed the implementation around HKA and governed-write
   semantics. They were precise about how to prove the chosen mechanism, not whether the mechanism
   belonged in the first product slice.
8. The Builder Thread precedent shows the missing alternative: one designated serialized writer,
   exact retry by request ID, and typed unavailability were enough for a bounded capability, while
   distributed locks, sync convergence, and filesystem recovery were explicitly out of scope.

The resulting process was good at preventing an unsafe enterprise mechanism from merging, but weak
at recognizing that the enterprise mechanism itself was the wrong slice for the product.

## Causal chain: contract to rework

```text
cross-class archival contract + HKA recovery wording
        |
        v
generic kernel and child decomposition
        |
        v
governed-write / replay / concurrency treated as capability baseline
        |
        v
high-risk classification (data, authority, replay, concurrency)
        |
        v
correct P1 findings: binding, receipt loss, CAS, path identity, journals, crash ordering
        |
        v
fresh mechanism reviews and local point fixes
        |
        v
no profile-boundary stop; new journals, aliases, grants, tokens, and race proofs
        |
        v
649-line PR head -> 14 unpublished repair commits / 10,624 local additions
```

This chain explains why the review findings were not “overly strict”. The strictness was applied
after the capability had already crossed its appropriate boundary.

## Why each HKA finding was protected, and where it stops being proportional

| Finding family | Why P1 was correct under HKA | Why it is not a P1 cold-tier prerequisite |
|---|---|---|
| Constructible GOV binding | A caller-controlled actor/action/resource token could authorize an HKA mutation. That is an authority bypass. | A local cold move can use the one serialized writer and a local operation receipt; it need not mint or validate a generalized GOV token. |
| Lost-receipt replay | Repeating a governed write after the receipt disappears can duplicate or corrupt a mutation. | A copy can be idempotent by destination identity/checksum and can fail closed before hot retirement; no cross-store exactly-once claim is needed. |
| Missing production seam | A test-only adapter does not prove the requested runtime capability. | It is a scope/contract issue for HKA, not evidence that cold-tier archival needs a recovery transaction engine. |
| Second public protocol | A kernel cannot consume an adapter that is outside its published protocol. | P1 can have one narrow adapter or one owner-native implementation; a broad protocol is not free value. |
| Equal/new-generation races | Concurrent HKA candidates can overwrite or lose a newer authoritative state. | One local writer removes the concurrent-writer premise; a checksum and generation in one manifest are enough for a first cut. |
| Symlink, alias, and path races | An attacker or concurrent mutation can redirect a privileged write. | These are future threat-model requirements absent from the trusted single-user profile; ordinary atomic paths and fail-loud checks cover the current failure model. |
| Receipt tamper/downgrade and read grants | HKA recovery must not turn weak evidence into authority or read sensitive material without a valid grant. | A local backup receipt is evidence for the owner, not a remote authorization system. Protect the file and document the trust boundary. |
| Journal namespace, loser/winner, and crash ordering | A durable recovery protocol must define every restart and replay transition. | P1 should avoid the durable journal mechanism; adding more proof to it is not simplification. |

## Stop-loss gate

The following gate belongs at capability admission and at review convergence:

1. Record the product profile, independent writer count, failure cost, recovery objective, threat
   model, and explicit out-of-scope list before decomposition.
2. Keep the existing low-convergence breaker: after one review round finds two P1s in the same
   stateful mechanism, or an adjacent P1 in that mechanism, stop ordinary point fixing.
3. Compare the mechanism to the recorded profile and complexity budget. If the repair requires a
   new authority store, durable replay journal, distributed lock, cross-store exact-once claim,
   automatic conflict reconstruction, or adversarial filesystem proof absent from the profile, stop
   the child capability and produce a bounded rescope receipt.
4. Preserve the P1 findings and their accounting. Do not downgrade them merely because the feature
   is being deferred; move them with the capability boundary.
5. Resume only from a new or amended contract that explicitly selects the larger profile and names
   its measurable obligation. A P2/P3 capability becomes a separate slice; it does not silently
   enlarge the P1 cold-tier slice.

## Research-question resolutions

### Which assumptions made overdesign rational?

The assumptions were implicit rather than evidenced: several authority stores, multiple writers,
crash/replay after a governed write, an adversarial or concurrently mutable filesystem, durable
operation identity, and a need for HKA in-place recovery. They are reasonable assumptions for a
regulated/distributed recovery system. They are not established for one person moving old notes from
hot storage to a local HDD.

### Which process surfaces lack early classification?

The missing classification is upstream of the existing risk routing. The Issue template, shared
Issue contract, architecture-research intake, feature-breakdown step 1, issue-to-code preflight,
and verification circuit breaker all lack the same small profile: user count, independent writers,
failure cost, recovery objective, threat model, and complexity budget. They should share one canonical
policy in `AGENTS.md`; the skills should reference it rather than duplicate it.

### How should the profiles escalate?

Use evidence, not vocabulary. “Governed write”, “replay”, or “concurrency” alone does not select P2
or P3. A second writer or observed collision selects P2. Multiple independent authority stores,
untrusted tenants, legal retention, contractual RPO/RTO, or adversarial integrity selects P3. The
architecture-research pass then defines only the invariants needed for that profile.

## Exact upstream proposals

These are proposed insertions only. They were not applied to `AGENTS.md` or any skill in this review.
The canonical policy belongs in `AGENTS.md`; the skills get thin routing references.

### 1. `AGENTS.md` — canonical policy

Insert after the current proportional-delivery/right-sizing guidance (`AGENTS.md:391-399`):

```text
**Product/scale profile gate.** Before architecture-research or feature-breakdown expands a
stateful capability, record `profile=P1|P2|P3`, user count, independent writer count, concrete
failure cost, recovery objective, and threat model. P1 is the default for the current
single-operator product: one local writer, trusted infrastructure, explicit integrity checks,
manual recovery, and no enterprise HA or distributed authority. Missing evidence is `unknown`, not
permission to select P2/P3. A new authority store, durable replay journal, distributed lock,
cross-store exactly-once claim, automatic conflict reconstruction, or adversarial filesystem
protocol that is absent from the profile is a stop-and-rescope trigger; preserve any P0/P1 finding
and its accounting. Use `docs/DESIGN_PRINCIPLES.md` as the product-profile authority and keep the
profile plus its complexity budget in the governing audit/spec/Issue.
```

Verify target: the proportional-delivery section contains all six profile fields, the P1 default,
the missing-evidence rule, and the explicit stop-and-rescope triggers; `DESIGN_PRINCIPLES.md`
remains the product authority.

```yaml
tcd_retrospective:
  change: "Add one canonical product/scale admission gate to AGENTS.md"
  causal_learning: "The existing risk gates protected a too-large mechanism but never challenged its profile"
  expected_benefit: "Stop enterprise expansion before child decomposition and repeated review repair"
  cost: "One required profile block per stateful capability"
  verification: "AGENTS.md contains the exact fields and stop triggers; no skill duplicates the policy"
  evidence: "GAF-05 PR head 649 additions; preserved local repair line 14 commits and 10,624 additions"
```

### 2. `architecture-research/SKILL.md` — intake reference

Insert after “When to trigger” and before “First context” (`architecture-research/SKILL.md:17-43`):

```text
### Product/scale admission

Before opening research questions, read the governing product profile and complexity budget. Record
`profile=P1|P2|P3`, users, independent writers, failure cost, recovery objective, threat model, and
explicit non-goals. Treat P1 as the null hypothesis for the single-operator product. Every P2/P3
assumption must have a concrete trigger; absent evidence excludes enterprise mechanisms from the
minimal kernel. If the proposed mechanism exceeds the profile or budget, stop and rescope the
capability before broadening the invariant set.
```

Verify target: every new research charter includes `Product/Scale Profile`, `Complexity Budget`,
`Escalation Evidence`, and `Out of Scope`; its RQs and MUST/GATE/DOCTOR kernel do not assume a larger
profile without an anchor.

```yaml
tcd_retrospective:
  change: "Make profile admission a required architecture-research intake step"
  causal_learning: "The prior audit found breadth discovery but not a scale/failure-cost decision"
  expected_benefit: "Reject unsupported P2/P3 assumptions before mechanism research"
  cost: "Small charter overhead; no extra agent or helper"
  verification: "Research charter has profile, triggers, budget, and explicit non-goals"
  evidence: "GAF causal audit docs/audits/GOVERNED_ARCHIVAL_FLOW_2026-08-22.md:430-540"
```

### 3. `feature-breakdown/SKILL.md` — boundary census

Insert after the concrete-boundary first step (`feature-breakdown/SKILL.md:197-230`):

```text
#### 1a. Write the product/scale and adjacent-capability census

Before creating child tasks, copy the governing profile and complexity budget into the parent
specification. Name the independent writers, actual failure cost, recovery objective, threat model,
and adjacent capabilities that are explicitly excluded (for example multi-writer sync, distributed
authority, or HKA in-place recovery). If a proposed child introduces a mechanism outside that
profile, stop at `enrich-docs` and return a rescope proposal; do not create a child Issue to discover
the boundary through implementation review.
```

Verify target: the parent spec has `Product/Scale Profile`, `Complexity Budget`, `Adjacent Classes /
Exclusions`, and `Why Not Broader`; no child is created for an untriggered larger profile.

```yaml
tcd_retrospective:
  change: "Require an adjacent-capability census before feature child decomposition"
  causal_learning: "Bounded child Issues made a missing capability decision look like implementation scope"
  expected_benefit: "Prevent HKA/DR or multi-writer work from entering a P1 archival graph"
  cost: "One parent-spec section and a deterministic enrich-docs stop"
  verification: "Parent spec fields exist and child list has no untriggered larger-profile task"
  evidence: "GAF README lines 51-85 and 104-126; Issue #5062/#5067 scope"
```

### 4. `issue-to-code/SKILL.md` — preflight reference

Insert after the pre-implementation classification and before the canonical workflow
(`issue-to-code/SKILL.md:37-112`):

```text
### Product/scale fit preflight

Read the governing profile and complexity budget before coding. Record `within_profile=true|false`
with users, independent writers, failure cost, recovery objective, and threat model. Do not infer
P2/P3 from generic words such as auth, replay, concurrency, or durable state. If the implementation
needs an authority store, replay journal, distributed lock, cross-store exactly-once claim,
automatic conflict reconstruction, or adversarial filesystem proof not named by the profile, stop
coding and route back to architecture-research/feature-breakdown for rescoping. A profile mismatch
is not permission to widen the Issue locally.
```

Verify target: the preflight receipt contains `within_profile`, the governing profile reference,
and an explicit out-of-scope comparison before local edits; a false result blocks publication.

```yaml
tcd_retrospective:
  change: "Add profile-fit evidence to issue-to-code preflight"
  causal_learning: "High-risk labels correctly escalated HKA but did not establish that HKA was needed"
  expected_benefit: "Prevent local agents from widening a bounded Issue through safety interpretation"
  cost: "One read-only preflight field and a fail-closed mismatch route"
  verification: "Preflight receipt has within_profile and false blocks publication"
  evidence: "PR #5094 review 5001994105; issue-to-code failure-mode and most-boring-solution rules"
```

### 5. `verification-and-closure/SKILL.md` — profile-boundary stop

Insert after the current low-convergence circuit breaker (`verification-and-closure/SKILL.md:322-368`):

```text
### Profile-boundary stop

The low-convergence breaker also fires when a correct P1 finding shows that the mechanism has crossed
the governing product profile or complexity budget. Do not point-fix or escalate the mechanism in
that case. Preserve the P1 finding and its accounting, block merge/closure, and write a bounded
rescope receipt naming the exceeded profile field and the new capability boundary. Resume only from
a new or amended contract that explicitly supplies the P2/P3 trigger and Verify targets.
```

Verify target: `profile_boundary_stop=required` is present in the review/closure receipt whenever a
mechanism exceeds profile or budget; it blocks repair/publish until the contract is amended.

```yaml
tcd_retrospective:
  change: "Allow review convergence to stop on profile mismatch, not only mechanism failure"
  causal_learning: "Repeated correct HKA P1s exposed a wrong capability boundary, but the current breaker kept repairing"
  expected_benefit: "Turn repeated review cost into a truthful rescope instead of a larger transaction engine"
  cost: "One closure disposition and no additional repair round"
  verification: "Profile-boundary stop blocks merge and records the exceeded field and rescope target"
  evidence: "Local HKA convergence packet: repeated P1 families across authority, journal, alias, receipt, path, and crash state"
```

## Disposition

- **HKA P1 findings:** accepted as correct evidence against the HKA contract; not downgraded.
- **HKA P2 protocol finding:** accepted as a contract/protocol mismatch; it does not justify a larger
  cold-tier kernel.
- **GAF-01..04:** retain their bounded integrity and adapter lessons, but do not let the broad GAF
  specification imply HKA recovery is part of the P1 cold-tier capability.
- **GAF-05 local repair line:** preserve read-only as evidence; no reset, cleanup, push, PR update,
  or lifecycle mutation was performed.
- **Process proposals:** advisory only; no `AGENTS.md`, skill, Issue, PR, label, Project, or product
  code change was made in this review.

## architecture_research_receipt

```yaml
architecture_research_receipt:
  exact_sha: f85011fd0a8d2fc86dced8a0c7c1c95a916d58b4
  retrieved_utc: 2026-08-23T19:32:01Z
  evidence_scope:
    - "origin/main and git history"
    - "repo skills, templates, source anchors, owner docs, and prior audit"
    - "GitHub REST read-only Issue #5062, Issue #5067, PR #5094, review comments, and merged GAF PRs"
    - "preserved GAF-05 worktree and local convergence packet, read-only"
  conclusion: "P1 single-operator/local is the proportionate current design; HKA DR is separate"
  proposed_upstream_artifacts:
    - "AGENTS.md canonical product/scale profile gate"
    - ".codex/skills/architecture-research/SKILL.md intake reference"
    - ".codex/skills/feature-breakdown/SKILL.md adjacent-capability census"
    - ".codex/skills/issue-to-code/SKILL.md profile-fit preflight"
    - ".codex/skills/verification-and-closure/SKILL.md profile-boundary stop"
  github_mutation: none
  product_code_change: none
  feature_breakdown: none
  open_decisions:
    - "Whether the owner accepts the five proposed process changes"
    - "Whether HKA in-place recovery remains a separately funded capability"
    - "Whether the current GAF specification should be amended through the normal PromotionIntent path"
```
