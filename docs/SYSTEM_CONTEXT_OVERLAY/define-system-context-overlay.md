---
name: Define System Context Overlay
description: Write the 15288 context-layer overlay doc — SoI definition, lifecycle-role classification rule, integrated context model, SoS glossary entry, enabling-system principle sentence, functional-allocation pointer
task_id: SBI-1
source_anchor: "docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §1, §2, §3, §4, §5, §9, §14"
parent_capability: SYSTEM_CONTEXT_OVERLAY
prerequisites: []
depends_on: []
can_parallelize_with: [fix-register-and-charter-hygiene.md, complete-pending-boundary-charters.md]
---

# Define System Context Overlay

## Purpose

Nothing in the repo currently classifies the *running external things* Yggdrasil depends on — the
Postgres instance, Ollama, Docker/Colima, Tailscale, iCloud, GitHub, Obsidian — as System of
Interest (SoI) elements, enabling systems, or external systems in ISO/IEC/IEEE 15288 terms. The
audit's executive summary calls this "the missing layer is classification vocabulary, not
structure" (audit §Executive summary, point 1). This task writes the one doc that defines that
vocabulary so every other SBI task can cite it instead of inventing its own wording.

## What This Task Does

Write one new doc under `docs/architecture/` containing exactly five things, each a direct
transcription of an already-settled audit finding (this task decides nothing new; it records what
the audit already resolved):

1. **SoI definition** (audit §1) — the Yggdrasil SoI is the local-first cognitive-prosthesis
   software system: the runtime (`app/`, `yggdrasil_runtime/`), its contracts and schemas, its
   system-owned durable artifacts, and its rebuildable machine surfaces. Include the two boundary
   refinements: the human is not a component (operator/authority locus,
   `docs/foundation/00-yggdrasil-doctrine.md:24-39`); vault content is custodied, not owned (the
   vault *surface* is a SoI responsibility, vault *content authority* sits with the human,
   `docs/PROJECT_KERNEL.md:11`, `docs/COGNITIVE_PROSTHESIS_CHARTER.md:30-32`).
2. **Lifecycle-role classification rule** (audit §2) — the port/adapter is always a SoI element;
   the attached thing's classification follows its lifecycle role. Reproduce the four-row
   classification table from audit §2 (SoI component / COTS system element / enabling system /
   external system) with its worked examples, and the one-sentence clarification that IFC's word
   "external" describes trust/control posture, not 15288 location.
