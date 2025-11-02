# Roadmap (next 1–2 sprints)

1) Extract real routers
   - `app/api/agent.py`, `app/api/interesting.py`, `app/api/dashboard.py`
   - `app/main.py` inkluderar routers; shimen kvar som fallback under en sprint.

2) Provider hardening
   - PG-probe i provider (snabb test-connection) → automatisk fallback till memory.
   - Miljöflagga `STORE_BACKEND` dokumenterad + kontraktstest.

3) Observability
   - Grundläggande event-logg kring Stores (outbox) med `trace_id`.

4) Cleanup `_legacy`
   - Mappa om importvägar, ta bort shims när routrar och stores är primära.

5) Classifier v2
   - Ta bort `SKIP_CLASSIFIER_TESTS`, kör ny API/graph-design och kontraktstester.

Note to future self: När vi startar Classifier-arbetet, sätt `SKIP_CLASSIFIER_TESTS=0` och kör hela sviten.
