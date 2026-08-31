---
name: Product Runtime TARS Channel Issue Migration Map
description: Snapshot map for reconciling legacy Product Runtime placement language in open Issues
type: migration-map
authority: Repository reconciliation aid; GitHub Issue state and each Issue contract remain authoritative
source_of_truth: GitHub open-Issue readback used by #5237
---

State: Repository-only migration map, observed 2026-08-31. This map does not change Issue lifecycle,
Project status, deployment authority, or runtime truth. It identifies open Issues whose current body
contains a materially relevant legacy placement term (`Demerzel`, `Mac mini`, `Colima`,
`workspace-prod`, or workstation `loopback`) and routes each one without silently rewriting its
contract.

Temporal class: snapshot
Review cadence: event-driven
Last reviewed: 2026-08-31
Last verified against: GitHub open-Issue readback on 2026-08-31

The allowed dispositions are deliberately finite:

- `valid control/client use` — the legacy term is valid context for a control, client, model-host, or
  explicitly local fallback and does not claim Product Runtime channel placement.
- `topology reconciliation` — the Issue must consume the TARS Product Runtime placement contract or
  reconcile a Builder/Platform boundary against it.
- `human gate after prerequisites` — live host, deployment, UAT, device, credential, or operator
  acceptance remains outside this repository slice and waits for its named prerequisite.
- `superseded` — a newer bounded contract owns the work; retain the historical Issue without reopening
  its old placement semantics.
- `protected in-progress` — the Issue has its own active bounded work; the migration map is context,
  not permission to broaden or rewrite that work.

## Snapshot and routing rule

The snapshot was produced from the open Issues in `RasmusTho/agentic-pkm-mvp` on 2026-08-31. A future
Issue that introduces one of the legacy terms into a Product Runtime placement or acceptance claim
must be added here with one disposition and one topology-correct next action. Historical evidence may
remain in an Issue, but future acceptance must point to the TARS-hosted Linux VM topology or an
explicit non-Product control/client/fallback boundary. Incidental mentions that are unrelated to
Product Runtime placement are retained as `valid control/client use` when their Issue still carries
an explicit host or acceptance reference, such as #3314 and #3367.

The snapshot is reproducible with this read-only query (searching Issue title and body):

```text
gh issue list --repo RasmusTho/agentic-pkm-mvp --state open --limit 1000 --json number,title,body
```

Apply the case-insensitive terms `Demerzel`, `Mac mini` or `Mac-mini`, `Colima`, `workspace-prod`,
or `loopback` to the concatenated title and body, then review each match for Product Runtime,
Builder System, control/client, fallback, or acceptance relevance. The 2026-08-31 readback returned
37 matches; all 37 are listed below, with incidental service/client contexts classified rather than
silently excluded. A later readback is a new snapshot and must refresh both this table and its test.

## Open Issue dispositions

