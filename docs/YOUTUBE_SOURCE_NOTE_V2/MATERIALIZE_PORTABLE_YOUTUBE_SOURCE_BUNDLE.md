---
name: Materialize portable YouTube source bundle
description: Create an identity-keyed vault bundle with a derived transcript and portable lineage manifest.
task_id: YSNV2-06
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Transcript is a derivative
parent_capability: YouTube Source Note v2
prerequisites: [YSNV2-04]
depends_on: [PERSIST_ANCHORED_TRANSCRIPT_AND_EXTRACTIONS.md]
can_parallelize_with: []
---

# Materialize Portable YouTube Source Bundle

## Purpose

Give the owner a browsable, portable source bundle while preserving the machine-side raw record as the only replay input and evidence authority.

## What This Task Does

Using resolved D2/D3 and the D5 versioned-companion mechanism delivered by YSNV2-04, keeps the original review-required note at its flat V1 path and materializes rebuildable `transcript.md` and `source.json` under a configured vault-relative YouTube attachment root. The stable source-identity folder contains immutable content-identity/version directories; a newer acquisition never overwrites bundle members referenced by an older candidate. A new candidate may carry the transcript link at first materialization; upgrading an existing candidate writes the link into a new versioned proposal companion and leaves the original note byte-identical. The bundle resolves all metadata-bundle fields in their valid top-level shapes.

## Concretely

The top attachment subfolder key is stable source identity, not title or content identity; beneath it, each immutable content identity/version gets its own directory containing `transcript.md`, `source.json`, and any retained frames. The flat display note may be renamed. The YouTube plugin/add-on owns the validated vault-relative `youtube_attachment_root` setting, defaulting to `Sources/YouTube/_attachments`. Transcript anchors are time-derived and mirrored with segment identifiers in that version's manifest. `transcript.md` declares derived/rebuildable/reference standing, cannot become replay input, and is linked from the synthesis/evidence-and-lineage surface of the newly materialized candidate or D5 versioned proposal companion.

## Why This Matters

Portable reading artifacts should stay useful after copying the vault, while upstream caption changes must neither fork the human-facing location nor make an older candidate resolve against newer evidence.

## Acceptance Criteria

- [ ] Attachment identity is title-independent; content-identity updates do not fork the attachment folder or overwrite the flat candidate note.
  Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_configured_attachment_root_is_source_identity_keyed_and_note_is_non_destructive`.
- [ ] Each content identity/version has immutable bundle members beneath the stable source folder; a newer version cannot overwrite or retarget an older candidate's transcript, manifest, anchors, or retained-frame links.
  Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_bundle_members_are_immutable_and_versioned_by_content_identity`.
- [ ] The configured attachment root is vault-relative, defaults safely, and rejects path traversal or an absolute path.
  Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_youtube_attachment_root_is_configurable_and_vault_relative`.
- [ ] The vault transcript is a rebuildable derived reference with time-derived anchors; replay reads raw instead.
  Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_transcript_projection_is_anchored_derived_and_never_replay_input`.
- [ ] Every newly materialized candidate or D5 versioned proposal companion links its vault transcript from the synthesis/evidence-and-lineage surface; an existing original candidate is never rewritten to add the link.
  Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_note_links_derived_transcript_from_synthesis_and_lineage`.
- [ ] `source.json` preserves content identity, stage/version, lineage, and resolves valid top-level metadata-bundle fields including object-form `scope_binding`.
  Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_bundle_manifest_validates_resolved_metadata_bundle`.
- [ ] Existing flat V1 candidate notes remain byte-identical and in place; bundle upgrades use a D5 versioned proposal companion while attachments use the configured root.
  Verify: `tests/knowledge_acquisition/test_youtube_source_bundle.py::test_existing_candidate_bundle_upgrade_uses_versioned_companion_without_note_mutation`.

## How to Verify (Pre-Merge)

- Run the seven named focused tests.
- Validate manifest fixtures with `schemas/metadata-bundle.schema.json` and a resolved `scope_binding` object.

## Out of Scope

Source-media acquisition and sibling upgrade behavior.

## Related Docs

- `docs/architecture/metadata-bundle.md :: Required rules`
- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback`
- `docs/CONTEXTUALIZATION_LAYER/COMPANION_NOTE_PATTERN.md`

## Related GitHub Issues

Draft issue type: `type:task`, `prio:high`, `agent:blocked` pending YSNV2-04; D2/D3 are resolved and D5 supplies the required non-destructive upgrade seam. SBS class: Product/Runtime. Recommended capability: Sol/xhigh; durable configured-path, provenance, and replay semantics require high capability.
