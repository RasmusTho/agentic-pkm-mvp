State: Life-wide artifact taxonomy for the Contextualization Layer (docs-only, target-state framing).
Doc role: Concept vocabulary / taxonomy
Authority: Names the artifact classes, lifecycle/authority/provenance/work-relation axes, and AI/governance rules that a life-wide PKM is expected to honor. Not an ontology, not a governance enforcement contract, not a runtime implementation plan, not a vault migration.

# Life-Wide Artifact Taxonomy

## 1. Purpose and scope

This document defines a **life-wide artifact taxonomy** for the Yggdrasil / Agentic PKM. It exists because a human-first, AI-assisted PKM must cover far more than evergreen knowledge notes. It must accommodate:

- short-lived lists (shopping, packing, errands)
- workspaces and projects (renovation, research, code, roleplaying)
- life areas (home, finance, health, relations, outdoor life)
- consumption flows (books, YouTube, podcasts, articles, email)
- creation flows (drafts, syntheses, idea development, decisions)
- operations (checklists, maintenance, warranties, receipts)
- memory (what was thought, did, decided, learned)
- media (photos, scans, screenshots, reference images)
- AI-assistance artifacts (suggestions, captions, summaries, candidates)
- machine artifacts (embeddings, indexes, mirrors)

This document is **docs-only**. It is a specification layer that names artifact classes and the governing dimensions around them. It does **not** describe runtime enforcement that exists today, does **not** migrate the current vault, and does **not** introduce validation logic.

It sits alongside the other Contextualization Layer documents and remains downstream of the cross-cutting concept contracts under `docs/CONCEPTS/`:

- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`
- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`

The three initial artifact classes from `HUMAN_AND_AGENTIC_ARTIFACTS.md` — Human Knowledge Artifacts, Agentic Memory Artifacts, and Machine Mirror Artifacts — remain the load-bearing classification. The taxonomy below refines those classes by naming the concrete sub-shapes a life-wide PKM encounters; it MUST NOT collapse them.

## 2. Conceptual separation

A life-wide PKM MUST keep these axes separate. None of them is a substitute for the others.

| Axis | What it answers | Examples |
| --- | --- | --- |
| Physical storage | Where the bytes live. | Obsidian vault, external media store, Gmail, Drive, generated index DB, cloud bucket. |
| Human navigation | How a human orients. | Folders, MOCs, dashboards, project notes, area notes, media indexes. |
| Semantic artifact class | What kind of thing this is. | `shopping_list`, `email_summary`, `evergreen_note`, `machine_mirror`. |
| Lifecycle | How stable / retained. | `ephemeral`, `active`, `durable`, `archived`, `rebuildable`. |
| Provenance | Where it came from. | user-authored, own photo, Gmail thread, YouTube URL, scanned PDF, AI summary, machine extraction. |
| Authority | Whether it may be trusted as source of truth or actioned. | human-authored, AI-generated, source-authoritative, system-authoritative, agent-editable, requires-review, governance-bearing. |
| Work relation | Why the artifact exists in the workflow. | capture, orient, decide, execute, learn, create, remember, resurface, communicate. |

Two consequences follow:

- Markdown is a shared substrate, not shared semantics. A shopping list, a book note, a project log, an evergreen concept, an Agentic Memory candidate, a machine mirror, and an email summary may all be Markdown. They MUST NOT be treated as the same kind of knowledge.
- Folder paths are ergonomic, not authoritative. `03_Knowledge/Evergreen/foo.md` is not automatically durable human knowledge; the artifact's class, lifecycle, and authority metadata decide.

## 3. Artifact class taxonomy

The taxonomy below names the concrete artifact classes a life-wide PKM is expected to support. Each class refines one of the three load-bearing classes from `HUMAN_AND_AGENTIC_ARTIFACTS.md`:

- **HK** — Human Knowledge Artifact
- **AM** — Agentic Memory Artifact
- **MM** — Machine Mirror Artifact
- **BA** — Bridge / Assembly Artifact (e.g. context bundles)
- **CN** — Companion Metadata Note

The column "AI action" uses these values:

