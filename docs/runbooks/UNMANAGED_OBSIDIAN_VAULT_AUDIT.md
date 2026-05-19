State: Docs-only audit and migration strategy for an unmanaged Obsidian vault.
Doc role: Runbook / strategy
Authority: Defines safe phases, required audit inputs, classification approach, and safety rules for applying the life-wide artifact taxonomy to an existing unmanaged vault. Does not migrate any content; does not define runtime behavior.

# Unmanaged Obsidian Vault Audit and Migration Strategy

## 1. Purpose

This runbook defines a safe, phased strategy for auditing an existing unmanaged Obsidian vault and gradually aligning it with the life-wide artifact taxonomy.

An unmanaged vault is one where:
- Notes have grown organically without explicit artifact classification.
- Folder structure reflects habit, not governed semantics.
- Media files may live as random attachments without provenance.
- There is no consistent metadata or lifecycle posture across notes.

The goal is **not** to bulk-rewrite the vault. It is to:
1. Understand what exists.
2. Introduce classification and templates for new work.
3. Migrate existing notes opportunistically — only when touched in normal use.
4. Optionally automate migration only after dry-runs, receipts, and explicit operator approval.

**This runbook is docs-only.** It does not migrate vault content. It does not introduce runtime automation. Execution of the phases described here is a human operator decision.

Cross-reference: `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md` — artifact classes, lifecycle, authority, provenance, and work-relation axes that this runbook applies.

## 2. Safety rules

These rules govern all phases. Violating them risks data loss, incorrect classification, or unauthorized AI mutations.

**MUST NOT:** Mutate the real vault during the audit phase. Read-only observation first.

**MUST NOT:** Bulk-rewrite notes. Existing notes without metadata are valid vault content; absence of frontmatter is not an error.

**MUST NOT:** Require uploading the full vault to any cloud service for analysis. Analysis is done locally.

**MUST NOT:** Treat folder paths as semantic truth. `03_Knowledge/Evergreen/foo.md` is not automatically a durable evergreen note; classification requires reading the note.

**MUST NOT:** Allow AI-generated classifications to become authoritative without human review. AI may propose classifications; the human confirms.

**MUST NOT:** Execute bulk automated mutation without:
1. A written dry-run receipt showing exactly what would change.
2. Explicit operator approval of that receipt.
3. A rollback path confirmed before execution.

**SHOULD:** Start small. Run each phase on a sample or scoped area before extending to the full vault.

**SHOULD:** Preserve originals. For any note or file targeted for migration, keep the original until the migration is confirmed correct.

## 3. Required audit inputs

Before any classification or migration work can begin, collect the following. Store the audit outputs in a temporary location outside the vault (e.g. `audit/` directory at the repo or workspace root), not inside the vault itself.

### 3.1 Folder tree

```bash
# Collect folder structure (no file content)
find "$VAULT_ROOT" -type d | sort > audit/vault-folder-tree.txt

# Count files by extension
find "$VAULT_ROOT" -type f | sed 's/.*\.//' | sort | uniq -c | sort -rn > audit/vault-file-counts-by-ext.txt
```

### 3.2 Note counts

```bash
# Total note count
find "$VAULT_ROOT" -name "*.md" | wc -l

# Notes per folder (top level)
for dir in "$VAULT_ROOT"/*/; do
  count=$(find "$dir" -name "*.md" | wc -l)
  echo "$count  $dir"
done | sort -rn
```

### 3.3 Attachment counts and types

```bash
# Non-markdown files (potential attachments)
find "$VAULT_ROOT" -type f ! -name "*.md" | wc -l

# Attachment types
find "$VAULT_ROOT" -type f ! -name "*.md" | sed 's/.*\.//' | tr '[:upper:]' '[:lower:]' | sort | uniq -c | sort -rn > audit/vault-attachment-types.txt

# Large files (potential media originals)
find "$VAULT_ROOT" -type f -size +1M | sort > audit/vault-large-files.txt
```

### 3.4 Plugin list

```bash
# Installed plugins
cat "$VAULT_ROOT/.obsidian/community-plugins.json" 2>/dev/null > audit/vault-plugins.json
ls "$VAULT_ROOT/.obsidian/plugins/" 2>/dev/null > audit/vault-plugin-dirs.txt
```

### 3.5 Representative sample notes

Select 20–40 notes across different folders and age ranges. Do not bias the sample toward "interesting" notes; include ordinary, stub, and blank notes.

```bash
# Random sample (requires shuf, adjust N)
find "$VAULT_ROOT" -name "*.md" | shuf -n 40 > audit/vault-sample-paths.txt
```

Copy the sample notes (not the full vault) to `audit/sample-notes/` for review.

### 3.6 Attachment and media tree

