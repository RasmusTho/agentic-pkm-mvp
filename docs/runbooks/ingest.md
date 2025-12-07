State: SoT v4.10 Reality-MVP (current, with known debt).
# Runbook – Ingest incidenter
- Symptom: dubbletter / saknade poster i `index-outbox.jsonl`
- Checklista:
  1) Verifiera fingerprint/hashing
  2) Kolla PII-redaktion inte nollar content
  3) Läs senaste rader i outbox, validera JSON
- Åtgärd: kör om `normalize/pipe` med `--trace-id`
