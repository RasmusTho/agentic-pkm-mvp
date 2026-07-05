State: Draft (advisory groundwork, 2026-07-04). The owner-reserved decision list for Heimdal: what Fable may NOT decide, plus the owner decisions captured in the 2026-07-04 session. Advisory until enacted through CES/ADR; creates no runtime behavior and no GitHub work.
Doc role: Owner-decision register (Draft)
Authority: Authoritative for which Heimdal decisions are reserved to the owner and for the recorded state of each captured decision. Subordinate to the ADRs/contracts that later enact any of these. Claims no shipped reality.
Owner: Rasmus (owner) — CES stewardship records
Temporal class: strategic
Review cadence: event-driven
Source of truth: this doc + the owner decision session 2026-07-04, ADR-0043, `ECOSYSTEM_SOS_MODEL.md`, `CAPABILITY_CHARTER.md`.

# Heimdal A4 — Owner decisions

Two parts: (1) the standing list of decisions **reserved to the owner** (Fable must stop and return
these, never decide them); (2) the **decisions already captured** on 2026-07-04.

---

## Part 1 — Reserved to the owner (Fable may not decide)

Fable (and any implementing agent) must treat the following as owner-only. Each is irreversible,
external-facing, legally loaded, or strategically load-bearing.

| ID | Reserved decision | Why it is the owner's |
|---|---|---|
| **R-SOS** | Whether the ecosystem is ratified as an acknowledged SoS and Yggdrasil is the whole (vs. a constituent) | Reshapes the current single-system SoT (ADR-0041); strategic + hard to reverse |
| **R-NAME** | Constituent/name assignments and any change to the name register | Naming is owner-gated; concept renames ripple across docs |
| **R-CONSENT** | Consent posture and always-on default (legal/ethical) | Legal exposure (recording, GDPR, third parties); ethical stance |
| **R-PRIVACY** | Who may read the raw layer, encryption/isolation posture, and what crosses the seam | Governs the most sensitive private data; hard to reverse once data flows |
| **R-RETENTION** | Retention/decay model and the raw-layer hard-retention bound | Privacy + irreversibility of deletion vs. keeping |
| **R-IDENTITY-OWNER** | Who owns the canonical identity register and its governance | Cross-constituent authority; identity errors are corrosive |
| **R-EXTERNAL** | Any capture of, or data flow to, external/third-party services or people | External-facing and often legally binding |
| **R-SPLIT** | Whether a split-trigger is accepted and the monorepo is split | Irreversible topology + ownership change |
| **R-PROMOTE** | Promoting any mechanism to the Layer-2 platform substrate | Redistributes ownership across constituents |
| **R-ENACT** | Enacting any `reshape` (naming, SoS model, glossary) into SoT | All reshapes are owner-gated via CES/ADR |

Fable's job on any of these is to **surface the decision with options and consequences**, not to pick.

---

## Part 2 — Captured decisions (owner session 2026-07-04)

Recorded as taken. These populate the FIXED section of `CAPABILITY_CHARTER.md` and ADR-0043. They are
**decided in principle**; enactment (glossary edits, contracts, runtime) is deferred and not performed
by this groundwork.

| ID | Decision | Owner choice (2026-07-04) | Enacts |
|---|---|---|---|
| **D-NAME-WHOLE** | Yggdrasil = whole vs. constituent | **Yggdrasil = the whole (world-tree / SoS).** Knowledge/memory constituent = **Munin**; agent-runtime = **Hugin** (`Mimer`→`Munin` concept rename) | ADR-0043 |
| **D-NAME-SENSOR** | Sensor name vs. `Heimdal`/observability collision | **Sensor keeps `Heimdal`;** observability alias reverts to boundary code `OEF` (one glossary edit, no shipped code) | ADR-0043 |
| **D-ADR41-TIMING** | Bundle Heimdal naming with ADR-0041 enactment? | **No — separate.** Heimdal naming is ADR-0043; ADR-0041/0042 enactment (#2855/#2856) stays independent | ADR-0043 |
| **D-CONSENT** | Consent / always-on posture | **Single-party consent; always-on capture OFF by default (opt-in per place/session); third parties marked/degraded** | Charter FIXED #4 |
| **D-PRIVACY** | Raw-layer privacy seam | **Raw layer encrypted at rest + isolated; access policy-gated (CrossScopeFlow-grant) for trusted downstream agents (not human-only); only minimized, attributed events cross the seam by default** | Charter FIXED #5 |
| **D-IDENTITY** | Entity/identity register topology | **Shared Layer-2 platform substrate** (no single constituent owns canonical identity) | SoS model §5; Charter FIXED #6 |
| **D-RETENTION** | Retention / decay model | **Event-triggered relevance decay (primary) + bounded hard retention on the raw layer** | Charter FIXED #7 |
| **D-BACKBONE** | Heimdal vs. KAP backbone | **Left OPEN for Fable.** Fixed guardrail: a shared provenance standard. Stream-vs-batch backbone is Fable's design | Charter OPEN #5 |

### Notes / reconciliations the enactment must carry

- **`Munin` reassignment** (`reshape`): `Munin`'s former glossary role ("raw-media / raw-memory
  module") is absorbed by Heimdal's raw observation layer; `Munin` now denotes the whole
  knowledge/memory constituent. Enactment updates `docs/GLOSSARY.md`.
- **Consent vs. raw access are deliberately different postures.** Capture is conservative
  (single-party, opt-in). *Once captured*, raw data is readable by trusted agents under policy
  (D-PRIVACY) — the owner chose retroactive re-analyzability over a human-only lock, with the seam
  held by encryption + CrossScopeFlow grants + receipts, not by denying agents.
- **No issues created.** This is docs-only groundwork; enactment work is filed later via the normal
  docs-to-issue path when the owner chooses to proceed.

## References

- `ECOSYSTEM_SOS_MODEL.md` (A1), `CAPABILITY_CHARTER.md` (A3), `FABLE_WINDOW.md` (A5).
- ADR-0043 — naming decisions.
- ADR-0041 / ADR-0042 — the unrelated in-flight decisions this is deliberately not bundled with.
