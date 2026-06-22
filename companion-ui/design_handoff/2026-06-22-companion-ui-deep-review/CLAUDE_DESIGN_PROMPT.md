# Paste-ready prompt for a Claude Design session

Paste the block below into a Claude Design session and attach the contents of this folder
(the five Markdown docs + the `img/` screenshots).

---

You are Claude Design, performing a **deep design review** of the Companion UI for Yggdrasil, a
single-user agentic personal-knowledge-management system. You cannot run the app or read the
repo — everything you need is attached.

Your job is **not** to say whether screens look good. It is to judge, for each user journey,
**(A) whether the workflow is intuitive** and **(B) whether the function is implemented well**,
then return a prioritised design specification.

Read the attached docs in this order, then follow `REVIEW_BRIEF.md` exactly:

1. `SYSTEM_CONTEXT.md` — what the system is, who the user is, the design philosophy (anti-
   dashboard, document-primary, calm re-entry, server-authoritative classification, governed
   action with receipts). Judge against these intentions.
2. `SURFACE_INVENTORY.md` — every screenshot mapped to its surface, trigger, journey, and any
   pre-noted observation.
3. `WORKFLOWS_TO_EVALUATE.md` — the seven journeys (J1–J7) to walk end-to-end. This is the spine
   of the review.
4. `OBSERVED_ISSUES.md` — defects already found. Start *past* these; go deeper, don't re-list.
5. `REVIEW_BRIEF.md` — the two-axis rubric, scope/authority boundaries, and the exact
   deliverable format.

Constraints:
- Produce **design specification, not code or PRs**.
- Do not propose moving runtime-declared classification (entry state, authority, receipts,
  posture) into the client — that boundary is load-bearing.
- The screenshots are **static, server-rendered, no live runtime**. Judge layout, hierarchy,
  state composition, and copy freely; for anything depending on motion, focus, live data, or
  round-trips, state the dependency and flag it for live UAT rather than asserting from a still.

Return exactly the deliverable structure in `REVIEW_BRIEF.md` §Deliverable format: executive
read → per-journey two-axis verdicts (J1–J7) → cross-cutting findings → prioritised
recommendations by type → acceptance criteria / UAT checklist. Lead with the answer; rank by
leverage; prefer the fewest high-impact changes over an exhaustive catalogue.
