State: Target-state presentation specification for the CKM Development Overview; not yet implemented.
Doc role: Design specification
Authority: Owns the bounded Direction A presentation contract for the generated CKM overview. Subordinate to ADR-0057 and `DEV_OVERVIEW_HTML_PROJECTION.md`; it changes no CKM data, scoring, or authority semantics.
Owner: BuilderOps governance
Temporal class: operational (implementation-ready)
Last reviewed: 2026-07-14

# CKM Development Overview — Direction A

This specification normalizes the owner-requested Claude Design response for the CKM Development Overview. Direction A is a presentation-only refinement of the existing generated, static HTML projection. It remains a standalone BuilderOps artifact: it is not a Companion UI plugin and does not introduce a hosted runtime surface.

Design provenance: Claude Design project `84f3df9c-cf63-4c0d-9fb9-ed8ec3dc1bc0`, imported 2026-07-14. The reviewed prototype `design-output/direction-a-prototype.html` had SHA-256 `5cfd1a13a99a4384519cd610289f6339fcfb45cada280e91656482afc4e4e9eb`. This document is the repo-governed implementation contract; the external design package is supporting material, not source of truth.

## CKM11-SCOPE

Refine `app/builderops/ckm/overview_html.py` so a reader can judge trust and maturity from collapsed capability rows without mistaking absence for a zero score. Add:

- a provenance banner and compact trust summary;
- a complete seven-dimension legend and aligned column rail;
- collapsed-row stale, low-confidence, candidate-share, and gap markers;
- scored, evidence-starved, and unassessed dimension-cell states;
- a subordinate aggregate labeled `min`, plus text-and-shape maturity-band encoding;
- explicit `node: confirmed` lifecycle wording;
- honest explanatory prose in expanded details;
- capability↔gap fragment links and grouped gap presentation;
- visible focus, disclosure, narrow-viewport, zoom, and non-color affordances.

The renderer signature remains `render_overview_html(store) -> str`. Store reads remain read-only and rendering remains deterministic.

## CKM11-STATIC-CONTRACT

The output remains one self-contained HTML file with inline CSS, native semantic HTML, and no JavaScript, remote fonts, images, stylesheets, or other network references. Missing or invalid database behavior is unchanged. Missing assessment is rendered as unavailable (`—` / `min —`), never as `0.00` or `0.0%`. Candidate and confirmed evidence remain visibly distinct.

Every color signal has a text or shape twin: maturity band uses dot plus word; trust states use named chips; candidate share uses a named percentage; unassessed uses a dash plus accessible text; evidence-starved uses a dotted treatment plus citation count.

## CKM11-DIMENSIONS

The collapsed vector keeps the declared order and uses these abbreviations:

| Label | Dimension |
| --- | --- |
| FUN | functional completeness |
| TST | test completeness |
| DOC | documentation quality |
| INT | integration completeness |
| OPS | operational readiness |
| ARC | architectural stability |
| REQ | requirement coverage |

The legend spells out every mapping. Each capability always exposes seven cells. A scored cell uses a proportional fill; an evidence-starved zero uses a dotted warning treatment; an unavailable assessment uses `—` without a score/fill variable. The cell group has a combined accessible label rather than seven tab stops.

## CKM11-ACCEPTANCE

1. Stale and low-confidence markers are descendants of the capability `summary`, so they remain visible while collapsed. Verify: `tests/builderops/ckm/test_overview_html.py::test_honesty_markers_render`
2. Every collapsed capability renders exactly seven dimension cells, and unavailable cells render `—` without a score/fill value. Verify: `tests/builderops/ckm/test_overview_html.py::test_unassessed_cells_render_dash`
3. Candidate-share summary markup is absent at zero and present with a percentage above zero. Verify: `tests/builderops/ckm/test_overview_html.py::test_candidate_chip_conditional`
4. Findings for known capabilities link to their capability fragments, and capabilities with findings link back to grouped gap fragments. Verify: `tests/builderops/ckm/test_overview_html.py::test_gap_capability_crosslinks`
5. The aggregate is labeled `min {value}` or `min —` and is never an anonymous summary numeral. Verify: `tests/builderops/ckm/test_overview_html.py::test_aggregate_demoted_label`
6. The generated-projection provenance banner precedes the capability map and the projection footer contract remains present. Verify: `tests/builderops/ckm/test_overview_html.py::test_projection_footer_always_present`
7. The legend contains all seven full dimension names and explains scored, evidence-starved, and unassessed cells. Verify: `tests/builderops/ckm/test_overview_html.py::test_legend_dimension_mapping`
8. Output remains self-contained with no scripts or external references. Verify: `tests/builderops/ckm/test_overview_html.py::test_no_external_references`
9. An empty store renders the provenance banner, a `0 capabilities` trust summary, empty map and gap states, and the footer. Verify: `tests/builderops/ckm/test_overview_html.py::test_empty_store_page_state`

## CKM11-ACCESSIBILITY

- Use native `details`, `summary`, and fragment links in document order.
- Preserve visible `:focus-visible` outlines on summaries and links.
- Provide a visible plus/minus disclosure affordance without motion.
- Use system font stacks and relative units; avoid horizontal scrolling at 390 px and at 200% zoom-equivalent widths.
- Give every collapsed trust signal a non-color label and every maturity band a dot plus text.
- Use unique expanded disclosure labels such as `Citations — test completeness (0)`.

## CKM11-OUT-OF-SCOPE

No filters, search, sort, comparison mode, URL state, evolution timeline, print expansion, JavaScript, hosting, Companion UI integration, CLI semantics, store changes, scoring changes, or evidence-model changes. Those are Direction B candidates and require observed owner need plus a separate contract.

## CKM11-VALIDATION

Run the focused renderer suite, standard lint/type/test baseline, and generate the overview against the live repository-backed CKM store. Capture desktop, expanded-row, and 390×844 views for visual comparison. Post the delivered child receipt and the review artifact on parent #3138; #3138 remains the owner-validation hub and is never a pickup issue.