- `none` — AI MUST NOT create, suggest, or edit this artifact.
- `queue-only` — AI MAY produce candidates but MUST queue them for human or governed promotion.
- `suggest` — AI MAY propose changes inline as suggestions; promotion still requires review.
- `edit` — AI MAY directly edit fields that are explicitly scoped as agent-editable.
- `create` — AI MAY create this artifact class outright (typically Agentic Memory or Machine Mirror).

Definitions:

### `fleeting_capture` (HK)

- **Definition:** Inbox-grade scratch capture: an unstructured fragment that has not yet been classified.
- **Lifecycle:** `ephemeral` → triaged into another class or discarded.
- **Authority:** Human-authored. Not authoritative for anything beyond raw memory of the user's own thought.
- **AI action:** `suggest` (classification, splitting, linking). MUST NOT silently promote.
- **Indexable:** Yes, but with short retention; rebuildable from triage history.
- **Promotable to durable knowledge:** Only via explicit triage that produces a different artifact class.
- **Human-readable/editable:** Yes.
- **Examples:** Inbox notes, voice-memo transcripts pre-triage, quick text dumps.

### `daily_log` (HK)

- **Definition:** Per-day journal / activity log of human-authored entries.
- **Lifecycle:** `active` during the day, `durable` once closed for the day, `archived` over time.
- **Authority:** Human-authored.
- **AI action:** `suggest` (linking, summarizing). `queue-only` for derived structured claims.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** No, only its referenced content (decisions, reflections, evergreens) is promotable.
- **Human-readable/editable:** Yes.
- **Examples:** Daily note in Obsidian, journaling entries, day logs.

### `shopping_list` (HK)

- **Definition:** Short-lived operational list of items to acquire.
- **Lifecycle:** `ephemeral` → cleared / archived after fulfillment.
- **Authority:** Human-authored, operationally authoritative for "what to buy now".
- **AI action:** `suggest` (recurring items, pattern proposals). MUST NOT silently promote the list itself into durable knowledge.
- **Indexable:** Optional and rebuildable; not retained as knowledge.
- **Promotable to durable knowledge:** No. Patterns extracted from many lists MAY be promoted via explicit review, but the list itself is operational.
- **Human-readable/editable:** Yes.
- **Examples:** Groceries, packing list, hardware-store list.

### `checklist` (HK)

- **Definition:** Repeatable or one-off operational checklist for executing a task.
- **Lifecycle:** `active` during use; reusable templates may be `durable`.
- **Authority:** Human-authored; operationally authoritative for the procedure described.
- **AI action:** `suggest` (template improvements, step additions). MUST NOT silently mutate checklists used as governance.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** Templates and learned-from-execution improvements MAY be promoted via review.
- **Human-readable/editable:** Yes.
- **Examples:** Release checklist, travel checklist, maintenance checklist.

### `project_note` (HK)

- **Definition:** Workspace note for an active project: scope, status, links, evidence.
- **Lifecycle:** `active` during the project, `archived` on completion.
- **Authority:** Human-authored.
- **AI action:** `suggest` linkage and status candidates; `queue-only` for structured project metadata changes.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** Decisions, learnings, and reflections extracted from a project MAY be promoted as separate artifacts.
- **Human-readable/editable:** Yes.
- **Examples:** Project log, scope doc, status note.

### `area_dashboard` (HK)

- **Definition:** Standing surface for a life area or domain: home, finance, health, relations, outdoor life.
- **Lifecycle:** `durable` while the area exists.
- **Authority:** Human-authored as a navigation surface.
- **AI action:** `suggest` (links, freshness flags). MUST NOT mutate the dashboard's governance role.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** Not itself; it is already durable as a navigation surface.
- **Human-readable/editable:** Yes.
- **Examples:** Home area dashboard, finance MOC-style dashboard.

### `source_note` (HK)

- **Definition:** The vault's representation of an external source: a book, article, podcast, video, page, etc. The source itself is the authority.
- **Lifecycle:** `active` while being consumed, `durable` as a reference anchor.
- **Authority:** Source-authoritative; the note is a controlled representation, not the source of truth.
- **AI action:** `suggest` metadata, transcripts, links. `queue-only` for classification changes.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** No; promotion happens via `literature_note`, `evergreen_note`, or `synthesis_note` derived from it.
- **Human-readable/editable:** Yes.
- **Examples:** Book record, article record, podcast record, paper record.

