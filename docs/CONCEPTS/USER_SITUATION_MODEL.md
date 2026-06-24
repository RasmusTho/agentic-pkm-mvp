State: Populated — situations enumerated with grounded human intent. Settled rows link their governing decision; partial/forward-line rows are marked; open product choices are in the Open Decisions register. R1 (entry-state enum vs. vault-selection) and R2 (latency-ladder vs. leave-point TTL) resolved by #2488/#2489 (2026-06-24). Remaining register items are genuine open product choices or tracked in other issues.
Doc role: Concept contract companion
Authority: Canonical statement of what the human wants when meeting the system in a given situation/state. Upstream of the entry-point and vault-optional capability specs, which implement these situations; subordinate to the function-axis docs (`docs/HUMAN-FLOWS.md`, `docs/CONCEPTS/USER_NEEDS_MODEL.md`). Settled rows are binding and linked to their governing decision; forward-line rows are intent statements pending runtime, not current-state claims (`docs/STATUS.md` owns shipped reality).
Owner: Product / human-function SoT

# User Situation Model

> Audience: product and architecture readers deciding how the system should behave when the
> human meets it in a particular condition (no vault yet, returning cold, runtime degraded,
> switching vaults, on a narrow device). Human intent is canonical; the runtime state machine
> implements it, it does not define it.

## Why this document exists

`docs/HUMAN-FLOWS.md` and `docs/CONCEPTS/USER_NEEDS_MODEL.md` model the **function axis** — *what the
system is for* (capture, reorient, commit, learn, create) and *what the human needs*. They are
strong on what the human is trying to **do**.

They do not model the **situation axis** — the *condition the human is in when they meet the
system*: there is no vault selected yet, this is first contact, they are returning cold after weeks,
the runtime is degraded, they are switching vaults, they are on a read-only tablet. The same
function (say, *reorient*) must behave differently depending on the situation the human is in.

The vault-selection work made the gap visible: decisions like "first contact shows a vault picker,
not a greeting" and "a long cold return offers no resume affordance" are **situational-intent**
decisions. They were reasoned out inside ADRs and capability specs because there was no upstream
artifact that enumerates the situations and states what the human wants in each. This document is
that artifact. Its job is to keep the next situational decision a matter of *reading* rather than
*re-arguing*, and to keep that material out of `docs/HUMAN-FLOWS.md` so the function-axis doc stays
about purpose.

This is the dual of the function axis:

| Axis | Question | Owning doc(s) |
| --- | --- | --- |
| Function | What is the human trying to do? | `docs/HUMAN-FLOWS.md`, `docs/CONCEPTS/USER_NEEDS_MODEL.md` |
| Situation | What condition is the human in when they meet the system? | **this document** |

## How to use this document

Use it when:
- deciding how a surface should behave on first contact, on return, when degraded, or with no/other vault,
- writing or reviewing an entry-point / vault / device capability spec — check it against the human
  intent declared here, do not invent the intent inside the spec,
- reviewing whether a runtime entry state still serves what the human actually wants in that situation.

Do not use it to:
- define the runtime state machine, transition table, or selectors — that is downstream
  (`docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md`),
- restate function-axis intent (capture/reorient/etc.) — link to the function-axis docs instead,
- record current shipped reality — `docs/STATUS.md` and owner docs own that.

## Relationship to downstream specs

