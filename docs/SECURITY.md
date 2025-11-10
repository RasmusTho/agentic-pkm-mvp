# Security

Lättviktspolicy för lokala/CI-körningar.

<!-- SECTION:SECURITY:BEGIN -->
## API-nycklar & endpoints
- Lagra nycklar (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`) endast i lokala `.env`-filer eller secrets store. Lägg aldrig in dem i Git, CI loggar eller docs.
- `LLM_PROVIDER=mock` är default i CI, så inga externa nycklar behövs för tester.
- När `OLLAMA_URL` exponeras över nätverk, skydda porten med ssh-tunnel/VPN. Standardantagande är lokalt interface.

## Minsta behörighet
- Postgres-kontot (`DATABASE_URL`) använder `app:app` med begränsade rättigheter. För produktion: skapa dedikerad roll med endast `INSERT/SELECT` för nödvändiga tabeller.
- CLI-kommandon skriver bara till `INDEX_OUTBOX_PATH`; kör dem under användare med begränsad access för att minska påverkan vid RCE.

## Secrets i CI
- GitHub Actions workflow använder inga hemligheter. Om framtida jobb kräver dem, lägg in via `secrets.*` och källkoda aldrig fallback-värden.
- `requirements.txt` innehåller endast publika paket; inga privata index används.

## Loggar och PII
- Se `docs/PRIVACY.md` för maskningspolicy. Grundregel: inga råa kund-/note-texter i `extra`.
- Vid fel i health/agent loggas endast stack/exception-namn; undvik att lägga in hela HTTP-svar.

## Nästa steg
1. Lägga på TLS/Basic Auth runt framtida FastAPI endpoints.
2. Hooka `CircuitBreaker` + `timeout_wrapper` runt externa anrop för att undvika DoS via hängande requests.
3. Lägg in `pre-commit` kontroll som söker efter `OLLAMA_URL`-URL:er som pekar utanför `localhost`.
<!-- SECTION:SECURITY:END -->
