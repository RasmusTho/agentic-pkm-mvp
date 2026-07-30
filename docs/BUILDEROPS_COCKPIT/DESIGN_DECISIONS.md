State: Decision ledger for the 2026-07-30 BuilderOps cockpit design intake. Every open question and
proposed design-system extension from the accepted design pack, closed as an explicit decision.
Doc role: Specification support (decision record). Subordinate to the ADRs it cites.

# Design decisions — BuilderOps cockpit

Source: the 2026-07-30 design exploration's `open-questions.md`
(archived provenance: `design/2026-07-30-cockpit-exploration/INTAKE.md`). Rule applied throughout:
tokens win over prose; nothing from the pack is canonical until accepted here. Decisions were taken
under `AGENTS.md :: Agency default` — reversible, non-external calls are decided and reported, not
escalated; the single owner-gated item is named as such.

## Design-system conflicts

### DS-1 — Design-system README prose contradicts the token sheet (five points) — ACCEPT tokens-win; README correction is design-project follow-up

The design session found the live design-system README disagreeing with `colors_and_type.css` on
background warmth, radii steps, focus ring, UI typeface, and glow usage, and resolved every point
in favor of the token sheet. Decision: the token sheet is the binding authority; the design-system
README (a Claude Design project artifact, not a repo file) should be corrected to match tokens at
the next design-system maintenance pass. No repo slice; recorded so the next design run does not
re-litigate it.

### DS-2 — `_ds_bundle.js` exports zero components — ACCEPT as known limitation; promotion of previews to exports is design-project follow-up

There are no exported primitives to reuse, only tokens and previews, so all cockpit CSS is built
against tokens. Decision: accepted for v1 (the shipped `app/web/static/cockpit.css` follows the
same rule). Promoting `components-badges` / `components-buttons` / `components-cards` previews to
real bundle exports is design-system work outside this capability.

### DS-3 — Signboard CSS is not Yggdrasil-bound — REJECT tokenization for v1

Signboard carries its own pre-Yggdrasil palette. Tokenizing it is not cockpit work: the cockpit
inherits Signboard's card *grammar*, not its values, and the Signboard serving surface was just
rewritten by PR #4406 (merged 2026-07-30). Decision: Signboard remains a visibly dated older
surface; tokenization only with an explicit owner demand, filed separately if ever.

## Proposed design-system extensions

### EXT-1 — Evidence-spine primitive — ACCEPT cockpit-local; rung count fixed at eight

The eight-rung spine (node + edge, classes `proven` / `derived` / `unlinked` / `absent`) is
accepted and shipped cockpit-locally (#4438: `RUNG_ORDER` in `app/builderops/cockpit_registry.py`).
The open sub-question — fixed vs configurable rung count — is decided: **fixed at eight** for this
surface; the rung order is the process chain and is not a parameter. Promotion to a shared
design-system primitive is deferred until a second surface needs it.

### EXT-2 — Receipt line with an explicit "delivered but never tried" state — ACCEPT cockpit-local

Accepted and shipped as the done band's two tiers, where "Tried by you" is empty by contract until
an owner-acceptance receipt contract exists (INV-DG-7,
`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md :: Invariants`). Extending the shared
`ReceiptPill` contract with `unverified-by-owner` is deferred design-system work.

### EXT-3 — Per-source freshness row — ACCEPT cockpit-local; stale is a distinct third state

Accepted; #4438 shipped the fresh/empty/unavailable states with per-pill `last_successful_read`,
satisfying INV-DG-6 for the planes read. The pack's third pill state — **stale** (readable but old,
amber) — is accepted and not yet enacted: each plane task defines its staleness threshold, a stale
source turns dependent rungs amber, and the numbers that source owns are withdrawn rather than
shown whole (see `README.md :: Cross-Task Invariants / Interaction Safety`). Promotion to a shared
primitive (the CKM view has its own variant) is deferred; when promoted, the two variants must
converge on one component.