### `literature_note` (HK)

- **Definition:** What the source says, captured in the user's words. A faithful restatement, not the user's own conclusions.
- **Lifecycle:** `active` while reading, `durable` once stable.
- **Authority:** Human-authored interpretation of a source. Distinct from the source itself.
- **AI action:** `suggest` (passage extraction, paraphrases). MUST NOT promote to evergreen.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** Yes, but only as input to evergreen or synthesis notes.
- **Human-readable/editable:** Yes.
- **Examples:** Chapter notes, quote interpretations, paraphrases.

### `media_note` (HK / CN)

- **Definition:** Companion note for a media file (photo, video, audio). Lives in the vault; the original media file is the source authority.
- **Lifecycle:** `durable` while the media is relevant.
- **Authority:** Source-authoritative is the media file; the note holds human-authored context.
- **AI action:** `suggest` captions, objects, OCR, faces, links — all non-authoritative. `queue-only` for changes to classification/authority.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** Captions and observations MAY be promoted into evergreen artifacts via review.
- **Human-readable/editable:** Yes.
- **Examples:** Companion note for a kitchen-paneling photo, family photo context note.

### `screenshot_note` (HK / CN)

- **Definition:** Companion note for a screenshot, often capturing UI state, errors, financial state, terminal output, conversation excerpts.
- **Lifecycle:** `active` during the incident or project, `durable` if it anchors a decision or record, often `archived`.
- **Authority:** Source-authoritative is the screenshot file; the note holds human context.
- **AI action:** `suggest` OCR text, app/window identification, redaction candidates. MUST treat screenshots as privacy-sensitive by default.
- **Indexable:** Yes, with privacy filtering.
- **Promotable to durable knowledge:** Only if explicitly reviewed; screenshots often carry sensitive data.
- **Human-readable/editable:** Yes.
- **Examples:** Error screenshot, bank screenshot, debug screenshot, chat screenshot.

### `scan_or_receipt_note` (HK / CN)

- **Definition:** Companion note for a scanned document: receipt, warranty, manual, contract, certificate.
- **Lifecycle:** `durable` for legal/financial relevance; `archived` after expiry.
- **Authority:** Source-authoritative is the scan/PDF; the note carries extracted metadata that is **not** authoritative on its own.
- **AI action:** `suggest` extracted fields (vendor, date, amount, serial number, expiry). `queue-only` for any change to authoritative metadata.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** No; the scan retains authority.
- **Human-readable/editable:** Yes.
- **Examples:** Receipt scan companion, warranty companion, contract companion, manual companion.

### `email_summary` (HK / CN)

- **Definition:** Vault-side summary of an email thread. The thread in Gmail (or other provider) is the authority. Email is not imported wholesale.
- **Lifecycle:** `active` while the thread is in play; `archived` once closed.
- **Authority:** Source-authoritative is the email thread. Summary is non-authoritative.
- **AI action:** `suggest` action/decision/reference flags, links. `queue-only` for classification or governance changes.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** Only via explicit extraction into decisions, evergreens, or reference notes.
- **Human-readable/editable:** Yes.
- **Examples:** Insurance thread summary, project thread summary, scheduling thread summary.

### `youtube_source_note` (HK / CN)

- **Definition:** Vault-side companion note for a YouTube video, treated as a source artifact (not a knowledge note).
- **Lifecycle:** `active` while consuming, `durable` as a reference anchor, `archived` if abandoned.
- **Authority:** Source-authoritative is the video URL. Transcript, AI summary, takeaways are non-authoritative.
- **AI action:** `suggest` transcript ingestion, summary, candidate takeaways. MUST NOT promote into evergreen on its own.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** Only via human review producing an evergreen, literature, or synthesis note.
- **Human-readable/editable:** Yes.
- **Examples:** Tutorial video record, talk record, vlog record.

### `contact_note` (HK)

