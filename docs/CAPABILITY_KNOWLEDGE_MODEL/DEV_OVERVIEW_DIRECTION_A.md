State: Implemented by issue #3689; delivery tracked by its implementation PR.
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
- no cross-dimension aggregate or maturity-band presentation; the per-dimension vector is the collapsed-row display;
- explicit `node: confirmed` lifecycle wording;
- explicit explanatory prose in expanded details that names assessment availability, stale-relative-to-evidence state, and candidate-evidence share without presenting absence as zero;
- capability↔gap fragment links and grouped gap presentation;
- visible focus, disclosure, narrow-viewport, zoom, and non-color affordances.

The renderer signature remains `render_overview_html(store) -> str`. Store reads remain read-only and rendering remains deterministic. Verify: CKM11 acceptance criterion 11.

## CKM11-STATIC-CONTRACT

The output remains one self-contained HTML file with inline CSS, native semantic HTML, and no JavaScript, remote fonts, images, stylesheets, or other network references. Verify: CKM11 acceptance criterion 8. Missing-database behavior is unchanged and rendering is deterministic. Verify: CKM11 acceptance criterion 11. Missing assessment is rendered as unavailable (`—`), never as `0.00` or `0.0%`. Candidate and confirmed evidence remain visibly distinct. Verify: CKM11 acceptance criteria 2, 3, and 12.

Every color signal has a text or shape twin: trust states use named chips; candidate share uses a named percentage; unassessed uses a dash plus accessible text; evidence-starved uses a dotted treatment plus citation count. Verify: CKM11 acceptance criteria 1, 2, 3, and 10.

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

The legend spells out every mapping. Verify: CKM11 acceptance criterion 7. Each capability always exposes seven cells. A scored cell uses a proportional fill; an evidence-starved zero uses a dotted warning treatment; an unavailable assessment uses `—` without a score/fill variable. Verify: CKM11 acceptance criterion 2. The cell group has a combined accessible label rather than seven tab stops. Verify: CKM11 acceptance criterion 10.

## CKM11-ACCEPTANCE

1. Stale and low-confidence markers are descendants of the capability `summary`, so they remain visible while collapsed. Verify: `tests/builderops/ckm/test_overview_html.py::test_honesty_markers_render`
2. Every collapsed capability renders exactly seven dimension cells: scored cells expose proportional fill values, evidence-starved zeroes use the dotted state, and unavailable cells render `—` without a score/fill value. Verify: `tests/builderops/ckm/test_overview_html.py::test_dimension_cells_render_three_states_and_proportional_fill`
3. Candidate-share summary markup is absent at zero and present with a percentage above zero. Verify: `tests/builderops/ckm/test_overview_html.py::test_candidate_chip_conditional`
4. Findings for known capabilities link to their capability fragments, and capabilities with findings link back to grouped gap fragments. Verify: `tests/builderops/ckm/test_overview_html.py::test_gap_capability_crosslinks`
5. The collapsed capability summary renders no cross-dimension aggregate or maturity band: no `min` aggregate chip, `band-*` class, `data-aggregate-band` attribute, or band label. Verify: `tests/builderops/ckm/test_overview_html.py::test_aggregate_demoted_label`
6. The generated-projection provenance banner precedes the capability map and the projection footer contract remains present. Verify: `tests/builderops/ckm/test_overview_html.py::test_provenance_banner_precedes_map_and_footer_remains`
7. The legend contains all seven full dimension names and explains scored, evidence-starved, and unassessed cells. Verify: `tests/builderops/ckm/test_overview_html.py::test_legend_dimension_mapping`
8. Output remains self-contained with no script elements, executable inline handlers, or external/network references. Verify: `tests/builderops/ckm/test_overview_html.py::test_no_scripts_or_external_references`
9. An empty store renders the provenance banner, a `0 capabilities` trust summary, empty map and gap states, and the footer. Verify: `tests/builderops/ckm/test_overview_html.py::test_empty_store_page_state`
10. Native disclosure/link semantics, visible focus rules, plus/minus disclosure affordance, relative typography, non-color state labels, unique citation summaries, and the narrow-viewport layout contract are present in the generated artifact. Verify: `tests/builderops/ckm/test_overview_html.py::test_accessibility_and_responsive_contract`; visual behavior at desktop, expanded-row, 390×844, and 200% zoom-equivalent widths: parent #3138 visual-review receipt explicitly naming all four reviewed states
11. Two renders over unchanged store state are byte-identical, the renderer does not mutate the store, and the CLI continues to reject a missing database without creating it. Verify: `tests/builderops/ckm/test_overview_html.py::test_pure_render_over_fixture_graph`; `tests/builderops/ckm/test_overview_html.py::test_cli_rejects_missing_database_without_creating_it`
12. Lifecycle status is labeled `node: {lifecycle}` so node confirmation cannot be read as evidence confirmation, and candidate/confirmed evidence retain distinct named markup. Verify: `tests/builderops/ckm/test_overview_html.py::test_node_lifecycle_and_evidence_confirmation_are_distinct`
13. Expanded capability details state whether an assessment is available, whether it is stale relative to evidence, and the candidate-evidence share in prose; unavailable assessment is described as unavailable rather than zero. Verify: `tests/builderops/ckm/test_overview_html.py::test_expanded_honesty_prose_names_trust_state`

## CKM11-ACCESSIBILITY

- Use native `details`, `summary`, and fragment links in document order. Verify: CKM11 acceptance criterion 10.
- Preserve visible `:focus-visible` outlines on summaries and links. Verify: CKM11 acceptance criterion 10.
- Provide a visible plus/minus disclosure affordance without motion. Verify: CKM11 acceptance criterion 10.
- Use system font stacks and relative units; avoid horizontal scrolling at 390 px and at 200% zoom-equivalent widths. Verify: CKM11 acceptance criterion 10 plus parent #3138 visual-review receipt.
- Give every collapsed trust signal a non-color label. Verify: CKM11 acceptance criteria 1 and 10.
- Use unique expanded disclosure labels such as `Citations — test completeness (0)`. Verify: CKM11 acceptance criterion 10.

## CKM11-OUT-OF-SCOPE

No filters, search, sort, comparison mode, URL state, evolution timeline, print expansion, JavaScript, hosting, Companion UI integration, CLI semantics, store changes, scoring changes, or evidence-model changes. Those are Direction B candidates and require observed owner need plus a separate contract.

## Direction B amendment

The default Direction A output remains byte-deterministic and script-free. Opt-in cockpit output may
contain exactly one inline script that only enables its disabled-first capability-map filters, reads
server-rendered filter tokens, toggles capability-row `hidden` state, and updates the filter count.
It does not change CKM authority, persist state, access a network, or affect trust, hazards,
comparison/refusal, subsystem counts, gaps, proposals, provenance, or the footer.

## CKM11-VALIDATION

Run the focused renderer suite, standard lint/type/test baseline, and generate the overview against the live repository-backed CKM store. Capture desktop, expanded-row, 390×844, and 200%-zoom-equivalent views for visual comparison. Post the delivered child receipt and the review artifact on parent #3138; #3138 remains the owner-validation hub and is never a pickup issue.