3. **Integrated system context model** (audit §4) — reproduce the ASCII context diagram and the
   taxonomy-reconciliation paragraph (spine subsystem → SBS boundary mapping, including "Capability
   → CAO+RCA, the split no doc currently states").
4. **SoS glossary entry + spine overlay note** (audit §3) — add a `System of Systems` entry to
   `docs/GLOSSARY.md` (none exists today) stating: no SoS exists within the SoI boundary (the spine
   subsystems fail every SoS taxon's independent-operability test,
   `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md:26`); the internal usage is colloquial for "modular,
   authority-separated single system," preserving ADR-0015's modularity intent; the one
   INCOSE-defensible SoS reading is the operator's assembled environment (Yggdrasil + Obsidian +
   iCloud, `docs/ARCHITECTURE.md:198`). Add a one-paragraph overlay note to
   `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` linking to the new glossary entry and this overlay doc
   — a note, not a rename (the rename is SBI-8's reshape question).
5. **Enabling-system principle sentence** (audit §9) — one sentence, appended to
   `docs/DESIGN_PRINCIPLES.md` (or cited from the overlay doc if the principles doc's own
   maintainers prefer a pointer — pick whichever the existing doc's structure makes cheaper): a
   design principle stating "development machinery and operational infrastructure never define
   product architecture." This is explicitly *not* a new principle document.
6. **Functional-allocation pointer** (audit §5, folds in SBI-6) — one sentence naming
   `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` as the system's functional-allocation view. No FBS, no
   function-ID register — the audit's own draft recommendation for one was refuted at its skeptic
   gate (closed issue #2409 already delivers the derivative view).

Link the new doc from `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`,
and add a `docs/DOCS_INDEX.md` row for it.

## Concretely

```bash
ls docs/architecture/system-context-overlay.md   # or equivalent name chosen at write time
grep -n "System of Systems" docs/GLOSSARY.md
grep -n "system-context-overlay\|SYSTEM_CONTEXT_OVERLAY" docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md
grep -n "docs/architecture/system-context-overlay.md" docs/DOCS_INDEX.md
grep -n "HUMAN_FLOW_TO_RUNTIME_MAP" docs/architecture/system-context-overlay.md
```

## Why This Matters

Every other task in this directory (SBI-2, SBI-3, SBI-5, SBI-8) cites this vocabulary. Without one
canonical doc, each downstream task would restate or subtly redefine "SoI" / "enabling system" /
"external system," recreating exactly the dual-listing contradiction the audit found (Ollama
described two incompatible ways because no doc owns the classification rule).

## Acceptance Criteria

- [ ] The overlay doc exists under `docs/architecture/` and contains all five required sections
      (SoI definition, lifecycle-role classification rule + table, integrated context model,
      SoS glossary/overlay-note reference, enabling-system principle sentence) plus the
      functional-allocation pointer.
      Verify: doc writeback at `docs/architecture/system-context-overlay.md` (or the chosen
      filename) — presence of all five sections plus the pointer sentence
- [ ] `docs/GLOSSARY.md` has a `System of Systems` entry matching audit §3's resolution (no SoS
      within the SoI; one defensible environment-level reading).
      Verify: doc writeback at `docs/GLOSSARY.md :: System of Systems`
- [ ] `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` carries a one-paragraph overlay note linking the new
      doc and the glossary entry, without renaming the file or rewording its existing claims.
      Verify: doc writeback at `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` (new paragraph, existing
      title and content otherwise unchanged)
- [ ] `docs/DESIGN_PRINCIPLES.md` (or the overlay doc, whichever the task determines is cheaper)
      states the enabling-system-boundary principle sentence.
      Verify: doc writeback at `docs/DESIGN_PRINCIPLES.md` or
      `docs/architecture/system-context-overlay.md :: Enabling-system principle`
- [ ] `docs/DOCS_INDEX.md` has a row for the new overlay doc.
      Verify: doc writeback at `docs/DOCS_INDEX.md` (new row, `docs/architecture/` section)
- [ ] The overlay doc names `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md` as the functional-allocation view
      and does not introduce a function-ID register.
      Verify: doc writeback at `docs/architecture/system-context-overlay.md :: Functional
      allocation` — no `AF-xx`/`CAP-xx`-style synthetic ID scheme present

## How to Verify (Pre-Merge)

1. `grep -c "^## " docs/architecture/system-context-overlay.md` — confirm five-plus sections exist.
2. `grep -n "System of Systems" docs/GLOSSARY.md` — confirm the entry landed.
3. Manual read-through: confirm every claim in the new doc traces to an audit §1-§5/§9 finding —
   this task must not introduce a claim the audit did not already make.
4. `grep -n "docs/architecture/system-context-overlay" docs/DOCS_INDEX.md
   docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md docs/SYSTEM_BREAKDOWN_STRUCTURE.md` — confirm the doc is
   linked from all three.

## Out of Scope

- Renaming `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` or rewording `docs/DESIGN_PRINCIPLES.md` §9's
  existing "System-of-Systems Thinking" section — both are reshape-routed to SBI-8.
- The infra classification column itself (SBI-2) and the spine↔SBS crosswalk rows (SBI-3) — this
  task defines the vocabulary and model those tasks apply; it does not populate their tables.
- The dual-role infrastructure stance and MCP topology question — explicitly deferred to
  `FABLE5_PROMPT_INFRA_DOMAIN_AND_MCP_TOPOLOGY.md` per audit §2 and §14; this task names and links,
  decides nothing.
- Any new function-ID register or FBS artifact (settled "do nothing" at the audit's skeptic gate).

## Related Docs

- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §1, §2, §3, §4, §5, §9`
- `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`, `docs/GLOSSARY.md`,
  `docs/DESIGN_PRINCIPLES.md`, `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`, `docs/DOCS_INDEX.md`
- `docs/foundation/00-yggdrasil-doctrine.md`, `docs/PROJECT_KERNEL.md`,
  `docs/COGNITIVE_PROSTHESIS_CHARTER.md`

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / medium effort — the content is a transcription of an
already-adversarially-reviewed audit section, not new analysis; the main risk is accidentally
introducing a claim the audit did not make. Escalate only if the enabling-system principle
placement (DESIGN_PRINCIPLES.md vs overlay doc) turns out to be contested.