```bash
# List all media-like files
find "$VAULT_ROOT" \( -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" -o -name "*.gif" \
  -o -name "*.webp" -o -name "*.heic" -o -name "*.pdf" -o -name "*.mp4" \
  -o -name "*.mov" -o -name "*.mp3" \) | sort > audit/vault-media-files.txt
```

### 3.7 Frontmatter audit

```bash
# Notes that already have frontmatter
grep -rl "^---" "$VAULT_ROOT" --include="*.md" | wc -l

# Notes with artifact_class already set
grep -rl "artifact_class:" "$VAULT_ROOT" --include="*.md" > audit/vault-already-classified.txt
```

## 4. Phase 1 — Observe

**Goal:** Understand what exists without touching anything.

**Who:** Human operator, with optional AI assistance for summarization (non-authoritative).

**Actions:**
1. Collect all audit inputs from Section 3.
2. Read the sample notes.
3. Identify recurring patterns: what kinds of things are in the vault? Books? Projects? Shopping lists? Journaling? Source dumps? Random captures?
4. Note the rough distribution of note "freshness": recent notes vs. abandoned stubs.
5. Identify media attachment patterns: are media files inside the vault, or linked externally?
6. Note any existing metadata conventions (tags, frontmatter, naming patterns).

**Outputs:**
- `audit/observe-findings.md` — a brief human-written summary of what was found.
- No classification yet. No changes to the vault.

**AI actions allowed:** AI may summarize the audit inputs and propose a rough classification sketch. These are non-authoritative observations, not classifications.

**AI actions not allowed:** AI MUST NOT write classification metadata into vault notes during this phase.

## 5. Phase 2 — Classify

**Goal:** Cluster the vault's notes into rough artifact classes without rewriting them.

**Who:** Human operator, with AI assistance for suggestions.

**Approach:** Work on the sample notes from the audit, not the full vault.

**For each sample note, answer:**

1. **What artifact class does this look like?** Use the taxonomy from `LIFE_WIDE_ARTIFACT_TAXONOMY.md`:
   - Is it a fleeting capture / inbox note? → `fleeting_capture`
   - Is it a shopping/packing/operational list? → `shopping_list` or `checklist`
   - Is it a running project log? → `project_note`
   - Is it a life-area overview? → `area_dashboard`
   - Is it a book/article record? → `source_note`
   - Is it notes on what a source says? → `literature_note`
   - Is it the user's own claims or concepts? → `evergreen_note`
   - Is it a cross-source synthesis? → `synthesis_note`
   - Is it a record of a decision? → `decision_record`
   - Is it a journal / reflection? → `reflection_note` or `daily_log`
   - Is it a companion for a photo/media file? → `media_note`
   - Is it a companion for an email thread? → `email_summary`
   - Is it a companion for a YouTube video? → `youtube_source_note`
   - Is it a companion for a receipt/scan/contract? → `scan_or_receipt_note`
   - Is it about a person? → `contact_note`
   - Is it unclear or mixed? → `fleeting_capture` (do not force a classification)

2. **What lifecycle posture does it have?**
   - Still relevant and being used → `active`
   - Settled, long-term useful → `durable`
   - Stale, no longer used → candidate for `archived`

3. **Does it have authority / privacy concerns?**
   - Does it contain financial data, health data, relationship details, credentials? → flag for `privacy: private`
   - Does it contain AI-generated content without review marking? → flag for `requires_review`

**Outputs:**
- `audit/classify-findings.md` — a rough cluster map: "approximately N% of notes appear to be X, Y% are Z, etc."
- `audit/classify-samples.md` — per-note classifications for the sample notes.
- No changes to the vault yet.

**AI actions allowed:** AI may propose classification for each sample note. All proposals are non-authoritative and recorded as AI suggestions.

**AI actions not allowed:** AI MUST NOT write classification metadata into vault notes during this phase.

## 6. Phase 3 — Introduce overlays

**Goal:** Apply the taxonomy to *new work* and to any notes the human is actively using. Do not touch old notes.

**Who:** Human operator.

**Actions:**

