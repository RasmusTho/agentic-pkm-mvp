State: Accepted (owner decision 2026-07-05; ratified 2026-07-06 via setup #3055). Establishes that constituent-surface repos are governed constituents of Yggdrasil, developed by the Builder System (not detached projects); names the native-app client repo **Bifrost**; and adopts **traditional Swedish spelling** for the ecosystem name register (**Heimdal**, **Bifrost**). Decision record only; creates no repo and moves no code. The mechanical rename across the corpus is a bounded enactment (#3060), deferred per the ADR-0044 rename precedent.
Doc role: Decision record (ADR)
Authority: Authoritative for (a) the cross-repo governance rule — how the Yggdrasil ecosystem spans more than one repository while keeping one governance authority, (b) the naming of the native-app client repo (**Bifrost**), and (c) the register's adoption of traditional Swedish spelling (Heimdal, Bifrost). Extends ADR-0044 (multi-repo precedent + Norse name register) and ADR-0049 §4 (topology C); amends the *spelling* of the register set in ADR-0043/0044. Does not create the repo, define any constituent's internals, or add a constituent (Bifrost hosts *clients* of Heimdal + Mimer; it is not a new constituent). Cross-repo scope + naming are owner-reserved (R-SOS / R-NAME) and recorded here as the owner's locked decision.
Owner: Architecture / CES stewardship (Rasmus)
Temporal class: Durable decision (supersede via a new ADR only if constituent-surface-repo ownership/governance changes, the register spelling is reversed, or the Bifrost referent is reassigned).
Source of truth: This ADR plus ADR-0049 §4 (native-app topology C), ADR-0044 (private-bindings-outside-public-repo precedent + name register + deferred-rename precedent), ADR-0043 (Norse name register + alias-collision-fix precedent), setup task #3055, rename enactment #3060, and `docs/ENVIRONMENTS.md` § Vault terminology (the mutable vault-label register that Bifrost currently also appears in).

# ADR-0050: Cross-repo governance + the Bifrost native-app repo; the name register adopts traditional Swedish spelling (Heimdal, Bifrost)

**Date:** 2026-07-05
**Status:** Accepted (owner decision 2026-07-05; ratified 2026-07-06 via setup #3055)

---

## Context

ADR-0049 §4 fixed the native-app topology (**C — one shell, two bounded clients, splittable**) but left the
apps' *home* open. The owner ruled (2026-07-05): the native apps get a **separate repository**, but its
development must be **owned by Yggdrasil / the Builder System** — a governed constituent repo, **not a
detached island**. This is not new ground: **ADR-0044** already places the **private-bindings constituent
outside the public repo** (OD-4), so the ecosystem is already an acknowledged System-of-Systems that
**spans repositories**. What was missing is the explicit rule that such a repo inherits ecosystem
governance rather than forking it, and a name for the app repo. The owner also ruled that the ecosystem
name register uses **traditional Swedish spelling** — **Heimdal** (not "Heimdall"), **Bifrost** (not
"Bifröst"). This ADR records all three.

## Decision (owner, locked 2026-07-05)

### 1. Constituent-surface repos are governed constituents of Yggdrasil

A repository that hosts a **surface of the ecosystem** — native-app clients, private-bindings, future
sibling servers — is a **governed constituent of Yggdrasil**, not an independent project. It inherits, and
does **not** fork, ecosystem governance:

- **Authority spans it.** The ecosystem ADR/CES record (ADR-0043/0044/0049 and this ADR) governs it; it has
  no separate constitution. Cross-repo decisions route through the same CES/ADR process.
- **The Builder System develops it.** The delivery-skills chain, the Issue task contract + templates, the
  PR contract/lanes, the label set, CI gates, and BuilderOps routing extend into it — **adapted to its
  stack** (for Bifrost: Swift/iOS/iPadOS/watchOS build + test + lint in place of the Python `ruff`/`mypy`/
  `pytest` gates). Agents build it the same way they build the hub repo.
- **One source of truth for tracking.** Epic B #3020, B1–B3 (#3023/#3024/#3026), and setup #3055 stay
  tracked in the **hub repo** until Bifrost has its own board; work is not double-tracked.
- **SBS-classified.** A constituent-surface repo is a **Product/Runtime System** surface **built by the
  Builder System**; the boundary is classified per `docs/architecture/SBS_OPERATING_MODEL.md`.

### 2. The native-app client repo is **Bifrost** (repo `bifrost`)

The topology-C app repo is named **Bifrost**. In the cosmology, **Bifrost is the rainbow bridge between
Midgård (the human world) and the realm of the gods — guarded by Heimdal.** That is exactly what these
apps are: the **bridge between the human and the ecosystem's constituents**, with Heimdal (the sensor)
standing at the near end. Bifrost is a **client-surface repo, not a new constituent**: the constituents
remain **Heimdal** (sensor) and **Mimer** (cognition); Bifrost hosts *their clients* (the Heimdal capture
client, the Mimer knowledge clients). It is added to the ecosystem **Norse name register** (extending
ADR-0043/0044) as a *repo/surface* name, under the pantheon-per-constituent naming principle.

### 2b. The name register adopts traditional Swedish spelling (Heimdal, Bifrost)

The ecosystem name register uses **traditional Swedish spelling**. The canonical forms are **Heimdal** (not
"Heimdall") and **Bifrost** (not "Bifröst"); Mimer, Yggdrasil, and Midgård already carry their Swedish
forms and are unchanged. This is the **authoritative spelling going forward** and amends the *spelling* of
the register set in ADR-0043/0044 (their structural decisions stand; only orthography changes).

Per the **ADR-0044 deferred-rename precedent** (the recorded `yggdrasil_runtime→Mimer` rename was booked as
a bounded mechanical enactment, not performed in the ADR), the corpus rename is a **bounded enactment
(#3060)**: `docs/HEIMDALL/`→`docs/HEIMDAL/` + content, the ADR living references/prose, the open Heimdal v1
/ Bifrost issues, and any future `heimdal` code namespace. **Merged historical decision prose is not
rewritten to misrepresent what was recorded**; the register (this ADR) is authoritative for current
spelling. Memory + design working artifacts are normalized in the same session.

**Vault-environment labels** likewise use Swedish spelling — the dev vault is **Nifelheim** (not
"Niflheim"). But vault labels are **mutable, non-hardcoded env names that are rarely referenced** (owner,
2026-07-05), so they are **not** part of the code/doc rename: the ~120 existing illustrative/fixture
references (including a test assertion) stand as-is, and Nifelheim is simply the label going forward. The
constituent/repo names (Heimdal, Bifrost) are the durable architectural names the rename normalizes.

### 3. Naming-collision disposition (Bifrost also labels the test vault) — owner-accepted

"Bifrost" also labels the **test vault** (dev = Nifelheim, test = **Bifrost**, prod = Midgård), so with the
Swedish spelling the repo name and the vault label are spelled identically. **Owner disposition
(2026-07-05): accept the collision — no test-vault rename.** Vault-environment labels are mutable, must not
be hardcoded, and are rarely referenced; the repo/bridge **Bifrost** is the durable architectural name and
wins on the rare occasion prose must disambiguate ("the Bifrost repo" vs "the test vault"). This differs
from ADR-0043's observability-alias collision, which was code-facing and warranted a rename to **OEF**; a
rarely-referenced vault label does not. No action; the collision is accepted and noted.

## Constraints honored

- Decision record only — **no repo is created**, no code moves, no vault is renamed, no corpus rename runs here.
- No constituent is added or redefined: Bifrost hosts clients of Heimdal + Mimer; the constituent set is
  unchanged (ADR-0044).
- Governance is inherited, not forked: one ecosystem CES/ADR authority across repos.
- Spelling change is orthographic only; ADR-0043/0044 structural decisions are untouched.
- Single-user stance preserved: one operator; the ecosystem spans repos, the human does not.

## Consequences

- The Bifrost repo, once created (setup #3055), is a first-class governed surface: ecosystem ADRs bind it,
  the Builder System builds it, and B1–B3 proceed inside it under the same delivery discipline.
- The ecosystem's multi-repo shape is now explicit (hub repo + private-bindings + Bifrost), generalizing
  ADR-0044's single precedent into a rule.
- The register's canonical spelling is Heimdal / Bifrost; the corpus rename runs as enactment #3060.
- The Bifrost/test-vault collision is **owner-accepted** (no test-vault rename; the vault is rarely
  referenced); prose qualifies where needed. The `bifrost` repo is created **private** (owner, 2026-07-05).
- Setup #3055 is **delivered** (2026-07-06): the `bifrost` repo exists (private), its README declares it a
  governed Yggdrasil constituent under ecosystem ADR/CES authority, and the Builder-System scaffolding —
  `AGENTS.md` (inherited authority), Issue + PR contracts, delivery-skill routing + `_shared` contracts,
  the label taxonomy, and Swift/iOS CI (build + test + lint) — is live in the repo. This ratification (this
  edit) records AC4; #3055 no longer blocks B1–B3.

## When to revisit

Supersede only if constituent-surface repos stop being Yggdrasil-owned / Builder-System-developed, if the
one-authority-across-repos rule changes, if the register spelling is reversed, or if the **Bifrost**
referent is reassigned.

## References

- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §4 — native-app topology C.
  *(Filename kept as a historical identifier; content + path refs normalized to Heimdal / `docs/HEIMDAL/`
  by enactment #3060.)*
- `docs/adr/ADR-0044-research08-d1-conforms-to-acknowledged-sos.md` — private-bindings-outside-public-repo
  precedent (OD-4), the Norse name register (extended here), and the deferred-rename precedent.
- `docs/adr/ADR-0043-heimdall-naming-and-norse-name-register.md` — name register + the observability-alias
  collision-fix precedent (→ OEF), the pattern applied to the Bifrost/test-vault collision.
- Rename enactment **#3060** (Heimdall→Heimdal, Bifröst→Bifrost across the corpus).
- Setup task #3055 (establish Bifrost under Builder-System governance); Epic B #3020; B1 #3023 / B2 #3024 /
  B3 #3026.
- `docs/ENVIRONMENTS.md` § Vault terminology — the mutable vault-label register (dev/test/prod).
