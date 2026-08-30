---
name: Run the Read-Only Owner Pilot
description: Run the future deployed-production owner pilot only after the exact browser-proof and applicable deployment receipts exist; if a `pkm-test` supplement is used, its disposable-state receipt is also required. It records answerability without false authority or durable acceptance.
task_id: ARO-08
github_issue: 4749
source_anchor: "docs/DEVUI.md :: Owner-experience acceptance criteria"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: [ARO-07]
depends_on: [PROVE_OVERVIEW_BROWSER_ACCESSIBILITY.md]
can_parallelize_with: []
recommended_capability: "Owner walkthrough with Codex Terra / high evidence capture"
capability_rationale: "The final check is a production-bound, zero-effect usability receipt that joins exact deployment identity, browser proof, and owner acknowledgement without performing a deployment."
execution_context: fresh_issue_agent
issue_local_helper_budget: 0
context_cost_estimate: medium
complexity: medium
verification_difficulty: high
defect_blast_radius: low
review_gate: owner-acknowledged exact-SHA validation receipt
---

# Run the Read-Only Owner Pilot

## Purpose

Run the three owner questions on the exact deployed, proven read-only shell without creating any
owner decision, acceptance, browser-persistence, or runtime-write state.

## Context

Parent: #4741

After all prerequisites are receipted, verify on one exact deployed SHA and naturally observed
production state that the owner can answer **What should I understand now?**, **Where is my
authority actually needed?**, and **What is truly ready to try?** without opening standalone
source UIs or creating a durable acceptance state. `M` is the exact current `main` SHA deployed for
this pilot, containing delivered #4835 and #4836; a PR head, pre-merge candidate, or older proof SHA
is not `M`. The historical #4748 proof at `c7c57300f2ec241778061078e7ad585454f0b880` remains
valid only when the receipt-sourced deployment and current `main` still equal that SHA; after `main`
advances, #4748 must supply a fresh exact-main proof for the new `M`.

This is a future executable pilot contract, not evidence that the shell has been deployed or that a
pilot has passed. The live URL and deployed SHA are intentionally absent until the #4748 and
deployment receipts supply them.

## Scope

- Run the three-zone owner walkthrough against the receipt-sourced VM-102 `devui_projection`
  service/project and its governed external read dependencies. Do not use a Product Runtime
  `pkm-*` project or vault as VM-102 deployment evidence. The current promotion ref is `main`;
  `stable` is dormant. This task does not promote, deploy, restart, or change either ref.
- Obtain `M` and the exact deployed URL only from the #4748 and deployment receipts. Require SHA
  equality across the CI/review/deploy receipt, gateway marker at `127.0.0.1:8113`, FastAPI
  `/version`, and `/api/health.version` before the journey begins. Port `18000` is diagnostics only.
- Use the deterministic #4748 matrix as the source of hostile/empty/degraded/error proof. A
  `pkm-test` supplemental state is allowed only as a separately authorized disposable evidence
  source, after its data class, namespace, setup, readback, teardown, and absence of foreign rows
  are proven disposable and isolated; it is never VM-102 deployment identity. The governed external
  read dependencies are observed strictly read-only.
- Record answers, evidence path, source conditions, reconstruction steps, Playwright trace,
  screenshots, checksums, manifest, and disposition in the final structured pilot ledger.
- Return discovered defects/gaps to their owning blocked contract without implementing repairs.

## What This Task Does

- Runs the three-zone, degraded-state, and no-durable-decision scenarios plus a real
  **Overview → server-supplied visual Focus link → return** Playwright journey at the exact
  deployed URL `http://127.0.0.1:8113/devui/overview`.
- Captures exact answers and reconstruction burden at the receipt-sourced deployed SHA and URL.
- Proves zero effects: no page or console errors, browser persistence/storage, unauthorized writes,
  commands, provider sessions, or durable acceptance state.
- Hands parent closure forward only if every disposition passes.

## Concretely

