# iPad Split Pane

_Started 2026-04-24 20:52 UTC_

---

## User



## Assistant

_[tool: list_files]_

_[tool: list_files]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: questions_v2]_

Looks like that came through empty — did you mean to send something? 

In the meantime, I've read the brief and explored the existing UI kit. Let me ask a few questions before I start wireframing so I'm exploring the right space.

## User

Questions answered:
- starting_point: Treat it as the baseline — wireframe variations and improvements on top of it
- form_factor_focus: Ipad 11inch- primary, desktop mac and pc secondary
- converse_modes: flexible
- layout_shape: Split pane — conversation left, artifact/document right, Explore a few options
- agent_visibility: Subtle distinction — same rhythm, lighter signal
- session_persistence: Explore a few options
- context_panel: Explore a few options
- num_variations: 3 — good spread
- what_to_push: Layout and information architecture, Visual language / Yggdrasil aesthetic, Novel / unexpected interaction models

## Assistant

_[tool: read_file]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: update_todos]_

_[tool: copy_starter_component]_

_[tool: copy_files]_

_[tool: update_todos]_

_[tool: write_file]_

Now I'll build the three wireframe directions. Let me think through what to show before writing:

**Direction A — Split pane:** Left session rail + center thread + right document/artifact pane. The canonical split for thinking-alongside-text. Artifact is always present; mode emerges from whether you're editing it.

**Direction B — Timeline bloom:** Single-column flow. No separate artifact pane. When a suggestion hits, the artifact card blooms outward from the message — expands inline into a 2-column moment. The document grows from the conversation, not beside it.

**Direction C — Document-first / margin conversation:** The vault note fills the stage. Conversation is a collapsible right margin. Agent annotations appear inline as margin marks on the document. Inverts the existing pattern entirely — document is primary, the agent is a margin voice.

_[tool: done]_

_[tool: str_replace_edit]_

_[tool: done]_

_[tool: fork_verifier_agent]_

Three wireframe directions are up — pan and zoom around the canvas, or click any artboard to focus it fullscreen.

**What each direction explores:**

**A — Split pane** (refinement of the existing kit): session rail + conversation thread + document pane always side-by-side. The artifact is always visible; mode emerges from whether you're editing it. Staged state shows as an amber bar docked between thread and composer, and as a highlighted region in the doc pane.

**B — Timeline bloom** (novel): no persistent document pane. The artifact only materializes when a suggestion hits — it blooms inline as a 2-column card (suggestion text left, diff preview right) then closes after apply/discard. The conversation is the primary object; the document is a momentary guest. Icon-only left rail keeps chrome minimal.

**C — Document-first** (inverted): the vault note fills the stage. Navigation moves to a top bar. The agent conversation lives in a collapsible 320px right margin, with agent annotations linked to highlighted passages in the document via margin dots. The document is primary; Hugin is a margin voice.

**Tensions to discuss:**
- B has the most novel IA but breaks down for long artifact work (you can't read the whole doc while thinking)
- C inverts the pattern elegantly for synthesis/editing sessions, less so for pure exploration sessions with no anchor note
- A is the safest and most familiar but the doc pane may feel like dead space when you're in pure exploration mode

Happy to dig into any of these, mix elements across directions, or push one into a more detailed state.

## User

Verifier agent check completed

## Assistant

_[tool: grep]_

The export is `DesignCanvas`, not `DCCanvas`. Quick fix:

_[tool: str_replace_edit]_

_[tool: grep]_

_[tool: grep]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: str_replace_edit]_

_[tool: done]_

_[tool: fork_verifier_agent]_

Clean — three wireframes are rendering. Pan/zoom around the canvas freely, or double-click any artboard to focus it fullscreen.

