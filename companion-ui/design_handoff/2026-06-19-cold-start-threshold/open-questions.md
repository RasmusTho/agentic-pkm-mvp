# Open questions — Cold-start entry threshold

Each question is triaged into one of:

- **resolve-before-promotion** — blocks Crossing B.
- **resolve-in-normalized-spec** — the normalized-spec author settles it.
- **defer-to-implementation-issue** — settled when the bounded issue is written.

**No `resolve-before-promotion` question is open.** The three operator decisions below were taken by the operator on 2026-06-19.

---

## Resolved by operator (2026-06-19)

### Q1. Adopt the recents-anchor ("Open your most recent note") Find sub-affordance? — *resolved: ADOPT*
The one element that gives a returning operator (full vault, > 14 d cold) something substantive to land on rather than a generic "Find a note", without claiming continuity (recency is a Find fact, not a `leave_point`).
**Decision: Adopt now**, as a server-declared, Find-framed, omitted-when-absent affordance. It requires a Core-Runtime contract field (see `implementation-contracts.md` §Proposed runtime contract field) so the UI renders a server fact, **never** a UI-side filesystem probe (which would violate "no direct vault I/O from the UI" and re-open the host-vs-container mount hazard #2141). *(Triage: defer-to-implementation-issue for the field shape; the decision itself is closed.)*

### Q2. `capture.open` on the entry surface — widen the spec, or drop capture from the door? — *resolved: WIDEN*
The inline capture field is the only *generative* affordance on an empty door; but `capture.open`'s declared Surface is `shell (⌘K) / map`, not `entry`.
**Decision: Amend the spec** — widen the `capture.open` Surface column to `shell (⌘K) / entry / map`. Zero new intents; reuses the shipped governed occupant verbatim; a proportional, governance-clean spec edit. Dropping it would re-open the "door is still just a passive no-file-open screen" complaint. *(Triage: resolve-in-normalized-spec — the Surface-column edit lands with the implementation PR per owner-doc bundling.)*

### Q3. Where do relocated governance/freshness telemetry projections live — and does rendering them in the map re-create the dashboard one layer deeper? — *resolved (operator default): read-only projection*
**Decision:** render relocated telemetry as **read-only projection, counts-not-tiles, no zero-state** inside the System map entry-point / governance nodes, and keep `freshness`/`as_of`/`trace` in the topbar runtime-status disclosure so an operator who relied on the deleted header meta row still has a pull path. **Hard requirement:** these must NOT render as live tiles. **Verify both pull paths actually render the values before deleting the header** — this is the one place "relocate behind the map" could quietly strand a diagnostic. *(Triage: defer-to-implementation-issue.)*

---

## Deferred to implementation issues

- **DQ4.** Exact copy for the eyebrow/headline variants (first-contact vs > 14 d cold) and the capture placeholder — settle in the cold_start threshold issue against `colors_and_type` / the Yggdrasil tokens.
- **DQ5.** Deterministic tiebreak rule for the recents-anchor when multiple notes share an `mtime` (path sort proposed) — settle in the Core-Runtime field issue.
- **DQ6.** Whether the topbar runtime-status disclosure already renders `freshness`/`trace`, or needs a new affordance — settle in the telemetry-relocation issue (gates header deletion).

## Not in scope for this package

- The pre-existing heading==body **duplication bug** on the `orienting`/`shell_active` path. It is filed as its own Companion-UI issue (it touches the warm-return path the operator sees most), **not** bundled into the threshold work. Root cause and fix point are recorded in `design-notes.md`.
- The dev cold-start **ingest gap** (objects present, chunks/embeddings empty) and the crash-loop fixes (#2140, #2142) — separate operational layers, already addressed; out of scope for the entry-surface design.