The owner answers Now, Needs you, and Ready to try from the shell; a withdrawn zone is reported as
withdrawn with its source reason, never as empty or completed.

## Why This Matters

The final outcome is reduced truthful reconstruction, which repository tests alone cannot attest.

## Source Anchors

- `docs/DEVUI.md :: Owner-experience acceptance criteria`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Capability acceptance`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/PROVE_OVERVIEW_BROWSER_ACCESSIBILITY.md :: Acceptance Criteria`

## SBS Impact

- Primary subsystem: Builder System / devUI owner validation
- Secondary subsystem(s): none
- Write class: durable owner-validation evidence only; no product or runtime write
- Authority impact: none; the pilot creates no decision or acceptance state
- Persistence impact: validation receipt only
- Derived/rebuildable impact: validates one exact rebuildable shell SHA
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: receipt-sourced production URL with optional disposable test-only state
- Sync/deployment impact: consumes an existing Demerzel production deployment receipt; performs no deployment
- External boundary impact: named owner walkthrough
- New or changed contract: final owner-pilot receipt
- Owner-doc impact: supplies evidence for later current-state reconciliation
- Transition debt impact: verifies reduction in standalone-UI reconstruction
- Fitness rule impact: three-zone answerability and no-durable-decision checks

## Constraints

This task owns the parent-validation receipt only. It changes no production code and does not deploy,
promote, restart, or mutate production. Any defect, source-authority gap, design gap, inaccessible
journey, identity mismatch, effect, error, storage use, or unauthorized write is returned to its
owning blocked contract and blocks the pilot.

Prerequisites are strict and serial: (1) #4748 delivery and its fresh exact-main receipt matching
the current deployed `main` SHA `M`;
(2) this repaired source contract; (3) Demerzel authentication and the boolean-only #4835
credential-presence prerequisite; (4) the deployed #4836 route and server-supplied Focus selectors;
(5) applicable main-tracking deployment/operator evidence for exactly `M`; (6) the
receipt-sourced deployed SHA/URL and identity agreement; and (7), only when a `pkm-test`
supplement is used, an approved disposable-state classification covering its data class, namespace,
setup, readback, teardown, and absence of foreign rows. A production-only pilot has no
supplemental-state prerequisite. The pilot must not be claimed or made ready from this document
alone.

The final `devui-stage-a-read-only-owner-pilot.v1` ledger is the only cross-run binding authority.
It records the separate final-M #4748 browser artifact and the independent production evidence; it
does not revive or require a pre-merge candidate artifact. Each evidence entry records its exact
Git SHA, its own canonical archive manifest, and `evidence_artifact_sha256`: the SHA-256 of a
canonical JSON object mapping every archived relative artifact path to that entry's file SHA-256.
The digest bytes are the RFC 8785 JSON Canonicalization Scheme (JCS) serialization of that object,
encoded as UTF-8 without a BOM and with no trailing newline or other bytes; producers and verifiers
reject non-finite JSON numbers and any non-string path/hash value. The `browser` entry inventory is
exactly the authenticated `devui-stage-a-exact-sha-state-matrix.v1` wrapper receipt, its strict
browser receipt, the source `manifest.json` emitted and uploaded by
`.github/workflows/browser-runtime.yml`, JUnit result, Playwright trace, and every screenshot. It
excludes only the pilot ledger entry's own rendered inventory manifest. The `production` entry has
a separate inventory of the applicable
VM-102 qualification/deployment/health receipts, receipt-sourced gateway and API identity
observations, the deployed Playwright journey's trace, screenshots, checksums, and journey
manifest, any explicitly used disposable-state receipt, and, only when a `pkm-test` supplement is
used, that supplement's trace, screenshots, checksums, and manifest; it never imports browser-bundle
files, owner-walkthrough output, owner acknowledgement, or the final owner-pilot ledger. The
owner-walkthrough result and acknowledgement are recorded and authenticated as ledger fields, but
are never inputs to the production digest. Each inventory is enumerated by its own manifest, has
unique relative
paths, and excludes the rendered manifest that contains its digest. Missing files, duplicate paths,
a malformed digest, or a digest that does not recompute from that entry's archived files fail the
pilot closed. This identity distinguishes materially different reruns at one Git SHA without
adding any cross-run field to `devui-overview-browser-accessibility.v1`.

