State: Draft (advisory design brief, 2026-07-05). The Claude Design entry brief for the Heimdall **watch/selection control surface** — how the human (principal) sees and steers what the agent watches, infers, and ingests. Frames the exploration; it does not decide the design. Advisory until a design pass runs and the owner rules; creates no runtime behavior and no GitHub work.
Doc role: Design brief (Draft) — Claude Design entry point for §9-k(b)
Authority: Authoritative for the *scope and constraints* of the watch/selection design exploration. Subordinate to `FABLE_COMPANION.md` §9-k (the confirmed ingestion-organ boundary) and `OWNER_DECISIONS.md`. Claims no shipped reality; proposes no runtime.
Owner: Architecture / product (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: this brief + `FABLE_COMPANION.md` §9-k(b) (captured owner UX inputs 2026-07-05), owner decision session 2026-07-05.

# Heimdall watch/selection — Claude Design brief

## Read first

- `FABLE_COMPANION.md` §9-k — the confirmed boundary: **Heimdall = ingestion organ** (watch → fetch → transcribe → attribute); **Mimer** = cognition from the handoff. Selection leans Mimer/agent (advisory).
- `FABLE_COMPANION.md` §9-k(b) — the five captured owner UX inputs this brief operationalizes.
- Repo principles this brief must honor: settings are **real writable surfaces**, not read-only mirrors; **no manual paths / no path-typing**; **minimize cognitive load** (fewest decisions, scannable, lead-with-the-answer); dyslexia-friendly (selection is a visual pick).

## 1. What we are designing

The **control surface** through which the principal (the human) sees and steers Heimdall's ingestion: what the agent is watching, *why* it started watching it, what it pulled in, what it skipped, and how the principal conveys intent — both **explicit** ("watch this", "never this") and **implicit** (their behaviour) — and steers **after the fact**.

We are **not** designing the ingestion backend (settled advisory, §9-k), nor the attention-calibration model (input 5 — separate, staged work). This brief is the **human control layer** over an agent that already watches the principal's interests autonomously under hard quality gates.

## 2. The central principle question (design this first)

> **Do we always route control through our own UI, or do we hold the principle that *everything is doable in Obsidian as `.md` files* and our UI is a complement with better ergonomics — never the sole home of any capability?**

The system's established stance leans **markdown-first**: companion notes, writable `.md` settings, chat-as-canvas. The owner's input 4 (the config "lives as a human-manageable `.md` settings surface in the vault") points the same way. So the **default to test** is:

- **Markdown is the substrate of record.** Every watch/selection capability is expressible and editable as `.md` in Obsidian — the principal could run the whole thing from plain notes if they chose.
- **The UI is a lens/complement.** It adds ergonomics (visual review feeds, one-tap steering, dashboards) but never becomes the *only* place a capability exists. Anything the UI can do is reflected in, and drivable from, the markdown.

**The honest tension to resolve in the exploration:** some journeys are poorly served by static markdown — visualising *inferred* interests (J3), and the attention dashboard of ingested-vs-skipped (J6), want live, scannable, interactive views. For each hard journey the design must answer: *is this **markdown-representable but nicer in UI** (principle holds), or **genuinely UI-only** (principle breaks here)?* A break is allowed only if it is named, justified, and the markdown still holds an honest record (even if read-only for that slice — declared per §persistence-is-not-read-only).

**Deliverable of this section:** a recommendation — markdown-first-with-UI-complement, held or broken, journey by journey.

## 3. Hard constraints (non-negotiable inputs)

1. **Principal–agent model (input 1).** The agent watches the principal's interests with **autonomy under hard quality gates**; the principal conveys **explicit and implicit** intent and can **steer after the fact**. The surface must make agent autonomy legible and reversible, never a black box.
2. **Per-source, switchable filters (input 2).** Intake filtering differs source to source; filters must be **turn-off-able in specific contexts** — the surface exposes this without becoming an admin console.
3. **Lives as `.md` in the vault (input 4), human-manageable.** Whatever the UI does, the settings/state have an honest `.md` home the principal can read and edit in Obsidian.
4. **No manual paths, minimal cognitive load, dyslexia-friendly.** No path-typing, no search-to-configure; selection is a visual pick; the surface leads with the answer and asks for the fewest decisions.
5. **Reversibility over prevention.** Because the agent acts autonomously, the safety model is *steer/undo after*, not *approve-before-everything* — consistent with proportional governance. Wrong intake must be one gesture to correct and to teach.

## 4. The principal–agent relationship the surface must express

The loop (advisory, §9-k(b)): **Heimdall senses the principal's behaviour → Mimer infers interests & designates sources/items → Heimdall fetches + transcribes → Mimer makes meaning.** The control surface sits across this loop and must let the principal:

- **See the inference** — "the agent started watching X because you did Y" (implicit intent made legible).
- **Correct the inference** — "no, not that", "more like this", cheaply, from any ingested item.
- **State intent explicitly** — "watch this", "never this kind", "everything from here", without leaving their flow.
- **Trust the gates** — see that hard quality requirements are holding (what was skipped and why).

## 5. Journeys to explore (J1–J7)

Each journey must be shown **both as it would work in plain `.md` in Obsidian AND as the UI complement**, and must answer the §2 principle question for that slice.

- **J1 — A source enters the watch-list by inference.** The principal sees *what* the agent started watching and *why* (the behavioural signal), and accepts / rejects / adjusts. (Legible autonomy.)
- **J2 — Explicit intent, in-flow.** "Watch this channel" / "never this" expressed from where the principal already is (a note, an item, the chat), not a settings trip.
- **J3 — Implicit intent reflected back.** How the principal sees the agent's *model of their interests* — the hardest markdown-vs-UI test. Is an interest map honestly expressible as `.md`, or does it need a live view?
- **J4 — Post-hoc steering from an item.** From a piece of ingested content: "less of this", "mute source", "wrong — not this kind" — and the agent visibly learns.
- **J5 — Per-source filter config + contextual off-switch.** Tune what a source contributes; turn filtering off for a source/context (input 2) without an admin-console feel.
- **J6 — Attention view: ingested vs considered-but-skipped.** Ties to calibration stage 1 (full visibility). The other hard markdown-vs-UI test — a dashboard wants interactivity; can markdown hold an honest version?
- **J7 — The `.md` settings surface itself.** What the watch/selection config looks like *as a note in Obsidian*, and exactly how the UI complements (not replaces) it.

## 6. What the exploration should produce

- A **recommendation on §2** (markdown-first held or broken, per journey), with the rationale.
- **Wireframes/mockups per journey** — both the `.md`-in-Obsidian form and the UI complement.
- A **sketch of the `.md` settings schema** (input 4) — the honest, human-manageable source of record.
- A **map of where autonomy is legible and reversible** across J1–J4 (the principal–agent trust surface).
- A short list of **journeys that had to break markdown-first**, each justified.

## 7. Out of scope

- The ingestion backend and Heimdall/Mimer boundary (settled advisory, §9-k).
- The **attention-calibration model** (input 5) — its own staged work; this surface only needs to *render* stage 1's "ingested vs skipped" (J6), not decide the calibration policy.
- Building anything — this is a design exploration; implementation is Issue-first after the owner rules.

## 8. Open questions to carry into the pass

- Does J3 (inferred-interest model) survive as `.md`, or is it the first honest break?
- Is there **one** surface across J1–J7, or a small family (in-flow steering vs a settings note vs a review feed)?
- How does chat (which already has mutation rights and may live outside Obsidian) relate to this surface — is chat the in-flow steering channel for J2/J4?

## SBS reconciliation summary

| Claim / section | Reconciliation | Routing |
| --- | --- | --- |
| Control surface framing, principal–agent model, journeys (§1, §4, §5) | `extend` — new design surface within the §9-k boundary | none |
| Markdown-first-with-UI-complement as the default to test (§2) | `conform` — to established repo stance (companion notes, writable `.md` settings, chat-as-canvas) | a journey that *breaks* it → declared + owner review |
| `.md` settings as writable source of record (§3.3, §6) | `conform` — persistence-is-not-read-only | none |
| Any surface that becomes UI-only | `reshape` — of the markdown-first principle | owner decision at design review |

## References

- `FABLE_COMPANION.md` §9-k, §9-k(b) — the boundary + captured UX inputs.
- Repo stance: companion-note architecture; writable `.md` settings; chat surface mutation rights; minimize-cognitive-load; no-manual-paths.
