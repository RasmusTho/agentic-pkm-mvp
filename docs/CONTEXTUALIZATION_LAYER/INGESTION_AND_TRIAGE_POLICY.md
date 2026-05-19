State: Ingestion and triage policy for the Contextualization Layer (docs-only, target-state framing).
Doc role: Concept contract / policy
Authority: Defines the ingestion pipeline states, per-pipeline capture-to-promotion flows, and AI/governance boundaries for life-wide artifact ingestion and triage. Not a runtime implementation, not a migration plan, not a schema.

# Ingestion and Triage Policy

## 1. Purpose

This document defines the **ingestion and triage policy** for life-wide artifacts in the Yggdrasil / Agentic PKM.

It exists because without an explicit triage policy, agents and automated processes may incorrectly promote AI summaries, source notes, shopping lists, screenshots, receipts, and ephemeral captures into durable knowledge — or silently discard source-authoritative material.

This document is explicitly:

- **Not a runtime implementation.** No scripts, pipelines, or services are defined here.
- **Not a migration plan.** Existing vault content is not reclassified by this document.
- **Not a schema.** No database tables, no required frontmatter, no validators.
- A **policy layer** that describes what may happen at each state and what transitions require human or governed approval.

This document sits on top of `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md` and `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md`. It applies the artifact classes, lifecycle states, authority model, and AI-governance rules defined there to concrete capture-to-promotion flows.

## 2. Ingestion pipeline states

> **Disambiguation:** These are triage workflow stages, not values for the `lifecycle` metadata field. The `lifecycle` field values (`ephemeral`, `active`, `durable`, `archived`, `rebuildable`) are defined in `ARTIFACT_METADATA_CONTRACT.md` and `LIFE_WIDE_ARTIFACT_TAXONOMY.md`. The states below describe where an artifact sits in the ingestion process, not its long-term durability posture.

Every artifact that enters the system passes through one or more of the following states. States are not strictly sequential for all artifact classes, but the model below defines what is allowed at each state.

### `captured`

The artifact has been recorded in some form but has not been classified, reviewed, or placed.

- **Examples:** An inbox note, a voice-memo transcript, a photo just taken, an email thread that triggered a vault import, a YouTube URL saved for later.
- **Allowed AI actions:** Suggest classification, suggest artifact class, suggest routing to a pipeline.
- **Disallowed AI actions:** Promote into durable knowledge; silently mutate governance-bearing metadata; mark as reviewed.
- **Human action required before:** any transition that changes artifact class, lifecycle, or authority.

### `triaged`

The artifact has been classified into a concrete artifact class and assigned a lifecycle posture. The human or a governed process has reviewed the classification.

- **Examples:** A shopping list classified as `shopping_list / ephemeral`; a photo classified as `media_note / durable`; an email summary classified as `email_summary / active`.
- **Allowed AI actions:** Suggest links, suggest related artifacts, suggest companion note content.
- **Disallowed AI actions:** Promote into durable knowledge without review; silently move to `promoted` or `discarded`.
- **Human action required before:** promotion into durable HK, or discard of any source-authoritative material.

### `linked`

The artifact has been placed in its context: linked to a project, area, MOC, or related artifact. Linkage does not change the artifact's class or authority.

- **Examples:** A project evidence photo linked to a project note; an email summary linked to a decision record; a source note linked from a literature note.
- **Allowed AI actions:** Suggest additional links, suggest related artifacts.
- **Note:** Linkage is an ergonomic action, not a governance action. A linked artifact is not promoted by virtue of being linked.

### `promoted`

The artifact or information derived from it has been explicitly moved into a durable Human Knowledge Artifact (`evergreen_note`, `synthesis_note`, `decision_record`) through human or governed review.

- **What promotion is:** a human reads the source artifact, extracts a durable claim or decision, and creates or updates a durable HK artifact. The source artifact may be archived or retained as provenance.
- **What promotion is not:** silently copying AI summary content into an evergreen note; auto-classifying an email summary as a decision record; marking a shopping list as durable.
- **Required:** explicit human review or a governed promotion process. AI may draft the candidate; the human or governed process decides.
- **Disallowed AI actions:** silently promote any artifact into durable HK without review; mutate a promoted artifact's class or authority after promotion.