- **Definition:** Note about a person (or org-equivalent): role, context, communication threads, relationship state.
- **Lifecycle:** `durable` while the relationship is relevant.
- **Authority:** Human-authored. Privacy-sensitive.
- **AI action:** `suggest` link candidates and freshness flags. MUST NOT silently infer relationships or sensitive attributes.
- **Indexable:** Yes, with privacy scoping.
- **Promotable to durable knowledge:** Not as such; specific facts MAY be promoted into evergreens via review.
- **Human-readable/editable:** Yes.
- **Examples:** Person dossier, client note, family member context.

### `decision_record` (HK)

- **Definition:** A record of a decision: context, options considered, chosen path, rationale, date.
- **Lifecycle:** `durable`; immutable historical record after the decision is logged.
- **Authority:** Human-authored, governance-bearing for the decision it captures.
- **AI action:** `suggest` drafting, linking. MUST NOT silently mutate a logged decision.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** Already durable.
- **Human-readable/editable:** Yes for new records; logged decisions SHOULD be append-only.
- **Examples:** ADR, life-decision record, project decision log.

### `reflection_note` (HK)

- **Definition:** First-person reflection: what was learned, felt, noticed; review-style writing.
- **Lifecycle:** `durable` once written.
- **Authority:** Human-authored. Authoritative for the user's own reflection at that time.
- **AI action:** `suggest` prompts and link candidates. MUST NOT rewrite the user's reflection.
- **Indexable:** Yes, with privacy scoping.
- **Promotable to durable knowledge:** Insights MAY be promoted into evergreens via review.
- **Human-readable/editable:** Yes.
- **Examples:** Weekly review, retrospective, journaled reflection.

### `evergreen_note` (HK)

- **Definition:** Durable, atomic human knowledge: a claim or concept the user understands and stands behind.
- **Lifecycle:** `durable`, with optional revision over time.
- **Authority:** Human-authored; durable knowledge.
- **AI action:** `suggest` linking, contradiction flags. `queue-only` for content edits. MUST NOT silently rewrite.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** Already durable.
- **Human-readable/editable:** Yes.
- **Examples:** Concept notes, claim notes, principle notes.

### `synthesis_note` (HK)

- **Definition:** Cross-source or cross-evergreen synthesis: the user pulls multiple inputs into a new framing.
- **Lifecycle:** `durable`.
- **Authority:** Human-authored.
- **AI action:** `suggest` candidate connections. MUST NOT author the synthesis on the user's behalf.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** Already durable.
- **Human-readable/editable:** Yes.
- **Examples:** Literature-review-style notes, framework notes, model-of-X notes.

### `companion_note` (CN)

- **Definition:** Human-readable, editable context attached to an artifact whose source of truth lives elsewhere.
- **Lifecycle:** Tracks the lifecycle of the artifact it accompanies.
- **Authority:** Source-authoritative is the underlying artifact; the companion is non-authoritative human/AI commentary.
- **AI action:** `suggest` or `queue-only` depending on the underlying artifact's class.
- **Indexable:** Yes.
- **Promotable to durable knowledge:** No, on its own; promotion happens via derived HK artifacts.
- **Human-readable/editable:** Yes.
- **Examples:** Companion notes for photos, emails, YouTube videos, receipts, projects.

### `ai_suggestion` (AM)

- **Definition:** A candidate produced by AI: link, classification, caption, summary, memory candidate, or other proposal.
- **Lifecycle:** `ephemeral` until accepted, rejected, or expired.
- **Authority:** AI-generated; non-authoritative by default. MUST NOT be treated as source of truth.
- **AI action:** `create`, `queue-only` for promotion into anything else.
- **Indexable:** Yes (as proposals, not as knowledge).
- **Promotable to durable knowledge:** Only via explicit human or governed review that produces a different artifact class.
- **Human-readable/editable:** Yes; rejection / acceptance is a first-class action.
- **Examples:** Suggested wikilink, suggested classification, suggested evergreen draft.

### `machine_mirror` (MM)

