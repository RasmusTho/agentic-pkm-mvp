State: Specification (design + bounded slices). Advisory until child issues are delivered. Covers G4: state-diff gate on the relevance tick, proactivity tiers bound to proportional governance + typed CrossScopeFlow, and the user quiet-mode dial.
Doc role: Specification (capability design: proactivity)
Authority: Owns the G4 design. Subordinate to `docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md`, `docs/CAPABILITY_CONTRACT_MODEL.md :: Proportional governance tiers` (#1881), `docs/architecture/cross-scope-flow.md`, and the CRE spec (`docs/CONTEXTUAL_RELEVANCE_ENGINE/`). Adds bindings and one new typed grant use; changes no existing authority rule.
Owner: Architecture / product (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed — code citations current; design is proposal
Last reviewed: 2026-07-05

# Proactivity Tiers, State-Diff & Quiet Mode (G4)

Current reality: the governed proactive loop exists and is live — `run_relevance_tick` computes
moments, materializes them through WriteGuard with receipts, and runs the attention loop's reach-out
decisions (`app/watcher/relevance_tick.py:43-106`), with a deterministic interruptibility threshold
and a hard zero-tolerance floor (`app/relevance/interruptibility.py:19-36`). Three deficits, per the
audit: (1) the evaluator runs on **every tick** regardless of whether anything changed
(`relevance_tick.py:73`); (2) the tier ladder from Observer→Partner has no formal binding to our
governance model, which is exactly where a boolean "just do it" flag would sneak in; (3) the human
has no persistent dial — interruptibility is env-fed (`RELEVANCE_INTERRUPTIBILITY`), not a settings
surface.

## 1. State-diff gate (the cost + churn lever)

**Contract.** The tick becomes `snapshot → diff → (evaluate only on delta)`:

```
RelevanceSnapshot
  snapshot_version   schema version
  vault_generation   cheap change signal(s): registry watcher revision / durable-store generation
  inputs_digest      hash over the evaluator's *declared inputs* (see below)
  computed_at        timestamp (for staleness diagnostics, not for decay semantics)
```

- The evaluator **declares its inputs** (the note-sets/patterns it reads). The digest covers exactly
  those; an input the evaluator does not read cannot force a wake-up. This keeps the gate honest as
  evaluators evolve — adding an input means extending the declaration, or the new input has no
  effect (visible in review, not silent).
- Persisted under `runtime/relevance/snapshot.json` — **derived and rebuildable**; deleting it
  causes one full evaluation, never an error (mirrors the derived-store posture).
- Gate semantics: digest unchanged ⇒ skip evaluation *and* skip materialization *and* emit nothing
  (no receipt churn — silence is free). Digest changed ⇒ run exactly today's path unchanged.
  A `force` escape exists for operator diagnostics (`relevance tick --force`).
- The gate never suppresses **time-triggered** patterns: declared patterns with time semantics
  (deadlines) contribute a time-bucket component to the digest so a due-threshold crossing *is* a
  delta. This is the one subtlety that makes naive state-diffing wrong — a vault can be unchanged
  while a deadline arrives.
- Today's `DeterministicRelevanceEvaluator` is cheap; the gate's real payoff is (a) receipt/attention
  churn now and (b) making an LLM-backed evaluator affordable later without renegotiating the loop.
  Build the gate before the expensive evaluator exists, not after it hurts.

## 2. Tier binding — the field's ladder mapped onto ours, nothing new invented

The field's Observer/Advisor/Assistant/Partner is a re-derivation of #1881. We bind, we do not add a
parallel system (`docs/CAPABILITY_CONTRACT_MODEL.md :: Tier definitions`):

| Proactivity tier | What the system may do | Binding (existing mechanism) |
|---|---|---|
| **Observer** | materialize moments; surface read-only at `GET /api/companion/now` | shipped today; `act`-tier materialization (reversible, vault-internal) with receipts |
| **Advisor** | attach a draft/proposal to the moment | Panel suggested-unchecked-checkbox path (GRADUATED_CURATION propose track); WriteGuard-gated; no same-pass execution |
| **Assistant** | apply reversible, vault-internal effects tied to a moment | `act` / `agent-review` tiers exactly per the #1881 per-flow table — the moment adds *no* authority; the flow's tier decides |
| **Partner** | outbound/external delivery (OS push, send) | **typed `CrossScopeFlow` grant only** — see below. OS-send remains deferred (`docs/HUMAN_FLOW_TO_RUNTIME_MAP.md:53`); this row defines the shape it must take when un-deferred |

**The Partner rule (the anti-boolean clause).** External delivery is an `export`-class operation —
material leaves the local trust boundary (`docs/architecture/cross-scope-flow.md:60-76`: export "is
its own high-sensitivity grant"). It is exercisable only under a `CrossScopeFlow` with:
`allowed_operations: [export]` scoped to a named delivery channel, `confirmation_required` per the
#1881 `ask-you` line for external effects, `audit_required: true`, and `expiry` set (grants are
bounded, not perpetual). There is no `proactive_send: true` setting anywhere in the system — the
invariant test asserts the delivery seam takes a flow grant object, not a flag. A standing grant
("morning digest to my phone, expires in 90 days") is legitimate *because* it is typed, named,
expiring, and audited — that is the difference between a dial and a bypass.

**No authority laundering through moments.** A moment is context, never authorization: nothing in
the attention loop may treat "a moment fired" as satisfying `confirmation_required` for any flow.
This is the precise failure mode the field's Partner tier smuggles in, and it gets its own probe.

## 3. Quiet-mode dial

A persistent, human-writable setting — not an env var — honoring the settings-as-writable-surface
posture:

- Surface: `@Settings/proactivity.md` (owner decision 7 for final location), compiled like other
  settings notes. Fields: `mode: quiet | normal | active`, optional per-channel minimums, optional
  schedule (e.g. `quiet: 21:00-07:00`).
- Semantics compose with — never replace — the deterministic threshold
  (`app/relevance/interruptibility.py`):
  - `quiet` ⇒ all gated rungs unreachable (the existing `(None, None)` default-to-silence curve),
    pull surfaces (`/api/companion/now`) unaffected. Quiet is a *ceiling on surfacing*.
  - `normal` ⇒ seeded curve as today.
  - `active` ⇒ may lower rung minimums by at most one band; **cannot** touch the zero-tolerance
    floor (`ZERO_TOLERANCE_STATES` remains absolute) and cannot reach Partner without a flow grant.
- The dial **never** affects governance: WriteGuard, receipts, materialization, and audit are
  identical in every mode. Quiet mode silences the megaphone, not the ledger. (Materialization
  continues under quiet — moments accumulate for pull; only reach-out is capped. This is deliberate:
  "stays quietly in the background until needed" means the background keeps working.)
- Uncertain/missing setting ⇒ `normal`; unreadable settings file ⇒ fail toward `quiet` (silence is
  the safe direction for reach-out, per the reach-out contract's default-to-silence rule).

## 4. Slices

1. **G4-1 State-diff gate.** Snapshot + declared-inputs digest + time-bucket component + gate in
   `run_relevance_tick` + `--force`. No behavior change when a delta exists.
   `Verify:` `tests/relevance/test_state_diff_gate.py` (unchanged vault ⇒ no evaluation/receipts;
   changed note ⇒ evaluation; deadline crossing with unchanged vault ⇒ evaluation; deleted snapshot
   ⇒ full run), `tests/invariants/test_proactivity_invariants.py::test_tick_reasons_only_on_delta`.
   Deps: none. **Sonnet.**
2. **G4-2 Tier binding + Partner flow schema.** Codify the binding table as policy data (not prose):
   the attention loop consults flow grants for any outbound rung; delivery seam signature takes a
   grant, not a flag; moments-are-not-authorization assertion at the seam.
   `Verify:` `tests/relevance/test_partner_requires_flow.py`,
   `tests/invariants/test_proactivity_invariants.py::test_partner_tier_requires_typed_flow`,
   `::test_moment_never_satisfies_confirmation`. Deps: G4-1; CrossScopeFlow schema work (#2544/#2548
   lineage) for the grant record shape. **Opus** (authority semantics).
3. **G4-3 Quiet-mode dial.** Settings note + compiler + threshold composition + fail-toward-quiet.
   `Verify:` `tests/relevance/test_quiet_mode_dial.py` (mode ceilings; zero-tolerance floor immune to
   `active`; unreadable settings ⇒ quiet; pull surface unaffected),
   `tests/invariants/test_proactivity_invariants.py::test_quiet_caps_surfacing_not_governance`.
   Deps: G4-2. **Sonnet.**

OS push delivery itself remains out of scope (deferred as today); G4-2 defines the gate it must pass
when it arrives, so un-deferring it later is a delivery slice, not an authority renegotiation.

## 5. Fitness invariants (registry candidates)

### tick_reasons_only_on_delta
- **Purpose:** The relevance evaluator does not run — and no moment/receipt/event is emitted — when
  the declared-inputs digest is unchanged and no time bucket crossed.
- **Expected failure mode:** every tick re-reasons over unchanged state (cost + receipt churn), or —
  inverse — a deadline crossing is missed because the vault didn't change.
- **Test path:** `tests/invariants/test_proactivity_invariants.py::test_tick_reasons_only_on_delta`.

### partner_tier_requires_typed_flow
- **Purpose:** Any outbound/external proactive delivery is exercised only under a CrossScopeFlow
  grant carrying `export`, `confirmation_required`, `audit_required`, and `expiry`. No boolean or
  env flag reaches the delivery seam.
- **Expected failure mode:** a `proactive_send`-style flag or a default-true grant object appears;
  external sends occur without audit records.
- **Test path:** `tests/invariants/test_proactivity_invariants.py::test_partner_tier_requires_typed_flow`.

### moment_never_satisfies_confirmation
- **Purpose:** A materialized moment cannot substitute for `confirmation_required` on any flow —
  moments are context, not authorization.
- **Test path:** `tests/invariants/test_proactivity_invariants.py::test_moment_never_satisfies_confirmation`.

### quiet_mode_caps_surfacing_not_governance
- **Purpose:** The dial can silence every gated rung, but WriteGuard, receipts, audit, and the
  zero-tolerance floor are mode-invariant; `active` can never unlock Partner or the floor.
- **Test path:** `tests/invariants/test_proactivity_invariants.py::test_quiet_caps_surfacing_not_governance`.

## 6. Rejected alternatives

- **A new proactivity-tier enum in the runtime:** rejected — the #1881 ladder already is the tier
  system; a parallel enum would drift. The binding table is policy data referencing existing tiers.
- **Quiet mode as suppression of materialization:** rejected — it would make quiet mode lossy (the
  ledger goes dark) and turn the dial into a governance actor. Quiet caps reach-out only.
- **Polling-rate reduction as the cost lever:** rejected — the field's own lesson (audit §IV) is
  that the saving is *reason on delta*, not *poll slower*; slower polling trades latency for cost
  without fixing churn.
