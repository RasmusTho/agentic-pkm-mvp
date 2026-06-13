---
name: Contextual Relevance Engine Specification
description: Specification directory for the proactive, adaptive contextual-relevance capability — context model + relevance evaluator + reach-out/scarcity gate + the moments they produce.
type: specification
authority: SoT for the CONTEXTUAL_RELEVANCE_ENGINE capability boundary and its bounded task breakdown. Subordinate to the human-need brief and the concept contracts it grounds; does not override current runtime truth in docs/STATUS.md / docs/ARCHITECTURE.md.
source_of_truth: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md
related_docs:
  - docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md
  - docs/HUMAN-FLOWS.md
  - docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md
  - docs/COGNITIVE_LOAD_PROJECTION_LAYER.md
  - docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md
  - docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md
  - docs/EMERGENT_FEATURES_MODEL.md
  - docs/FINDING_AND_REORIENTING/README.md
---

State: Active specification directory (forward line; not shipped reality). Grounds the human-need brief `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` into bounded tasks. Parent feature issue and child issues are filed on GitHub; GitHub is the authoritative backlog and validation record. Capability name is provisional.

# Contextual Relevance Engine — Specification

This directory specifies **what the system needs to build** for the Contextual Relevance Engine: a
proactive, adaptive capability that surfaces *the right thing at the right moment*, context-dependent.
The human-need framing, design dialogue, and settled decisions live in the brief
(`docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md`); this directory turns that into bounded, independently
mergeable tasks.

## Capability boundary

One general engine, not a fixed set of moments. Underneath any moment: a **context model**, an
**adaptive relevance evaluator**, **patterns** (user-declared first, emergent later), and a
**deterministic discipline layer** (scarcity, the #1881 governance tiers, vault-first, local-first).
The genuinely new dimension over the existing v6.0 seams (orientation, resurfacing, commitment,
context dimensions) is **proactivity** — the system anticipates the moment and reaches out, instead
of waiting to be pulled.

## Implementation tasks

| Order | Task | Kind | Pickup state |
| --- | --- | --- | --- |
| 1 | [`DEFINE_MOMENT_AND_CONTEXT_MODEL`](DEFINE_MOMENT_AND_CONTEXT_MODEL.md) | design / concept contract | delivered (#1922, PR #1939) |
| 2 | [`DEFINE_RELEVANCE_AND_SCARCITY_CONTRACTS`](DEFINE_RELEVANCE_AND_SCARCITY_CONTRACTS.md) | design / concept contract | ready (#1923) |
| 3 | [`BUILD_VAULT_NATIVE_PULL_MOMENTS`](BUILD_VAULT_NATIVE_PULL_MOMENTS.md) | implementation | blocked on 2 |
| 4 | [`BUILD_PROACTIVE_ATTENTION_LOOP`](BUILD_PROACTIVE_ATTENTION_LOOP.md) | implementation | blocked on 1–3 |

The first two tasks define the contracts the capability needs (it is a novel capability; the
contracts do not exist yet). They are docs/concept-contract tasks whose ACs verify against doc
anchors and are ratified in PR review — the owner shapes the design there. The implementation tasks
name spec-level test commitments that sharpen once the contracts land.

### Deferred (not yet broken down)

- **External connectors** — calendars (work / private / family), email (job / private), tasks,
  location. This absorbs the parked **#1796** Q15 (agenda/calendar source) and Q16 (location source
  + privacy). Deferred deliberately: the local-first privacy posture is undecided, so a spec now
  would be premature. Break this down (`feature-breakdown enrich-docs`) only after the core engine
  ships and the privacy posture is decided. The engine is designed to run fully on vault-native data
  without it.

## Execution order

`DEFINE_MOMENT_AND_CONTEXT_MODEL → DEFINE_RELEVANCE_AND_SCARCITY_CONTRACTS → BUILD_VAULT_NATIVE_PULL_MOMENTS → BUILD_PROACTIVE_ATTENTION_LOOP → (deferred) external connectors`

## Capability-level acceptance

The capability can be claimed as supported only when:

- a vault-native moment is computed from real vault data and rendered at the glance surface, with a
  durable Markdown artifact and a receipt;
- the proactive attention loop fires a reach-out only when a moment's urgency clears the current
  context-dependent interruption threshold, never at the zero-tolerance floor (sleep / declared DND),
  and defers (does not drop) when suppressed;
- every durable effect is governed (write guard + receipt) per the #1881 tiers; no hidden writes; no
  LLM-triggered execution outside the receipt trail;
- owner-doc promotion: a writeback into `docs/HUMAN-FLOWS.md` §5 (rhythms made proactive) and a new
  row in `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`.

## Relationship to GitHub issues

The specification is the source of truth for *what to build*; GitHub issues track *what to pick up
next*. The parent feature issue is a blocked validation hub while child slices are outstanding; each
delivered child posts a validation receipt to it. One task spec may map to more than one issue if the
implementation is large.

GitHub issues:

- Parent feature issue (validation hub, `agent:blocked`): **#1921**
- `DEFINE_MOMENT_AND_CONTEXT_MODEL`: **#1922** — `agent:blocked` → flips to `agent:ready` when this brief/spec PR (#1918) merges
- `DEFINE_RELEVANCE_AND_SCARCITY_CONTRACTS`: **#1923** — `agent:blocked` (on #1922)
- `BUILD_VAULT_NATIVE_PULL_MOMENTS`: **#1924** — `agent:blocked` (on #1922, #1923)
- `BUILD_PROACTIVE_ATTENTION_LOOP`: **#1925** — `agent:blocked` (on #1922–#1924); final child, carries the owner-doc promotion handoff

All four children are filed `agent:blocked` pending merge of the brief/spec (PR #1918) and the design-contract chain. #1922 is the first to become ready.