## Acceptance Criteria

- [ ] The pilot obtains its exact deployed URL and SHA from the #4748/deployment receipts and
      proves equality across the current CI/review/deploy receipt, `/version`,
      `/api/health.version`, and gateway marker before the journey.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] For each zone, the final structured ledger records the exact answer, evidence path, source
      conditions, elapsed reconstruction steps, and pass/fail disposition.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The ledger binds the distinct final-M #4748 browser evidence and production evidence. Each
      entry has a recomputable `evidence_artifact_sha256` over its own canonical inventory: the
      browser entry contains the authenticated wrapper, source manifest, and only browser-bundle artifacts, while the production entry contains
      only production/owner evidence and any used disposable-state receipt. Each entry fails closed
      when its archived artifact set is missing or mismatched; the strict #4748 receipt does not
      reference a candidate receipt.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The owner identifies every degraded/withdrawn state without reading it as empty, healthy,
      decided, delivered, or ready.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] Needs-you never presents a technical block and Ready-to-try never follows merge/done/closure
      without the accepted explicit source facts.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] A deployed Playwright journey always follows Overview to a server-supplied visual Focus link
      and returns while preserving subject/evidence context, with zero effects, errors, storage,
      or unauthorized writes; no standalone subsystem UI is required for the tested answers.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] If a `pkm-test` supplement is used, its disposable state matrix produces no effects, page or
      console errors, browser persistence/storage, or unauthorized writes; traces, screenshots,
      checksums, and manifest are durable and bound to the deployed identity. If no supplement is
      used, the production-only evidence records that the deterministic #4748 matrix supplied the
      unobserved hostile/degraded states and that no test state was created.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The owner explicitly acknowledges the bounded result; the pilot creates no tried/accepted/
      dismissed state, task, command, provider session, or product/runtime write receipt.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] A current-state writeback to `docs/DEVUI.md` is proposed only after PASS and remains outside
      this task before that result.
  - Verify: doc writeback at `docs/DEVUI.md :: Current state and target`

## How to Verify (Pre-Merge)

- Confirm every strict prerequisite, including #4748 at the current deployed `M`, the repaired source contract, the
  boolean-only #4835 prerequisite, Demerzel access, applicable main-tracking deployment/operator
  evidence for exactly `M`, and the receipt-sourced URL/SHA. If a `pkm-test` supplement is used,
  also confirm its approved disposable-state classification; otherwise record the production-only
  path explicitly.
- Run the five named pilot checks and the Overview → Focus → return Playwright journey.
- Post the owner-acknowledged structured result and any blockers to the parent; do not repair them
  here. Only a PASS may trigger a separate current-state owner-doc writeback decision.

## Suggested Validation

- Validate every named pilot scenario, deployment-identity agreement, disposable-state boundary,
  no-effect evidence, and durable evidence manifest against the receipt-sourced deployed URL/SHA.

## Out of Scope

- Code/doc repair, owner action execution, durable feedback state, analytics, or broader adoption.

## Related Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`

## Source Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/PROVE_OVERVIEW_BROWSER_ACCESSIBILITY.md`

## Applies learning (optional)

- None.

## Related GitHub Issues

Filed as blocked child [#4749](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4749) serially
after #4748. It awaits the repaired contract, Demerzel prod access and boolean-only #4835
prerequisite, #4836 selectors, #4748's exact-main receipt, applicable main-tracking
deployment/operator evidence for exactly `M`, and receipt-sourced deployed URL/SHA. If the pilot
supplements the receipt-sourced VM-102 Dev UI evidence with separately authorized `pkm-test` state,
it additionally requires an approved disposable-state classification.
