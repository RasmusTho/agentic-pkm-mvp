# Privacy & PII

Pipeline hanterar personligt material (anteckningar, ljud) och måste därför vara återhållsam med loggar och lagring.

<!-- SECTION:PRIVACY:BEGIN -->
## Vad körs lokalt
- Ingestion, transcribe och QA körs helt lokalt i default-läge (`LLM_PROVIDER=mock` eller Ollama på samma maskin).
- Enda nätanropen går till Ollama/OpenAI/DeepSeek om du själv väljer det. Ingen molnlagring sker implicit.

## Loggpolicy
- `json_log` skriver endast metadata (trace_id, node, latency, status). Lägg aldrig full text eller ljudtranskript i `extra`.
- Health CLI loggar endast status + eventuella felmeddelanden (t.ex. `yt-dlp import misslyckades`), aldrig hemliga strängar.
- Om du behöver felsöka innehållet, håll filerna lokalt och radera dem efteråt.

## PII-redaktion
- Före delning av loggar: kör `jq 'del(.extra)'` eller anonymisera `trace_id`.
- När agenten producerar svar, se till att `sources` bara innehåller referenser (`doc_id`, `source_ref`), inte hela texten.
- Transcribe-resultat (`payload.segments`) ligger i `INDEX_OUTBOX_PATH`. Flytta filen till krypterad disk om innehållet är känsligt.

## Retention
- `tmp/index-outbox.jsonl` betraktas som temporär arbetsfil. Rotera enligt `docs/OPERATIONS.md` och radera äldre kopior >30 dagar om inte annat avtalats.
- `tmp/audio/*.wav` tas bort automatiskt efter transcribe så länge filerna ligger i systemets temp-katalog (se `_is_temporary` i `app/media/transcribe.py:113-135`).

## GDPR/Compliance anteckning
- Eftersom allt kör lokalt finns ingen registerföring i moln. Vid eventuell molndrift måste ett personuppgiftsbiträdesavtal upprättas och loggar rensas på PII innan uppladdning.
<!-- SECTION:PRIVACY:END -->
