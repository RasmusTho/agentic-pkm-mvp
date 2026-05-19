State: Media artifact contract for the Contextualization Layer (docs-only, target-state framing).
Doc role: Concept contract
Authority: Defines the media artifact roles, subtypes, authority rules, provenance rules, and AI governance for media originals, derivatives, vault-side notes, machine indexes, and navigation surfaces. Not a media pipeline implementation, not a runtime schema, not a vault migration plan.

# Media Artifact Contract

## 1. Purpose

This document defines the **media artifact contract** for the Yggdrasil / Agentic PKM.

It exists because media artifacts — photos, screenshots, scans, receipts, manuals, contracts, and reference images — have distinct authority, provenance, lifecycle, and privacy semantics that differ from note artifacts. Media must not be treated as unmanaged Obsidian attachments or as equivalent to Markdown notes.

This document is explicitly:

- **Not a media pipeline implementation.** No ingestion scripts, OCR pipelines, face-detection services, or media-store APIs are defined here.
- **Not a runtime schema.** No database tables, indexes, or validators are wired here.
- **Not a vault migration plan.** Existing media files are not moved or renamed by this contract.
- **Not a final on-disk layout decision.** File naming, directory structure, and companion-note location remain downstream decisions.
- A **documentation-level contract** that future implementation and validation work can attach to.

This document sits alongside `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` and refines Section 10 ("Media handling") of `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md` into a dedicated contract surface.

## 2. Relationship to adjacent contracts

| Contract | Role |
| --- | --- |
| `LIFE_WIDE_ARTIFACT_TAXONOMY.md` | Governs conceptual intent for all life-wide artifact classes, including the media subtypes and their taxonomy positions. This contract governs field-level expression. |
| `ARTIFACT_METADATA_CONTRACT.md` | Defines shared minimal fields and per-class metadata shapes; Section 12.7 provides the `media_note` example. The current document extends that with media-specific roles, subtypes, and rules. |
| `COMPANION_NOTE_PATTERN.md` | Governs companion note placement, linkage, readability, and conflict rules. Media notes are a companion-note sub-pattern; this contract adds media-specific provisos. |
| `HUMAN_AND_AGENTIC_ARTIFACTS.md` | Names the three load-bearing artifact classes. Media originals are source artifacts in the Human Knowledge family; machine media indexes are Machine Mirror artifacts. |
| `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` | Governs projection and source authority. Media originals are authoritative sources; derivatives and indexes are projections. |
| `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` | Governs trust tiers and write gating. AI captions, OCR, and extraction results are non-authoritative by default under the trust model. |

## 3. Media artifact roles

A media artifact in the PKM is not a single thing. This contract distinguishes five roles. Each role has different authority, lifecycle, and governance semantics.

### 3.1 `media_original`

The original file as captured or received. The authoritative source.