| Issue | Disposition | Topology-correct next action |
| --- | --- | --- |
| #5237 | topology reconciliation | Deliver this repository-only contract, then refresh the #4913 validation ledger. |
| #5181 | topology reconciliation | Consume #5237 and reconcile the separate VM 102 Builder System target; do not treat it as Product Runtime placement. |
| #5056 | protected in-progress | Continue the BuilderOps VM 102 rebuildable slice under its own contract; no Product Runtime placement is implied. |
| #5052 | topology reconciliation | Reconcile the TARS/BuilderOps migration against the separate Product Runtime channel contract before any live operation. |
| #4918 | human gate after prerequisites | Keep the topology-only cutover blocked until #5237, qualification, rehearsal, backup, rollback, and operator authorization are complete. |
| #4913 | topology reconciliation | Consume #5237 before advancing the STARTUP-05/06 chain; retain the parent as validation hub. |
| #4899 | human gate after prerequisites | Perform the owner-gated Colima persistent-substrate operation only if a local fallback is deliberately selected; it does not qualify TARS. |
| #4785 | protected in-progress | Continue the exception-redaction repair; placement wording is historical context and not a runtime-host claim. |
| #4773 | human gate after prerequisites | Await human device/build acceptance; the Mac mini is a client/control boundary, not Product Runtime placement. |
| #4767 | protected in-progress | Continue the bounded read-path repair under current runtime authority; preserve the historical Colima observation. |
| #4749 | human gate after prerequisites | Wait for the named read-only owner-pilot prerequisites and receipt-sourced runtime identity. |
| #4741 | human gate after prerequisites | Complete the read-only owner path only after its current-host and owner-acceptance prerequisites are evidenced. |
| #4697 | protected in-progress | Repair the Model Inquiry contract under its own authority; loopback is admission context, never approval. |
| #4076 | human gate after prerequisites | Install/verify the deploy-host alert path through the named operator boundary; do not infer it from workstation state. |
| #3925 | protected in-progress | Continue the YouTubeSync CLI contract; local loopback remains a client transport option, not Product Runtime placement. |
| #3843 | human gate after prerequisites | Continue Keychain provisioning only through its owner-authorized credential contract. |
| #3793 | topology reconciliation | Reconcile BuilderOps PostgreSQL authority with the VM 102 target; do not move Product Runtime channel authority. |
| #3788 | topology reconciliation | Reconcile the older BuilderOps VM 102/API-first contract with #5052 and #5181 before any activation. |
| #3690 | protected in-progress | Apply ADR-0062 only through its own BuilderOps cutover prerequisites and current VM 102 authority. |
| #3657 | human gate after prerequisites | Resolve the Codex execution-schema access boundary through the named owner/operator path. |
| #3604 | protected in-progress | Continue post-merge closure recovery under Builder System governance; Demerzel wording is not Product Runtime placement. |
| #3603 | protected in-progress | Continue the verification/merge service contract against VM 102; preserve its scoped control-plane role. |
| #3409 | human gate after prerequisites | Run the host-load capacity work only with its explicit operator/runtime prerequisites; do not assume Mac mini placement. |
| #3376 | protected in-progress | Reconcile Karakeep acceptance against the current TARS channel contract before live validation. |
| #3367 | valid control/client use | Keep the managed mac-mini Karakeep service context separate from Product Runtime placement; route any Product Runtime acceptance to qualified TARS channels. |
| #3341 | human gate after prerequisites | Await the native observer and transport acceptance boundary; loopback/Tailscale is client ingress context only. |
| #3340 | human gate after prerequisites | Complete the observer parent only after its live capture and owner prerequisites are evidenced. |
| #3335 | human gate after prerequisites | Complete voice-loop live validation only through the current test-channel runtime receipt. |
| #3331 | human gate after prerequisites | Complete episode-debrief live validation only through the current test-channel runtime receipt. |
| #3325 | human gate after prerequisites | Complete Standing Questions validation only through a current, receipt-sourced test runtime. |
| #3314 | valid control/client use | Keep the operator/mac-mini acceptance reference client-scoped; any live Product Runtime proof must use the qualified TARS channel. |
| #3191 | human gate after prerequisites | Run capture round-trip validation only after an authoritative test channel is available. |
| #3175 | human gate after prerequisites | Run Episode Resolution live-day validation only after the current test-channel gate is available. |
| #3169 | human gate after prerequisites | Run control-surface round-trip validation only through the authoritative test channel. |
| #2965 | human gate after prerequisites | Resolve the off-machine backup destination and operator acceptance; historical Mac mini/T7 facts remain evidence only. |
| #2292 | valid control/client use | Continue embedding reliability under capability configuration; Colima/Ollama references do not select Product Runtime placement. |
| #2086 | topology reconciliation | Reconcile TTS production prerequisites with #5237's TARS channel contract before enablement or live acceptance. |

## Boundary and evidence rule

This map is not a closure list. A disposition does not close, relabel, claim, or make an Issue ready,
and it does not convert repository tests into host qualification or deployment evidence. The exact
Issue contract, current labels, linked PR, and owner acceptance remain authoritative. VM 102 remains
the complete Builder System / Dev System target; Product Runtime channel placement remains the
TARS-hosted Linux VM topology; Demerzel/Mac mini remains a control/development/client/operator
boundary; local Compose/Colima remains fallback-only.
