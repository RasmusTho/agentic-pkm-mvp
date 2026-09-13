---
name: Run the Read-Only Owner Pilot
description: Run the future deployed-production owner pilot only after the exact browser-proof and applicable deployment receipts exist; if a `pkm-test` supplement is used, its disposable-state receipt is also required. It records answerability without false authority or durable acceptance.
task_id: ARO-08
github_issue: 4749
source_anchor: "docs/DEVUI.md :: Owner-experience acceptance criteria"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: [ARO-07, ARO-09, "exact-candidate managed deployment and health"]
depends_on: [PROVE_OVERVIEW_BROWSER_ACCESSIBILITY.md, RECONCILE_MANAGED_OWNER_PILOT.md]
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

State: Target-state live-pilot task specification; no managed deployment or owner pilot is proved.
Doc role: Specification
Authority: The VM102 receipt owner governs runtime admission; this task owns only zero-effect pilot evidence and bounded owner acknowledgement.

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
this pilot, containing the reused #4836 shell and delivered managed extension; a PR head, pre-merge candidate, or older proof SHA
is not `M`. The historical #4748 proof at `c7c57300f2ec241778061078e7ad585454f0b880` remains
valid only when the receipt-sourced deployment and current `main` still equal that SHA; after `main`
advances, #4748 must supply a fresh exact-main proof for the new `M`.

This is a future executable pilot contract, not evidence that the shell has been deployed or that a
pilot has passed. The target origin below does not supply an observed live URL or deployed SHA; only the applicable
browser and independent deployment receipts may supply those observations.

## Scope

- Run only on the receipt-sourced VM-102 `builderops-devui` / `devui` deployment and its explicitly
  admitted read dependencies. The single target browser origin is `http://127.0.0.1:8113`, with
  entry page `/devui/overview`. This URL is a target contract, not a claim that it is served now.
- Consume [Managed read journey admission](../BUILDEROPS_CONTROL_PLANE/README.md#managed-read-journey-admission)
  for the exact entrypoint, direct-loopback admission, shell/assets/typed Focus and finite source
  transports. The prepared listener has only an Overview API and diagnostics; a separately
  delivered managed browser/source extension is a strict external prerequisite for this pilot.
- Obtain deployed `M`, image/config identity and observed URL from the independent deployment and
  health receipts. Require equality with attested CI/review/release evidence, managed `/version`,
  served shell/assets and applicable #4748 exact-main browser evidence before the journey. Neither
  `/healthz` liveness nor the former Product `/api/health.version` is managed deployment proof.
- Preserve the exact #4748 hostile-state proof and both independent artifact inventories below.
  If a separately authorized `pkm-test` supplement is used, require its disposable-state receipt;
  it never becomes VM102 identity or a Product service dependency. No test state is created by a
  production-only pilot.
- Record answers, evidence path, source conditions, reconstruction steps, trace/screenshots,
  checksums, manifest and disposition. Return defects to the owning contract without repairs.
- Perform no promote/deploy/restart, credential action, command, provider session or durable owner
  outcome. `main` is the promotion ref and `stable` remains dormant. Operator authorization of
  deployment and the owner's later acknowledgement of this read-only evidence are distinct.

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
- Sync/deployment impact: consumes existing VM-102 Dev System qualification/deployment/health receipts
  for `devui_projection` and its governed external read dependencies; performs no deployment
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

Prerequisites are strict: the merged ARO-09 contract; the separately delivered and admitted
managed shell/assets, typed Focus and required work/GitHub/document sources; applicable design
evidence; fresh exact-final-main #4748 proof for deployed `M` including managed-origin applicability;
the complete inventory → qualification/activation → deployment → health chain and applicable
operator/promotion acknowledgement for that candidate; and observed URL/source/image/config
agreement. The [receipt owner](../BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract)
names every producer, including external SoI/model and complete-system smoke and the real #4076
operator boundary. No Demerzel/Product credential-presence test is an independent-listener gate.
If a `pkm-test` supplement is used, its approved disposable data class, namespace, setup, readback,
teardown and absence of foreign rows are additionally required. The production-only path has no
supplemental-state prerequisite. The owner's acknowledgement of the walkthrough is an output,
not a prerequisite for starting it; this task creates no candidate trial/acceptance decision.

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
VM-102 qualification/deployment/health receipts, receipt-sourced managed shell and diagnostic identity
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
      proves exact source/image/config equality across current CI/review/deploy/health evidence,
      managed `/version`, served shell/assets and applicable exact-main browser proof before the journey.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] For each zone, the final structured ledger records the exact answer, evidence path, source
      conditions, elapsed reconstruction steps, and pass/fail disposition.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] The ledger binds the distinct final-M #4748 browser evidence and production evidence. Each
      entry has a recomputable `evidence_artifact_sha256` over its own canonical inventory: the
      browser entry contains the authenticated wrapper, source manifest, and only browser-bundle
      artifacts, while the production entry contains applicable production evidence, the deployed
      journey artifacts, and, when a `pkm-test` supplement is used, its disposable-state receipt
      plus trace, screenshots, checksums, and manifest. Each entry fails closed
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

This is a live-validation task; repository review can validate its procedure but cannot pass it.
Before execution verify every external prerequisite in Constraints, the managed URL and exact
candidate identity, independent evidence inventories and any explicitly used disposable state.
Run the five named pilot checks and Overview → server-supplied Focus → fresh Overview journey.
Post the owner-acknowledged structured result and blockers to #4741. Only PASS permits a separate
current-state owner-doc writeback; it supplies no deployment or effectful owner acceptance.

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

[#4749](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4749) remains the separately gated
read-only pilot under #4741. ARO-09/#5504 repairs its contract; #5181 owns operational qualification
and deployment evidence. Historical #4748 proof stays closed at its tested SHA and must be refreshed
for the exact managed candidate. Source/shell admission and real operator evidence remain external
prerequisites; the pilot owns the walkthrough and bounded owner acknowledgement.