### `archived`

The artifact is retained for historical reference but is no longer in active use. It remains visible but does not drive active navigation or agent context.

- **Examples:** A completed project note, a closed email thread summary, an older receipt, a superseded decision record.
- **Allowed AI actions:** Include in retrieval results with staleness signal; suggest re-promotion if relevant.
- **Note:** Archiving is reversible. An archived artifact may be re-activated if circumstances change.

### `discarded`

The artifact is removed from the vault / system. This is irreversible for the original; companions and indexes may be rebuilt.

- **Who may discard:**
  - The human, explicitly.
  - A governed process with an explicit dry-run receipt and operator approval.
- **Disallowed:** Automated discard of source-authoritative material (original scan files, email threads, legal documents, photos) without explicit human or operator approval.
- **AI action:** `none` for originals. AI may suggest candidates for discard; the human decides.

### State summary table

| State | AI may | Human required for |
| --- | --- | --- |
| `captured` | Suggest class, suggest routing | Classification confirmation; promotion |
| `triaged` | Suggest links, suggest companions | Promotion into durable HK; discard of source-authoritative material |
| `linked` | Suggest additional links | Governance-bearing reclassification |
| `promoted` | Draft companion notes; suggest related | Promotion decision itself; post-promotion reclassification |
| `archived` | Retrieve with staleness signal | Re-activation; permanent deletion |
| `discarded` | — | Any discard of source-authoritative material |

## 3. Global governance rules

These rules apply across all pipelines and all artifact classes.

**AI-generated outputs are non-authoritative by default.**
AI may summarize, caption, OCR, classify, suggest links, and draft companion notes. These outputs are proposals, not knowledge, until a human or governed process reviews and promotes them.

**AI must not silently promote source material into durable knowledge.**
Promotion from `ai_suggestion`, `email_summary`, `youtube_source_note`, or any other non-HK class into `evergreen_note`, `synthesis_note`, or `decision_record` requires explicit human review. AI may queue a candidate; the human decides.

**AI must not silently mutate governance-bearing metadata.**
Fields that drive lifecycle, authority, or classification (`lifecycle`, `authority`, `artifact_class`, `review_state`) MUST NOT be changed by AI without human or governed-process review. AI may propose; the human or governed process commits.

**Deletion or discard of source evidence requires caution.**
Source-authoritative material (original scan files, email threads, legal documents, photos) MUST NOT be automatically discarded. AI may suggest candidates; the operator must approve with a dry-run receipt.

**Privacy-sensitive artifacts require explicit handling.**
Screenshots, personal photos, contact notes, financial records, and health records carry elevated privacy risk. They MUST NOT be silently added to shared retrieval surfaces or context bundles. Privacy-sensitive defaults: screenshots default to `privacy: review-required`; personal photos and contact notes default to `privacy: private`.

**AI-generated summaries require the `requires_review` flag.**
Any artifact with AI-generated content that has not been human-reviewed MUST carry `review_state: unreviewed` and `authority.requires_review: true`. This flag prevents the artifact from being treated as authoritative knowledge.

## 4. Per-pipeline flows

### 4.1 Shopping list

**Artifact class:** `shopping_list`
**Lifecycle:** `ephemeral` → cleared/archived after fulfillment

```
capture → active list → completed/cleared → optional pattern extraction
```

**Capture:** Human creates or dictates a list. AI may suggest recurring items, but the list is human-owned from the start.

**Active list:** `lifecycle: active`. Agent-editable fields: checking off items under explicit instruction. AI MUST NOT add items without explicit instruction.

**Completed/cleared:** When fulfilled, move to `lifecycle: archived` or discard. The list itself does not become knowledge.

**Pattern extraction (optional):** Over time, patterns extracted from many completed lists (e.g. regular grocery items) MAY be proposed as a durable preference or reference note. This requires:
1. A human reviews the proposed pattern.
2. The result is a new `evergreen_note` or similar durable artifact — not a mutation of the shopping list.

