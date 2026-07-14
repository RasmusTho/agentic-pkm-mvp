State: Mixed-status index. The original Heimdal "A" artifacts remain advisory design history, but their architecture window has been enacted and Heimdal's v1 capture-to-projection pipeline is shipped in `app/heimdal/`; use `docs/STATUS.md` and `docs/ARCHITECTURE.md` for current runtime truth.
Doc role: Directory index (Draft)
Authority: Index/entry point for the Heimdal document set. The A-artifact descriptions preserve their original advisory scope; current shipped reality is owned by `docs/STATUS.md` and `docs/ARCHITECTURE.md`.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: the docs indexed below + owner decision session 2026-07-04.

# Heimdal — Event Capture & Attribution (groundwork)

**Heimdal** is a proposed new constituent of the personal agentic ecosystem: continuous observation
of reality, converted into **attributed, timestamped events** with **confidence** and **provenance**.
Its responsibility ends at a **published event**; downstream constituents (Munin = knowledge/memory,
Hugin = agent-runtime) are read-models of that stream.

This directory holds the **"A" artifacts** — docs-only groundwork that fixes the container and hands
a Fable-5 architecture window a bounded problem. **Everything here is advisory** until enacted through
CES/ADR. Nothing here is shipped, and no GitHub work is created by it.

## The artifacts

| # | Artifact | What it fixes |
|---|---|---|
| **A1** | [ECOSYSTEM_SOS_MODEL.md](ECOSYSTEM_SOS_MODEL.md) | Acknowledged-SoS model, three-layer split, monorepo + split-triggers, substrate inventory — *where Heimdal sits* |
| **A2** | [ADR-0043](../adr/ADR-0043-heimdall-naming-and-norse-name-register.md) | Heimdal naming, Norse name register, observability-alias collision fix — *what things are called* |
| **A3** | [CAPABILITY_CHARTER.md](CAPABILITY_CHARTER.md) | FIXED constraints vs. OPEN problems + proposed fitness invariants — *the Fable brief* |
| **A4** | [OWNER_DECISIONS.md](OWNER_DECISIONS.md) | What Fable may not decide + the captured owner decisions — *the guardrails* |
| **A5** | [FABLE_WINDOW.md](FABLE_WINDOW.md) | Companion-doc pattern, model routing, scope boundaries — *how the window runs* |
| **→** | [FABLE_COMPANION.md](FABLE_COMPANION.md) | **The Fable window's design output** (2026-07-05): the proposed design for all 8 OPEN problems, anchored in the voice-memo v1 vertical, plus an adversarial red-team pass and owner decisions a–k — *the design that unlocks the build* |
| **⇢ B3** | [CAPTURE_TRANSPORT_FEASIBILITY.md](CAPTURE_TRANSPORT_FEASIBILITY.md) | **Downstream decision-support** (2026-07-06): Apple-ecosystem transport feasibility (Watch→Mac Mini) feeding the blocked Bifrost **B3** ([#3026](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3026)) owner decision — three transport models + decision table + two gating experiments. Conforms to the shipped v1 clean-folder capture (#3025); extends the §7.1/§9-h direct-transfer v2 item. Advisory. |

Read order: **A1 → A2 → A4 → A3 → A5 → FABLE_COMPANION** (container → names → guardrails → brief → mechanics → design). `CAPTURE_TRANSPORT_FEASIBILITY` is downstream of that window — read it when scoping B3 transport.

> **Naming update (2026-07-05):** the Munin/Hugin split below is superseded by **ADR-0044** (PR #2920):
> the whole = **Yggdrasil**; the knowledge-and-cognition constituent is **Mimer** (undivided, the
> current system); **Hugin/Munin are reserved/inactive**. `FABLE_COMPANION.md` uses Mimer throughout.
> The A1–A5 text still says Munin/Hugin and is pre-Mimer enactment cleanup (#2890) — not edited here.

## Fixed direction (do not relitigate)

- The ecosystem is an **acknowledged System-of-Systems**; **Yggdrasil = the whole**; Heimdal is a
  **sibling constituent**, not a subsystem of Munin. (A1 §1)
- Heimdal owns the **append-only fact stream**; everything downstream is a projection. (A1 §2)
- Naming: **Yggdrasil** (whole), **Munin** (knowledge/memory), **Hugin** (agent-runtime),
  **Heimdal** (sensor); observability alias → **OEF**. (A2)
- This is a `reshape` relative to the current single-system framing (ADR-0041) and routes through
  CES/ADR at enactment. Not bundled with ADR-0041/0042 (#2855/#2856).

## Status

Docs-only groundwork, delivered via the docs-authoring lane. Owner decisions captured 2026-07-04.
The **Fable-5 architecture window has now run** (2026-07-05): its design output is
[FABLE_COMPANION.md](FABLE_COMPANION.md) — advisory, surfacing owner decisions a–i and a build-blocking
red-team verdict (close F2 + F5 before the v1 vertical). Enactment (glossary/Mimer reconciliation,
contracts, and building the vertical via Issue-first) is deferred to later, owner-initiated work;
nothing here changes shipped reality.
