# Vault Templates — Life-Wide Artifact Examples

These are example Markdown templates for common life-wide artifact classes in the Yggdrasil / Agentic PKM.

**These are examples, not requirements.** Every note does not need frontmatter, and templates are not mandatory. Use them as a starting point when you want to apply the life-wide artifact taxonomy consistently.

**On AI-generated fields:** Fields marked `# [AI-suggested, non-authoritative]` in the templates indicate content that an AI assistant might fill in. These fields are proposals until a human reviews and confirms them. Do not treat AI-generated fields as authoritative knowledge.

## Templates

| Template | Artifact class | Lifecycle |
| --- | --- | --- |
| [project-moc.md](project-moc.md) | `project_note` | `active` → `archived` |
| [area-dashboard.md](area-dashboard.md) | `area_dashboard` | `durable` |
| [media-note.md](media-note.md) | `media_note` | `durable` |
| [email-summary.md](email-summary.md) | `email_summary` | `active` → `archived` |
| [youtube-source-note.md](youtube-source-note.md) | `youtube_source_note` | `active` → `durable` |
| [book-source-note.md](book-source-note.md) | `source_note` | `active` → `durable` |
| [literature-note.md](literature-note.md) | `literature_note` | `active` → `durable` |
| [decision-record.md](decision-record.md) | `decision_record` | `durable` |
| [shopping-list.md](shopping-list.md) | `shopping_list` | `ephemeral` |
| [receipt-scan-note.md](receipt-scan-note.md) | `scan_or_receipt_note` | `durable` → `archived` |
| [weekly-review.md](weekly-review.md) | `reflection_note` | `durable` |

## Key rules (brief)

- **Folder paths are not semantics.** A note in `03_Knowledge/Evergreen/` is not automatically durable; the `artifact_class` and `lifecycle` fields decide.
- **AI fields are non-authoritative by default.** Mark them explicitly.
- **Source authority stays with the original.** For media, scans, emails, and YouTube: the external file or thread is authoritative; the vault note is a companion.
- **Promotion into durable knowledge is explicit.** AI summaries, source notes, and literature notes do not become evergreen knowledge by themselves.

## Related contracts

- `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md` — artifact classes and axes
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` — field semantics
- `docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md` — media-specific rules
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md` — capture-to-promotion flows