**AI boundary:** AI may suggest items, check items under instruction, and observe patterns. AI MUST NOT promote the list itself into durable knowledge.

### 4.2 Email thread / email summary

**Artifact class:** `email_summary`
**Lifecycle:** `active` while thread is in play → `archived` once closed

```
email thread (provider) → email_summary in vault → actions / evidence / source / archive
```

**Capture:** The email thread stays in the provider (Gmail, etc.). The vault receives an `email_summary` — a controlled representation, not the full thread.

**email_summary contents:** Subject/participants, key points, action items, decision markers, reference pointers. AI may draft; `review_state: unreviewed` until reviewed.

**Triage transitions:**
- Actions extracted → become `checklist` items, `decision_record` candidates, or project notes via explicit human review.
- Evidence → link to relevant project or legal artifact.
- Source reference → link from `source_note` or `literature_note`.
- Archive → `lifecycle: archived` when thread is closed.

**AI boundary:** AI may summarize threads, propose action extraction, and suggest links. AI MUST NOT:
- Treat the summary as the authoritative record (the provider thread governs).
- Silently promote an extracted "decision" into a `decision_record`.
- Discard the email thread from the provider.

### 4.3 YouTube source note

**Artifact class:** `youtube_source_note`
**Lifecycle:** `active` while consuming → `durable` as reference anchor → `archived` if abandoned

```
url → transcript / source note → AI summary → human takeaways → optional evergreen / synthesis
```

**Capture:** Human saves a YouTube URL. Vault receives a `youtube_source_note` with the URL and available metadata.

**Transcript (optional):** AI may extract or import a transcript. The transcript is non-authoritative until reviewed. `provenance.source_kind: youtube_url` plus `ai_extraction` for the transcript.

**AI summary:** AI may produce a summary. Non-authoritative; `review_state: unreviewed`.

**Human takeaways:** The human reads/watches and writes their own takeaways inline. These are the first human-authored content in this pipeline.

**Promotion path:**
- Human takeaways MAY be promoted into a `literature_note` or `evergreen_note` via explicit human review.
- AI MUST NOT promote a YouTube AI summary directly into an evergreen note.

**AI boundary:** AI may generate transcript, produce summary, suggest candidate takeaways. AI MUST NOT author the takeaways on behalf of the human or silently create an evergreen note from the summary.

### 4.4 Book / article source note

**Artifact class:** `source_note` → `literature_note` → `evergreen_note` / `synthesis_note`
**Lifecycle:** `active` while consuming → `durable` as reference anchor

```
source_note (the book/article as artifact)
    → literature_notes (what the author says, in the user's words)
    → human takeaways
    → evergreen_notes (what the user now claims or understands)
    → synthesis_notes (cross-source synthesis the user produces)
```

**These are four distinct artifact classes, not one.**

**Capture:** Human creates a `source_note` for the book or article. `lifecycle: active`.

**Literature notes:** As the human reads, they create `literature_note` artifacts — faithful restatements of what the source says, in the human's own words. These are input to evergreen notes, not knowledge themselves.

**Human takeaways / evergreen notes:** What the human now understands, claims, or stands behind. These are the human's own knowledge, not the source's.

**Synthesis notes:** When the human synthesizes across multiple sources or evergreens, they produce a `synthesis_note`.

**AI boundary:**
- AI may suggest passage extraction and paraphrase hints for literature notes.
- AI MUST NOT create evergreen or synthesis notes on behalf of the human.
- AI MUST NOT collapse source notes, literature notes, and evergreens into one artifact.

### 4.5 Photo / media note

**Artifact class:** `media_note`
**Lifecycle:** `durable` while media is relevant

```
media ingest → original stored → metadata extraction → media note → MOC / project linkage
```

**Capture / ingest:** The original file is captured and stored in the media store (outside the vault note flow). The vault receives nothing until a `media_note` is explicitly created.

**Original stored:** `media_original` in the dedicated media store. Stable, not renamed by automated processes.

