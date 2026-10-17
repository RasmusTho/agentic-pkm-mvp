# Manual field-contract and telemetry probe

This namespace retains the new #6174 manual, history-free #3798/#3803 probe. The complete
[v2 receipt](../shadow_rehydration_3798_field_contract.v2.json) reopens the exact source, packet,
original response, comparison and execution/telemetry chain. All outputs are create-only. The
original response and three live-read envelopes were written once by the fresh observer and never
reformatted or repaired.

## Retained source and custody

`accepted/` is the actual v2 source: fresh Issue/PR/review-thread, dispatcher and remote-main reads;
the evaluator checkpoint at `2026-10-17T21:16:01.267814+00:00`; and actual run-state dry-run,
acceptance and readback for `shadow-field-contract-3798-accepted-20261017`. Readback equals the
packet's source receipt. Remote main then was `7517008c49086e9b2acdc03d753785fced944661`.
This is a checkpoint, not a claim that external state remains current indefinitely.

The namespace's top-level `live-*`, `source-checkpoint.json` and `run-state-accepted.json` files
are earlier preparation captures retained unchanged for historical custody. They are not the final
v2 packet source: the preliminary CI value predates the explicit named-scope CI object. Nothing
silently replaces that history or the separate frozen v1 evidence from #6165.

## Actual fresh invocation and measurements

The parent admitted `/root/fresh_shadow_fields_3798` with no inherited history at configured
`gpt-6-luna` / `xhigh`, without rejection or fallback. Admission configuration is observed;
underlying engine identity is not introspected. The observer read only the frozen packet, its
explicit live sources, and its four new output files for hashing. See `probe/native-capture.json`
for the trusted recorder attestation and original raw hashes.

- Packet: 31,502 exact UTF-8 bytes, SHA256
  `b7ec0ce7fb140bcaddfedde6245d9200ebde44adb6d36bb6b3015e99aab9ebe0`.
- Original response: 6,937 exact UTF-8 bytes, SHA256
  `a6e1b74af8327a414901bd720e2c4329800d4b6e0370d2154c65e720dbdc41a1`.
- Wall-clock interval: parent pre-invocation marker `21:51:28Z` through original-artifact readback
  `21:53:24Z` on 2026-10-17, **116 seconds**. It includes orchestration/dispatch and capture, not
  model-active duration or human effort. Admission was observed at `21:51:41Z`; event timestamps
  are parent confirmations at one-second resolution, not precise carrier instants.
- Probe interval: one successful agent start, two packet/response handoffs, zero admission retries
  and zero implementation/review/CI repairs. Five earlier protected implementation review-repair
  passes are outside this bounded interval; they are retained on Issue #6174, not erased by these
  zero counts. Live-read retries are not native admission retries.
- Input/output tokens, monetary cost and human minutes are unknown because the carrier supplied no
  authoritative usage/billing receipt and no human effort was measured or attested. Bytes are not
  tokens. The response-byte measurement excludes the three separate live-read envelopes.

## Field result and readiness limits

| Field | Result | Meaning |
| --- | --- | --- |
| Checkpoint decision delta | match | Exact ordered source strings reconstructed. |
| Checkpoint gate invariants | match | Advisory source gate declarations preserved; no gate bypass. |
| Checkpoint recommendations | match | Source recommendation/reason projection, not a live next action. |
| Slice status | unknown | Fresh PR read unavailable; no checkpoint-filled lifecycle claim. |
| Open review findings | unknown | Composite GitHub evidence unavailable; no borrowed source proof. |
| External state | unknown | Dispatcher observed; GitHub and remote main unavailable. Refresh required. |
| Live next action | not comparable | Unknown in this run; not forced to equal checkpoint recommendations. |
| Missing claims | match | Reports slice status, open review findings and external state as unavailable. |
| Fabricated claims | unknown | No independent fabrication audit; drift/absence is not fabrication. |

The unchanged observer records two PR-view failures with API connection errors and two remote
`ls-remote` failures with host-resolution errors. Its local `origin/main` diagnostic was not used
as remote truth. Issue and review-thread reads succeeded, but the composite GitHub envelope cannot
claim observed availability without its fresh PR object. These are observer-attested capture
failures, not a host/network diagnosis or an authorization to recover infrastructure. Delivery
verification uses its own live GitHub evidence, never retrofits these probe claims.

The field/byte/clock/event capture path is replayable and the unknown result is useful evidence.
This run does **not** establish positive live GitHub/remote-head rehydration, successful coordinator
rotation, automatic compression, dispatch changes, or an overall readiness score. A later manual
rotation experiment remains separately authorized work and needs its own live evidence. Custody
hashes and typed payload checks do not authenticate fetches, the operator, or upstream truth.

The focused retained-evidence test replays the standalone receipt and verifies original raw hashes
and accepted checkpoint equality. Rerunning a producer must select a new output path; refusal to
overwrite these originals is expected behavior.