### EXT-4 — Refused-claim state template — ACCEPT cockpit-local

Accepted and shipped (#4438): a dead source yields "cannot be counted", never zero; distinct from
error and from true emptiness. Promotion to a design-system template is deferred.

### EXT-5 — Button-class marking (`contract` / `agent` / `out`) — ACCEPT direction; only `out` exists in v1

The three-class distinction (typed contract call / agent start with prepared prompt / out-link to
the authority) is accepted as the binding model for any future cockpit action. Decision for v1: the
cockpit is entirely read-only, so only the `out` class (out-link, no mutation) is rendered. The
`contract` and `agent` classes arrive only with future action slices that carry their own contracts;
introducing them earlier would violate the read-only v1 boundary. The pack's placement
recommendation — a `Button` variant axis in the design system rather than cockpit-local styling —
is accepted as direction but deferred with the other design-system promotions (same posture as
EXT-1..4).

### EXT-6 — Hold-to-confirm interaction — REJECT for v1

No writes exist in v1, so the interaction has no site. Additionally it cannot become canonical
before an equivalent non-press accessibility path is designed. Re-open only with the first
write-capable slice.

### EXT-7 — Risk meter (four ticks) — ACCEPT as within-band ordering signal only

Accepted with the constraint written into its contract: ordering applies strictly *within* a band,
never between bands, and per ADR-0057 A1 a maturity/risk number is a signal to read, not a
selection input. No scalar maturity number is ever displayed; a thread never disappears or is
demoted for scoring low. Enacted by `CHAIN_DERIVED_STATES.md`.

## Owner-facing questions about the surface

### Q1 — What makes a thread forgotten? — ACCEPT the design's model

Forgotten = age **plus** absence of movement in the thread's own authority (GitHub/dispatcher
events), both shown in clear text on the card — equivalently, the process chain has stalled without
closure. Pure age is rejected: it would turn the forgotten band into a seniority list. Enacted by
`CHAIN_DERIVED_STATES.md`.

### Q2 — Should the forgotten band have a cap? — ACCEPT no cap

The band grows without limit (23 rows at 41 threads in the drawn many-at-once state). A cap with
"+n older" introduces a silence nobody sees, which is exactly the failure mode this surface exists
to prevent. The surface gets longer, never quieter.

### Q3 — Where does "tried by you" live until a receipt contract exists? — ACCEPT visible absence

The tier renders, is empty, and says why — an honest claim, shipped in #4438. The
owner-acceptance receipt contract itself (INV-DG-7; completion item 5 in
`docs/audits/DELIVERY_GRAPH_JOIN_SUBSTRATE_2026-07-30.md :: RQ3 — Renderable today; minimal
completion set`) is **owner-gated** and out of v1; it is the one intake item this ledger cannot
close.

### Q4 — Should horizontal capability scrolling have a cap? — ACCEPT no cap; stacking at narrow widths

Capability lanes grow horizontally without an artificial cap; at narrow widths and 200% zoom the
drawn state is a single stacked column in document order with no horizontal scrolling. Enacted by
`DOCS_PLANE_CAPABILITY_LANES.md` and `SURFACE_LENSES.md`.

### Q5 — Rate-limit / cache posture for read-time GitHub joins — DECIDED: live reads, no persisted cache, refused claim on failure

v1 reads GitHub through REST at render time with no cache that survives a reload; each read names
its own instant, and a failed or rate-limited read degrades to the refused-claim state
("cannot be counted"), never to stale data presented as fresh. GitHub-derived fields that come from
the dispatcher's sync mirror **must begin naming the mirror's own watermark**
(`sync_state.last_pull_at`) instead of implying liveness — the delivered registry does not do this
yet; `GITHUB_LIVE_PLANE.md` carries the AC.
The mirror-cache posture (a fourth source-pill state, "read from mirror, not from the authority")
belongs to the future ADR-0062 independent-service home and is out of v1. Enacted by
`GITHUB_LIVE_PLANE.md`.
