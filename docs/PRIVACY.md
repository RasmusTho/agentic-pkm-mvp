# Privacy & PII

The pipeline processes personal material (notes, audio), so logs and storage must remain conservative.

<!-- SECTION:PRIVACY:BEGIN -->
## Local execution
- Ingestion, transcription, and QA run entirely locally by default (`LLM_PROVIDER=mock` or Ollama on the same machine).
- The only outbound calls are to Ollama/OpenAI/DeepSeek when explicitly enabled. No implicit cloud storage.

## Logging policy
- `json_log` records metadata only (trace_id, node, latency, status). Never place raw text/audio inside `extra`.
- Health CLI logs status + concise failure reasons (e.g., `yt-dlp import failed`), never secrets.
- For deeper debugging, keep files local and delete them once inspected.

## PII redaction
- Before sharing logs: run `jq 'del(.extra)'` or anonymize `trace_id`.
- Agent answers should keep `sources` limited to references (`doc_id`, `source_ref`), not verbatim text.
- Transcribe output (`payload.segments`) resides in `INDEX_OUTBOX_PATH`. Move the file to encrypted storage if it contains sensitive material.

## Retention
- `tmp/index-outbox.jsonl` is a working file. Rotate per `docs/OPERATIONS.md` and delete copies older than 30 days unless policy states otherwise.
- `tmp/audio/*.wav` is removed automatically when the file sits inside the OS temp dir (see `_is_temporary` in `app/media/transcribe.py:113-135`).

## GDPR / compliance note
- Everything runs locally, so no cloud record exists. If a cloud deployment is ever introduced, execute a data processing agreement and scrub logs of PII before upload.
<!-- SECTION:PRIVACY:END -->
