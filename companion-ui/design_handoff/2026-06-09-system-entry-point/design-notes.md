# Design notes — System Entry Point

System rationale for the companion's front door: why the entry point is shaped this way, and how it composes the existing fragmented surfaces into one coherent whole.

---

## 1. The problem this solves

The companion has surfaces but no *entrance*. Orientation, the active-note workspace, the Vault Browser, Panel, memory review, resurfacing, and the temporal overlays each exist as their own handoff package or staging prototype. A newcomer has no single place to stand and see the whole. Worse, the natural failure mode of an "AI workspace" is to paper over that gap with a **dashboard** — a home screen of cards, counts, and feeds that the system fills with manufactured activity. `COGNITIVE_PRINCIPLES.md` names that anti-principle explicitly ("No AI-dashboard posture") and `SYSTEM_OVERVIEW.md` states the system "should behave as a cognitive prosthesis … not as a productivity dashboard, task system, or AI workspace."

So the entry point cannot be a dashboard. It has to be a *door into continuity of thought*. The design answer is: **the document is the front door, and orientation is how you walk through it.**

## 2. The spine: document-first, overlay-first, one screen

Every owner-doc converges on the same spine, so the shell is built directly on it:

- The **active document is the cognitive anchor** (`INTERACTION_PRINCIPLES.md`, `SYSTEM_OVERVIEW.md`). It occupies the primary column and is never displaced.
- **Chat is subordinate.** It lives in the right margin rail (a bottom sheet in portrait, per `OVERLAY_GRAMMAR.md`), can propose into the document, and cannot commit to the vault. It is a *canvas surface*, not a command surface.
- **Everything else is an overlay** that augments the current document context and dismisses without a route change (`OVERLAY_GRAMMAR.md`: "Overlays augment the current document context; they do not replace it"). The Vault Browser, the Panel command surface, the memory review, source peek, the posture switch, and the system map all open *over* the anchor and return to it. There are no separate apps and no full-screen context replacement.

The result is one screen, not a constellation of routes. This is what makes the system legible from one place: you never leave the document to use the companion; the companion comes to the document.

## 3. Setup and first contact: orientation, not onboarding

The brief forbids onboarding flows and engagement mechanics — there is one known expert user. So "setup" is not a wizard; it is **re-entry**. On every load the shell asks the runtime for an orientation snapshot (`GET /api/companion/orientation`, `WORKSPACE_ORIENTATION_CONTRACT.md`) and renders one of a small set of entrances determined by how long the user has been away. We borrow the **latency ladder** from `CONTINUITY_AND_DECAY.md` directly:

| Gap | Entry shape in the prototype |
|---|---|
| First contact (no `leave_point`) | "Nothing is open yet." One calm way in. No manufactured activity. |
| 2h – 3d (full mist) | The four fixed re-entry questions, rendered peripherally. Canonical re-entry. |
| 3d – 14d (long mist) | The four questions + a delta strip (what changed) + a right-margin whisper column. |
| > 14d (cold) | **No re-entry overlay.** Showing one would be a false claim of continuity. Re-enter through the vault. |

Two decisions matter here. First, **the four re-entry questions are fixed** ("What was I doing / Where did momentum stop / What remains unresolved / What changed since") — their shape is not negotiated per session, which keeps the moment low-load. Second, **re-entry is felt at the periphery**: a warm gold tint, a gravity well at the lower margin, corner glyphs, and the whisper column — never a card that centers on the document. As `CONTINUITY_AND_DECAY.md` puts it, "Cognition returns to the document, not to the system." When the mist dissolves (on Resume), a residual ambient layer persists: a caret echo at the stop point and marginalia dots.

This is why the entrance is read-only. Orientation may **surface** open loops, changes, and resurfacing candidates, and it may **emit** a `mutation_intent` toward the memory review boundary — but it never **applies** anything. The user resumes by choosing; the system never resumes *for* them.

## 4. Composing the existing surfaces

The system map is not a new surface — it is the **index that makes the existing ones one system**. Each node states how it is reached from the anchor and how it returns:

- **Converse / Chat** is the margin rail. It is where externalized thinking happens. It proposes; it does not commit. Lifted from `2026-05-03-converse` and `converse_layout.html`, normalized to tokens.
- **Canvas suggestion flow** is a *staged block inside the document body* (`CANVAS_SUGGESTION_FLOW.md`). Apply runs the **body-edit lane** via `canvas_writer` and returns **no receipt**; this is deliberately distinct from the governance-bearing lane. The block stays on the anchor — no overlay, because the edit *is* the document.
- **Panel / command surface** is the command palette (`⌘K`). It is the governed-action lane: propose → confirm → execute → receipt, through `WriteGuard`. The prototype shows a blocked proposal (cross-note write outside the allowlist) rendered calmly, not as an alarm. Panel is **not** Chat — keeping them visually and behaviorally separate is the authority-separation invariant made legible.
- **Vault Browser** (Find) is a left drawer; browse is read-only and `queue_review` is the one governed handoff. Opening a note re-anchors the shell around it (`GET /api/companion/workspace?note_path=…`).
- **Memory candidate review** (Reorient seam) is a right drawer. Orientation only emitted an intent; promotion happens here, through a governed decision. "Unreviewed memory is not semantic authority" is stated on the surface itself.
- **Temporal / provenance overlays** are the re-entry mist, decay marginalia, and source peek — continuity surfaces, not separate worlds. Provenance is visible wherever agent-contributed content appears.
- **Cognitive postures** (Orientation / Exploration / Synthesis / Review / Recovery) are a shift in emphasis, not a mode wall. The switch preserves the carry-forward set (anchor, provenance, unresolved tension) per `POSTURE_TRANSITIONS.md`. The shell opens in **Recovery** after a re-entry, which is the posture that "restores prior trajectory before new branching."

The same staged proposal object appears identically in Chat and in the document with the same status and actions, satisfying `OVERLAY_GRAMMAR.md`'s continuity rule.

## 5. Attention as a constraint, not a feature

`ATTENTION_MODEL.md` and the orientation contract's cognitive-load display budget both insist that the orientation moment must not become a new working-memory burden. The entry point honors this by **showing a scarce subset**: counts, not enumerations ("3 open loops · 1 staged · 2 tension", with an *inspect* affordance rather than an inline list). Nothing badges, pulses for attention, or escalates. Resurfacing is a why-now suggestion with provenance, never a notification. This is the difference between a prosthesis for continuity and an inbox.

### Earned guidance, not embedded help (the long-time-user rule)

The product is built for one expert who lives here daily, so explanatory help must not be permanent chrome. The design splits "help" into two kinds:

- **Evidence stays, always.** Provenance lines, `authority-tag`s, receipt pills, icon tooltips, the `⌘K` command surface, and source peek are the things an expert needs to *trust state*. They are terse and persistent.
- **Explanation is opt-in and decays to nothing.** The "what is this surface / how does re-entry work" prose lives in a single **guidance layer**, toggled by an `ⓘ` affordance (in the topbar, in each overlay head, and on the re-entry card) and **off by default**. The established user sees a clean, evidence-only surface; a newcomer — or a handoff reviewer reading this package — turns guidance on to get the explanatory callouts. The toggle is UI-local (`data-guidance` on the root); it persists nothing and carries no authority.

This resolves the brief's built-in tension directly: a newcomer can still understand the whole system from one place (guidance on + the system map), while the everyday surface for the long-time user stays terse, per the design system's "no filler / low attentional load" constraints. The System map itself is pull-based (sought from the topbar, never shown unbidden), which is the same principle applied to the system-level explainer.

## 6. Visual system

The prototype uses the canonical `colors_and_type.css` tokens unchanged — no new visual language:

- **EB Garamond** for the wordmark, the document title, and re-entry trajectory titles (depth, longevity).
- **Space Grotesk** for all UI chrome and body.
- **JetBrains Mono** for everything the runtime emits — paths, ids, `authority_role`, timestamps, `source_ref`. The mono voice means "this is evidence, not summary."
- Color carries authority meaning, mapped from `CORE_TERM_MAPPING.md`: **gold** for the warm/continuity and governance accent, **cyan** for triggers and links, **vault green** for healthy/applied, **amber** for staged/uncommitted/attention, **agent blue** for agent-contributed content, **destructive red** for refusal/blocked. Agent voice (Hugin) is always blue and labelled; it is never laundered into uncited primary text.
- Lucide-style icons at stroke 1.5, paired with labels. No emoji.
- Motion is minimal and purposeful. Per platform constraints, all visible end-states are the base style; entrance motion is additive only, so print, reduced-motion, and non-animating contexts always show content.