- **Definition:** Machine-derived projection of authoritative state: embeddings, indexes, derived tables, mirrors of governance state.
- **Lifecycle:** `rebuildable`; never the system of record.
- **Authority:** System-authoritative only as a derived projection; MUST NOT be treated as source of truth.
- **AI action:** `create` (regenerate) and `edit` only within explicit refresh contracts.
- **Indexable:** Yes; the mirror often *is* the index.
- **Promotable to durable knowledge:** No.
- **Human-readable/editable:** Not typically; mirrors are rebuildable from authoritative sources.
- **Examples:** Vector index, media object/face index, link graph mirror, embedding store, OCR index.

The `synthesis_note` / `evergreen_note` / `literature_note` / `source_note` distinction is load-bearing: a system that collapses quotes, summaries, and personal claims into one layer cannot honor authority. The `ai_suggestion` / HK distinction is equally load-bearing: AI candidates are not knowledge until reviewed.

## 4. Lifecycle model

A life-wide PKM SHOULD recognize the following lifecycle states. Each artifact class declares which states apply to it.

- `ephemeral` — hours to days; expected to be cleared, triaged, or expire.
- `active` — days to months; in current use.
- `durable` — months to years; retained as long-term knowledge or record.
- `archived` — historical, no longer active, retained for audit / memory.
- `rebuildable` — machine-derived; safe to delete and regenerate from authoritative state.

Transitions are not free. Promotion from `ephemeral` or `active` into `durable` is a governance-bearing action and SHOULD pass through explicit human or governed review when the destination is a durable Human Knowledge Artifact (`evergreen_note`, `synthesis_note`, `decision_record`).

Lifecycle is distinct from **activation** (whether an artifact is currently in use for context); activation is owned by `CONTEXT_ACTIVATION_SEMANTICS.md` and is not redefined here.

## 5. Authority model

Authority answers: may this artifact be trusted as source of truth, and may an agent act on it?

The following authority flags MAY apply to an artifact (multiple can be true simultaneously):

