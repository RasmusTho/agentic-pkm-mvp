State: SKELETON / draft — situation axis scaffold. Situations enumerated; per-situation human intent is partly settled (linked) and partly stubbed (TBD). Not yet a Core SoT; intended to become one once populated and reviewed.
Doc role: Concept contract companion (skeleton)
Authority: Intended canonical statement of what the human wants when meeting the system in a given situation/state. Upstream of the entry-point and vault-optional capability specs, which implement these situations; subordinate to the function-axis docs (`docs/HUMAN-FLOWS.md`, `docs/CONCEPTS/USER_NEEDS_MODEL.md`). While this doc is a skeleton it is descriptive, not yet binding; settled rows already binding are linked to their governing decision.
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

- `docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md` — server-resolved states `boot`, `no_vault`,
  `cold_start`, `orienting`, `shell_active`.
- `docs/SYSTEM_ENTRY_POINT/REENTRY_ORIENTATION_TREATMENT.md` — latency-ladder re-entry shapes.
- `docs/VAULT_OPTIONAL_RUNTIME/README.md` and its slices — boot-without-vault, no-vault resolution,
  optional-vault boundaries.
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` — normative entry-point spec the renderer keys off.

When a downstream spec and this model disagree on *what the human wants*, this model is the one to
fix or appeal to; when they disagree on *current behavior*, the owner doc / `STATUS.md` wins.

## Skeleton status and how to populate

This is a scaffold. Each situation below carries:
- **Situation** — the condition the human is in (stable).
- **Human intent** — what the human wants here. *This is the field to populate.* Settled rows link
  their governing decision; unsettled rows are marked `TBD` and are the real backlog this doc
  surfaces.
- **Good / Bad** — the success and failure shape of the situation (often stubbed).
- **Realized by** — the downstream state/spec, where one exists.
- **Status** — `settled` (intent decided, linked), `partial`, or `stub` (intent not yet decided).

Populating a `stub` row, or extracting one into a bounded issue, is later `docs-to-issue` work; this
PR only stands up the scaffold.

---

## Cluster A — Entry and lifecycle situations

How the human first meets, leaves, and re-meets the system.

### A1. First contact — no vault selected yet

- **Situation:** the system has never been pointed at a vault (or none is currently selected).
- **Human intent:** be offered an explicit way to select/open a vault — *not* greeted as if returning
  to known context. First contact is a vault-picker situation, not a cold-start greeting.
- **Good:** a clear, low-ceremony vault picker; the system boots and is usable without a vault for
  everything that does not require one.
- **Bad:** a fabricated "welcome back" snapshot; gating the whole boot path on a configured vault.
- **Realized by:** `no_vault` (entry state machine); `docs/VAULT_OPTIONAL_RUNTIME/` boot-without-vault
  and no-vault-resolution slices.
- **Status:** `settled` — vault selection is source of truth; system boots with no vault selected
  (entry model "no_vault vs return"; no-vault idle boot).

### A2. Boot / handshake in progress

- **Situation:** the system is starting and orientation has not yet resolved.
- **Human intent:** a stable, honest "starting" state — no fabricated content, a clear path once boot resolves.
- **Good:** a declared transient state that resolves into the right situation; client retry returns here.
- **Bad:** showing stale or invented orientation content as if live.
- **Realized by:** `boot` (entry state machine).
- **Status:** `partial` — runtime state exists; human-intent wording here is a stub to confirm.

### A3. Returning warm — short gap (recent leave point)

- **Situation:** the human returns after a short absence with a live leave point.
- **Human intent:** resume quickly — pick up near where they left off with a warm re-entry affordance.
- **Good:** a warm re-entry card / resume anchor that lowers restart cost.
- **Bad:** forcing a full cold re-orientation when context is still fresh.
- **Realized by:** `orienting` with a re-entry shape; warm re-entry card.
- **Status:** `settled` — ≤7d return resumes via a warm re-entry card.

### A4. Returning cold — long gap

- **Situation:** the human returns after a long absence; the leave point has expired.
- **Human intent:** be re-oriented, *not* offered a stale resume. A long cold return should anchor on
  current reality (recents/open loops), not on a now-meaningless "continue where you left off".
- **Good:** orientation to what matters now; no resume affordance that points at expired context.
- **Bad:** a resume button that drops the human into stale or unreachable context.
- **Realized by:** `cold_start` (entry state machine) — renders no re-entry overlay region.
- **Status:** `settled` — >14d cold return has no resume affordance (leave_point TTL 7d < cold_start
  14d makes resume unreachable by design).

### A5. Active session — working in a document

- **Situation:** the human is actively working on a selected note.
- **Human intent:** the document is the surface; orientation/overlays return to the document anchor
  rather than becoming separate apps.
- **Good:** the workspace shell stays document-anchored; surfaces compose around the note.
- **Bad:** overlays that strand the human away from the document they were working on.
- **Realized by:** `shell_active` (entry state machine).
- **Status:** `partial` — state exists; intent wording is a stub to confirm against the entry-point spec.

### A6. Mid-session interruption and return-to-context

- **Situation:** the human was interrupted mid-thread and is coming back within the same working span.
- **Human intent:** see what this work was, what mattered, and what was next, without reconstructing it.
- **Good:** latency-ladder re-entry treatment sized to how long they were away.
- **Bad:** a flat restart that discards in-flight context.
- **Realized by:** `orienting` + re-entry shapes (`REENTRY_ORIENTATION_TREATMENT.md`).
- **Status:** `partial`.

---

## Cluster B — Vault and scope situations

Which vault is active, and what happens when that changes or is unavailable.

### B1. Switching the active vault

- **Situation:** the human changes which vault is active.
- **Human intent:** TBD — switch cleanly without leaking the previous vault's context; the new active
  vault becomes source of truth.
- **Good / Bad:** TBD.
- **Realized by:** vault-selection cutover (selection as SoT); multi-vault epic (downstream).
- **Status:** `stub` — intent to be decided; anchor on "selection is source of truth, names are
  mutable, never hardcode vault identity".

### B2. Configured vault missing or misconfigured

- **Situation:** a vault is configured but its path is set-but-missing or otherwise invalid.
- **Human intent:** fail loud and route to an explicit "open vault" choice — never silently fall back
  to a wrong/empty vault.
- **Good:** a clear, recoverable error that leads to vault selection.
- **Bad:** a silent fallback that writes into or reads from the wrong place.
- **Realized by:** open-vault-on-missing-vault path.
- **Status:** `partial` — fail-loud decided; the picker route is a forward target.

### B3. Multiple vaults across environments

- **Situation:** the human (or the system) spans more than one vault (e.g. distinct personal vaults,
  or dev/test/prod environment vaults).
- **Human intent:** TBD — keep vault identity explicit and non-hardcoded; environment vaults stay isolated.
- **Good / Bad:** TBD.
- **Realized by:** multi-vault epic; environment/vault terminology owner doc.
- **Status:** `stub`.

---

## Cluster C — Device and continuity situations

Same human, different device roles, with local-first artifacts primary.

### C1. Rich home node

- **Situation:** the human is on the primary node that runs the full ingest/watch/runtime loop.
- **Human intent:** full assistance available; this node carries the richer capability.
- **Status:** `partial` — described in `HUMAN-FLOWS.md` §13 satellite/tablet flow; intent wording stub.

### C2. Read-light tablet (eventual sync)

- **Situation:** the human is on a tablet reading and lightly editing via file sync, with delayed state.
- **Human intent:** minimum continuity functions (read central artifacts, basic orientation, capture)
  remain available; asymmetry is understandable and does not threaten trust in the artifacts.
- **Status:** `partial`.

### C3. Narrow / git satellite node

- **Situation:** the human is on a laptop/satellite with narrower or delayed local capability.
- **Human intent:** continuity recoverable from file-based artifacts; reduced capability is legible,
  not a silent degradation.
- **Status:** `partial`.

---

## Cluster D — Health and degradation situations

When the runtime is not at full capability.

### D1. Degraded runtime / stale projections

- **Situation:** part of the runtime is unavailable or projections are stale.
- **Human intent:** TBD — make degradation visible (cross-flags), keep core artifacts usable, never
  present stale derived data as fresh.
- **Realized by:** `degraded` / `stale` cross-flags (entry state machine).
- **Status:** `stub`.

### D2. Runtime unavailable

- **Situation:** orientation/runtime cannot be reached at all.
- **Human intent:** an honest unavailable state with a retry path; no fabricated snapshot content.
- **Realized by:** `no_vault` resolution on orientation failure + `entry.retry` affordance.
- **Status:** `partial`.

---

## Cluster E — Evolution situations

The system changes over time and across nodes.

### E1. Capability maturity asymmetry

- **Situation:** a capability is more mature on one node or version than another.
- **Human intent:** TBD — asymmetry stays understandable; human value and artifact intelligibility are
  preserved across the transition (function continuity over module sameness).
- **Status:** `stub` — anchor on `USER_NEEDS_MODEL.md` §10/§12 (evolvability, modularity).

---

## Open situations to triage

Candidate situations not yet placed; confirm whether each is a distinct situation or a variant of one above:
- partial / interrupted capture (captured but not yet placed) — situation or function-axis concern?
- shared / multi-user presence — currently out of scope (single-user stance), but note the seam.
- explicit do-not-disturb / sleep — already owned as a scarcity-gate floor; cross-link rather than duplicate.

## References

- `docs/HUMAN-FLOWS.md` — function axis (purpose, rhythms, life-cases).
- `docs/CONCEPTS/USER_NEEDS_MODEL.md` — human needs and intended benefits.
- `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md` — acceptance per scenario (to be extended with situational scenarios).
- `docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md` — downstream entry-state implementation.
- `docs/VAULT_OPTIONAL_RUNTIME/README.md` — downstream vault-optional implementation.
