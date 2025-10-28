# Roadmap — SoT v4.3.1 → v4.4 → v5.0

## v4.3.1 — Obsidian-first (Active)
Status: Open

**Mål:** Flytta system-settings till kanonisk YAML-fil och etablera dual-layer-design.

- Källsanning: `vault/_system/settings/system-settings.yaml`
- Läsbar yta: `vault/settings/Overview.md`
- Testdriven validering: `tests/system/test_settings_schema.py` via `make smoke`
- Vault-struktur uppdaterad med `@Desk` och `@Inbox`
- Endast `_system/**` hård-ignoreras
- Indexerings-regler (`index.rules[]`) styr mjuk exkludering:
  - `review_state: inbox` → soft_exclude weight 0.05
  - `review_state: archived` → include weight 0.25
  - `review_state: promoted` → include weight 1.0
  - `review_state: evergreen` → include weight 1.2

**Definition of Done**
- `make smoke` passerar lokalt + i CI.
- YAML-filen valideras mot schema.
- Overview.md refererar rätt kanonisk väg.
- Docs uppdaterade: ROADMAP, STATUS, architecture/next-steps.

---

## v4.4 — Observability & Conflict Resolution
Status: Planned

- OTel-spårning av LLM-spans till Jaeger.
- Deterministisk merge-policy för frontmatter/body.
- Broker-backad outbox (Debezium/Kafka) ≤ 2 s SLA.
- E2E-trace verifieras via `make smoke`.

---

## v5.0 — Reasoning Alpha (förhandsplan)
Status: Future

- Symboliskt lager (triples/claims/rules/provenance).
- Reasoner/Guard-stubs + SHACL-batchvalidering.
- Första neurosymboliska loop mellan AMG och reasoning-lager.
