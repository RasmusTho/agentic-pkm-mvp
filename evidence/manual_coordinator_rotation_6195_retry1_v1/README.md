# Actual manual read-only role experiment — NONCONFORMING

Issue [#6236](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6236) exercised one manually
activated replacement of a bounded read-only coordinator role for closed #6195 / merged #6200.
The actual role chain and post-activation terminal continuation occurred, but the frozen producer
protocol did **not** conform: admission and response engine-source explanation strings differ.
This is not a full-success or conforming-capture report. No automatic rotation, writer/lifecycle
transfer, process fence, active-epic scheduling, dispatch or Product-memory effect follows.

## Canonical result and preserved refusal

The current runtime target `manual_coordinator_rotation_6195.v1` is
[`nonconforming-result.v1.json`](nonconforming-result.v1.json), consumed only through the explicit
`build-result` / `verify-result` modes. It binds the unchanged actual input graph, original strict
refusal, exact historical verifier source and its custody mapping. It reports
`frozen_protocol_conformance=NONCONFORMING`, never silently falling back from strict admission.

The two original source strings are retained verbatim:

| Retained object | `engine_identity_source` |
| --- | --- |
| `operator/admission.corrected.original.json` | `unknown(native carrier exposes no independent engine identity)` |
| `successor/initial/agent-response.original.json` | `native carrier exposes no independent engine identity` |

The actual requested/admitted model, reasoning, actor, admission time and literal unknown engine
value agree. The pre-read transport did not supply the response's different literal reason.
This is an operator metadata-producer/transport concordance defect, not native unavailability or
an additional Luna capability failure. No string was canonicalized or original amended.

The default strict `build` / `verify` path continues to refuse this exact graph. Actual negative
subprocess output, exit 2, argv, module/input bindings and actual post-replay clock are in
[`writer/frozen-v2-refusal.original.json`](writer/frozen-v2-refusal.original.json). Its
`12:28:43Z` retention observation is distinct from the earlier first refusal, whose exact process
start/end clock was not measured. No conforming `receipt.json` exists. The initial unchanged v2
comparison/telemetry/probe receipt remains valid; that is not a final frozen-rotation verdict.

Before code repair, the exact then-current verifier was preserved as
`writer/frozen-verifier-5d657d8905f8f61ad24723fc55018bd1149a86d35345fe7cb4805cc59df8ff37.py.txt`:
SHA256 `5d657d8905f8f61ad24723fc55018bd1149a86d35345fe7cb4805cc59df8ff37`, 32,512 bytes.
Hash/length equality was checked at actual clock `12:33:24Z`. The separate source-custody mapping
records that the captured module ref was its location then, not a claim that current-path bytes
remain unchanged. The retained test replays both archived and current strict sources and the
explicit result. The earlier derived `nonconforming-result.json` is preserved as a superseded
reporting draft; it is not the current normalized result or an original live capture.

The canonical technical clarification was applied and read back exactly before implementation:
[maintenance/design receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6236#issuecomment-6249981448),
body SHA256 `ee1e7c240527c5221017f0b426c9b9aedda8cbf924b85d47f525a2c3d64876aa`.
All six ACs and exact Verify targets remain. A clean independent mechanism review preceded code;
fresh exact-candidate review and current-head CI remain separate delivery gates. This engineering
reporting correction does not waive the frozen producer violation or authorize a second rotation.

## Frozen source and admission custody

The actual accepted evaluator source was captured at `11:56:47.338969Z`, after direct main had
advanced to `73c7ff63b2302ef2b6b74bb5153cf3f96ebf62fb`. It was accepted/read back before freezing.
The operator externally pinned these exact bytes before invoking the fresh native context:

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| `context-pack.json` | 55,875 | `c67a830a1d1111750368849e269177e0c6f59d474bb83f2b4c5dbaf0ac1d2e34` |
| `capture-contract.json` | 1,514 | `36a2bda8af7a092d7b660fb203dd620790d57c1865bec01d8f5efa97d252f022` |
| `ingestion-contract.json` | 34,649 | `9fe0aabeb5fcf11704e61bd1f6dd5db4347347d5ff8ce6a1fd013d35389074db` |
| `accepted/source-checkpoint.json` | 3,825 | `4ae081dc4a273a76a87283667d9e01f4d9ad173936f712c752f8ec32209c615a` |
| `accepted/run-state-readback.json` | 4,541 | `077ce63f351dfade3008a8333bc2e8404a717cf465ec1da8dfdb06a14eeb0c4f` |

The durable freeze comment followed native admission; no comment-before-admission ordering is
claimed. The externally pinned contract and every original remain unchanged. Packet-only initial
readiness preceded the operational metadata handoff and actor-owned live capture.

The erroneous `operator/admission.json` used the previous experiment ID. It remains immutable and
is refused. A new `admission.corrected.original.json` retained the same real native actor/time
and was delivered before any live capture. Its complete source string is not retroactively changed
to match the response. The invalid first metadata transfer at `12:05:37Z` is additional to the
mandatory protocol bundle count; corrected-metadata confirmation was observed at `12:06:45Z`.

## Actual manual phase chronology (UTC, 2026-10-18)

The operator/incumbent experimental coordinator was `/root`; successor was the same native actor
`/root/manual_rotation_successor_6236_retry1` throughout. Writer was
`/root/implement_manual_rotation_6236`. Event actor names identify the associated successor, not a
claim that it invoked its own admission or operator follow-ups.

| Observation | Actual UTC |
| --- | --- |
| Pre-native-request clock | 12:04:34 |
| Successful native admission observation | 12:04:48 |
| Corrected metadata confirmation before capture | 12:06:45 |
| Initial GitHub / repository / dispatcher clocks | 12:07:14 / 12:07:22 / 12:07:32 |
| Initial original response / root readback | 12:08:07 / 12:08:42 |
| Separate explicit operator decision | 12:15:58 |
| Incumbent experimental-role quiescence | 12:16:07 |
| ROLE request 1 / successor acknowledgment / root readback | 12:16:21 / 12:16:38 / 12:16:53 |
| Separate manual activation / ROLE request 2 | 12:17:02 / 12:17:17 |
| Same-successor continuation start | 12:17:41 |
| Continuation GitHub / repository / dispatcher clocks | 12:18:15 / 12:18:22 / 12:18:28 |
| Continuation original completion / root readback | 12:19:18 / 12:20:12 |

Every source/response time joins its retained actual `clock.curr_time` object. Full raw stdout,
argv, exit and output-budget/count metadata join every live payload and the actual planner output;
initial five commands and continuation six commands all returned zero with no truncation observed.
These are trusted native/actor/recorder attestations, not authenticated upstream truth.

The fidelity consumer also requires every field in the carried Issue5/PR8 `--json` selections,
with exact primitive/container types and the consumed label, merge, CheckRun/StatusContext and
review-page fields. Raw/envelope equality alone cannot establish completeness when both omit
the same key. Legitimate null/empty/pending and mixed check states remain valid; extra upstream
metadata is retained, not stripped or treated as a universal closed GitHub schema. Nonterminal
review cursors must advance without repetition. These checks do not authenticate unseen upstream
bytes or repair originals. The actual retained result remains explicitly NONCONFORMING.

The initial comparison has seven matching fields, fabricated claims unknown and live next action
not comparable. Every external-state dimension/support matched at that initial observation.
This does not include or conceal the separately reported admission-source mismatch.
Continuation independently observed main `2bc3034da1f84a981e33e9a9be1ad450aec95d23`, outranking the
checkpoint. Closed/merged facts and complete empty review threads remained current. The actual
terminal planner returned no blockers and four optional Project proposals; none was executed.
The successor recommended `leave_external_state_unchanged`. CI classification covers all returned
historical PR rollup entries, not a current required-CI verdict for #6236.

## Scoped measurements, repairs and capability

- Initial v2 interval `12:04:34–12:08:42`: 248 recorder-inclusive seconds, 55,875 packet bytes,
  6,630 response bytes, one successful start and two packet/response handoffs. Its shipped v2
  code/test, review, CI and admission-retry counters are zero; the separate metadata artifact repair
  is not reclassified as code/test work or silently omitted from the larger experiment.
- Actual observed nonconforming experiment interval `12:04:34–12:20:12`: 938 recorder-inclusive
  seconds, one start, two later ROLE requests, seven mandatory protocol/bundle transfers plus one
  extra invalid metadata transfer, and 3,320 continuation bytes. Continuation start-to-completion
  is 97 seconds. None of these wall intervals estimates model-active or human effort.
- Exactly three in-interval `implementation_repair` events remain separately bound: operator ID
  metadata artifact repair (`12:06:45`), finite anonymous-query spelling parser correction
  (completion observation `12:14:22`), and derived source-reference artifact correction
  (success observation `12:15:14`). The erroneous evidence-ref file remains retained and refused;
  a new corrected file supplied the actual packet-carried source ref. No original was rewritten.
- Admission retries, read-command corrections, review repairs and CI repairs within that observed
  interval are zero under the operator's complete-scope attestation. One later contract/reporting
  mechanism repair occurred after `12:20:12`; it includes the finite raw-source binding correction
  during local assembly and is not a fourth in-interval event. A separate later protected P1
  source-completeness review repair is retained in PR #6237 finding `4307098664` and its repair
  receipts, not backdated into that interval. Complete delivery totals are unknown.
- Archival capture/log wording predating the final join used planned/positive labels. Those raw
  labels remain custody, not a present conformance verdict; the current result is NONCONFORMING.

Actual native starts involved so far are four, with zero native admission rejection/fallback:

| Native context | Accepted configuration / observation |
| --- | --- |
| Sole writer | `gpt-6.1-sol/max`, history-free; parent observation 11:26:59, not exact process start |
| Invalid first successor | `gpt-6-luna/low`, history-free; observation 11:45:04, never activated |
| Retry1 successor | configured general-delivery `gpt-6-luna/xhigh`, history-free; 12:04:48 |
| Independent reviewer | configured verification `gpt-6.1-sol/max`, history-free; parent 12:22:51, own first clock 12:23:00 |

Accepted invocation configuration is not independent engine introspection. Root actual model and
reasoning, input/output tokens, monetary cost, model-active duration, human minutes and complete
delivery totals remain unknown. No cost/quality aggregate or universal threshold is inferred.

The first graph in `../manual_coordinator_rotation_6195_v1/` remains immutable invalid evidence:
its observer disclosed a dropped returned PR status field and estimated response timestamp.
No decision/quiescence/acknowledgment/activation/continuation occurred. Its 179-second recorder
interval is not a valid probe duration. It was a strict-capture adequacy repair, not native rejection.
Existing LearningSignal `lrn_20261018114847_d49ca83c` is reused; no duplicate store/learning ledger
or follow-up Issue is created. Task-local direct serialization/clock instructions and capability
reassessment were applied; the related later metadata-reporting correction is classified separately.

## Replay

From repository root with a supported Python interpreter, the strict command must refuse:

```bash
python3 -m app.builderops.manual_coordinator_rotation build \
  --input-file evidence/manual_coordinator_rotation_6195_retry1_v1/rotation-input.json \
  --capture-contract-file evidence/manual_coordinator_rotation_6195_retry1_v1/capture-contract.json \
  --expected-capture-sha256 36a2bda8af7a092d7b660fb203dd620790d57c1865bec01d8f5efa97d252f022
```

Explicit result replay accepts the factual nonconforming report, not frozen capture conformance:

```bash
python3 -m app.builderops.manual_coordinator_rotation verify-result \
  --input-file evidence/manual_coordinator_rotation_6195_retry1_v1/nonconforming-result.v1.json \
  --capture-contract-file evidence/manual_coordinator_rotation_6195_retry1_v1/capture-contract.json \
  --expected-capture-sha256 36a2bda8af7a092d7b660fb203dd620790d57c1865bec01d8f5efa97d252f022
```

The unchanged exact Verify test `test_retained_manual_rotation_replays_actual_chain` runs both
current/historical strict refusals and explicit serialized result replay. The remaining focused
matrix exercises hard identity/phase/target/fidelity/custody corruption, unknown measurements,
malformed/coerced/duplicate/nonfinite JSON, create-only aliases, no effects and v1/v2 compatibility.

Docs Governance Decision:

- Artifact role: reference/audit evidence, subordinate to the existing two current-state owner passages.
- Owner: Builder System / CES boundary, as already assigned by the governing Issue and SBS.
- Action: update existing manual-probe and routing passages with actual NONCONFORMING result and limits.
- Traceability: #6236 six ACs, unchanged Verify targets, exact retained source/phase/result bindings.
- DOCS_INDEX impact: none; no owner, role, canonical route or stable docs entrypoint changes.
- SBS/interface ownership: Builder evidence only; no Product/Runtime behavior or user memory.
- Next skill or no-change receipt: continue issue-to-code, publish-pr, verification-and-closure and PR-specific owner-doc reconciliation.
- Human Exception: none; bounded technical reporting repair, not a reserved owner decision.
