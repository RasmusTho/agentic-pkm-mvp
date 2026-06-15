State: DRAFT for human review — NOT an active plan, NOT a backlog-wave source, NOT wired into `docs/DOCS_INDEX.md`. Produced 2026-06-15 from the Cognitive Maintenance vs Expansion audit. It proposes how the pre-positioned Cognitive Expansion surfaces become live without bypassing governance. It does **not** flip any flag, create any issue, or supersede `docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md`. Adopt, rewrite, or discard after the one-vertical-loop proof lands.
Doc role: Draft design proposal
Owner: (unassigned — pending owner decision)
Temporal class: proposal

# DRAFT — The Expansion Activation Gate

## Why this draft exists

The Maintenance vs Expansion audit (code-grounded, 2026-06-15) established:

- **Cognitive Maintenance** (preserve cognition) is broadly **live and test-backed** — 10/10 core capabilities wired into the running runtime.
- **Cognitive Expansion** (improve cognition) is mostly **built-but-not-live**: chat/canvas cognition is `CANVAS_ENABLED=0`; ASK answer-generation is `REASONING_ENABLE` default-off (live ASK returns literal snippets, no generated answer); planner, commitment surfacing, knowledge compilation, and cross-note synthesis have **zero runtime callers**.

This asymmetry is **intentional sequencing**, not neglect: `MAJOR_ROADMAP_RESET_2026_06_04.md` freezes expansion until one human-agent vertical loop is proven and context/memory **admissibility** is defined. The seams are pre-positioned so they can be switched on *safely*.

The problem this draft addresses: today each Expansion surface is gated by an **ad-hoc, per-surface flag** (`CANVAS_ENABLED`, `REASONING_ENABLE`) or by simply having no caller. There is no *uniform, governed* answer to the question "what must be true before this generative capability is allowed to run on the human's behalf?" That uniform answer is the **Expansion Activation Gate**. It is the single bridge that connects the original generative vision (Charter §2.1 Expansion) to the modern control plane (authority, admissibility, receipts).

## What the gate is

A capability flips **seam → live** only when it can satisfy one shared activation contract — not a bespoke flag. The gate is a precondition checked once per capability at activation, then enforced per-invocation by existing machinery (WriteGuard, receipts, authority class).

Proposed activation contract (each capability must declare):

1. **Admissibility** — exactly what context it may read to form a proposal (which spheres/domains, which memory classes, what provenance), expressed against the admissibility contract (Wave 0 deliverable). No capability may admit context that is not declared.
2. **Authority class** — `read-only` / `propose-only` / `governed-execution`. Determines whether output can touch the vault at all, and through which path. Most Expansion surfaces start `read-only`.
3. **Reversibility & receipt** — every activation-gated action emits a receipt (what it did, why, on whose authority, what it admitted). `governed-execution` additionally requires a reversible write through WriteGuard.
4. **Observability** — the capability is visible in `status` / health as activated, with its authority class and admissibility scope legible without reading code.
5. **Loop precondition** — named upstream gate(s) that must already be green (e.g. "proven vertical loop", "admissibility contract defined").

This replaces `CANVAS_ENABLED` / `REASONING_ENABLE`-style booleans with a declared, inspectable activation record per capability. The existing `CAPABILITY_CONTRACT_MODEL.md` vocabulary (`authority_class`, `capability_class`, `risk_tier`, `reversibility`, `approval_envelope`, `provenance_required`) is most of the schema already — the gate is the *activation discipline* over it.

## How it composes with existing docs (no new competing architecture)

- `COGNITIVE_PROSTHESIS_CHARTER.md` §2.1/§2.2 — owns *why* (Maintenance/Expansion, the arc). Unchanged.
- `EMERGENT_FEATURES_MODEL.md` — already the **composition spine** (trigger + context bundle + capability + policy + proposal/action + receipt + feedback). The gate is the *activation precondition* on that spine, not a parallel model.
- `CAPABILITY_CONTRACT_MODEL.md` — already owns the metadata vocabulary. The gate consumes it.
- `STATUS.md` — owns the current **activation ladder** (what is live/seam/dormant today). Already added.
- **New surface needed?** Only one, and only later: an **admissibility contract** (`docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`) — the reset already names "define memory/context admissibility" as a blocker, so this is owed regardless of this draft. The activation *gate* itself can live as a section in `EMERGENT_FEATURES_MODEL.md` rather than a new doc.

## The next wave — sequenced to the roadmap reset

The reset's order is law here: prove control before expanding. Each wave has a hard entry gate.

### Wave 0 — Prove the control model (prerequisite; already the reset's v6.1 "Done")
- **Prove one vertical loop**: vault intent → proposal → human confirmation → bounded action → receipt → UI/vault visibility, end-to-end on a real vault. The Panel confirm→execute path is the closest live candidate.
- **Define context/memory admissibility** as a contract: what may influence a proposal, from which sphere/memory class, with what provenance.
- **Exit criteria**: one loop demonstrated with a receipt; admissibility contract written and reviewed.
- *Nothing in later waves starts until Wave 0 exits.*

### Wave 1 — First generative seam: ASK answer synthesis (lowest authority)
- Flip `REASONING_ENABLE` semantics into a gate record: ASK answer-generation runs `read-only`, admits only declared retrieval context, emits a provenance-bearing receipt for the synthesized answer.
- **Why first**: zero write authority, highest user value (ASK actually *synthesizes* instead of returning snippets), smallest blast radius. It is the cleanest proof that the gate works.
- **Exit**: live ASK produces grounded, receipted, source-attributed answers; refusals/uncertainty preserved.

### Wave 2 — Canvas / chat co-authoring cognition
- Activate `app/chat/*` (the strongest generative stack, currently `CANVAS_ENABLED=0`) through the gate at `propose-only`, then `governed-execution` for direct note edits via the existing Chat→Panel governance handoff.
- **Entry**: Wave 1 green + write-authority receipts proven on the vertical loop.

### Wave 3 — Planner / next-action + commitment surfacing
- Bring the dormant `app/planner/*` + `app/domain/commitments.py` into a running service (today nothing but CLI imports them) at `propose-only`: surface next/waiting commitments and propose next actions, gated by admissibility.
- **Entry**: commitment runtime activated (#1960 line); Wave 2 proposal path proven.

### Wave 4 — Knowledge compilation / synthesis over time
- Activate `app/knowledge_compilation/*` and cross-note synthesis (`app/reasoning/multi.py`, both zero-caller today) as governed, non-canonical compiled artifacts with admission handoff.
- **Entry**: Waves 1–3 green; governed writeback proven.

### Outcome closure (cross-cutting, starts at Wave 1)
- Implement the HUMAN-FLOWS "Close the loop on human outcomes" signal as a lightweight review-rhythm prompt, so each activated Expansion capability is measured by whether the human's cognition improved — not by mechanism-level metrics.

## Non-goals of this draft
- It does **not** turn any flag on, write any runtime code, or create any GitHub issue.
- It does **not** re-open the reset's freeze; Wave 0 *is* the reset's own gate.
- It does **not** add multiple new top-level docs — at most one admissibility contract (already owed) plus a gate section in the existing composition spine.

## Open questions for the owner
1. Should the activation gate live as a section in `EMERGENT_FEATURES_MODEL.md`, or as its own short concept contract? (Recommendation: a section, to avoid proliferation.)
2. Is the Panel confirm→execute path the right vertical-loop proof, or should the loop be proven on a fresh, narrower slice?
3. Should Wave 1 (ASK synthesis) be promoted ahead of broader Companion UI production hardening, given it is read-only and high-value?
