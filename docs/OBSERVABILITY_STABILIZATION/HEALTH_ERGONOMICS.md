---
name: Operator Health — Ergonomics & Information Architecture
description: The design contract for how runtime health is surfaced to the human in the Companion UI — glanceable hierarchy, plain-language states, grouped by the operator's questions. Binding on OBSSTAB-08/-09/-10.
parent_capability: Observability Stabilization
state: Design contract (referenced by the operator-UI slices).
---

# Operator Health — Ergonomics & Information Architecture

This is the **design source of truth** for how health is shown to the human. The operator diagnoses through the Companion UI as a *user*, not via the CLI, and has dyslexia — so health must be **glanceable, plain-language, and grouped by the human's questions**, not a projection of system field names. OBSSTAB-08/-09/-10 implement this contract; OBSSTAB-11 keeps `/healthz` honest underneath it.

## Principle: a glanceable hierarchy, not a dashboard

Three levels, each independently legible. Detail lives one level down — never front-loaded.

| Level | Surface | What it shows | Interaction |
|---|---|---|---|
| **0 — Toppnivå** | Ambient glyph, present in *every* entry/working state | ONE calm state (worst of the four), as **colour + glyph + word** | none — readable in < 1 s |
| **1 — Hälsokort** | Small card | The four groups, each one plain-language line with a status dot | one click / hover |
| **2 — Operatörsvy** | The operator drawer | The same four groups expanded + a plain-language **next step** | drill-in |

Anti-dashboard (per `docs/COMPANION_UI_COGNITIVE_LOAD_OPERATING_MODEL.md` and the entry-surface posture): **one calm indicator, never a grid of metric tiles.**

## The four states (Level 0 vocabulary)

Worst state wins (precedence top to bottom). Always shown as colour **and** glyph **and** word — never colour alone.

| State | Colour | Driven by | Plain meaning |
|---|---|---|---|
| **Frisk** | green | `required_ok` true · `write_guard` active · worker/watcher fresh · not degraded | allt flödar |
| **Uppmärksamhet** | amber | worker/watcher stale · backlog growing · optional dep missing · `catch_up` (core still serves) | se över |
| **Pausad** | coral | `authority_spine.write_guard` == blocked (degraded / safe_mode) — writes paused, reads still work | skrivningar pausade |
| **Nere** | red | `required_ok` false · core dependency (DB / runtime) unreachable · health endpoint unreachable | kärnberoende nere |

## The four groups (Level 1 — grouped by the human's question)

Never label a row with a raw field name. Each row = the human's question → plain status + dot.

| Group | The human's question | Bound to (runtime signal) |
|---|---|---|
| **Inflöde** | "tar den emot mina anteckningar?" | `health.runtime.worker` liveness + `status.worker_queue.pending_estimate` + `ingestion.last_ingest` |
| **Skrivningar** | "kan jag och agenterna skriva?" | `health.authority_spine.write_guard` |
| **Minne** | "hittar den rätt när jag frågar?" | ASK latency/error (`status.ask`) + recall / embedding freshness |
| **Version** | "vad kör som?" | `/version` git SHA + build age |

## Ergonomics rules (binding acceptance constraints)

- **Plain Swedish, sentence case, no jargon.** No raw field names, JSON, status codes, or tracebacks reach the human (the existing `_sanitize_health_value` gate still applies).
- **Colour + glyph + word together**, always — colour is never the only carrier (dyslexia / colour-blindness).
- **Level 0 is present in every entry state** (cold_start, no-vault, orienting) and needs no note open and no interaction.
- **Level 1 has exactly the four groups**, each a single line; no group expands beyond one line at this level.
- **Level 2 ends in a next step**, not a diagnosis dump: `health.suggested_actions` are rephrased as a plain action ("Starta om workern"), never shown as a raw action string or stack trace.
- **Numbers rounded; times relative** ("3 min sedan", "120 ms", "42 väntar").

## Acceptance criteria this contract adds to the slices

- [ ] The Level-0 glyph conveys state via colour **and** glyph **and** word, and renders in cold_start / no-vault / orienting. Verify: `tests/companion_ui/test_operator_health_glyph.py::test_glyph_uses_colour_glyph_and_word`
- [ ] Worst-of-four precedence holds (a blocked write-guard with a healthy worker still reads "Pausad", not "Frisk"). Verify: `tests/companion_ui/test_operator_health_glyph.py::test_worst_state_precedence`
- [ ] The Level-1 card groups into exactly Inflöde / Skrivningar / Minne / Version, each one plain-language line. Verify: `tests/companion_ui/test_operator_drawer_render.py::test_health_card_four_groups_plain_language`
- [ ] No raw field name, JSON, or traceback is rendered to the human on any level. Verify: `tests/companion_ui/test_operator_drawer_render.py::test_no_raw_fields_leak_to_ui`
- [ ] `suggested_actions` render as a plain next-step action, not a raw string. Verify: `tests/companion_ui/test_operator_drawer_render.py::test_suggested_action_is_plain_language`

## Related Docs

- `OPERATOR_HEALTH_GLYPH_AMBIENT.md` (OBSSTAB-08) · `OPERATOR_DRAWER_RENDERS_LOADBEARING_HEALTH.md` (OBSSTAB-09) · `OPERATOR_DRAWER_SHOWS_BACKLOG.md` (OBSSTAB-10)
- `docs/COMPANION_UI_COGNITIVE_LOAD_OPERATING_MODEL.md` · `docs/HEALTH.md` (false-green register, OBSSTAB-06)
