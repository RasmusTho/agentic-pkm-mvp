# Manual live-access shadow rehydration probe

This #6195 namespace repeats the existing explicit-v2 manual contract for closed Issue #3798 and
merged PR #3803. It changes no production module, evidence protocol or authority effects. Earlier
v1 and #6174 v2 experiment files remain unchanged. All packets, source custody and observer
originals in this namespace are create-only.

## Accepted checkpoint and source custody

`accepted/` retains actual Issue/PR, complete review-thread, dispatcher and direct
`origin` / `refs/heads/main` captures. The existing evaluator emitted the checkpoint at
`2026-10-18T06:43:22.088666+00:00`; run-state dry-run, acceptance and readback for
`shadow-live-access-3798-accepted-20261018` agree exactly with the retained evaluator receipt.
`source-capture.json` retains actor, commands, target, UTC observation, exit/result class and the
existing native permission boundary. Source access is not proof of observer access.

Remote main was `cc3cdb562a0039e5bce209f3979de4642e484d87`. Before freezing retry1 the owner
re-read that direct remote identity and the target lifecycle/head/merge identities; they still
agreed. This reuse preserves the original accepted checkpoint, not a claim that external state
cannot drift. The observer must independently read live state and retain any drift.

## Failed first response, retained without repair

`probe/` retains the first packet and all four raw observer originals. That observer's own
post-admission GitHub Issue/PR/review-thread, direct remote-main and dispatcher reads succeeded.
Its original response nevertheless failed the shipped semantic consumer: the two agent-reporting
fields used an `observer:` reference instead of the required exact `agent:<probe-id>` reference.
`compare` exited 2 and created no comparison. This attempt has **no valid probe receipt** and is
not accepted measurement evidence merely because its reads succeeded.

The frozen first packet is 29,141 bytes, SHA256
`91a8c448e1b0cab1a6b332b1fbd4cd3c9b800cdc0aec7b8a41325e28989636ec`; the original response is
8,185 bytes, SHA256 `91dca02bb48594866e0b6488414ecfdb340d54fb1d00fc3f1b1f52a496f59cb4`.
`probe/native-capture.json` binds all originals and retains the recorder-attested interval from
`06:45:05Z` through `06:48:18Z` on 2026-10-18: 193 seconds including orchestration, dispatch and
capture. The interval has one successful native admission, two packet/response handoffs, no native
admission retry and no implementation/review/CI code repairs. One local dispatcher invocation
correction removed a prose trailing dot after an exit-2 argument refusal; the corrected read exited
0. It is not an admission retry or a code repair.

The between-attempt packet-producer correction carries all existing semantic admission rules in
the new packet's instructions, including exact reporting provenance and literal argument vectors.
It does not weaken the consumer, repair an original, demonstrate model unavailability or justify a
capability fallback. The [governing Issue's divergence record](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6195#issuecomment-6246769719)
already preserves this capture-learning result; no duplicate learning ledger or Product memory is
created. A focused test verifies the original refusal and immutable bindings.

## Qualifying fresh retry and measured result

`probe-retry1/` is a separately admitted, history-free observation against the corrected packet.
Its own GitHub Issue/PR/review-thread, direct remote-main and dispatcher commands all exited 0;
GitHub and Git transport used the existing sanctioned `require_escalated` invocation, while the
local dispatcher read used the default sandbox. No credentials, ACL, DNS or host-network settings
changed. All six review threads were read on one complete page and were resolved. The original
packet/response/live envelopes were written once and independently hashed by the recorder before
handoff. The [qualifying v2 receipt](../shadow_rehydration_3798_live_access.v2.json) passes the
unchanged standalone complete-chain consumer, including a separate-process replay.

| Field | Result | Observed meaning |
| --- | --- | --- |
| Checkpoint decision delta, gate invariants, recommendations | match | Exact checkpoint meanings and ordered strings retained, not substituted for live facts. |
| Slice status | match | Fresh Issue CLOSED and PR MERGED. |
| Open review findings | match | Complete read, six resolved threads, no unresolved URLs. |
| External state | match | Independent Issue/PR/head/merge, historical CI scope, direct origin/main and dispatcher facts agree with this checkpoint. |
| Live next action | not comparable | Preserve the closed/merged slice; not the evaluator's thin-worker recommendation. |
| Missing claims | match | No comparable observed field is unknown. |
| Fabricated claims | unknown | No independent fabrication audit; match or drift is not fabrication proof. |

External refresh is not required for these captured facts. That is one measured result, not an
all-match requirement, aggregate score, readiness threshold or claim that live state stays fixed.
The CI dimension is red because the returned historical rollup includes `CANCELLED` entries; its
explicit scope includes all returned entries and is **not** a current required-CI verdict or the
delivery merge gate.

- Corrected packet: 30,772 bytes, SHA256
  `83451b93a0c2b98de6fe70e6850c14fc984894fc8ecfb34a4d82c01671269cce`.
- Original response: 7,230 bytes, SHA256
  `c9d709efbbf6bec564c89b57b9053f08906a303f229c244b7888cd0986289b54`.
- Named wall interval: root's pre-invocation marker `06:51:46Z` through exact original readback
  `06:54:43Z` on 2026-10-18, 177 seconds including orchestration, dispatch and capture. Successful
  admission and packet handoff were observed at `06:52:08Z`; these are recorder confirmation
  ticks, not precise carrier instants or model-active duration.
- This retry interval has one successful start, two packet/response handoffs, zero admission
  retries, zero code/test/review/CI repairs and zero read-command corrections. The first failed
  attempt and one between-attempt instruction correction remain separate; the intervals are not
  summed into whole-delivery time. Three new native starts were observed through retry readback:
  one writer and two separate observers. Later review and delivery effects belong in the PR's
  receipt, not this capture's counters.

`execution.json` and `native-capture.json` retain recorder evidence; the production telemetry helper
derives bytes, elapsed time and event counts from their exact inputs. Technical temporary-storage,
Git-permission and producer/test-invocation corrections outside the capture are listed separately
in `native-capture.json`, not hidden by narrow zero repair counts. Input/output tokens, monetary
cost, human minutes, model-active time and independently introspected engine identity remain
unknown. Admitted configured `gpt-6-luna` / `xhigh` is not engine introspection; bytes are not
tokens and wall time is not effort.

The focused retained-evidence test replays evaluator/run-state equality and the complete production
receipt, checks raw originals, and rejects missing, unavailable or foreign-target required live
envelopes as positive access proof. Existing v1/v2 tests retain strict chain, create-only and empty
authority-effect coverage. Custody and trusted observer/recorder attestations do not authenticate
upstream truth. No automatic rotation, compression, takeover, dispatch change, launch authority or
Product/runtime memory follows from this manual result.
