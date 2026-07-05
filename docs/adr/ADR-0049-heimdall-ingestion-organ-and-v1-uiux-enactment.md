State: Proposed (owner decisions captured 2026-07-05; ratifies the §9-k reshape from `docs/HEIMDALL/FABLE_COMPANION.md` plus the three v1 UI/UX enactment decisions from the Heimdall UI/UX design thread). Records the owner's locked decisions; performs no code change and creates no runtime. Enactment is issue-first, deferred to follow-ups.
Doc role: Decision record (ADR)
Authority: Authoritative for (a) the Heimdall↔Mimer ingestion boundary (Heimdall = the ecosystem ingestion organ), and (b) the v1 human-facing UI/UX posture for Heimdall (markdown-first control surface, capture posture, native-app topology). Extends ADR-0044's constituent structure; reshapes the §5 records-of-reality-vs-authored-content boundary in FABLE_COMPANION and moves KAP's acquisition front-end from Mimer to Heimdall. Does not redefine Mimer's internals. SoS scope + the capture/privacy posture are owner-reserved (R-SOS / R-EXTERNAL) and recorded here as the owner's locked decision, not an agent's.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if the ingestion boundary, the markdown-first control-surface principle, the capture posture, or the app topology is reversed).
Source of truth: This ADR plus `docs/HEIMDALL/FABLE_COMPANION.md` §9-k + §11 (the confirmed boundary, captured UX inputs, and v1 critical path), the Heimdall UI/UX design thread (design-of-record: the converged Claude Design v2 output + the owner decision sheet, working artifacts held outside the repo per design convention), and ADR-0043 / ADR-0044 (constituent naming + structure, extended here).

# ADR-0049: Heimdall as the ecosystem ingestion organ + v1 UI/UX enactment (markdown-first control surface, discrete-capture posture, one-shell app topology)

**Date:** 2026-07-05
**Status:** Proposed (owner decisions locked 2026-07-05; ratification pending review)

---

## Context

Two owner-directed lines converged on 2026-07-05:

- **The Heimdall Fable window** (`docs/HEIMDALL/FABLE_COMPANION.md`) produced the v1 design and, at
  **§9-k**, captured a confirmed owner decision that **Heimdall is the ecosystem's ingestion/sensing
  organ** — it owns **watch → fetch → transcribe → attribute** for *all* external sources (voice memos,
  YouTube/podcasts/web, later ambient), and Mimer owns cognition from the handoff. §9-k explicitly flagged
  this as a `reshape` of the §5 boundary that **routes through CES/ADR at enactment**, and left the
  human-facing control surface to a separate design thread.
- **The Heimdall UI/UX design thread** (Thread B) ran a journey-based exploration of Heimdall's whole
  human-facing surface, and the owner ran an independent Claude Design pass. Both converged on
  **"Markdown holds the record; the UI is the lens,"** and the owner then locked three enactment decisions
  (capture posture, app topology, and two declared "bends").

This ADR ratifies the §9-k reshape and records the three UI/UX enactment decisions, so that v1 can proceed
issue-first. It performs no code change.

## Decision (owner, locked 2026-07-05)

### 1. Heimdall is the ecosystem ingestion organ (ratifies §9-k)

Heimdall owns the front of the chain for **every** external source: **watch → fetch → transcribe →
attribute → published event / candidate**. **Mimer** owns cognition from the handoff: **extract meaning →
integrate → promote to knowledge**. Mimer never watches, fetches, or transcribes. Handoff point: Heimdall
resolves *who/what was observed* (attribution, register refs, provenance, confidence); Mimer decides *what
it means*. This **demotes** FABLE_COMPANION §5.1's records-of-reality-vs-authored-content line from an
*ownership* boundary to an event **typing**, and **moves KAP's acquisition front-end** (source plugins,
download, ASR) from Mimer to Heimdall; KAP's residual cognition/candidate-refinement stays in Mimer.
Entity **resolution** is Mimer's (identity is knowledge): Heimdall emits entity **mentions**; the
canonical register is Mimer-owned and **markdown-built** (notes canonical; any graph DB is a derived,
rebuildable index).

### 2. Markdown-first control surface — held, with two declared bends

Heimdall's entire control state is a small folder of **writable notes in the vault** (`_heimdall/**`, the
entity notes, and the captured memos themselves). Every capability — watching, never-listing, interest
weights, per-source filters, entity merges, consent grants, device config — is a **note edit the agent
reads as intent**. Any UI is a **lens with better ergonomics, never the sole home of a capability**;
anything the UI can do is reflected in, and drivable from, the markdown. **Two surfaces bend** (declared,
justified, not silent): the **item-level skip firehose** (attention view) and **live device telemetry**
(battery/signal/buffer) are *runtime data, not artifacts of record* — markdown keeps the durable part
(counts, reasons, every override; device identity, config, consent binding, capture-gap log, last-known
snapshot), while the moment-to-moment / high-volume slice is a UI-only lens. **No capability is UI-only**;
if one is ever found to be, that is a `break` requiring a new owner decision + ADR.