- **human-authored** — written or curated by the user.
- **AI-generated** — produced by an AI process.
- **source-authoritative** — the authoritative artifact for its content (the photo file, the email thread, the PDF, the user's own decision record).
- **system-authoritative** — the system holds this as a derived but governed projection (e.g. a mirror with a refresh contract).
- **agent-editable** — explicit scope in which agents MAY edit fields without prior queueing.
- **requires-review** — change-of-state requires human or governed-process review.
- **governance-bearing** — carries governance semantics (decision, authority assertion, classification, lifecycle change).

Normative rule:

> **AI-generated content and metadata MUST be non-authoritative by default.** AI MAY produce drafts, captions, summaries, classifications, and link candidates. Promotion into authoritative or durable state requires explicit human review or a governed process.

In particular:

- AI MUST NOT silently mutate `governance-bearing` metadata.
- AI MUST NOT silently promote an `ai_suggestion` into an `evergreen_note`, `synthesis_note`, or `decision_record`.
- Where authority is in doubt, AI MUST queue a proposal rather than commit a change.

## 6. Provenance model

Provenance records where an artifact or claim came from. A life-wide PKM SHOULD recognize at least these provenance kinds:

- `user_authored` — the user typed it.
- `own_photo` — captured by the user.
- `own_screenshot` — captured by the user (possibly sensitive).
- `own_scan` — scanned/imaged by the user.
- `email_thread` — Gmail or other provider.
- `youtube_url` — a YouTube video as source.
- `web_article` — a web page / article.
- `book` — a printed or digital book.
- `pdf` — a PDF file.
- `ai_summary` — AI-derived summary of any of the above.
- `ai_caption` — AI caption of media.
- `ai_extraction` — AI extraction (OCR, fields, entities).
- `machine_index` — machine-built projection (mirror).

Provenance MUST NOT be lost when artifacts are derived. A `youtube_source_note` derived from an AI transcript MUST carry both the `youtube_url` provenance for the video and the `ai_extraction` provenance for the transcript.

## 7. Work-relation model

Work relation answers: why does this artifact exist in the workflow? Agents MUST behave differently across these relations.

- `capture` — record without immediate processing.
- `orient` — help the user locate themselves and the relevant artifacts.
- `decide` — support or record a decision.
- `execute` — drive action: a list, a checklist, a step.
- `learn` — extract understanding from sources.
- `create` — produce a new artifact (draft, synthesis).
- `remember` — preserve history, reflection, or identity.
- `resurface` — bring relevant prior artifacts back into context.
- `communicate` — outward-facing artifact (email draft, message draft, share).

A note meant to **orient** SHOULD NOT be silently edited by an agent the way a note meant to **execute** might be (e.g. checking off a checklist item under explicit instruction). A note meant to **decide** is governance-bearing and changes to it MUST pass through review.

## 8. Folder and MOC guidance

A vault MAY adopt a folder layout for ergonomic reasons. The folder layout below is illustrative only. It is **not** authoritative for artifact class or lifecycle.

```text
00_Inbox/
  Captures/
  Imports/
  Triage/

01_Work/
  Projects/
  Active Drafts/
  Decisions/

02_Life/
  Home/
  Finance/
  Health/
  People/
  Travel/
  Hobbies/

03_Knowledge/
  Sources/
  Literature/
  Evergreen/
  Synthesis/
  MOCs/

04_Operations/
  Checklists/
  Shopping/
  Maintenance/
  Receipts/
  Subscriptions/

05_Media_Index/
  Photos/
  Screenshots/
  Scans/
  Reference Images/

90_Archive/
  Projects/
  Areas/
  Old Imports/

.system/
  mirrors/
  indexes/
  receipts/
  logs/
```

Rules:

- Folders are ergonomics. Metadata and links carry governed semantics.
- LYT/MOC surfaces are human navigation and orientation tools, not ontology. A MOC MUST NOT be treated as the system's source of truth about what exists.
- PARA-style Projects / Areas / Resources / Archive may remain useful ergonomic working surfaces, but they MUST NOT be treated as semantic authority.
- The same artifact MAY appear under different navigation surfaces (an MOC, a project note, an area dashboard) without changing its class, lifecycle, or authority.

## 9. Concrete examples

These examples show how the taxonomy expresses itself for common artifact flows. Frontmatter is illustrative and points toward future updates to `ARTIFACT_METADATA_CONTRACT.md`; it is not a contract on its own.

### 9.1 Shopping list

Flow:

```text
capture → active list → completed / cleared → optional pattern extraction
```

The list itself does not become durable knowledge. Patterns extracted across many lists MAY be promoted via review.

```yaml
---
artifact_class: shopping_list
lifecycle: ephemeral
work_relation: execute
area: home
authority:
  human_authored: true
  ai_generated: false
  agent_editable: true   # checking items off under explicit instruction
  governance_bearing: false
---
```

### 9.2 Email summary

Email is **not** imported wholesale into the vault. The vault contains a controlled representation; authority remains in the provider.

```text
email thread → email_summary → actions / evidence / source / archive
```

```yaml
---
artifact_class: email_summary
lifecycle: active
work_relation: orient
source:
  kind: email_thread
  provider: gmail
  thread_id: "<gmail thread id>"
participants: []
contains_action: true
contains_decision: false
contains_reference: true
authority:
  source_authoritative: false
  summary_authoritative: false
  ai_generated: true
  requires_review: true
---
```

### 9.3 YouTube source note

YouTube videos are sources, not knowledge.

```text
url → transcript / source note → AI summary → human takeaways → optional evergreen / synthesis
```

```yaml
---
artifact_class: youtube_source_note
lifecycle: active
work_relation: learn
source:
  kind: youtube_url
  url: "<video url>"
  creator: "<channel>"
watched_status: queued | watched | abandoned
transcript_available: true
ai_summary: "<AI-generated summary, non-authoritative>"
human_takeaways: []
authority:
  source_authoritative: false
  ai_generated: true
  requires_review: true
---
```

### 9.4 Book / source vs literature vs evergreen vs synthesis

Four distinct artifacts, not one:

```text
source_note        = the book as artifact (record, metadata, link to copy)
literature_notes   = what the author says, in the user's words
evergreen_notes    = what the user now claims or understands
synthesis_notes    = cross-source synthesis the user produces
```

A system that collapses these layers MUST NOT be considered a faithful implementation of this taxonomy.

### 9.5 Project evidence photo

A media note with provenance pointing at an original photo file stored outside the ordinary vault note flow.

```yaml
---
artifact_class: media_note
artifact_type: photo
lifecycle: durable
work_relation: remember
area: home
project: kitchen-paneling
provenance:
  source_kind: own_photo
  source_file: /Media/Yggdrasil/Photos/Originals/2026/2026-05-18-Kitchen/20260518_142233_kitchen-panel-test.jpg
captured_at: 2026-05-18T14:22:33+02:00
people: []
objects:
  - oak veneer
  - wall panel
ai_caption: "Oak veneer panel test leaning against kitchen wall."
human_caption: "Test of natural oak veneer against existing oak floor."
authority:
  human_authored: true
  ai_generated_fields:
    - ai_caption
    - objects
  source_authoritative: false   # the photo file holds source authority
  system_authoritative: false
privacy: private
---
```

### 9.6 Screenshot

Screenshots typically anchor incident, debug, or evidence flows and MAY be privacy-sensitive.

```text
screenshot → OCR → incident / project / debug note → optional archive
```

```yaml
---
artifact_class: screenshot_note
lifecycle: active
work_relation: capture
provenance:
  source_kind: own_screenshot
  source_file: /Media/Yggdrasil/Screenshots/2026/2026-05-18-error.png
ai_ocr_text: "<extracted text, non-authoritative>"
privacy: review-required
authority:
  human_authored: true
  ai_generated_fields:
    - ai_ocr_text
  source_authoritative: false   # the screenshot file holds source authority; this note does not
  system_authoritative: false
  requires_review: true
---
```

### 9.7 Receipt / scan

Authority remains in the original; AI extractions are non-authoritative.

```yaml
---
artifact_class: scan_or_receipt_note
document_type: receipt   # receipt | warranty | manual | contract
lifecycle: durable
work_relation: remember
provenance:
  source_kind: own_scan
  source_file: /Media/Yggdrasil/Scans/2026/2026-05-18-receipt.pdf
extracted:
  vendor: "<vendor>"
  date: "2026-05-18"
  amount: "<amount>"
  warranty_until: "2028-05-18"
authority:
  human_authored: true
  ai_generated_fields:
    - extracted.vendor
    - extracted.date
    - extracted.amount
    - extracted.warranty_until
  source_authoritative: false   # the scan/PDF file holds source authority; this note does not
  ai_summary_authoritative: false
  system_authoritative: false
  requires_review: true
---
```

### 9.8 Evergreen note

Durable, atomic human knowledge. Distinct from any of the source / literature / AI-summary layers above.

```yaml
---
artifact_class: evergreen_note
lifecycle: durable
work_relation: learn
authority:
  human_authored: true
  ai_generated: false
  governance_bearing: false
---
```

## 10. Media handling

Images, video, audio, scans, and screenshots MUST NOT be treated merely as Obsidian attachments. They are first-class source artifacts with companion notes and rebuildable indexes.

Media artifact roles:

- `media_original` — the original file (photo, video, audio, PDF, scan). Authoritative source.
- `media_derivative` — edits, exports, thumbnails. Derived; non-authoritative on its own.
- `media_note` — human-readable companion note in the vault.
- `media_index` — rebuildable machine index (objects, faces, OCR, embeddings). MUST NOT be source of truth.
- `media_moc` — human navigation surface over media; not ontology.

Recognized image / media categories (non-exhaustive):

- `personal_photo`
- `project_evidence_photo`
- `reference_image`
- `screenshot`
- `scan`
- `receipt`
- `manual`
- `contract`

Rules:

- Originals SHOULD be stable and preferably stored outside ordinary vault note flow (e.g. a dedicated media store), with the vault note linking to them.
- Media notes live in the vault and link to originals; they MUST carry provenance.
- AI captions, OCR, object detection, face detection, and embeddings are non-authoritative by default; they MUST be marked as AI-generated fields.
- Screenshots may contain sensitive information and require privacy/provenance handling; they SHOULD default to private and `requires-review` for promotion.
- Scans, receipts, contracts, and manuals retain source authority in the original file. AI summaries MUST NOT be treated as authoritative for legal/financial use.
- Machine media indexes are `rebuildable` and MUST NOT become source of truth. Deleting an index MUST be safe.

## 11. Companion-note implication

> Companion notes provide human-readable, editable context around artifacts whose source of truth lives elsewhere.

The companion-note pattern (see `COMPANION_NOTE_PATTERN.md`) is how this taxonomy keeps source authority in the original artifact while still allowing the vault to carry human context and AI candidates.

Common companion pairings:

```text
Photo file       → companion media note
Email thread     → companion email summary note
YouTube video    → companion source note
Receipt PDF      → companion receipt note
Project folder   → companion project MOC
Scanned contract → companion scan note
Screenshot       → companion screenshot note
```

Companion notes MUST NOT silently override the underlying artifact's authority. AI-generated fields in a companion note are AI-generated, regardless of where they appear.

## 12. AI and governance rules

The following rules govern AI and agent behavior under this taxonomy:

- AI MAY summarize, caption, suggest links, extract metadata, propose classification, and draft companion notes.
- **AI-generated outputs are non-authoritative by default.**
- AI MUST NOT silently promote source material into durable knowledge.
- AI MUST NOT silently mutate governance-bearing metadata.
- AI SHOULD queue proposals when authority, lifecycle, classification, or cross-note effects are involved.
- Human review or a governed process is required for promotion into durable knowledge or authoritative state.

> AI generates candidates; the human or governed process decides promotion.

This rule preserves the Yggdrasil authority boundary across the full taxonomy: Human Knowledge Artifacts, Agentic Memory Artifacts, and Machine Mirror Artifacts remain distinct kinds of artifact and MUST NOT be collapsed.

## 13. Non-goals and anti-patterns

This document is not a runtime contract and not a vault migration. It also rejects the following anti-patterns explicitly.

### Anti-pattern 1 — Folder path as semantics

Wrong:

```text
03_Knowledge/Evergreen/foo.md is, by virtue of its folder, durable human knowledge.
```

Correct:

```yaml
artifact_class: evergreen_note
lifecycle: durable
authority:
  human_authored: true
```

### Anti-pattern 2 — AI summary as authoritative knowledge

Wrong:

```text
AI summarized a YouTube video, therefore the summary is knowledge.
```

Correct:

```text
AI summary is a non-authoritative source derivative until reviewed and promoted by a human or governed process.
```

### Anti-pattern 3 — Attachments as unmanaged blobs

Wrong:

```text
Images and PDFs live randomly inside notes as attachments with no provenance.
```

Correct:

```text
Media originals are source artifacts; vault companion notes carry provenance, captions, and links.
```

### Anti-pattern 4 — Everything becomes evergreen

Wrong:

```text
Shopping lists, receipts, meeting notes, book summaries, and AI summaries are all knowledge notes.
```

Correct:

```text
Different artifacts have different lifecycles, authority boundaries, and allowed agent actions.
```

### Anti-pattern 5 — LYT MOCs as ontology

Wrong:

```text
A MOC defines what the system thinks exists.
```

Correct:

```text
A MOC is a human navigation surface over governed artifacts; ontology lives in artifact metadata.
```

Additional non-goals:

- Do not migrate the user's current vault.
- Do not introduce runtime enforcement.
- Do not define a complete media pipeline implementation.
- Do not make folder paths authoritative.
- Do not make AI-generated metadata authoritative by default.
- Do not collapse Human Knowledge Artifacts, Agentic Memory Artifacts, and Machine Mirror Artifacts.

## 14. Implications for future work

This taxonomy implies, but does not deliver, the following follow-up work:

1. Update `ARTIFACT_METADATA_CONTRACT.md` to support the artifact classes, lifecycle states, authority flags, provenance kinds, and work-relation values named here.
2. Define a dedicated media artifact contract covering originals, derivatives, companion notes, and rebuildable indexes.
3. Define an ingestion and triage policy for inbox capture, email, YouTube, scans, and screenshots.
4. Add companion-note templates for source / media / email / receipt / project artifacts.
5. Add runtime validation only after the docs and examples stabilize, and only behind explicit governed-process review.

Until those follow-ups land, this document is a specification layer that agents and humans MAY use to classify artifacts in a way that does not assume folder paths are truth.
