State: Design intake receipt, 2026-07-31. Archive of the accepted 2026-07-30 BuilderOps cockpit
design exploration. Supporting design input only — the normalized authority is
`docs/BUILDEROPS_COCKPIT/README.md` and `docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md`.

# Design intake — BuilderOps cockpit exploration 2026-07-30

## What this directory holds

The visual deliverables of the accepted design session, verbatim:

| File | SHA-256 | Role |
|---|---|---|
| `redesigns.html` | `971c1498317fabc7602fa16bb4933ecc0216c1b5325af04a941fafa208e850c9` | The drawn states: Normal (three lenses: bands, graph, one-question-at-a-time), many-at-once (41 threads), empty-true, empty-dead-source, degraded (stale CKM), narrow+200%. CSS-only state switcher (radio + `:has()`); works with JavaScript off; print forces all states open. |
| `cockpit.css` | `524fd3785a501aad9e22407e5006114253e38e8fe4dd12345c823540b0bbedc2` | The exploration's own CSS. Consumes only `var(--*)` tokens from the token sheet; no new values. |
| `colors_and_type.css` | `7d8cdd49f59061f895959159a08e82348e7e02eb8b8ba7426020a50c7fa915b1` | Unmodified copy of the bound Yggdrasil token sheet. Byte-identical to the repo binding source `companion-ui/companion-app/colors_and_type.css`. |

The prototype's UI copy is Swedish (the design session's working language). It is preserved
verbatim because it is the accepted deliverable; altering it would falsify the design receipt. The
shipped surface (`app/web/static/cockpit.html`) is English, per repo language policy.

## What is deliberately not archived here

The session's six prose documents (README with the design-system receipt, open-questions,
state-gallery, edge-states, authority-boundaries, implementation-contracts) are Swedish-language
handoff prose. Per repo language policy and the handoff-artifact rule (bulky handoff packs live
outside the repo), their full text stays in the owner's design pack (Claude Design project
`Yggdrasil Design System` / owner's export archive). Every normative claim they carry has been
normalized in English into:

- `docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md` — every open question and proposed design-system
  extension as an explicit accept/reject decision
- `docs/BUILDEROPS_COCKPIT/README.md` and the task specifications — the accepted behavior

Nothing was accepted silently: if a claim from the prose pack is not in the decisions ledger or a
task spec, it is not accepted.

## Yggdrasil Design Handoff Receipt

- Surface: BuilderOps cockpit registry (`/cockpit` on the existing BuilderOps API host)
- Authority state: design exploration → normalized through this spec directory; the pack itself is
  never authority
- Design system name: `Yggdrasil Design System`
- Design system ID: `f2b13410-af14-4875-8029-445352123f57`
- Selection/attachment mechanism: design system bound to the Claude Design project; live-bound
  `colors_and_type.css`, `_ds_bundle.js`, `_ds_manifest.json` attached under `_ds/` in the session
- Repo token source: `companion-ui/companion-app/colors_and_type.css`
- Token SHA-256: `7d8cdd49f59061f895959159a08e82348e7e02eb8b8ba7426020a50c7fa915b1` (11,027 bytes)
- Token parity: **pass** — pack copy and repo binding source verified byte-identical at intake
  (2026-07-31); the shipped surface's copy is CI-enforced by
  `tests/api/test_cockpit_api.py::test_token_sheet_parity_with_binding_source`
- Output/project: this archive; design session deliverables produced 2026-07-30
- Visual verification: the session validated desktop, narrow+200%, keyboard, print,
  JavaScript-off, empty, degraded, and refused states; token conflicts resolved tokens-over-prose
  (see `DESIGN_DECISIONS.md :: DS-1`)
- Crossing state: Builder-surface crossing — external package kept as supporting design input;
  accepted intent normalized through this specification directory; implementation only from
  bounded Issues (not the Companion UI Crossing B chain)
- Open authority questions: all fifteen intake items closed as explicit decisions in
  `DESIGN_DECISIONS.md`; the only owner-gated remainder is the owner-acceptance receipt contract
  (INV-DG-7), tracked in the spec as out of v1