### 3. Capture posture — discrete for v1, always-on-ready

v1 ships **Posture A (discrete)**: deliberate press-to-record voice memos via the iOS Shortcut → watched
iCloud folder. Single-party by declaration; `self_record` standing consent; local-only ASR (raw audio
never leaves the device, no silent cloud fallback). **Posture B (always-on / ambient)** is **not** built in
v1 but the surface is **designed to inherit it**: the consent note already writes the B-shaped mechanism
(VAD gating, third-party withhold-and-review, retention/erasure), so enabling ambient capture later is a
grant + adapter change, not a redesign. The choice to enable B is a future owner decision carrying the
third-party / GDPR weight; v1 does not incur it.

### 4. Native app — Topology C (one shell, two bounded clients, splittable)

The native app is **one shell ("Yggdrasil")** hosting **two bounded internal clients** — a Heimdall
(capture) client and a Mimer (knowledge) client — each binding **only** to its own constituent's contract,
both reading/writing **only** the same vault notes. Not two separate apps day-one; not a merged app. The
constituent boundary is enforced at the app layer, so a later **split into two apps is a repackaging, not a
rewrite**, triggered only if always-on-mic App-Store review, capture-vs-reader stability, or a standalone
capture device demands it. Platform split: **Heimdall client → iPhone + Watch** (capture/consent/device
health; absent on iPad); **Mimer client → iPhone + iPad-first** (the thinking canvas: multi-column,
Pencil/keyboard, drag-to-vault, side-by-side entity confirmation). Obsidian is retained as the full-power
editor of the same vault; **the apps are additional lenses, never the sole home**.

### 5. This records the owner's locked decision; enactment is issue-first

This ADR performs **no** code change and creates no runtime. The v1 build follows the FABLE_COMPANION §11
critical path, reconciled with decisions 2–4, as bounded issue-first slices (a Heimdall v1 epic + children).
The red-team's build-blockers stand: **content-quarantine (F2)** and **reversible register split (F5)** are
build-now before the vertical; **F1/F3/F4/F6** dispositions ride owner decisions §9-e/§9-h/§9-i.

## Constraints honored

- Decision record only — no code, no rename, no glossary edit, no runtime lands here.
- Mimer's internals are not redefined (14 boundaries + CES + correctness kernel intact); the entity
  register lands on Mimer's side on Mimer's schedule.
- Single-user stance preserved: one operator; constituents grow, the human does not.
- Local-first / privacy posture intact: raw audio on-device, no silent cloud, vault-sync of derived
  content is declared egress (HEIM-12).
- The reshape vs FABLE_COMPANION §5 / ADR-0043/0044 constituent scope is owner-gated and recorded here.

## Consequences

- The ingestion boundary is settled: **Heimdall = watch→fetch→transcribe→attribute for all sources**;
  **Mimer = cognition from the handoff**. KAP's acquisition front-end moves to Heimdall; ADR-0043/0044's
  constituent definitions are **extended** (Heimdall's scope now explicitly covers all external ingestion).
- v1 scope is bounded and low-risk: discrete capture only, so no third-party/GDPR/ambient complexity in the
  first vertical; the always-on mechanism exists on paper and in the consent note, dormant.
- One native app to build and sign into, with the split option preserved.
- The two bends (attention firehose, device telemetry) are the only sanctioned UI-only lenses; both keep a
  durable markdown record. Any future UI-only *capability* re-opens this ADR.
- A follow-up reconciliation is required for prose that still uses superseded names (`Hugin/Munin/Odin`) or
  the pre-§9-k boundary; **this ADR wins** where they disagree (tracked with the ADR-0044 alignment
  follow-up #2890).

## When to revisit

Supersede only if the ingestion boundary is redrawn, the markdown-first control-surface principle is
broken by a UI-only capability, the capture posture flips to always-on-default, or the app topology
changes (a hard two-apps split, or a merged app).

## References

- `docs/HEIMDALL/FABLE_COMPANION.md` — §9-k (confirmed ingestion-organ boundary + captured UX inputs),
  §9-k decision run (entity register Mimer-owned/markdown-built; ASR local fail-loud; YouTube seam;
  voice-memo capture), §11 (v1 critical path), §10 (red-team F1–F6).
- `docs/HEIMDALL/OWNER_DECISIONS.md` (A4), `docs/HEIMDALL/CAPABILITY_CHARTER.md` (A3),
  `docs/HEIMDALL/ENTITY_IDENTIFICATION_RESEARCH.md`.
- `docs/adr/ADR-0043` (Heimdall naming), `docs/adr/ADR-0044` (Yggdrasil/Mimer structure) — extended here.
- Heimdall UI/UX design thread — converged Claude Design v2 output + owner decision sheet (working
  artifacts outside the repo per design convention).