1. **Adopt templates for new notes.** Use the templates in `docs/examples/vault-templates/` (defined in PR #1096, pending merge) for new notes going forward. This does not require migrating old notes.

2. **Set up a capture inbox area.** Designate an inbox folder (e.g. `00_Inbox/`) for new `fleeting_capture` notes. Route new captures there before triage.

3. **Create or update area dashboards.** For each active life area, create or update an `area_dashboard` note using the template. Link active projects and references.

4. **Add templates or MOCs for active projects.** For currently active projects, create or update `project_note` artifacts using the template.

5. **Add metadata to notes the human opens anyway.** When the human opens an existing note for any reason, they may optionally add `artifact_class`, `lifecycle`, and `privacy` frontmatter at that time. This is opportunistic, not required.

**Principle:** The overlay approach means new work immediately uses governed semantics, while old notes are left untouched until they are next used.

**AI actions allowed:** AI may suggest classifications and draft frontmatter for notes the human is actively reviewing. All suggestions are non-authoritative proposals.

**AI actions not allowed:** AI MUST NOT bulk-add frontmatter to notes not currently being reviewed.

## 7. Phase 4 — Opportunistic migration

**Goal:** Gradually bring existing notes into alignment with the taxonomy, one note at a time, when touched in normal use.

**Who:** Human operator (with optional AI drafting assistance).

**Trigger:** A note is opened for any reason — editing, reading, linking from a new note, or review.

**At trigger:**
1. The human reads the note.
2. The human (optionally with AI suggestion) decides the appropriate `artifact_class`, `lifecycle`, `authority`, and `privacy`.
3. The human adds or updates frontmatter inline.
4. If the note is a companion for an external artifact (media, scan, email), the human adds a `provenance.source_file` or `provenance.source_kind` pointer.

**This is not a project in itself.** It is a background activity that happens over weeks and months of normal use. There is no deadline and no requirement to classify every note.

**Tracking (optional):** The human may maintain a simple list of "classified this week" to observe coverage over time.

**AI actions allowed:** When a note is open for review, AI may propose frontmatter. The human confirms.

**AI actions not allowed:** AI MUST NOT trigger opportunistic migration on notes not currently being reviewed.

## 8. Phase 5 — Optional automation

**Goal:** Accelerate migration for large batches of notes where the pattern is clear and the risk is low, after manual phases have established confidence.

**Prerequisites:**
- Phase 1–4 complete for a representative sample.
- A clear, human-confirmed classification pattern for the target batch (e.g. "all notes in `04_Operations/Shopping/` are `shopping_list / ephemeral`").
- A dry-run tool that shows exactly what would change without making changes.
- A written dry-run receipt reviewed and approved by the operator.
- A rollback path confirmed (e.g. git commit before automation, or backup).

**Dry-run receipt format:**

```markdown
## Automation dry-run receipt — {{date}}

**Target:** {{folder or pattern}}
**Change:** Add frontmatter `artifact_class: {{class}}`, `lifecycle: {{lifecycle}}`
**Affected notes:** {{count}} files
**Sample of affected notes:**
  - {{path}} — current state: no frontmatter → proposed: {{frontmatter snippet}}
  - {{path}} — current state: {{existing}} → proposed: {{merged}}
**Notes that would be skipped:** {{count}} (already classified, or ambiguous)
**Rollback:** `git checkout -- {{target folder}}`
**Operator approval:** [ ] Confirmed
```

**Only after the operator confirms the receipt** may the automation run.

**AI actions allowed:** AI may draft the automation script, generate the dry-run receipt, and report on results. The human reviews and approves before execution.

**AI actions not allowed:** AI MUST NOT execute the automation without an approved dry-run receipt. AI MUST NOT discard original content during automation.

## 9. Audit receipt

After completing an audit pass (Phase 1 + 2), record the findings in an audit receipt.

```markdown
## Vault audit receipt — {{date}}

**Vault root:** {{path}}
**Total notes:** {{count}}
**Total attachments:** {{count}}
**Sample size:** {{count}} notes

**Rough distribution:**
- {{artifact_class}}: ~{{N%}} of notes
- {{artifact_class}}: ~{{N%}} of notes

**Privacy flags found:**
- Notes with likely financial data: ~{{N}}
- Notes with personal/health data: ~{{N}}
- Notes with AI-generated content unmarked: ~{{N}}

**Existing metadata coverage:**
- Notes with any frontmatter: {{N}}
- Notes with artifact_class already set: {{N}}

**Media files:**
- Total: {{count}}
- Inside vault: {{count}} (recommend moving to media store)
- Already externally stored: {{count}}

**Recommended next steps:**
1. {{Specific action}}
2. {{Specific action}}

**Operator:** {{name}}
**Classification confidence:** Low | Medium | High
**Ready for Phase 3 (overlays)?** Yes / No
```

Store the receipt as `audit/audit-receipt-{{date}}.md`.

## 10. Non-goals

This runbook does **not**:

- migrate vault content automatically,
- implement a migration script,
- require uploading the vault to any cloud service,
- define a specific on-disk folder structure,
- mandate that every note must have frontmatter,
- require a particular Obsidian plugin or tool,
- define runtime validation or enforcement.

## 11. Related documents

- `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md` — artifact classes and axes
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` — field semantics
- `docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md` — media-specific rules (pending merge, PR #1094)
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md` — triage and promotion flows (pending merge, PR #1095)
- `docs/examples/vault-templates/` — template examples for new notes (pending merge, PR #1096)