## 7. Conflicts found between sources

Resolved in favor of the owner-doc / governance posture, per `DESIGN_HANDOFF_GOVERNANCE.md`:

1. **Palette.** The design-system *guide* describes a warm near-black + parchment + Norse-gold scheme, but the repo's actual `colors_and_type.css` is a cool blue-black "Tron" palette with electric cyan. The CSS file is the binding token source and the brief instructs reuse of it, so the prototype follows the CSS and treats the guide's prose as aspirational. Flagged for the normalized spec.
2. **"Don't build a shell yet."** `DESIGN_BRIEF.md` (a preserved earlier artifact) says not to extract a multi-surface shell until a second UI-bound surface exists. `COMPANION_UI_STATE_MAP.md` now lists multiple shipped/dev-staging surfaces (orientation, active-note workspace, Vault Browser, Panel), so that precondition is met. The newer state-map and `SYSTEM_OVERVIEW.md` posture govern; the unifying shell is now warranted and is presented as guidance.
3. **Off-palette staging shell.** `companion-app/panel_visual_shell.html` uses an ad-hoc theme (Inter, `#1a1a2e`, `#e94560`) that predates the token sheet. The entry point normalizes Panel onto the canonical tokens; the divergence is noted as a thing the normalized spec should reconcile, not a competing visual direction.

No conflict was found that this package resolves *against* an owner-doc. Where this design proposes structure the owner-docs do not yet specify (the entry-point state enum, the shell composition), it is explicitly a proposal — see `implementation-contracts.md` and `open-questions.md`.

## 8. Setup, ambient context, and capture (v2 additions)

A second pass added the surfaces a daily user needs to actually *live* here, each built to stay on the right side of the anti-dashboard / anti-task-manager / anti-notification line.

- **Settings** is Local UI, grounded in `DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md`: display (theme/size/spacing) and listening (modality/speed) preferences re-render identical content with the canonical Markdown hash **byte-unchanged**, never reaching the vault or a save endpoint. A `local-only render` badge appears whenever a preference diverges. Settings also hosts the guidance-layer default, quiet hours, and the local-first connection posture (the UI never selects or names a vault).
- **Read-back** is a *small* per-surface control, exactly as `LOCAL_FIRST_TTS_CONTRACT.md` frames it: a `Listen` affordance opens a SpeechPlan (normalized text, locale, voice, skipped code, warnings) that the user inspects *before* any audio; it runs only after a human action, never autoplays, and never routes through a mutation endpoint. It is not a media player with persistent chrome — its footprint is a button and an on-demand popover.
- **The Context lane** is the honest answer to "make my previous/current/next meetings and my local-shop list close at hand." It is **not** a calendar app, a task list, or a feed. Time and place are *ambient salience signals* that raise the relevance of material the user already owns, surfaced as quiet why-now bands when the lane is pulled. This maps to the orientation contract's `resurface.candidates[].why_now` model (trigger + source + relevance basis), and it honors `SALIENCE_AND_TENSION` / `ATTENTION_MODEL`: **salience, not urgency; resurfacing, not notification.** The lane never pushes. Because no owner-doc grounds a calendar or location source, the lane and its place band ship as explicit **placeholders** (`open-questions.md` Q15–Q16), scoped so they don't gate the grounded surfaces.
- **Capture** is the brief's named Capture surface and the home for "things I need to take care of that aren't tied to a meeting." Critically, it is **vault intake, not an app-owned checklist**: a capture is a commitment to future-self appended to the vault inbox through the governed write path, with no due date and no nagging. It resurfaces later by relevance (the context lane, re-entry) the way any vault material does. This is the deliberate refusal of the task-manager posture the system forbids.
- **Receipts / history** gives governed outcomes a place to live beyond a transient toast — read-only, runtime-produced, "the UI must not invent a receipt."

The throughline for all five: time, place, and to-dos do not become three dashboards. They become *capture into the vault* + *salience over the vault*, which is continuity-of-thought support, not a productivity surface.
