State: Draft (advisory groundwork, 2026-07-04). Defines how the Fable-5 architecture window for Heimdall runs: the companion-doc pattern, model routing, and scope boundaries. Advisory until enacted through CES/ADR; creates no runtime behavior and no GitHub work.
Doc role: Process/mechanics doc (Draft) — Fable window
Authority: Authoritative for the *mechanics* of the Heimdall Fable window (how it is run, what it may produce, where its output lands). Subordinate to `CAPABILITY_CHARTER.md` (what Fable solves) and `OWNER_DECISIONS.md` (what it may not decide). Claims no shipped reality.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: this doc + `CAPABILITY_CHARTER.md`, `OWNER_DECISIONS.md`, `AGENTS.md :: Total Cost of Development`, the RESEARCH-08 ecosystem-federation companion-doc precedent, owner decision session 2026-07-04.

# Heimdall A5 — Fable window mechanics

Heimdall's OPEN problems (`CAPABILITY_CHARTER.md`) are hard architecture. This doc fixes *how* the
Fable-5 window that solves them is run, so the window produces a reviewable design instead of drifting
into implementation or relitigating fixed constraints.

## 1. Companion-doc pattern `[conform]`

The window follows the same companion-doc pattern used for RESEARCH-08 (ecosystem federation): a
single **living companion document** is the durable thread for the whole window.

- **One companion doc.** Create `docs/HEIMDALL/FABLE_COMPANION.md` when the window opens. It is the
  running record: the prompt/framing, Fable's design output, alternatives considered, owner Q&A, and
  the decision log. It is a *thread*, not a one-shot report.
- **Self-sufficient.** The companion doc must stand alone — no machine-local or gitignored state, no
  "see the chat." Anyone on any device can pick it up from the repo. (Repo rule:
  `feedback_issue_self_sufficiency`.)
- **Charter is upstream, companion is downstream.** The charter (A3) and owner decisions (A4) are the
  fixed inputs; the companion doc records everything the window *derives*. If the window discovers a
  fixed constraint is wrong, that is a `reshape` → stop and route to the owner (see §3), do not edit
  the charter from inside the window.
- **SBS reconciliation per claim.** Every load-bearing claim the companion doc makes is tagged
  `conform` / `extend` / `reshape`, and reshapes route via CES/ADR — same discipline as these A-docs.

## 2. Model routing — Fable is for hard architecture only `[conform]`

Per `AGENTS.md :: Total Cost of Development` and the standing subagent-routing rule, model choice is
by task tier, and **Fable is reserved for the hard-architecture / adversarial work** — not the whole
window.

| Work in the window | Capability |
|---|---|
| Core architecture design (event contract, confidence model, attribution coupling, bus choice, backbone, threat model) | **Fable** — high/max reasoning; this is the reason the window exists |
| Adversarial review of a proposed design (refute the threat model, find seam leaks) | **Fable** — adversarial pass |
| Drafting/normalizing docs from a settled design, cross-referencing, schema-mirroring | **Sonnet** — implementation/docs tier |
| Mechanical edits, link-fixing, glossary reconciliation at enactment | **Sonnet / Haiku** — mechanical |
| Owner decision framing (Problem → Options → Consequences) | Whatever is already in context; the *decision* is the owner's |

Do **not** default the whole window to Fable, and do **not** let a cheaper tier make the
load-bearing architecture calls — both are TCD mistakes (over-modeling and under-modeling
respectively).

## 3. Scope boundaries `[conform]`

The window is a **design** window. Hard boundaries:

- **No code, no runtime, no schemas-as-shipped.** Output is design docs + prose-mirror contracts +
  proposed invariants. Implementation is a later Issue-first lane after the design is accepted.
- **No GitHub work created from inside the window** unless the owner explicitly turns a settled design
  into backlog via `docs-to-issue`.
- **Fixed constraints are read-only.** Touching anything in `CAPABILITY_CHARTER.md :: FIXED` or
  `OWNER_DECISIONS.md :: Part 1` is out of scope; surface it as an owner decision instead.
- **Stop conditions (return to owner):** any reserved decision (`OWNER_DECISIONS.md` Part 1); any
  discovery that a FIXED constraint is unworkable; any external-facing or legal question; any proposed
  `reshape` of existing SoT.
- **Definition of done for the window:** an accepted design in the companion doc, with (a) the event
  contract, (b) confidence + attribution model, (c) bus + backbone recommendation with alternatives,
  (d) trust/threat model, (e) refined fitness invariants, each SBS-tagged and each open owner-decision
  surfaced — ready for `docs-to-issue` when the owner chooses to build.

## 4. Relationship to the A-artifacts `[conform]`

```
A1 ECOSYSTEM_SOS_MODEL   →  where Heimdall sits (fixed container)
A2 ADR-0043 (naming)     →  what things are called (fixed)
A4 OWNER_DECISIONS       →  what Fable may not decide (fixed) + captured decisions
A3 CAPABILITY_CHARTER    →  FIXED vs OPEN problem statement (the brief)
A5 FABLE_WINDOW (this)   →  how the window runs
        │
        ▼
   FABLE_COMPANION       →  the living design thread (created when the window opens)
```

## SBS reconciliation summary

| Section | Reconciliation |
|---|---|
| Companion-doc pattern; model routing; scope boundaries; A-artifact relationship | `conform` to existing repo patterns (RESEARCH-08 companion doc, TCD routing, docs-authoring lane) |
| Any design output that changes a fixed constraint | `reshape` → owner via CES/ADR |

## References

- `CAPABILITY_CHARTER.md` (A3) — the brief.
- `OWNER_DECISIONS.md` (A4) — reserved decisions + captured decisions.
- `ECOSYSTEM_SOS_MODEL.md` (A1), ADR-0043 (A2).
- `AGENTS.md :: Total Cost of Development` and `:: Agency default` — capability routing + when to ask.
- RESEARCH-08 (ecosystem federation) — companion-doc precedent.