This document is **upstream and normative on human intent**. The following are **downstream
implementers** — they realize the situations as runtime states, transitions, and UI; they should
cite the relevant situation here rather than declaring the intent themselves:

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` — the normative entry-point state model the renderer keys off.
- `docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md` — server-resolved states `boot`, `no_vault`,
  `cold_start`, `orienting`, `shell_active` and the `degraded`/`stale` cross-flags.
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` — orientation payloads, degraded/unavailable contracts.
- `companion-ui/docs/CONTINUITY_AND_DECAY.md` + `docs/SYSTEM_ENTRY_POINT/REENTRY_ORIENTATION_TREATMENT.md` — latency ladder and re-entry shapes.
- `docs/VAULT_OPTIONAL_RUNTIME/**` — boot-without-vault, no-vault resolution, optional-vault boundaries.
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`, `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`, `docs/ENVIRONMENTS.md` — vault status, topology, and terminology.

When a downstream spec and this model disagree on *what the human wants*, this model is the one to
fix or appeal to; when they disagree on *current behavior*, the owner doc / `STATUS.md` wins.

## Status legend

Each situation carries a **Status**:
- `settled` — human intent is decided and binding; the governing decision is named.
- `partial` — intent is decided in principle but the runtime (or a reconciling spec) is incomplete.
- `forward-line` — intent is grounded in a stable principle but no runtime realizes it yet.

Two situations also carry a **⚠ contradiction** flag: the product intent is settled, but two
downstream specs currently disagree on the mechanism. These are doc bugs to fix, collected in the
Open Decisions register, not blanks to fill here.

## Cross-cutting constraint — dyslexia-friendly input (no manual paths)

The human is dyslexia-first. **No human-facing situation may require typing or pasting a filesystem
path, search string, or other free-text identifier to proceed.** Wherever a situation needs the human
to point at something — select a vault, locate a moved vault, open a recent note — it must be a
*visual pick*: a native folder/file chooser, a list of recognizable candidates, recents, or browse —
never a text field the human has to spell correctly. This is an accessibility requirement, not a
preference (owner decision, 2026-06-24). It binds A1 (vault selection), B2 (vault recovery), and any
future human entry surface.

This is the **human** half of the dual user model: it constrains human-facing surfaces only.
Agent-facing CLI/API surfaces are unaffected — paths and structured identifiers are appropriate
there. The canonical statement of the dual user model and the dyslexia-friendly boundary lives in
`docs/HUMAN-FLOWS.md` §0 ("Dyslexia-friendly surfaces and the dual user model"); this constraint is
its situational-input instance.

---

## Cluster A — Entry and lifecycle situations

How the human first meets, leaves, and re-meets the system.

### A1. First contact — no vault selected yet

- **Situation:** the system has never been pointed at a vault, or none is currently selected.
- **Human intent:** be guided through a short initiation flow that offers a clear choice — **create a
  new vault** or **open an existing one** — and complete either path through a friendly *visual*
  chooser. The human must never type or paste a path or search string; selection is always by
  browse/pick (native folder chooser, recent-vaults list, visible candidates) per the cross-cutting
  dyslexia-friendly constraint above. First contact is a guided create-or-open situation, not a
  greeting and not a text-entry form. The system still boots and stays usable for everything that
  does not require a vault (`docs/VAULT_OPTIONAL_RUNTIME/BOOT_RUNTIME_WITHOUT_VAULT.md`); the
  companion boundary returns an explicit `vault_selection_required` with recent vaults to open, never
  an empty or wrong fallback (`docs/VAULT_OPTIONAL_RUNTIME/RESOLVE_NO_VAULT_STATE.md`).
- **Good:** a guided flow where both *create new* and *open existing* are reachable without typing a
  path; selection is by visual pick / recents / browse; selecting re-resolves in-process and renders
  real note bodies with no restart; the system is usable without a vault for non-vault functions.
- **Bad:** asking the human to type or paste a path/search string anywhere in selection or creation;
  a fabricated "welcome back" snapshot; falling back to a CWD-relative `./vault`; gating the whole
  boot path on a configured vault.
- **Realized by:** `vault_selection_required` over `resolve_optional_vault_root()`; picker UI (#1867)
  — to be extended with a guided create-new-vault path.
- **Status:** `settled` — vault selection is source of truth; system boots with no vault
  (`docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`; "Vault Optional at Runtime", #2004/#2006); the
  first-contact flow is the **guided create-or-open chooser with no path typing** (owner decision,
  2026-06-24, R1). **R1 reconciled (#2488):** the no-vault-bound first-contact picker resolves to
  the **`no_vault`** state (not a `cold_start` sub-shape). The `vault_selection_required` sentinel
  from `resolve_optional_vault_root()` maps to `data-entry-state="no_vault"` in the shipped
  renderer (`serve_dev_page.py`; asserted by `test_workspace_no_vault_picker.py`). The `no_vault`
  state covers two cases: (a) orientation HTTP 503 (runtime unreachable) and (b) orientation
  returning `vault_selection_required` (no vault bound). `cold_start` is reserved for the
  vault-bound cold trajectory only (>7d, leave_point absent). See `companion-ui/docs/
  SYSTEM_ENTRY_POINT_SPEC.md §First-contact / no-vault-bound picker`. Picker UI implementation
  (#1867 + #2312) is downstream.

### A2. Boot / handshake in progress

- **Situation:** the system is starting and orientation has not yet resolved.
- **Human intent:** a calm, honest "starting" state — no fabricated snapshot, no alarm — that resolves
  into the right situation once the handshake completes, and the state any client retry returns to
  (`docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md`).
- **Good:** the shell declares `boot` in the pending-orientation render; on failure it transitions to
  an honest unavailable state with a retry path.
- **Bad:** showing stale or invented orientation content as if live; the UI re-deriving entry state
  locally instead of rendering the server-declared one ("server declares; UI renders").
- **Realized by:** `boot` state in `resolve_entry_state()`.
- **Status:** `settled` (SEP-01, #1783).

### A3. Returning warm — short gap (recent leave point)

- **Situation:** the human returns after a short absence with a live leave point.
- **Human intent:** low-cost cognitive re-entry — enough context to resume the trajectory without
  reconstructing it — felt at the periphery, never as a dashboard. The treatment is calibrated to the
  gap (identity under ~90s; faint ambient cues through a few hours; a four-question "full mist" card
  for longer short gaps), and unresolved tension shows as *counts, not enumerations*
  (`companion-ui/docs/CONTINUITY_AND_DECAY.md`; `docs/SYSTEM_ENTRY_POINT/REENTRY_ORIENTATION_TREATMENT.md`).
- **Good:** a warm re-entry shape sized to the gap; resume is a peripheral affordance; visible items
  are capped (display budget), the shell opens in a recovery posture.
- **Bad:** a card that enumerates/badges/centers on the document (an inbox, not a continuity aid); any
  notification/urgency/push semantics; asking the human to declare their trajectory state.
- **Realized by:** `orienting` + `data-reentry-shape`; `leave_point` projected by orientation (ADR-0008).
- **Status:** `settled` (SEP-01/SEP-02; ≤7d return resumes via a warm re-entry card, #2453).

### A4. Returning cold — long gap ⚠

- **Situation:** the human returns after a long absence; the leave point has expired.
- **Human intent:** honesty over false continuity. The system must not claim to reconstruct a
  trajectory it cannot back. A long cold return anchors on current reality (an honest "re-entry is
  through the vault" threshold, optionally a labelled "open your most recent note" Find affordance
  that carries *no* continuity semantics) and offers no resume
  (`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`; `companion-ui/docs/CONTINUITY_AND_DECAY.md`).
- **Good:** `cold_start` renders a calm threshold with no mist/card/count; provenance is stated
  honestly; any recents anchor is an opt-in sub-affordance, never auto-opened.
- **Bad:** a resume button pointing at expired/unreachable context; the renderer ignoring the resolved
  `cold_start` state and drawing the orientation grid anyway (the 2026-06-19 divergence).
- **Realized by:** `cold_start` (leave_point absent OR cold trajectory >7d — beyond the leave-point cursor TTL, ADR-0008).
- **Status:** `settled` — threshold and cold boundary aligned (#2171/#2176; >7d cold return has no
  resume affordance; #2453; #2472 closed as unreachable). **R2 resolved (#2489):** the latency
  ladder's `long_mist` upper bound is now 7d (was 14d) in `companion-ui/docs/CONTINUITY_AND_DECAY.md`
  and `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`; the 7–14d window that was unbacked by the
  leave-point cursor TTL (ADR-0008) is no longer described as recoverable. No surface promises a
  re-entry the trace cannot back. The leave-point TTL remains 7d (ADR-0008 unchanged); extending
  resume to 14d would require a new ADR and is a separate product decision.

### A5. Active session — working in a document

- **Situation:** the human is actively working on a selected note.
- **Human intent:** the document is the anchor and the front door, not a dashboard. Every assistive
  surface (Panel, vault browser, command palette, capture, memory review, receipts) augments the
  current document and dismisses back to it with no route reset and no loss of staged suggestions or
  open-loop counts (`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` overlay-grammar rule). Durable
  mutations route only through the governed pipeline; the canvas body-edit lane is the one deliberate
  receipt-free exception.
- **Good:** `shell_active` with the document open; overlays open/close without leaving the state;
  governed intents surface receipts; Chat ≠ Panel ≠ Automation stays distinct.
- **Bad:** an overlay that replaces the document or resets navigation; the entry surface becoming a
  home screen of cards/counts/feeds; the UI inventing receipts.
- **Realized by:** `shell_active`; adaptive 3-column workspace (#1395) + overlay host (SEP-03).
- **Status:** `settled` (SEP-01/03/04/07–10; state gallery #1795).

### A6. Mid-session interruption and return-to-context

- **Situation:** the human was interrupted mid-thread and returns within the same working span.
- **Human intent:** unresolved cognitive tension is preserved and re-presentable at the lowest
  interruption cost — open synthesis and conflicting sources hold ambient visibility and do *not*
  decay on the standard time curve; a residual ambient layer (caret echo, marginalia) persists into
  the resumed session, and dismissal never erases staged suggestions or open-loop counts
  (`companion-ui/docs/CONTINUITY_AND_DECAY.md`). If the leave point is stale/missing, resume is a
  calm guard-held state that names the cause and states nothing was mutated — not a silent jump or an
  error toast.
- **Good:** residual ambient layer on resume; staged objects stay bound to their source note; a stale
  leave point still renders a qualified, guard-held resume.
- **Bad:** silently resuming into a moved/missing artifact; dismissal erasing tension/counts; letting
  unresolved tension decay before it is resolved.
- **Realized by:** `orienting → shell_active` via `entry.resume`; residual ambient layer; guard-held
  stale treatment (`companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md`).
- **Status:** `settled` (SEP-02), subject to the same 7d leave-point cursor TTL as A4; interruptions longer than 7d resolve to `cold_start` (R2 resolved, #2489).

---

## Cluster B — Vault and scope situations

Which vault is active, and what happens when that changes or is unavailable.

### B1. Switching the active vault

- **Situation:** the human moves the system's attention from one registered vault to another.
- **Human intent:** switch in-process without restart and without the previous vault's content,
  watchers, or permissions bleeding into the new one; the newly-selected vault becomes the single
  source of truth (a configured `VAULT_ROOT` is explicitly not the active vault). Reorientation must
  be at-worst-neutral so the human never has to remember "which vault was I in?"
  (`docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`; `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`).
- **Good:** selecting vault B re-resolves in-process and renders B's notes with no restart; old
  watchers/jobs stop, caches clear, settings reload, permissions re-derive; writes cannot escape the
  newly-selected vault (WriteGuard + path containment).
- **Bad:** split-brain (reads off the configured root while selection reports a different/none active
  vault) — the RCA Option-2 was decided to kill; stale watcher/index from vault A running against B,
  or B inheriting A's role/permissions.
- **Realized by:** `/api/companion/vault/{context,select}` + known/recent registry + last-active; the
  `vault.changed` lifecycle.
- **Status:** `settled` for single-active switch (Option-2 cutover, #2309/PR #2325).
  **Open product choice:** whether conversational/agent context, recall candidates, and in-memory
  retrieval state must hard-reset across a switch is undecided — see register item R3.

### B2. Configured vault missing or misconfigured

- **Situation:** the last-pointed path is gone, or the folder exists but its settings are broken.
- **Human intent:** be told the truth and offered a safe, non-destructive recovery — never a silent
  substitute vault and never an overwrite. Missing data is an *error*, not a no-vault state: a
  set-but-missing `VAULT_ROOT` fails loud, while an *unset* binding is the legitimate no-vault idle
  state; invalid settings are reported, not applied
  (`docs/ENVIRONMENTS.md`; `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`).
- **Good:** distinct statuses (`missing` / `invalid` / `uninitialized`) each with a non-destructive
  recovery (locate, choose another, reload settings, initialize) — where "locate"/"choose another"
  is a visual folder chooser, never a path field (cross-cutting constraint); set-but-missing fails
  loud across resolver, watcher, and start path.
- **Bad:** asking the human to type the correct path to recover; silent resolution to `./vault` so
  the UI looks empty/wrong (the "notes won't render" incident); a recovery action overwriting user
  files; invalid/conflicted settings applied silently.
- **Realized by:** `VaultStatus` (`none`/`selected`/`missing`/`invalid`/`uninitialized`) +
  `VaultRootMisconfiguredError`.
- **Status:** `settled` (fail-loud on set-but-missing; recovery matrix). `partial` residual: migrating
  legacy eager `resolve_vault_root()` consumers off the silent fallback is still in flight (#2311).

### B3. Multiple vaults across environments

- **Situation:** the same product runs against several vaults — by channel (dev/test/prod), or
  potentially one human's material laid across more than one vault.
- **Human intent:** keep vault identity explicit and operator-owned (names mutable, never hardcoded);
  keep environment vaults isolated (dev/test/prod must not share one writable surface). Any
  multi-vault *topology* must keep one identity per artifact, no hidden source of truth, real
  authority boundaries, and stay losslessly reducible to a single vault — single-vault is the floor,
  not a default to move away from (`docs/ENVIRONMENTS.md`; `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`).
- **Good:** each channel binds a distinct operator-configured vault with scoped DB/artifacts; any
  topology preserves identity, provenance, orientation, and reversibility; the human can select a
  vault on any disk in-process once it is registered.
- **Bad:** environment isolation collapsing; a topology used as a workaround for missing scope or
  retrieval, forcing the human to remember which vault to look in, or forking artifact identity.
- **Realized by:** per-channel environment model (shipped, cross-environment); the topology *rules*
  (`VAULT_TOPOLOGY_CONTRACT.md`); multi-active-vault runtime deferred to epic #2143.
- **Status:** `partial` — environment separation settled; same-human multi-*active*-vault is deferred
  and only foundationally enabled (one active vault today). Whether to build it, plus init-scaffolding
  placement (#2312) and nested-vault boundaries (#2313), are open — see register items R4–R6.

---

## Cluster C — Device and continuity situations

Same human, different device roles, with local-first artifacts primary. Multi-node sync is a stable
forward-line intent, not shipped runtime: the synchronization/federation subsystem is declared but
runs as a single-node no-op in the current baseline (ADR-0020), so these rows state intent the
runtime does not yet realize.

### C1. Rich home node

- **Situation:** the human is on the primary device that runs the full ingest/watch/runtime loop.
- **Human intent:** one device carries the full cognitive runtime so heavy assistance has a home, and
  it can do the housekeeping/promotion/consolidation that narrower nodes defer — without becoming a
  *required, always-online hub* the human must centralize everything in
  (`docs/HUMAN-FLOWS.md` §3/§13; `docs/CONCEPTS/USER_NEEDS_MODEL.md` #11).
- **Good:** full intelligence locally over the complete vault; the home node owns its own rebuildable
  stores/indexes and resolves global-structure conflicts.
- **Bad:** the home node's derived DB/index becoming the authoritative cognitive record over the vault
  files; the human pressured to centralize everything in one always-online node.
- **Realized by:** the current single-node runtime; the *named* master role is forward-line (ADR-0020).
- **Status:** `partial` — single rich node exists; the master-vs-satellite distinction is declared-not-built.

### C2. Read-light tablet (eventual sync)

- **Situation:** the human reads and lightly edits from a tablet, with changes propagated by file sync
  (iCloud), tolerating eventual rather than instantaneous convergence.
- **Human intent:** central artifacts (vault Markdown + companion notes) render and stay comprehensible
  without the runtime present; offline edits converge later; lag is normal operation, not failure; the
  minimum preserved is capture, reading central artifacts, and basic orientation
  (`docs/HUMAN-FLOWS.md` §3/§13; `docs/CONCEPTS/USER_NEEDS_MODEL.md` #11).
- **Good:** artifacts readable offline; a lagging/partial replica is the *same* artifact, not a new
  identity or data loss; richer assistance may simply be absent here and that asymmetry is legible.
- **Bad:** treating the lagging replica as a different artifact; a meaning-bearing sync collision
  silently overwriting an edit; demanding the tablet run the rich runtime to be useful.
- **Realized by:** iCloud-as-transport is realized (the runtime reacts to changed files); the tablet
  *node* with read-light capability and conflict handling is forward-line (`PROTOCOL_SATELLITE_SYNC.md`).
- **Status:** `partial` — file transport real; read-light client and conflict UX unbuilt. **Open
  product choice:** is "light editing" bounded to body edits, or may the tablet make governance-bearing
  changes offline? Undecided — see register item R7.

### C3. Narrow / git satellite node

- **Situation:** a laptop or narrower satellite participates over Git-backed sync with delayed or
  reduced local capability.
- **Human intent:** the satellite holds a possibly-partial replica, runs local capability over its
  subset, edits offline, and syncs tracked Markdown back, while keeping local-file ownership and
  recovering continuity from the file-based artifacts; `uuid` stays the stable cross-instance identity
  through merges (`docs/HUMAN-FLOWS.md` §3/§13; `PROTOCOL_SATELLITE_SYNC.md`; `PORTABILITY_CONTRACT.md`).
- **Good:** partial replicas and narrow roles are legitimate states; stores are rebuilt per-instance,
  not replicated; continuity recoverable from text even when runtime state differs across nodes.
- **Bad:** a same-note conflict resolved by silent agent overwrite (complex semantic conflicts need
  human review); cross-OS path/Unicode/newline divergence creating ghost-duplicate identities;
  narrowness dropping below the minimum continuity floor.
- **Realized by:** forward-line (`PROTOCOL_SATELLITE_SYNC.md`; only `instance_id` plumbing exists today).
- **Status:** `forward-line`. **Open product choice:** the human-facing conflict experience for a
  converged-late iCloud/Git conflict (where it surfaces, on which node) is unspecified — register item R8.

---

## Cluster D — Health and degradation situations

When the runtime is not at full capability. The core posture is **settled**: degradation is
*shown-with-warning, source named, never fabricated, never silently substituted* — "trust is lost
more by silent overreach than by visible incompleteness" (`docs/HUMAN-FLOWS.md` §11).

### D1. Degraded runtime / stale projections

- **Situation:** the runtime is reachable but one or more sources are partial or out of date.
- **Human intent:** keep working with an honest, visibly-marked partial view rather than a
  fabricated-complete one; the missing source is *named*, the rest of the surface stays calm, and any
  qualified resume states plainly that nothing was mutated
  (`companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`; `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`).
- **Good:** partial resolution returns a degraded snapshot of the same shape with `degraded_reasons`
  populated and a `data-degraded` flag; an amber banner names the missing source; `degraded`/`stale`
  are cross-flags decorating `orienting`/`shell_active`, never new implicit states.
- **Bad:** a partial result presented as a fresh complete snapshot; a local UI default substituted for
  a missing source; a stale state rendered as a generic error toast.
- **Realized by:** HTTP 200 degraded snapshot (`meta.freshness`, `meta.degraded_reasons`,
  `data-degraded`/`data-stale`); operator-side `view_freshness` honesty signal.
- **Status:** `settled` (#1783/#1784; state gallery #1795). Deferred (not undecided): whether a stale
  snapshot should auto-refresh in the background is flag-gated and off by default — register item R9.

### D2. Runtime unavailable

- **Situation:** the runtime aggregate cannot be reached at all.
- **Human intent:** be told the truth — "the source could not be reached" — with a calm read-only
  retry path and no fabricated snapshot; anything already typed (e.g. an in-flight capture) is plainly
  marked *not yet written* and never silently dropped (`docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md`;
  `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`).
- **Good:** a 503 resolves to an honest unavailable shell with an `entry.retry` affordance that returns
  to `boot`; an unsent capture stays usable and labelled not-yet-written.
- **Bad:** representing unavailability as a successful fresh snapshot; inventing a local default;
  silently swallowing typed text.
- **Realized by:** typed 503 payload from orientation; `entry.retry` (no pipeline); `boot ↔ no_vault`
  transitions.
- **Status:** `settled` (#1783). **Naming caveat:** `no_vault` labels *both* "no vault selected" and
  "runtime unreachable"; whether the human-facing copy should distinguish them is open — register item R10.

---

## Cluster E — Evolution situations

The system changes over time and across nodes.

### E1. Capability maturity asymmetry

- **Situation:** a capability (memory, retrieval, sync) is more mature on one node or version than another.
- **Human intent:** keep using the system while modules mature unevenly, without that asymmetry breaking
  continuity or trust; minimum continuity functions remain everywhere, modules evolve independently
  behind the stable vault surface, and the asymmetry is intelligible rather than read as failure
  (`docs/HUMAN-FLOWS.md` §3; `docs/CONCEPTS/USER_NEEDS_MODEL.md` #10/#12).
- **Good:** a capability can be mature on one node/version and absent on another while artifacts stay
  trustworthy regardless of which node touched them; the human is never trapped in an early model.
- **Bad:** a less-mature node silently writing lower-quality content into canonical artifacts the human
  can't distinguish from mature-node output; asymmetry forcing total redesign; modularity destroying usability.
- **Realized by:** forward-line — no runtime declares per-node/per-version maturity today; the nearest
  concrete mechanism is the single-node safety-strip `available`/`disabled` flag.
- **Status:** `forward-line`. **Open product choices:** should a node advertise which capabilities are
  mature/partial/absent, and should instance/version provenance be recorded for lower-maturity writes so
  they can be re-evaluated later? Both undecided — register items R11–R12.

---

## Open Decisions register

The point of this axis is to make situational decisions explicit. The items below are what populating
the model surfaced — grouped by what they actually need. They are candidates for `docs-to-issue`
extraction, not decisions to make inside this doc.

### Group 1 — Spec contradictions (resolved)

- **R1 — Entry-state enum vs. vault-selection state (A1) — RESOLVED (#2488, 2026-06-24).**
  Owner decision (2026-06-24): first contact without a vault bound is a **guided initiation flow** offering
  *create a new vault* or *open an existing one*, completed through a friendly visual chooser with
  **no manual path or search-string entry** (dyslexia-friendly; see the cross-cutting constraint).
  Resolved: the no-vault-bound first-contact picker resolves to the **`no_vault`** state (not a
  `cold_start` sub-shape). `SYSTEM_ENTRY_POINT_SPEC.md §First-contact / no-vault-bound picker` documents
  that `no_vault` covers both the 503 (runtime unreachable) and `vault_selection_required` (no vault
  bound) cases; `cold_start` is reserved for the vault-bound cold trajectory (>7d). The shipped renderer
  and `test_workspace_no_vault_picker.py` are the ground truth. Picker UI (#1867 + #2312) downstream.
- **R2 — Latency ladder promises re-entry the leave-point TTL can't back (A4/A6) — RESOLVED (#2489, 2026-06-24).**
  The ladder described a recoverable `long_mist` out to 14d; the leave-point cursor TTL (ADR-0008) is
  hard-capped at 7d. Resolved: `CONTINUITY_AND_DECAY.md` and `SYSTEM_ENTRY_POINT_SPEC.md` now align
  `long_mist` to 3d–7d and cold (>7d) — no surface promises recoverable re-entry beyond the TTL. ADR-0008
  unchanged; extending to 14d is a separate ADR decision.

### Group 2 — Open product choices (genuinely unowned)

- **R3 — Context-leak posture on vault switch (B1).** On switch, must conversational/agent context,
  recall candidates, and in-memory retrieval state hard-reset, or may they carry across? Cached paths
  and settings already reset; cross-vault *memory/context* reset is unspecified.
- **R7 — Tablet edit authority (C2).** Is "light editing" bounded to body edits (mirroring the
  WriteGuard active-note-body posture), or may a tablet make governance-bearing changes (classification,
  promotion, lifecycle) offline?
- **R8 — Meaning-bearing conflict UX (C2/C3).** How and where is a converged-late iCloud/Git same-note
  conflict presented to the human, on which node? Agents must not overwrite silently — but the surface is unspecified.
- **R10 — `no_vault` copy split (D2).** Should the runtime-unreachable case present distinct copy
  ("system unreachable — retry") from the no-vault-selected case ("pick a vault"), or is one shared
  calm surface intended? *Presentation only; low stakes.*
- **R11 — Declaring maturity to the human (E1).** Should a node advertise which capabilities are
  mature/partial/absent (generalizing the safety-strip flag), so asymmetry stays "understandable"?
- **R12 — Provenance of lower-maturity writes (E1).** When a less-mature node writes a canonical
  artifact, should instance/version provenance be recorded so it can be re-evaluated later?

### Group 3 — Already tracked / parked (decision pending, has an owner or issue)

- **R4 — Personal multi-vault in scope vs environment-only (B3).** Is same-human multi-*active*-vault
  (adjacent / master-satellite) something to build, or is multi-vault only the dev/test/prod split?
  Permitted but not mandated by the topology contract; epic #2143 unscheduled.
- **R5 — Initialize-folder-as-vault scaffolding placement (B3).** May the runtime write `settings/*.md`
  scaffolding into a *personal* content vault on init, and where? Issue #2312, `needs-human`.
- **R6 — Nested-vault boundary behavior (B3).** How to treat privately-initiated sub-vaults inside a
  selected vault (boundary detection, authority, enumeration)? Issue #2313, `needs-human`.
- **R9 — Ambient auto-refresh of a stale snapshot (D1).** Whether a degraded/stale snapshot
  foreground-refreshes itself is flag-gated (`COMPANION_ORIENTATION_AMBIENT_REFRESH`, ADR-0011) and off
  by default. Deferred, not undecided.
- **Master/satellite role + sync scheduling (C1–C3).** The synchronization/federation subsystem is a
  declared no-op single-node implementation until scheduled (ADR-0020). The device rows stay
  `forward-line` until this has a runtime milestone.

## Companion follow-up

Extend `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md` with situational scenarios (first contact / no vault,
warm vs cold return, degraded boot, vault switch) so they carry acceptance signals like the
function-scenarios do. Tracked separately from this doc.

## References

- `docs/HUMAN-FLOWS.md` — function axis (purpose, rhythms, life-cases).
- `docs/CONCEPTS/USER_NEEDS_MODEL.md` — human needs and intended benefits.
- `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md` — acceptance per scenario (to be extended with situational scenarios).
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`, `docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md` — entry-state implementation.
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`, `companion-ui/docs/CONTINUITY_AND_DECAY.md` — orientation + re-entry.
- `docs/VAULT_OPTIONAL_RUNTIME/README.md`, `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`, `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`, `docs/ENVIRONMENTS.md` — vault situations.