Let me know what direction feels most promising, or if you want to mix elements (e.g. B's minimal icon rail + A's persistent doc pane, or C's document-primary layout with a bloom moment for suggestions).

## User

explore c more; the document is the artefact.
Colour scheme may be to attention grabing, but let's see
This should be useful first and nice looking second.
Cognitive load reduction and easy access to the needed functionality is core

## Assistant

_[tool: update_todos]_

Good direction. Let me think through what "C deep" means before building:

- **Document is the artifact** → it needs real reading ergonomics: good measure, comfortable type, Garamond body
- **Cognitive load** → one accent at a time. The neon system is fighting for attention everywhere; I'll pull it back hard — color only on the single most actionable thing on screen
- **Rail states** → collapsed (focus), active (dialogue), suggestion moment (staged edit in margin)
- **Useful first** → explore what the margin rail actually needs to show vs. what can be deferred

_[tool: str_replace_edit]_

_[tool: read_file]_

_[tool: str_replace_edit]_

_[tool: done]_

_[tool: fork_verifier_agent]_

Three C deep-dive states are up — scroll right past the initial directions to find the "Direction C — deep dive" section.

**What each state shows:**

**C.1 — Focus (rail collapsed):** Document at proper reading measure (~640px / ~65ch). Rail shrinks to a 32px strip — Hugin presence dot + "3 new" unread count. Nothing else competes for attention. This is the reading/writing mode.

**C.2 — Dialogue (rail active):** Rail expands to 288px. Agent messages differentiated only by a very faint background tint — no coloured borders, no glows. Sources appear as footnote-style path refs (`↳ Projects/Q2-arch.md`) below the message, not as coloured chips. Only two coloured elements on the entire screen: vault dot (green) + Send button (cyan).

**C.3 — Suggestion moment:** The proposed addition appears inline in the document as an amber-tinted region with a "proposed addition" label. The rest of the document dims to ~35% opacity. The margin card mirrors it exactly — same amber, same label. Prior conversation turns also dim. Composer greys out with "apply or discard to continue." One thing to act on, everything else steps back.

**The colour reduction principle being tested:** at any given moment, only the single most actionable element carries colour. The system doesn't shout — it whispers, then speaks clearly when it needs you.

What would you like to push next? Some directions:
- A fourth state showing the **session-switching / no-anchor-note** flow
- **iPad portrait** adaptation — how the rail behaves at 834px wide
- Deeper on **sources/context** — how referenced notes surface without overwhelming
- Start moving one of these toward higher fidelity

## User

continue this work

## Assistant

Good — picking up where we left off. The three C deep-dive states are solid. Let me think about what's most useful next:

The natural next step is resolving the **open questions that the wireframes expose but don't answer**:
1. How does the rail handle **session switching** — is it a separate view or a drawer over the document?
2. **iPad portrait** (834×1194) — the 288px rail eats too much of the 834px width; does it stack or overlay?
3. **Sources/context panel** — how do referenced notes surface without a dedicated pane?

I'll add a second row of C deep-dive artboards covering these three, keeping the same muted palette.

_[tool: read_file]_

Good — structure is clear. I'll add three more states to the C deep-dive section:

**C.4 — Session switching:** drawer slides over the document (not a nav away from it), document stays visible underneath at ~40% opacity  
**C.5 — Portrait adaptation (834×1194):** rail overlays as a sheet from the bottom edge, document is never squashed  
**C.6 — Source peek:** a referenced note surfaces as a transient overlay anchored to the margin dot — not a new pane, not a modal

_[tool: str_replace_edit]_

_[tool: done]_

Three new states added to the C deep-dive row:

**C.4 — Session drawer:** Slides in from the left as an overlay over the document — the doc stays visible at ~25% behind a blur scrim. No navigation away. Dismiss by tapping the scrim or ✕ to return to exactly where you were.

**C.5 — Portrait (834×1194):** Document fills the full width — no pane squashing. Nav labels drop to icon-only. The conversation rail becomes a bottom sheet with a drag handle, peeks the latest message + composer. Drag up to expand, drag down to collapse to a 32px strip — same collapsed state as landscape, just at the bottom edge instead of the right edge.

**C.6 — Source peek:** Tap any margin dot (the blue circles that mark agent-annotated passages) to get a transient peek card anchored to that dot. The referenced passage is highlighted inside the source note. "1 of 2 references" + ← → for navigation. No new pane, no modal — just a floating card that dismisses on ✕ or outside tap.

The full IA is now sketched across 6 states. The key structural decisions it surfaces:

1. **All interactions are overlays** — nothing navigates away from the document
2. **The rail has 3 sizes:** 32px strip / 288px panel / full-height sheet (portrait)
3. **Sources live in the margin** — dots, not chips; peeked inline, not in a separate pane

What's next — push one of these to higher fidelity, or are there other open questions to resolve first?

## User

how do i get Claude code or codex make this into a functional app?

## Assistant

Two good paths, depending on your stack:

**Claude Code (Anthropic)**
Your best bet for this project given the Obsidian/vault angle. It works directly in your terminal against a local codebase.
1. Install: `npm install -g @anthropic-ai/claude-code` then run `claude` in your project directory
2. Point it at these wireframes: export this file (download button in the toolbar) and drop it in your repo, or just describe the screens in your prompt
3. It works best with an existing scaffold — if you haven't started the PWA yet, ask it to scaffold a React + Vite app first, then implement screen by screen

**OpenAI Codex / ChatGPT with code**
Similar workflow but cloud-based. Upload the HTML file directly in a ChatGPT conversation and say "implement this as a React app." Less good at multi-session codebase work.

---

**The better handoff is a spec, not just the wireframes.** I can generate a developer handoff package from these wireframes — a single document that describes:
- All 6 screen states with annotated dimensions
- Component inventory (CTopBar, MarginRail, SessionDrawer, SourcePeek, etc.)
- Interaction specs (rail states, overlay behaviors, suggestion flow)
- The color/type tokens from the design system

That gives Claude Code something precise to implement rather than having it interpret visual wireframes. Want me to generate that?

## User

please give me a handof promt.
I have this folder where I want the UI to live: repo root/companion-ui.
this was my old design brief:

## Assistant

_[tool: invoke_skill]_

_[tool: update_todos]_

On it. Writing the full handoff package now.

_[tool: write_file]_

Now copying the design files into the handoff folder and packaging it.

_[tool: copy_files]_

_[tool: present_fs_item_for_download]_

The zip contains:

- **README.md** — the full spec: all 6 screen states, every component, interaction patterns, API contract, colour tokens, and the ready-to-paste Claude Code prompt at the bottom
- **Companion UI Wireframes.html** — the 9-state interactive canvas (open in a browser alongside the README)
- **design-canvas.jsx** + **colors_and_type.css** — reference files

Drop the folder at `<repo root>/companion-ui/design_handoff/` and paste the prompt from the bottom of README.md into Claude Code to get started.

