# Architecture Snapshot (v4.5 – runtime & stores)

## Runtime lifecycle
- FastAPI använder nu **lifespan** (ingen `@on_event`), vilket ger deterministisk start/stop.
- Shimen i `app/main.py` exponerar `/agent/health`, `/interesting`, `/dashboard` och är säker att monkeypatcha i tester.

## Store backend selection
- `app/stores/provider.py` väljer backend så här:
  1) `STORE_BACKEND` kan tvinga `"pg"` eller `"memory"`.
  2) I övrigt: om `DATABASE_URL` finns och är rimlig → `"pg"`, annars `"memory"`.
- In-memory-läget är **process-persist** via en cachead fabrik (`_memory_stores()`).

## In-memory semantics
- Samma `MemoryObjects`/`MemoryDecisions` delas i processen. `reset_memory_stores()` finns för test-isolering.

## Guards
- **No direct DB imports**: allt som muterar/läser data ska gå via Stores.
- **Classifier v2 guard**: `SKIP_CLASSIFIER_TESTS=1` tills omskrivningen landar.

## Near-term refactor plan
- Flytta endpoints till riktiga routers (behåll shimen tills routrar är på plats).
- Fasa ut `_legacy` när ersättande wiring är klar.
