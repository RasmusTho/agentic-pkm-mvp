---
uuid: "77232B90CAE14637A4E90A18DAF71DE4"
title: "System Settings — Overview"
origin: "local"
review_state: "processed"
trust: "own"
source_ref: "vault://settings/settings.md"
version: "0.3.0"
canonical: "vault/_system/settings/system-settings.yaml"
---

# System Settings

Kanoniska konfigurationen lever i [[../_system/settings/system-settings.yaml]] och valideras mot `schemas/system-settings.schema.json`.

## Snabbkommandon

- `python -m app.cli.settings --policy` visar gällande synkpolicy.
- `python -m app.cli.settings --section index.rules` listar indexeringsregler.
- `make smoke` kör schema-, regel- och E2E-tester för inställningarna.