**Metadata extraction:** AI may extract caption, objects, faces, OCR (for scans/screenshots), date/location from EXIF. All extractions are non-authoritative; marked as `ai_generated_fields`.

**Media note creation:** A `media_note` is created in the vault linking to the original. Human caption and context are added.

**MOC / project linkage:** The media note is linked to the relevant project, area, or MOC.

**AI boundary:** See `MEDIA_ARTIFACT_CONTRACT.md` Section 5 for full rules. Summary: AI may suggest captions and labels; AI MUST NOT make originals rebuildable or treat AI captions as authoritative.

### 4.6 Screenshot

**Artifact class:** `screenshot_note`
**Lifecycle:** `active` during incident/project → `durable` if anchors a decision → `archived`

```
screenshot → OCR → incident / project / debug note → optional archive
```

**Capture:** Screenshot taken. Stored in media store. `privacy: review-required` by default.

**OCR (optional):** AI may extract text. Non-authoritative; `ai_generated_fields: [ai_ocr_text]`.

**Note creation:** `screenshot_note` created with provenance pointer to original file. Human context added.

**Incident/project note linkage:** Link to the relevant project, incident, or debug investigation.

**Archive/discard:** When the incident/project is resolved, archive or discard. MUST NOT discard before the human has reviewed whether the screenshot anchors a decision or evidence record.

**AI boundary:** AI may OCR, identify app/window, flag likely-sensitive content for review. AI MUST NOT:
- Make screenshot content retrievable in shared surfaces before privacy review.
- Silently discard screenshots that may anchor evidence.

### 4.7 Receipt / scan / manual / contract

**Artifact class:** `scan_or_receipt_note`
**Lifecycle:** `durable` for legal/financial relevance → `archived` after

```
scan / original → extracted metadata → scan/receipt note → operations / project / evidence linkage
```

**Capture:** Physical document scanned, PDF received, or photo of receipt taken. Original file stored in media store.

**Metadata extraction:** AI may extract vendor, date, amount, serial numbers, key dates. All non-authoritative; `ai_generated_fields`.

**Note creation:** `scan_or_receipt_note` created with:
- Provenance pointer to original scan/file.
- Extracted fields marked as AI-generated.
- Human-verified fields if the human has reviewed them.

**Linkage:** Link to operations area, project, or evidence record as appropriate.

**Archive:** When the relevant period ends (warranty expired, property sold, contract terminated), archive or discard per retention policy. Legal documents: retain for the applicable legal retention period.

**AI boundary:** AI may extract fields and propose links. AI MUST NOT:
- Treat extracted fields as authoritative for legal/financial purposes.
- Automatically discard original scan files.
- Promote a receipt note into a financial decision record without human review.

### 4.8 Project note

**Artifact class:** `project_note`
**Lifecycle:** `active` during project → `archived` on completion

```
project created → scope/status note → decisions / evidence linked → completion → archive
```

**Capture:** Human creates a `project_note` to anchor a project.

**Active life:** Human maintains scope, status, and links. AI may suggest linkage updates and freshness flags. AI MUST NOT autonomously change project scope or status.

**Decision extraction:** Decisions made during the project MAY be promoted into `decision_record` artifacts via explicit human review.

**Completion / archive:** On completion, the project note is archived. Decisions, learnings, and reflections extracted during the project retain their own lifecycle.

**AI boundary:** AI may suggest links and status candidates. AI MUST NOT auto-close projects or auto-archive project notes.

### 4.9 Evergreen note

**Artifact class:** `evergreen_note`
**Lifecycle:** `durable`

```
human claim / insight → evergreen note (durable from creation)
```

Evergreen notes are created by humans as direct knowledge output. They may be initiated by AI suggestion, but the human writes the final content.

**Promotion into evergreen:**
- From literature notes, source notes, or YouTube takeaways: explicit human review produces a new `evergreen_note`. The source artifact is not mutated.
- From AI suggestion: the AI creates an `ai_suggestion` artifact; the human reviews, edits, and promotes it into an `evergreen_note`. The `ai_suggestion` is not silently converted.

**AI boundary:** AI may suggest linking, contradiction flags, and candidate phrasing. AI MUST NOT rewrite the human's evergreen note or silently create one on their behalf.

