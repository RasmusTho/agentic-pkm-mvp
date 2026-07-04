State: Advisory research artifact (RESEARCH-03, issue #2781, epic #2778; 2026-07-04). Registry-extension proposal for `docs/testing/invariant-tests.md` — it does NOT edit the live registry. Property specs become enforceable through the bounded follow-up issues filed from this artifact; registry adoption of the new entries is an explicit owner/CES step, not a side effect of merging this doc.
Doc role: Reference (testing / fitness synthesis)
Authority: Evidence-based; derives every proposed invariant from `docs/architecture/formal-model.md` (RESEARCH-02) §3, the kernel audit (`docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md` §2), and post-kernel delivery state (14 of 16 kernel children closed as of 2026-07-04). Where this artifact and an owner doc disagree, the owner doc wins.

# Invariant Synthesis 2026-07 — Formal Model → Machine-Checkable Properties

The registry (`docs/testing/invariant-tests.md`, 28 named invariants) grew from architecture
foundation work; the Runtime Correctness Kernel (#2762) grew from the 2026-07-02 audit. Both accreted
from incidents and audits. This artifact is the systematic pass the registry never had: it takes the
formal model's transition system (Σ, T‹name›, Q/C invariants) and derives, for **every model
invariant not yet enforced**, a property-based test specification a Sonnet-tier agent can implement
without re-deriving the theory.

Method: start from `formal-model.md :: 3. Invariants :: Gaps, model → registry` (the five candidates
RESEARCH-02 explicitly recorded for this pass), add the residues its §7 divergences and the
post-kernel audit issues (#2899, #2901) left open, subtract everything the kernel children already
enforce, and convert the remainder into hypothesis-style property specs with named `Verify:` targets.

## What is already enforced (subtracted, not re-specified)

| Model invariant | Enforced by | Evidence |
|---|---|---|
| I-S2 transactional vault-sync | KERNEL-01 #2763 (+ #2864, #2896 hardening) | `tests/integration/test_vault_sync_atomicity.py` |
| I-E1 mandatory idempotency keys | KERNEL-02 #2764 | outbox tests + no-None-callsite gate |
| I-S4/I-S1 fail-loud store resolution (partial) | KERNEL-03/04 #2765/#2766, decisions writer #2788 | startup fail-loud tests; **residue: #2901** (second writer generation still live — see P-6) |
| I-D3 retrieval reads durable index | KERNEL-05 #2767 | kill-and-restart test, `rebuild_from_durable_index` |
| I-D1 transform provenance | KERNEL-06 #2768 | doctor staleness + incremental reconcile |
| I-A2 UNKNOWN route | KERNEL-07 #2769 | garbage-stub fuzz test |
| I-E5/I-C1 typed topics | KERNEL-08 #2770 | topic schema registry coverage test |
| I-A4 plan admission + wall-clock | KERNEL-09 #2771 | admission-rejection fixtures |
| I-E2 handler idempotency | KERNEL-11 #2773 | dispatch-twice harness (`tests/.../test_handler_idempotency*`) |
| I-E4 dead-letter loud | KERNEL-12 #2774 | health-contract surfacing test |
| I-A5 scope prefilter + envelope | KERNEL-10 #2772 (in delivery) | `tests/retrieval/test_scope_prefilter_before_rank.py` (per spec) |
| Registry rows 1–28 | as listed in `invariant-tests.md :: Coverage map` | schema/static/runtime/xfail as registered |

The registry's remaining `xfail_runtime_skeleton` rows (promotion, projection-not-evidence,
authority-transition mutation path, execution self-authorization, sibling aggregation, sync,
observability-not-policy, storage-write-not-authority, propose-when-uncertain) are **already
registered obligations** — they need their runtime slices, not new specs. This artifact adds only
what no registry row and no kernel child covers.

## Property specs

Conventions: hypothesis-style state-machine sketches (`RuleBasedStateMachine`); `hypothesis` becomes
a dev-dependency when the first follow-up lands (it is not installed today — the follow-up issues
carry that). Every spec names its enforcement-category **target** using the registry's categories,
and a `Verify:` commitment under the proposed `tests/properties/` layout (below). TCD hints use
`AGENTS.md :: Total Cost of Development` vocabulary.

### P-1 `guard_asserted_at_write_seam`

- **Purpose:** WriteGuard is asserted *inside* every seam that can write the vault — never left to
  caller convention. A new caller of a write seam is safe by construction.
- **Derivation:** formal model gap 1. The seam-local fixes have since landed one by one — F-A panel
  writeback (#2808, `app/agents/panel_agent/runtime.py` now asserts `"panel.writeback"` at the
  seam), F-B settings writeback (#2809), F-F note_hygiene (#2810, guarded), vault-layout scaffolder
  (#2877) — which proves the *class* keeps recurring and being fixed retail. Still unguarded on
  `main` (verified 2026-07-04): the knowledge write port itself
  (`app/knowledge/write_ops.py::write_note_from_absolute` — the shared root cause), identity-heal
  (`app/vault/manager.py::_ensure_frontmatter_id` via `write_frontmatter`), and the checkbox-rollback
  compensating write (`app/panel/checkbox_projection.py` exception handler calling
  `write_note_from_absolute` directly). The strongest form asserts WG inside the port with a named
  bootstrap escape (the #2877 `DEFAULT_BOOTSTRAP_ACTIONS` precedent: a denying guard still blocks;
  only genuine pre-selection provision passes); the property then pins the class wholesale so the
  next new seam is safe by construction instead of by the next retail fix.
- **Property spec (two layers):**
  - *Static gate* (cheap, catches new seams): enumerate every non-test call path that reaches a
    vault-writing primitive (`write_text`/`write_frontmatter`/knowledge-port functions) and assert
    each transitively passes a `WriteGuard.assert_writes_allowed` call in the same seam module or is
    on the registered bootstrap-escape list. Generator: the import/call graph itself (no hypothesis).
  - *Runtime property*: `given(seam=sampled_from(REGISTERED_WRITE_SEAMS), guard_state=denying_guard())`
    → operations: invoke the seam with a fixture artifact → assertion: the write raises/blocks and
    the vault fixture is byte-identical (atomicity of the block, per the #2877 scaffolder shape).
- **Enforcement target:** `static_test` (gate) + `runtime_test` (property) — GATE class.
- **Verify:** `tests/properties/test_guard_at_seam.py::test_every_write_seam_asserts_writeguard`,
  `::test_denying_guard_blocks_atomically`.
- **TCD hint:** Sonnet / high (call-graph enumeration has hidden edges; two prior partial fixes —
  #2809 settings writeback, #2877 scaffolder — define the pattern to generalize).

### P-2 `event_completeness_or_registered_mirror`

- **Purpose:** every `P.objects` / `P.vectors` mutation either emits its outbox event or occurs at a
  call site on a **registered mirror list** — so `replay(P.outbox, V)` reconstructs `P` up to a
  *named*, reviewable exception set instead of an unknown one.
- **Derivation:** formal model gap 2 and seam C8 (11 production `save_object(emit_outbox=False)`
  sites enumerated in `formal-model.md :: 4`, e.g. `app/services/indexer.py` (the T-materialize sink,
  legal by design — the causing event is its own record), `app/promotion/consumer.py`,
  `app/agents/panel_agent/*`). Incident class: #2863 — an observation-scope `save_object` outbox-key
  defect meant content changes *emitted nothing*; the fix landed 2026-07-04, but nothing today
  prevents the next silent-mirror regression.
- **Property spec:** state machine over a fixture vault + memory-backend stores.
  Generators: sequences of model transitions (`T-sync`, `T-materialize`, `T-promote`, panel
  writeback, delete/rename) with random note contents/paths.
  Operations: apply each transition through the real app seam.
  Assertion (invariant checked after every step): for each `P.objects`/`P.vectors` row mutated in
  the step, either ≥1 outbox row exists whose `(topic, idempotency_key)` derives from that mutation,
  or the mutating call site ∈ `REGISTERED_MIRRORS` (a small in-repo constant list with one-line
  justifications, created by the follow-up). Completeness corollary: replaying the collected events
  against a fresh store reproduces all non-mirror rows.
- **Enforcement target:** `runtime_test` (property) + `static_test` (the mirror list is closed: grep
  gate that every `emit_outbox=False` call site is listed).
- **Verify:** `tests/properties/test_event_completeness.py::test_mutations_emit_or_are_registered_mirrors`,
  `::test_replay_reproduces_non_mirror_state`.
- **TCD hint:** Sonnet / high for the harness; Haiku / low for the mirror-list census (it is already
  enumerated in the formal model).

### P-3 `read_purity_except_registered_heals`

- **Purpose:** no GET/read path mutates durable state, except transitions on a registered heal list
  (heal-on-read is legal only when declared: `T-uuid-heal` and identity-heal are transitions, not
  side effects).
- **Derivation:** formal model invariant Q4, violated three ways today (uuid-heal from
  `GET /companion/workspace`, identity-heal from lazy vault load via
  `app/vault/manager.py::_ensure_frontmatter_id`, ASK's receipt appends to J-sinks). Model verdict:
  the *undocumented* ones are the defect, not healing itself. ASK's J-appends are advisory-sink
  writes (FD-J, losable by declaration) — the registered list classifies them explicitly rather than
  pretending they do not exist.
- **Property spec:** route-walk property. Generators: every registered GET/read route (enumerated
  from the FastAPI app's route table — dynamic, so a new route cannot silently escape) × fixture
  vault states (with/without uuid, healthy/unhealthy guard). Operations: call the route with spy
  wrappers on vault-write primitives, store connections, and sqlite files. Assertion: zero durable
  writes unless the (route, write-class) pair ∈ `REGISTERED_HEAL_TRANSITIONS` / registered advisory
  J-sinks; registered heals must additionally be WG-gated (ties into P-1).
- **Enforcement target:** `runtime_test`; the route-table enumeration makes it a no-silent-cap gate
  (new route without classification = failure, mirroring the #2773 harness rule).
- **Verify:** `tests/properties/test_read_purity.py::test_get_routes_do_not_write_durably`.
- **TCD hint:** Sonnet / medium (mechanical once the spy fixture exists; the fixture is the work).

### P-4 `guards_fail_closed`

- **Purpose:** a WriteGuard *evaluation error* blocks the write (fail-closed). A guard that fails
  open is not a guard.
- **Derivation:** formal model gap 4. Known deliberate violation: `note/save` fails open on guard
  evaluation error (`app/api/routes/companion.py`, deliberate per inline comment) — divergence
  **F-C, needs-owner-decision** (human-edit availability vs gate integrity), surfaced on epic #2778.
- **Property spec:** `given(seam=sampled_from(REGISTERED_WRITE_SEAMS), guard=raising_guard())` →
  invoke seam → assert write blocked + vault unchanged + a loud, classifiable error surfaced (not a
  swallowed exception). Note the asymmetry with P-1: P-1 tests a *denying* guard, P-4 tests a
  *broken* guard.
- **Enforcement target:** `runtime_test` for all seams except `note/save`;
  `doc_only` for `note/save` **until the named owner decision F-C resolves** — this is the single
  permitted doc_only in this artifact, per the issue constraint ("except where a named owner
  decision blocks enforcement"). The spec is written; flipping F-C to fail-closed makes it
  enforceable with a one-line change to the seam list.
- **Verify:** `tests/properties/test_guard_at_seam.py::test_raising_guard_blocks_write` (shares the
  P-1 module and seam register).
- **TCD hint:** Haiku / low once P-1's seam register exists (same machinery, different guard stub).

### P-5 `receipt_before_ack`

- **Purpose:** generalize the T-capture shape: a mutating API transition acknowledges success only
  after its authority receipt/event row is durable. An effect whose accountability record can be
  lost was never accountable.
- **Derivation:** formal model gap 5; T-capture is the reference shape
  (`app/api/routes/capture.py` — ACK only after the event row persists, else
  `authority_receipt_persistence_failed`). Q3's durability residue: D-1 settings receipts fixed
  (#2787); remaining residue **D-7-adjacent**: `app/agents/reviewer/agent.py` and
  `app/agents/set_evaluator/agent.py` still wrap decision writes in their own `try/except: pass`,
  re-swallowing at the call site what #2788 made fail-loud in the writer.
- **Property spec:** per mutating route/transition on a registered list: inject a failing
  event/receipt store (raises on insert) → invoke → assert the HTTP/CLI result is a failure (5xx or
  non-zero), never a success-with-lost-receipt. Second operation class: kill-window ordering — with
  a recording store, assert the receipt insert happens-before the ACK write point (ordering
  assertion, not wall-clock).
- **Enforcement target:** `runtime_test` per transition, rolled out incrementally along the
  registered transition list (T-capture first as the passing exemplar, then panel confirm, review
  decide, promote); the caller-side swallow residue is a bounded code fix inside the same follow-up.
- **Verify:** `tests/properties/test_receipt_before_ack.py::test_failing_receipt_store_fails_the_transition`.
- **TCD hint:** Sonnet / medium-high (touches error paths on real routes; needs care not to change
  behavior contracts while pinning them).

### P-6 `single_writer_per_table`

- **Purpose:** each durable table has exactly one writing module (audit I-S1); a second writer
  generation cannot silently coexist.
- **Derivation:** audit I-S1; **live violation found post-kernel: #2901** — `PgObjects` writes both
  `store_objects` and legacy `objects` with no assert guard. #2901 owns the *fix*; this property
  pins the invariant so the class cannot recur.
- **Property spec:** static enumeration (no hypothesis): for each durable table name, grep/AST-walk
  the writers (INSERT/UPDATE/UPSERT sites) and assert the writer-module set matches a declared
  one-writer map (`docs/DB_SCHEMA.md` as the naming source). New table without a declared writer =
  failure (no silent cap).
- **Enforcement target:** `static_test` GATE.
- **Verify:** `tests/properties/test_single_writer.py::test_one_writer_module_per_table`.
- **TCD hint:** Haiku / low–Sonnet / medium (AST walk is mechanical; the declared map needs one
  careful authoring pass). **Reconcile:** lands *after or with* #2901's fix, never before (it would
  fail red on a known issue).

### P-7 `tombstone_preserves_lineage`

- **Purpose:** deleting a note leaves a `P.objects` tombstone (`path=NULL`) and every decisions/audit
  row anchored to it survives with intact FK references — the D-2 ratified contract, pinned.
- **Derivation:** runtime-semantics D-2 (ratified: tombstone), D-5 resolution (#2788 realigned
  `decisions.object_id` to `ON DELETE SET NULL`); formal model Q2 (lineage never truncated) and the
  §5 coupling caveat (FD-P canonical logs are meaningful only with the object rows they reference).
- **Property spec:** generators: fixture vault notes with decision/audit rows attached; operations:
  human-delete → watcher delete propagation (`vault_sync.delete_note`), optional re-ingest of a new
  note at the same path; assertions: objects row persists with `path=NULL`; decisions/audit rows
  unchanged and non-orphaned; vectors purged; the re-ingested note gets a *new* object_id (no
  identity resurrection).
- **Enforcement target:** `runtime_test` (also serves as the regression floor under any future
  event-triggered-decay lifecycle work — the decay design must *change this test deliberately*, not
  break it silently).
- **Verify:** `tests/properties/test_tombstone_lineage.py::test_delete_leaves_anchored_tombstone`.
- **TCD hint:** Sonnet / medium.

## Priority

Ranking by blast radius = (what breaks) × (how silently), each tied to a real incident class:

| # | Property | Incident class it would have caught | Why this rank |
|---|---|---|---|
| 1 | P-2 event_completeness | **#2863** (observation-scope content changes emitted nothing, 2026-07); **#2242** (`processed_total=0` for weeks — consumption silently absent); CW-1 class | The system's costliest failure mode is "quietly does nothing"; P-2 makes the event log's honesty machine-checked instead of audited annually |
| 2 | P-1 guard_at_seam | F-A class — panel CLI/worker writes ran unguarded until #2808 (2026-07); four retail fixes in one week (#2808/#2809/#2810/#2877) prove recurrence; #1991 class (half-applied producers → 2026-06-14 promotion slog) | Only invariant whose violation lets an agent mutate the canonical plane ungoverned; three seams still open (port, identity-heal, checkbox rollback) |
| 3 | P-5 receipt_before_ack | D-1 (settings receipts unreproducible pre-#2787); reviewer/set_evaluator swallow residue (live) | Accountability substrate for every governed write; cheap to pin now, expensive to retrofit after more transitions accrete |
| 4 | P-6 single_writer | **#2901** (live: dual object-writer generations); CW-1 dual-schema history (`embeddings` vs `store_vector_index`) | Recurred once already after the kernel "fixed" it — exactly the class that needs a gate, not a cleanup |
| 5 | P-3 read_purity | Q4 violations (uuid-heal from GET, lazy identity-heal) — no incident yet, but #2903/#2905 (watcher scan-loop raising per-note) shows how unclassified side effects on hot read paths compound | Bounds the mutation surface; makes the formal model's transition catalog *stay* total |
| 6 | P-7 tombstone_lineage | D-5 (decisions would have CASCADE-vanished on first object cleanup; fixed #2788) | Fixed-code needs a pin; also the floor for the future decay lifecycle |
| 7 | P-4 guards_fail_closed | F-C (note/save deliberate fail-open) | Spec ready; enforcement gated on a named owner decision — rank reflects the decision dependency, not importance |

## Proposed `tests/properties/` layout and CI placement

```
tests/properties/
  __init__.py
  _machinery.py        # seam register (REGISTERED_WRITE_SEAMS), REGISTERED_MIRRORS,
                       # REGISTERED_HEAL_TRANSITIONS, spy-store fixtures, denying/raising guards
  test_guard_at_seam.py        # P-1, P-4
  test_event_completeness.py   # P-2
  test_read_purity.py          # P-3
  test_receipt_before_ack.py   # P-5
  test_single_writer.py        # P-6 (static; no hypothesis)
  test_tombstone_lineage.py    # P-7
```

- **CI placement:** all `not pg` (memory-backend stores + fixture vault; no Postgres dependency),
  running in the standard PR gate. Stateful hypothesis runs use bounded profiles
  (`max_examples` small in CI, larger in the nightly/dispatch lane) so the gate stays fast — the
  same posture the eval runner uses for thresholds.
- **Import-gate honesty rule:** `tests/invariants/_helpers.py::require_future_runtime` converts
  *only* "the target module does not exist yet" into xfail and re-raises real breakage. The property
  layer adopts the same rule for seams that do not exist yet: a property whose seam register entry
  is not yet implementable xfails with a named reason, and a broken seam fails loudly. No blanket
  `@pytest.mark.xfail`.
- **Verify-the-verifier:** `harness-selfverify` gains one intentional-violation fixture per property
  cluster (e.g. an unregistered `emit_outbox=False` call in a test-only module MUST fail P-2's
  static gate) — the registry's closed-on-green rot rule applied to this layer from day one.
- **Dependency:** `hypothesis` added to dev dependencies by the first follow-up (absent today).

## Spec-shape dry run (Suggested Validation)

A throwaway P-2-shaped state machine (stdlib-random miniature over an in-memory store + event-log
pair, three operation classes, mirror-list exception) was implemented and executed during authoring
to prove the spec shape is implementable exactly as written above: mutation-without-event detected
on an unregistered site in <100 random steps; registered-mirror path passes; replay comparison
reproduces the non-mirror rows. Decision (in-PR): **deleted, not kept** — the real implementation
belongs to the follow-up issues with `hypothesis`, and a committed toy would rot into a false
exemplar. Result recorded here; run log in the PR body.

## Follow-up issues

Filed 2026-07-04 (bounded, one property-cluster each, TCD hints inline; reconciled against #2762
children — no overlap with the #2773 dispatch-twice harness, which covers handler idempotency, not
producer completeness):

- **#2909** — `tests/properties/` bootstrap + P-2 event-completeness property + registered-mirror
  census (prio:high, ready; the other four depend on its `_machinery.py`).
- **#2910** — P-1 + P-4 guard-at-seam static gate + denying/raising-guard properties + the three
  remaining unguarded seams (knowledge write port, identity-heal, checkbox rollback; generalizes
  the closed retail fixes #2808/#2809/#2810/#2877).
- **#2911** — P-3 read-purity route-walk property + registered-heal list.
- **#2912** — P-5 receipt-before-ack ordering property + reviewer/set_evaluator swallow fix.
- **#2913** — P-7 tombstone-lineage property (D-2 pin + decay-lifecycle regression floor).
- **P-6 routed onto #2901** (comment posted): the live dual-writer defect already has a contract;
  the single-writer gate lands with its fix rather than as a duplicate issue.

## SBS reconciliation (binding)

- **Conforms:** every property is an OEF fitness probe over existing boundary contracts (GOV write
  protocol, PDM/DRI persistence semantics, RCA candidate semantics); OEF observes and gates CI, GOV
  keeps normative authority — no probe closes a loop itself (`invariant-tests.md` posture, ADR-0022,
  ADR-0035).
- **Extends:** (a) the registry's enforcement-category vocabulary gains a de-facto `property_test`
  flavor — recorded here as `runtime_test` with stateful generators, so **no format fork**; (b) the
  registered-exception lists (mirrors, heals, bootstrap escapes) are new small OEF-owned code
  artifacts. Both route to CES with the registry-adoption step.
- **No reshape proposed.**

## Registry adoption (owner/CES step, not this PR)

On ratification, P-1…P-7 become registry entries in the standard entry format (purpose, protected
principle, boundaries, fixture, failure mode, enforcement, test path). Protected-principle mapping:
P-1/P-4 → matrix #9/#15 (governed mutation); P-2/P-5 → #3/#9 (provenance, receipts); P-3 → new
sub-commitment under #9 (reads are not writes); P-6 → #12 (storage discipline); P-7 → #3 (lineage).

## Related docs

- `docs/architecture/formal-model.md` §3 (gap list this artifact consumes), §4 (C8 census), §7 (F-A…F-F)
- `docs/architecture/runtime-semantics.md` (D-1…D-7 dispositions; D-2 tombstone ratification)
- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md` §2 (I-* proposal this extends)
- `docs/testing/invariant-tests.md` (the registry; conventions reused, never forked)
- `docs/foundation/ARCHITECTURAL_CONSTITUTION.md` (RESEARCH-07; principles these properties evaluate)
- Post-kernel audit issues: #2899 (integration coverage), #2901 (second writer generation)