- **Examples:** `20260518_kitchen-panel.jpg`, `receipt-2026-05-18.pdf`, `contract-lease-2024.pdf`, `screenshot-error-2026-05-18.png`.
- **Authority:** Source-authoritative. The original file is the system of record for its content.
- **Lifecycle:** `durable` for legal/financial/personal records; `active` for project-phase evidence; `rebuildable` never — originals are not rebuildable from the vault.
- **Storage posture:** Originals SHOULD be stored outside the ordinary vault note flow (e.g. a dedicated media store or folder tree that the vault links to, not inside the vault's `.attachments` dump). This prevents vault bloat, supports large-file handling, and separates the authoritative record from the vault's operational note flow.
- **Mutability:** Originals SHOULD NOT be silently overwritten or renamed by automated processes. Any rename or move requires an explicit operator action.
- **AI action:** `none` — AI MUST NOT rewrite, overwrite, or discard originals. AI may read originals for caption/OCR/extraction, but outputs are non-authoritative.

### 3.2 `media_derivative`

An edited, exported, resized, cropped, or otherwise derived version of a `media_original`.

- **Examples:** Thumbnail, web-export JPEG, rotated copy, annotated screenshot, redacted contract PDF.
- **Authority:** Non-authoritative on its own; derives authority from the original.
- **Lifecycle:** `rebuildable` unless explicitly marked as non-rebuildable (e.g. a legally-signed annotated copy).
- **Storage posture:** Derivatives may live closer to the vault note flow than originals, since they are disposable. Link back to the original is required.
- **Mutability:** Safe to regenerate, overwrite, or discard unless marked `not_rebuildable: true` in accompanying metadata.
- **AI action:** `create` for automatic thumbnails/exports; `edit` within explicit refresh contracts.

### 3.3 `media_note`

A vault-side companion note that holds human-readable context about a media original. The companion note lives in the vault; the original lives in the media store.

- **Examples:** Kitchen-paneling photo note, family photo note, screenshot note, receipt companion note.
- **Authority:** Source-authoritative is the original file. The note holds human context, AI-generated suggestions, and provenance metadata. The note does not replace the original.
- **Lifecycle:** Tracks the lifecycle of the original it accompanies. `durable` for records with long-term relevance; `active` for project-phase evidence.
- **Linkage requirement:** The note MUST carry a `provenance.source_file` pointer back to the original. Without this pointer the companion breaks source authority.
- **AI action:** `suggest` (captions, object labels, OCR text, provenance hints). All AI-generated fields are non-authoritative and MUST be marked as such. `queue-only` for classification or authority changes.
- **Human-readable/editable:** Yes. A human MUST be able to open the note, read the context, and correct any AI-generated field.

### 3.4 `media_index`

A machine-built index of media metadata: object detection, face detection, OCR extracted text, embeddings, or search projections over media.

- **Examples:** Face index, object index, OCR index, vector embedding store for media files, thumbnail gallery projection.
- **Authority:** System-derived projection only. NOT source of truth. Authority belongs to the originals the index was built from.
- **Lifecycle:** `rebuildable`. Deleting the index and rebuilding it from originals MUST produce an equivalent artifact.
- **Storage posture:** Lives in the system/machine layer (`.system/mirrors/` or equivalent); not inside vault notes.
- **Mutability:** Safe to discard and rebuild. Manual edits that need to survive belong in the source `media_note` or `media_original`, not in the index.
- **AI action:** `create` (regenerate) and `edit` only within explicit refresh contracts. MUST NOT become source of truth for any governance-bearing decision.

### 3.5 `media_moc`

A human-authored navigation surface over media: a map of content (MOC), gallery note, or media browse index that helps the human orient among media artifacts.

- **Examples:** "Kitchen Renovation — Photo Gallery", "2026 Receipt Archive", "Design Reference Images".
- **Authority:** Human navigation surface. NOT ontology. A media MOC does not define what media exists; it helps the human find media that exists.
- **Lifecycle:** `durable` while the area or project is active; `archived` when no longer navigated.
- **AI action:** `suggest` (new entries, freshness flags). MUST NOT mutate the MOC's governance role or override human curation choices.

## 4. Media subtypes

The following subtypes identify the concrete kinds of media artifact this system handles. Each subtype inherits the role semantics from Section 3 and adds privacy, provenance, and authority provisos.

### 4.1 `personal_photo`

A photo of personal life: family, events, places, activities.

- **Privacy:** `private` by default. MUST NOT be shared, indexed in public surfaces, or made retrievable in multi-user contexts without explicit consent.
- **Provenance:** `own_photo`.
- **AI action:** `suggest` captions, location hints, people hints — all non-authoritative. MUST NOT silently infer sensitive attributes (people's identities, relationships, health states). Face detection outputs are non-authoritative candidate suggestions requiring human review.
- **Lifecycle:** `durable` for photos the human wants to keep; `archived` for older collections.

### 4.2 `project_evidence_photo`

A photo documenting project state: construction phases, before/after comparisons, material samples, inspection evidence.

- **Privacy:** `internal` or `private` depending on content.
- **Provenance:** `own_photo`.
- **AI action:** `suggest` object/material labels, phase labels — all non-authoritative.
- **Lifecycle:** `durable` while the project is active; `archived` on completion or after warranty period.
- **Note:** Project evidence photos may carry legal or warranty significance. AI-extracted labels MUST NOT be treated as authoritative for legal/insurance/construction purposes.

### 4.3 `reference_image`

An image sourced externally: material samples from suppliers, design references from websites, product images, maps, diagrams.

- **Privacy:** Depends on source. Many reference images are public; some may be copyrighted or contain personal data.
- **Provenance:** `web_article`, `pdf`, or named source. MUST carry usage-right and provenance metadata.
- **Authority caution:** The image itself is not the user's creation. Source and usage rights MUST be recorded. AI MUST NOT treat a reference image as the user's own work.
- **Lifecycle:** `active` during the project consuming the reference; `archived` after use.
- **Usage-right field:** `usage_rights` — `personal_use_only`, `commercial_ok`, `unknown`, `copyright_claimed`. Unknown defaults to `personal_use_only` posture.

### 4.4 `screenshot`

A captured image of a screen: UI state, error message, financial state, conversation excerpt, code output, terminal output.

- **Privacy:** `review-required` by default. Screenshots frequently contain sensitive information (account numbers, personal messages, health data, financial data, passwords visible on screen). MUST be treated as privacy-sensitive until reviewed.
- **Provenance:** `own_screenshot`.
- **AI action:** `suggest` OCR text, app/window identification, redaction candidates — all non-authoritative. AI MUST flag likely-sensitive content for human review.
- **Lifecycle:** `active` during the incident or project; `durable` if it anchors a decision or evidence record; `archived` after the relevant period.
- **Promotion caution:** Screenshots may include private conversations, financial state, or credentials. Promotion into searchable or shareable surfaces requires explicit human review.

### 4.5 `scan`

A scanned physical document: receipt, warranty card, user manual, contract, certificate, or identity document.

- **Privacy:** `private` for identity documents and health records; `review-required` for financial and legal documents; `internal` for warranties and manuals.
- **Provenance:** `own_scan`.
- **Authority:** The scan/PDF file is the source of authority. AI-extracted fields (vendor, date, amount, serial, expiry) are non-authoritative summaries. For legal or financial disputes, the scan/PDF file — or the original physical document — is the authoritative record.
- **Lifecycle:** `durable` for legal/financial relevance; `archived` after the relevant period (expiry, disposal of property, end of warranty).

### 4.6 `receipt`

A scan or photograph of a purchase receipt.

- **Privacy:** `private` or `review-required`.
- **Provenance:** `own_scan` or `own_photo`.
- **AI action:** `suggest` extracted fields (vendor, date, amount, currency, line items, tax, payment method, warranty trigger). All AI-extracted fields are non-authoritative; the scan/photo is the authoritative record.
- **Lifecycle:** `durable` while warranty is relevant, subscription is active, or for tax/expense period; `archived` after.

### 4.7 `manual`

A product or service manual: appliance manual, software documentation, construction material spec sheet.

- **Privacy:** Usually `internal`; rarely sensitive.
- **Provenance:** `pdf` or `web_article`.
- **Authority:** The manufacturer/publisher holds authority. The vault copy is a reference.
- **AI action:** `suggest` searchable labels, key-spec extraction, maintenance-schedule hints. All non-authoritative.
- **Lifecycle:** `durable` while the product is owned; `archived` when product is disposed.

### 4.8 `contract`

A legal document: lease, purchase contract, service agreement, employment contract, insurance policy.

- **Privacy:** `private`.
- **Provenance:** `own_scan`, `pdf`, or named counterparty.
- **Authority:** The legally-executed document holds authority. AI summaries of contract terms are non-authoritative and MUST NOT be used for legal decision-making.
- **AI action:** `suggest` key-date extraction, party names, obligation summaries — all non-authoritative. AI MUST warn that legal interpretation requires human or professional review.
- **Lifecycle:** `durable` for the contract's active period; `archived` after termination, plus applicable retention period.

## 5. Authority and provenance rules

These rules apply across all media artifact roles and subtypes.

### 5.1 Source authority stays with the original

The `media_original` is the source of truth for its content. Media notes, derivatives, indexes, and AI-extracted fields are projections of that source. When a claim from a media note conflicts with what the original file contains, the original governs.

This rule applies even when the original has not been re-examined recently. "The note says X" is not authority; "the original file shows X" is.

### 5.2 AI-generated fields are non-authoritative by default

Any field produced by an AI process — caption, OCR text, object label, face suggestion, date extraction, amount extraction — is non-authoritative by default. It is a proposal, not a fact.

Marking: AI-generated fields MUST be grouped under an `ai_generated_fields` list or equivalent marker in the `authority` block, or carried in a companion note rather than inline in the primary note. This makes the boundary visible to both humans and agents.

Promotion: An AI-generated field becomes authoritative only when a human or governed process explicitly reviews and promotes it. `review_state: reviewed` and the removal of the AI-generated marker are the signals of that promotion.

### 5.3 Screenshots are privacy-sensitive by default

Screenshots MUST carry `privacy: review-required` unless explicitly reviewed and reclassified. Agents MUST NOT:
- Make screenshots retrievable in shared or multi-user surfaces before privacy review.
- Index screenshot OCR text in shared search surfaces without review.
- Include screenshot content in context bundles delivered to external surfaces.

### 5.4 Legal/financial originals require special caution

For receipts, contracts, scans, and identity documents:
- AI summaries MUST NOT be used as the record for legal, financial, or compliance purposes.
- The original file or physical document is the authoritative record.
- Deletion or discarding of legal/financial originals MUST NOT be automatic; it requires explicit human action.

### 5.5 Machine media indexes must not become source of truth

A `media_index` is a rebuildable projection. It MUST NOT:
- Override or replace the `media_original` as source of truth.
- Drive governance-bearing decisions (e.g. "we have no photos of the kitchen before work" based on index absence — the index may be incomplete).
- Be manually edited as if it were authoritative — edits belong in the `media_note` or `media_original`.

Deleting a `media_index` MUST be safe. The only consequence SHOULD be that rebuild is needed.

### 5.6 MOCs are navigation, not ontology

A `media_moc` describes how the human navigates their media. It does not define what media exists, what is authoritative, or what is private. Adding an image to a MOC does not change its authority or privacy posture.

## 6. Metadata shape

Media notes carry standard fields from `ARTIFACT_METADATA_CONTRACT.md` plus media-specific additions. Field names below are logical; on-disk form is a downstream decision.

### 6.1 `media_note` frontmatter pattern

```yaml
---
artifact_class: media_note           # concrete taxonomy class name (implies human_knowledge / companion_metadata)
artifact_type: <subtype>             # personal_photo | project_evidence_photo | reference_image | screenshot | scan | receipt | manual | contract
lifecycle: <lifecycle>               # durable | active | archived
work_relation: <work_relation>       # remember | capture | execute | orient | decide
area: <area>                         # home | finance | health | work | relations | outdoor_life | ...
project: <project>                   # project identifier if applicable

provenance:
  source_kind: <kind>                # own_photo | own_screenshot | own_scan | pdf | web_article | ...
  source_file: <absolute or relative path to original>
  original_captured_at: <ISO-8601>   # when the original was created / captured
  source_url: <url>                  # for reference images only

ai_caption: "<AI-generated caption, non-authoritative>"
human_caption: "<Human-authored caption, authoritative>"

# For scan/receipt/contract/manual:
extracted:
  vendor: "<AI-extracted, non-authoritative>"
  date: "<AI-extracted, non-authoritative>"
  amount: "<AI-extracted, non-authoritative>"
  # ...

usage_rights: personal_use_only      # for reference_image subtype

authority:
  human_authored: true
  ai_generated_fields:
    - ai_caption
    - extracted.vendor
    - extracted.date
    - extracted.amount
  source_authoritative: false        # authority belongs to the original file, not this note
  system_authoritative: false

privacy: <privacy>                   # private | review-required | internal

review_state: unreviewed             # unreviewed | reviewed | accepted

created: <ISO-8601-date>
updated: <ISO-8601-date>
---
```

Not every field is required on every note. The bar for including a field inline: a human reader would find the field meaningful and not visually noisy. System-oriented metadata belongs in a companion metadata note.

### 6.2 Required fields by subtype

| Field | personal_photo | project_evidence | reference_image | screenshot | scan/receipt | manual/contract |
| --- | --- | --- | --- | --- | --- | --- |
| `provenance.source_kind` | Required | Required | Required | Required | Required | Required |
| `provenance.source_file` | Required | Required | — | Required | Required | Required |
| `provenance.source_url` | — | — | Required | — | — | — |
| `privacy` | Required | Recommended | Recommended | Required | Required | Required |
| `usage_rights` | — | — | Recommended | — | — | — |
| `authority` block | Recommended | Recommended | Required | Recommended | Required | Required |
| `ai_generated_fields` | Recommended | Recommended | — | Recommended | Recommended | Recommended |

## 7. Examples

### 7.1 Project evidence photo

A photograph documenting material selection for a home renovation project.

```yaml
---
artifact_class: media_note
artifact_type: project_evidence_photo
lifecycle: durable
work_relation: remember
area: home
project: kitchen-paneling

provenance:
  source_kind: own_photo
  source_file: /Media/Yggdrasil/Photos/Originals/2026/2026-05-18-Kitchen/20260518_142233_kitchen-panel-test.jpg
  original_captured_at: 2026-05-18T14:22:33+02:00

ai_caption: "Oak veneer panel test leaning against kitchen wall."
human_caption: "Test of natural oak veneer against existing oak floor — sample looks promising."

authority:
  human_authored: true
  ai_generated_fields:
    - ai_caption
  source_authoritative: false
  system_authoritative: false

privacy: internal
review_state: unreviewed
created: 2026-05-18
updated: 2026-05-18
---

## Context

Sample brought home from [Supplier] to compare against existing oak floor. AI caption is a rough
label only; the human caption captures the intent.

## Related

- [[Kitchen Paneling Project]]
- [[Material Selection — Oak Veneer]]
```

The photo file at `source_file` is the authoritative record. The AI caption is a draft label; the human caption carries the actual context.

### 7.2 Screenshot used as debug or evidence artifact

A screenshot of an application error or system state, captured for investigation or project documentation.

```yaml
---
artifact_class: media_note
artifact_type: screenshot
lifecycle: active
work_relation: capture
area: work
project: build-pipeline-debug

provenance:
  source_kind: own_screenshot
  source_file: /Media/Yggdrasil/Screenshots/2026/2026-05-18-build-error.png
  original_captured_at: 2026-05-18T09:14:22+02:00

ai_ocr_text: "<AI-extracted text from screenshot, non-authoritative>"

authority:
  human_authored: true
  ai_generated_fields:
    - ai_ocr_text
  source_authoritative: false
  system_authoritative: false
  requires_review: true

privacy: review-required
review_state: unreviewed
created: 2026-05-18
updated: 2026-05-18
---

## Context

Build pipeline error after upgrading dependency. Screenshot captures the full stack trace.
OCR text above is AI-extracted for searchability; the screenshot file is the authoritative record.

## Status

- [ ] Root cause identified
- [ ] Fix applied

## Related

- [[Build Pipeline — 2026-05 Upgrade]]
```

Privacy defaults to `review-required` because the screenshot may contain credentials, tokens, or sensitive paths even when the intent is to capture an error.

### 7.3 Receipt scan with extracted metadata

A scanned purchase receipt with AI-extracted fields for quick lookup.

```yaml
---
artifact_class: media_note
artifact_type: receipt
lifecycle: durable
work_relation: remember
area: home
project: kitchen-paneling

provenance:
  source_kind: own_scan
  source_file: /Media/Yggdrasil/Scans/2026/2026-05-18-oak-veneer-receipt.pdf
  original_captured_at: 2026-05-18

extracted:
  vendor: "Träteam AB"
  date: "2026-05-18"
  amount: "3 240 SEK"
  line_items:
    - "Oak veneer sheet 2400×1200, 12mm (×3)"
  warranty_trigger: false

authority:
  human_authored: true
  ai_generated_fields:
    - extracted.vendor
    - extracted.date
    - extracted.amount
    - extracted.line_items
  source_authoritative: false   # the scan PDF is the authoritative record
  ai_summary_authoritative: false
  system_authoritative: false
  requires_review: true

privacy: private
review_state: unreviewed
created: 2026-05-18
updated: 2026-05-18
---

## Notes

Receipt for oak veneer sheets used in kitchen paneling test. AI-extracted fields above are
for convenience lookup only; the scan PDF is the authoritative record for any financial or
warranty purposes.
```

The extracted fields are AI proposals. For expense reporting, tax, or warranty claims, the original scan PDF governs.

### 7.4 Reference image with usage-right and provenance caution

A product or material image from a supplier website, used as a design reference.

```yaml
---
artifact_class: media_note
artifact_type: reference_image
lifecycle: active
work_relation: orient
area: home
project: kitchen-paneling

provenance:
  source_kind: web_article
  source_url: https://supplier-example.com/products/oak-veneer-sheet
  source_file: /Media/Yggdrasil/Reference/2026/2026-05-15-oak-veneer-supplier.jpg
  original_captured_at: 2026-05-15

usage_rights: personal_use_only

authority:
  human_authored: false
  ai_generated_fields: []
  source_authoritative: false   # the supplier's original image/page holds authority
  system_authoritative: false

privacy: internal
review_state: unreviewed
created: 2026-05-15
updated: 2026-05-15
---

## Notes

Supplier reference image for oak veneer sheets. Not the user's own photo.
Usage: personal reference only. Do not publish or redistribute.
For authoritative product specs, see the supplier's current product page.
```

`usage_rights: personal_use_only` signals that this image should not be republished, indexed in shared surfaces, or embedded in documents distributed to others.

### 7.5 Personal photo with privacy posture

A family photograph with explicit privacy declaration.

```yaml
---
artifact_class: media_note
artifact_type: personal_photo
lifecycle: durable
work_relation: remember
area: relations

provenance:
  source_kind: own_photo
  source_file: /Media/Yggdrasil/Photos/Originals/2026/2026-05-18-family/20260518_173000_birthday.jpg
  original_captured_at: 2026-05-18T17:30:00+02:00

human_caption: "Birthday dinner — family gathered at the table."

authority:
  human_authored: true
  ai_generated_fields: []
  source_authoritative: false
  system_authoritative: false

privacy: private
review_state: unreviewed
created: 2026-05-18
updated: 2026-05-18
---

## Notes

Family birthday dinner photo. Private — not for sharing or indexing in any non-private surface.
```

`privacy: private` means this note and its linked original MUST NOT appear in shared retrieval results, shared context bundles, or any surface accessible to non-owner agents or users.

## 8. Non-goals

This document does **not**:

- implement a media ingestion pipeline,
- implement OCR, face detection, or object detection services,
- define a database schema or migration plan,
- decide the final on-disk layout for media originals or vault notes,
- require moving existing user photos or scans,
- define a runtime validation plan (that belongs to a separate implementation issue),
- claim that any of the described fields are currently validated at runtime.

## 9. Open questions

- **Where should media originals be stored relative to the vault?** A dedicated sibling media store, an iCloud-backed Photos library, a separate directory with vault links, or a cloud-bucket URL? The contract says "outside ordinary vault note flow"; the specific solution is a downstream operator decision.
- **Which AI media operations should be automatic vs. explicit?** Auto-captioning on ingest, OCR on receipts, and thumbnail generation have different risk profiles. The governance boundary for automatic vs. queued AI media operations is deferred to a future AI-action policy.
- **How should face/person detection be governed?** Face detection outputs require privacy review before any action; the specific review workflow and opt-in/out posture are not defined here.
- **Should media notes carry `stale_after` fields?** Some media context (project status, active receipt) has a natural staleness horizon; others (personal photos) do not.
- **How should AI redaction proposals for screenshots work?** Identifying and proposing redaction of sensitive regions is a natural AI action, but the approval/rejection workflow is not yet specified.
