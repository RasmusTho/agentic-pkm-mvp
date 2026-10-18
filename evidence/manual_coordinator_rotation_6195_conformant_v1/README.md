# Actual conformant manual read-only role experiment

Issue [#6244](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6244) corrects exact admission
metadata transport and records one new manually activated read-only terminal-reconciliation role
for closed #6195 / merged #6200. The runtime receipt identity is
`manual_coordinator_rotation_6195_conformant.v1` at
[`writer/receipt.v1.json`](writer/receipt.v1.json). Its existing strict schema remains
`manual_coordinator_rotation_6195.v1`; no new protocol, equality relaxation or NONCONFORMING
fallback is used. Strict build and a separate-process verify both accepted first try and produced
byte-identical 15,217-byte receipts, SHA256
`733e4af975fb3755f1697616922f8ae799b2226a8fc355de95a690b6b365b75e`.
The actual results and post-replay clock are retained in
[`writer/strict-replay-native.original.json`](writer/strict-replay-native.original.json).

This proves one explicit operator-mediated read-only role boundary and fresh continuation. It
does not establish whole-session replacement, active-epic scheduling, process exclusion/fencing,
writer/lifecycle/lease transfer, automatic rotation/compression/dispatch/adoption, worker launch,
Product memory or production behavior. The operator/incumbent was the actual native `/root`,
not an asserted human click. The outer writer and its worktree/lease stayed unchanged.

## Exact producer and preserved history

The finite `metadata` mode in `app.builderops.manual_coordinator_rotation` validates the
independently pinned capture contract, accepted source, actor/target/context and actual retained
successful admission. It derives only the existing six-field v2 `agent` object by exact copies,
mapping admission `at`/`status` to response `start_observed_at`/`start_status`. It does not infer an
engine identity or paraphrase source explanation text. The same mode's optional
`--observation-file` is an exact pre-activation original-response check, never an activator.

The actual successor ran this producer after the retained native admission and before its own
live reads. It directly serialized stdout into
[`successor/initial/admitted-agent-metadata.original.json`](successor/initial/admitted-agent-metadata.original.json)
and used the same complete object as response `agent`. The admission projection, produced object
and original response match exactly, including
`unknown(native carrier exposes no independent engine identity)`. This derived metadata is not a
sixth live-read fact. The writer independently replayed the serialized metadata preflight,
source-fidelity join and unchanged v2 compare/telemetry/receipt before operator decision; raw
results are in [`writer/initial-validation-native.original.json`](writer/initial-validation-native.original.json).

The earlier [invalid first capture](../manual_coordinator_rotation_6195_v1/) and
[actual NONCONFORMING experiment](../manual_coordinator_rotation_6195_retry1_v1/README.md) remain
immutable. Their originals, differing engine-source strings, original strict refusal, archived
verifier and opt-in explicit NONCONFORMING result retain their original meaning. The whole two
historical prefixes are digest-pinned by the regression test; the old mismatch still strictly
refuses. No admission was manufactured or changed after a response to create equality.

## Fresh source and independent freeze

The new source captured current GitHub Issue/PR and complete one-page, zero-thread review truth,
direct `origin` / `refs/heads/main`, and dispatcher status. Actual source clocks were
`16:40:25Z`, `16:40:28Z`, and `16:40:29Z` on 2026-10-18. Direct main was
`6aa98b572a6dd497a3d035f0860bed40d613a306`. The existing evaluator emitted a new checkpoint;
the existing run-state dry-run preceded acceptance and equal readback. Raw native source outputs
and clock objects remain in [`accepted/source-capture.original.json`](accepted/source-capture.original.json).
These are source observations, not borrowed successor access.

The actual capture-contract clock was `16:43:05Z`. Root independently inspected and froze the
following bytes before the native successor invocation:

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| `context-pack.json` | 58,717 | `307f366b8eb960338d19b66bfb6c7342208e6d22a617e2dc3d579a1c78df5122` |
| `capture-contract.json` | 1,520 | `d945db4695e2534a2b4511ea14f63fce3bbe840e3bc0e7028983cc14e93f9deb` |
| `ingestion-contract.json` | 34,649 | `9fe0aabeb5fcf11704e61bd1f6dd5db4347347d5ff8ce6a1fd013d35389074db` |
| `accepted/source-checkpoint.json` | 3,912 | `a4fc299509eb72c736f8387b36df4adb58311fb1b698c156dfd3bfe33506d93b` |
| `accepted/run-state-readback.json` | 4,628 | `154fe509b448ff8698d561264ce5ed9209fc47c6bb60d6d5a916db0615b795d2` |

The [independent freeze](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6244#issuecomment-6252466896)
preceded invocation. The [actual admission](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6244#issuecomment-6252478763)
preceded actor release for metadata/live capture. The independent expected capture digest was
carried separately, never recomputed from a changed admission or response. The ingestion schema
bytes are unchanged from the strict protocol. The packet carries the full response/read/fidelity/
acknowledgment/continuation schemas, exact vectors, sanctioned read-only permission boundary and
direct-serialization/clock instructions. The successor received only that packet, its carried
instructions and exact operational metadata, not prior chat, implementation reasoning, code/tests
or source-custody contents. Its admitted role was `/root/manual_rotation_successor_6244`.

## Actual manual chronology

All times below are actual UTC observations on 2026-10-18, not estimated process times. Native
command output strings and `clock.curr_time` objects are directly retained in the two fidelity
originals and operator event records.

| Observation | UTC |
| --- | --- |
| Pre-native-request clock | 16:45:04 |
| Successful native admission observation | 16:45:18 |
| Exact admission-metadata handoff observation | 16:46:25 |
| Initial GitHub / repository / dispatcher clocks | 16:47:03 / 16:47:10 / 16:47:16 |
| Initial original response / root readback | 16:48:29 / 16:49:40 |
| Separate explicit operator decision | 16:51:44 |
| Incumbent experimental-role quiescence | 16:51:53 |
| Acknowledgment request / same-actor acknowledgment / root readback | 16:52:12 / 16:52:24 / 16:52:49 |
| Distinct manual activation / activation handoff | 16:52:59 / 16:53:11 |
| Same-successor continuation start | 16:53:36 |
| Continuation GitHub / repository / dispatcher clocks | 16:53:52 / 16:53:55 / 16:53:55 |
| Continuation original completion / root readback | 16:55:17 / 16:56:29 |

The initial five and continuation six raw commands all completed with exit 0 and no truncation.
Requested Issue5/PR8 fields, nested GitHub rollup families, complete progress-safe review pagination,
direct remote SHA/ref, dispatcher objects, planner argv/output and actual clocks are cross-bound
by the strict consumer. Both complete live review reads found zero threads. Both fresh direct
main reads observed `6aa98b572a6dd497a3d035f0860bed40d613a306`, agreeing with the checkpoint;
live truth would still outrank drift. Seven initial field results match (six comparable fields
plus missing-claim reporting); fabrication is unknown, live next action is not comparable and
refresh is not required. Historical all-returned PR-rollup CI is green in this capture; it is not
a current required-CI or delivery merge verdict.

Root inspected the actual comparison and raw fidelity before a distinct decision. Quiescence
applied only to its incumbent experimental read-only role. The same successor acknowledged before
separate activation, then refreshed every live source and ran the actual existing no-effect
terminal planner. Its output contained four optional Project projection proposals; none was
executed. The original recommendation is retained verbatim in the continuation and strict receipt:
leave external state unchanged. This did not create or authorize another follow-up Issue.

## Scoped measurement and capability

- Initial interval `16:45:04–16:49:40`: 276 recorder-inclusive seconds, 58,717 packet bytes,
  7,049 original-response bytes, one successful native start and two v2 packet/response transfers.
- Full experiment interval `16:45:04–16:56:29`: 685 recorder-inclusive seconds, one successor
  start, two later native phase follow-ups and seven mandatory artifact/bundle transfers. The
  distinct metadata handoff is counted here. Continuation is 3,611 bytes; its own start-to-completion
  interval is 101 seconds. Packet-transfer time is the observed native acceptance tick, not a
  claimed exact transport instant.
- Recorder-complete scoped admission retries, implementation/review/CI repairs and capture-command
  corrections are zero. Planned source preparation, an earlier local cross-filesystem hardlink-test
  adjustment and runpy invocation correction preceded this interval. Later planned retained-test,
  docs, evidence-registration and delivery work is separate, not backdated into it.
- One unrelated writer publication-preparation `rg` diagnostic failed shell-glob expansion without
  retry during the wall interval. It was not a successor live-capture/producer/planner command or
  a code/test/derived repair. The event totals are experiment-domain counts, never an all-delivery
  zero-tool-failure claim. Whole-delivery duration and correction totals remain unknown.

The writer was actually admitted as configured `strong_reasoning`, `gpt-6.1-sol/max`, history-free;
root observed success at `16:30:14Z`. The successor was actually admitted as configured
`general_delivery`, `gpt-6-luna/xhigh`, history-free at `16:45:18Z`. At experiment end these were
two actual native starts in this slice, with zero native rejection/fallback; an independent
current-SHA verification invocation was still a later delivery step, not a third experiment
start. Accepted invocation configuration is not independent engine introspection. Engine identity,
root actual model/reasoning, input/output tokens, monetary cost, model-active time, human minutes
and whole-delivery totals remain unknown. Bytes are not tokens; wall time is not model or human
effort. No universal score, fixed threshold or automatic policy follows.

This new run had no invalid candidate, rejected admission or fallback. The unchanged generic strict
receipt's `scope_exclusions` mentions the historical invalid first candidate; that exclusion is not
evidence of another start in this run. After the 685-second interval, root's first read-only summary
formatter incorrectly expected the CLI acknowledgment to contain full receipt measurements and
threw after strict verify had already returned 0. Reading the retained receipt and repeating pure
verify corrected only that later display; no original, source or code changed. This is later delivery
logging, not an experiment repair or a measured whole-delivery total. The durable operator result is
[the Issue receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/6244#issuecomment-6252629722).

## Replay

From repository root, separate serialized strict verification accepts:

```bash
python3 -m app.builderops.manual_coordinator_rotation verify \
  --input-file evidence/manual_coordinator_rotation_6195_conformant_v1/writer/receipt.v1.json \
  --capture-contract-file evidence/manual_coordinator_rotation_6195_conformant_v1/capture-contract.json \
  --expected-capture-sha256 d945db4695e2534a2b4511ea14f63fce3bbe840e3bc0e7028983cc14e93f9deb
```

Replacing `verify`/receipt input with `build`/`writer/rotation-input.json` independently rebuilds
the same strict receipt. Supplying a new `--output` path is create-only; existing files, aliases
and partial outputs refuse. The regressions exercise serialized metadata and strict consumers,
malformed/duplicate/non-finite/coerced JSON, phase/source/actor/target/context rebinding, requested
field omissions, legitimate nested families, advancing pages, original preservation and no effects.
The actual retained-chain test is separate from synthetic negative-proof fixtures.

Historical strict refusal and opt-in explicit NONCONFORMING replay remain separate:

```bash
python3 -m app.builderops.manual_coordinator_rotation build \
  --input-file evidence/manual_coordinator_rotation_6195_retry1_v1/rotation-input.json \
  --capture-contract-file evidence/manual_coordinator_rotation_6195_retry1_v1/capture-contract.json \
  --expected-capture-sha256 36a2bda8af7a092d7b660fb203dd620790d57c1865bec01d8f5efa97d252f022

python3 -m app.builderops.manual_coordinator_rotation verify-result \
  --input-file evidence/manual_coordinator_rotation_6195_retry1_v1/nonconforming-result.v1.json \
  --capture-contract-file evidence/manual_coordinator_rotation_6195_retry1_v1/capture-contract.json \
  --expected-capture-sha256 36a2bda8af7a092d7b660fb203dd620790d57c1865bec01d8f5efa97d252f022
```

The first historical command exits 2 with its unchanged exact source-explanation refusal; the
second exits 0 with explicit NONCONFORMING reporting. Neither result substitutes for this new
conformant chain. Required current-head delivery CI and independent review remain separate gates.
