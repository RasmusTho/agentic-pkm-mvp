# SoT 4.3.1–5 Bridge — Next Steps

Focus: Kvalitet, observability och robusthet före expansion.

1. Etablera källsanning för settings i `vault/_system/settings/system-settings.yaml` och validera i CI.
2. Lägg till OTel-spårning på agent-PER-nivå och visa trace i Jaeger.
3. Definiera deterministisk merge/konfliktpolicy för frontmatter/body.
4. Spika broker-backad outbox och besluta via ADR.

Definition of Done (4.3.1):
- settings.md finns och valideras automatiskt mot schema i CI.
- make smoke kör testet lokalt och i CI.
- yaml_roundtrip write_on_diff finns för säkra skrivningar.

## Next Step: Integrate Promotion Agent
- Implement the full chain: promotion intent → event → frontmatter → index.
- Verify UX (checkbox disappears, no extra menus).
- Extend smoke/E2E tests with scenario intent → promoted → index visible.
- Prepare batch move job (nightly cron via promotion worker).
