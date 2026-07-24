---
name: Support Deterministic Print Output
description: Make every final cockpit section printable from closed or filtered screen state and record the terminal HTML/PDF validation receipt.
task_id: CKM-DB-06
source_anchor: docs/CKM_COCKPIT_DIRECTION_B/README.md :: Verification, validation, and owner-doc promotion
parent_capability: CKM Cockpit Direction B
prerequisites: [CKM-DB-05]
depends_on: [GENERATE_GOVERNED_PROPOSAL_DRAFTS.md]
can_parallelize_with: []
---

# Support Deterministic Print Output

## Purpose

Finish the cockpit with a stable review artifact that includes all evidence-bearing sections even
when screen details are closed or rows are currently filtered.

## What This Task Does

- Add print-only CSS to the same self-contained HTML artifact.
- Force every capability row visible with `[hidden] { display: block !important; }`.
- Override the user-agent closed-details presentation with
  `details > :not(summary) { display: block !important; }`; do not claim CSS mutates `open`.
- Hide filter controls and interactive disclosure glyphs while retaining headings/summaries.
- Prevent avoidable page breaks inside trust, hazard, comparison/refusal, capability, gap, proposal,
  and provenance blocks.
- Preserve visible non-authority, generation identity, projection-input digest, state identity, and
  sorted watermarks on print.
- Produce the terminal deterministic HTML digest and manual PDF inspection receipt for the parent.

## Concretely

The required core print rules are:

```css
@media print {
  [hidden] { display: block !important; }
  details > :not(summary) { display: block !important; }
  .cockpit-filter-controls, noscript { display: none !important; }
}
```

Additional print layout rules may adjust colour, backgrounds, wrapping, and page-break behavior but
cannot remove trust/refusal/provenance text or rely on JavaScript to open details.

## Why This Matters

A PDF generated from a filtered or collapsed screen can silently omit the very caveats needed to
interpret the view. CSS must override presentation state directly, and the final manual receipt must
verify browser output because a string-level CSS assertion cannot prove pagination or disclosure
rendering.

## Acceptance Criteria

- [ ] Print CSS forces filtered capability rows and every closed `details` body visible without changing the `open` attribute or running a second script.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_print_css_reveals_hidden_rows_and_closed_details`
- [ ] Filter controls/disclosure glyphs are omitted on print while semantic summaries, labels, and all source content remain.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_print_hides_controls_not_semantics`
- [ ] Printed content retains the non-authority banner, trust identity, hazards, comparison or refusal, every capability/detail, unfiltered gaps, proposal disclaimers, and provenance footer.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_print_contract_covers_every_final_section`
- [ ] Print rules avoid colour-only meaning and preserve readable wrapping/page-break behavior for long IDs, digests, watermarks, findings, citations, and proposal text.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_print_styles_preserve_text_and_section_integrity`
- [ ] The complete production CLI artifact answers the four fixed owner questions without ranking, trend, cause, forecast, authority, or write affordances.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_answers_fixed_owner_questions_without_authority`
- [ ] The final fixture artifact is byte-deterministic for identical inputs and its SHA-256 digest is recorded on the parent.
  Verify: deterministic HTML digest in the CKM-DB-06 parent handoff receipt
- [ ] A manual PDF generated with rows filtered and all details closed visibly contains every final section/detail and has no clipped/overlapping trust, refusal, citation, or disclaimer text.
  Verify: attached PDF plus manual visual checklist in the CKM-DB-06 parent handoff receipt
- [ ] The terminal handoff resolves owner-doc and transition-debt posture and requests independent parent acceptance; it does not close the parent from the child.
  Verify: CKM-DB-06 delivery receipt on the Direction B parent issue

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_overview_html.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Generate the final fixture artifact twice with the same explicit time and compare SHA-256 digests.
- In a browser, set a zero-result filter, close every `details`, print to PDF, and inspect every item
  in the manual visual checklist before attaching the receipt.

## Out of Scope

- PDF generation library or server
- JavaScript-driven print preparation or a second script
- Persisting screen state
- Hosted sharing, multi-user review, signing, or archival policy
- Parent closure or owner-doc promotion from the child PR

## Related Docs

- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`
- `app/builderops/ckm/overview_html.py`
- `tests/builderops/ckm/test_overview_html.py`

## Related GitHub Issues

Create one terminal child under the Direction B parent, dependency-blocked on CKM-DB-05. Cheapest
acceptable TCD route: **Terra/high** because CSS/test mechanics are bounded but final acceptance
depends on manual visual evidence and complete cross-slice coverage; use Sol/high for the independent
parent-acceptance review if residual omission risk remains.