### 4.10 Synthesis note

**Artifact class:** `synthesis_note`
**Lifecycle:** `durable`

```
multiple evergreens / literature notes / sources → synthesis_note (human-authored)
```

Synthesis notes are cross-source or cross-evergreen integrations the human produces. They cannot be AI-authored on the human's behalf.

**AI boundary:** AI may suggest candidate connections and surface related artifacts. AI MUST NOT author the synthesis.

### 4.11 Archive / discard

Applies to any artifact whose active lifecycle has ended.

**Archive:** Move to `lifecycle: archived`. Retain for historical reference. Reversible.

**Discard / delete:**
- For human-owned, non-source-authoritative artifacts: human may discard.
- For source-authoritative originals (photos, scans, email threads, legal docs): requires explicit human action. AI may propose discard candidates but MUST NOT auto-discard.
- For machine mirrors / indexes: safe to discard and rebuild.
- For automated bulk discard: requires dry-run receipt + operator approval. AI MUST NOT execute bulk discard without these.

## 5. AI action summary by pipeline

| Pipeline | AI may | AI must not |
| --- | --- | --- |
| Shopping list | Suggest items, check off under instruction, observe patterns | Promote list into knowledge; add items without instruction |
| Email summary | Summarize thread, propose action extraction, suggest links | Treat summary as authoritative; promote extracted "decision" silently |
| YouTube source | Extract transcript, produce summary, suggest takeaways | Author human takeaways; create evergreen from summary |
| Book/article | Suggest literature note passages, propose paraphrases | Create evergreen or synthesis on behalf of human; collapse layers |
| Photo/media | Caption, label objects, extract EXIF | Override original authority; treat captions as authoritative |
| Screenshot | OCR, identify window/app, flag sensitive content | Make content retrievable before privacy review; auto-discard |
| Receipt/scan | Extract fields, suggest links | Treat extracted fields as authoritative for legal use; auto-discard originals |
| Project note | Suggest links, flag freshness | Autonomously change scope/status; auto-close/archive |
| Evergreen note | Suggest links, flag contradictions, draft candidates | Rewrite human's note; silently create evergreen from AI output |
| Synthesis note | Surface related artifacts, suggest connections | Author the synthesis |
| Archive/discard | Propose candidates | Auto-discard source-authoritative material; execute bulk discard without receipt |

## 6. Promotion path summary

Promotion from ephemeral or active state into durable Human Knowledge Artifact follows this path:

```
source artifact (any class)
    → AI drafts candidate (optional; marks review_state: queued)
    → human reviews
    → human creates or promotes to durable HK artifact (evergreen_note, synthesis_note, decision_record)
    → source artifact archived or retained as provenance
```

Key invariants:
- The durable HK artifact is a distinct, new artifact — not a mutation of the source.
- The source artifact retains its own class and authority.
- AI drafts are clearly marked as non-authoritative until human review.
- Promotion is always explicit; no pipeline auto-promotes on behalf of the human.

## 7. Non-goals

This document does **not**:

- implement ingestion pipelines or import scripts,
- implement OCR, transcript, or AI-extraction services,
- define a database schema or runtime validation plan,
- migrate existing vault content,
- require specific tool or service choices for ingestion,
- claim that these policies are enforced at runtime today (they are a target-state framing).

## 8. Open questions

- **Which pipelines should be triggered automatically vs. explicitly?** Auto-captioning on photo ingest and auto-summary on email import have different risk profiles. The trigger model is a downstream operator decision.
- **How should the inbox / capture area be structured?** A dedicated `00_Inbox/` folder, a single capture note, or an agent-managed triage queue? The physical structure is not defined here.
- **How should privacy review for screenshots be surfaced?** A review queue in the vault, a companion note flag, or an active UI prompt? The review UX is not defined here.
- **How should bulk-import receipts be generated?** For photo library imports or mass email imports, a dry-run receipt schema is needed. Not defined here.
- **How should conflicting AI classification and human classification be resolved?** The resolution workflow is a downstream governance decision.
