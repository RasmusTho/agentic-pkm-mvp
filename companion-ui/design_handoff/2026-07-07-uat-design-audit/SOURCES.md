# Source manifest — 2026-07-07 UAT design audit

This manifest records what is durably available and what was not retained. It does not upgrade
this handoff package from design guidance/input to implementation or runtime authority.

## Durable repository and GitHub records

- Audit package introduction: PR [#3359](https://github.com/RasmusTho/agentic-pkm-mvp/pull/3359), merged as `cfb230bf1bd9481438ef944560239475b3c4b52b`.
- Governance repair contract: issue [#3431](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3431).
- Normalized remediation hub: issue [#3360](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3360).
- Normalized executable issues and their linked PR/validation receipts:
  - posture single source: [#3361](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3361)
  - quiet panel rail: [#3362](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3362)
  - Receipts v2: [#3363](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3363)
  - note-shell status slot: [#3364](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3364)
- Retained package artifacts: `README.md`, `DESIGN_AUDIT.md`, `redesigns.html`, and
  `colors_and_type.css` in this directory.

GitHub issues, merged PRs, tests, and validation receipts are the durable delivery evidence. The
audit narrative and mockups remain design guidance only.

## Inputs not retained as durable evidence

The following inputs named by the original audit were not checked into this repository and no
stable external receipt was preserved for them:

- original Claude Design audit prompt
- original UAT report
- original findings exports (two JSON files)
- 24 UAT screenshots, historically labelled `00a`–`23`

The audit no longer cites the missing filenames as verifiable sources. Screenshot labels remain in
`DESIGN_AUDIT.md` only as historical references to the author's review. The mockups recreate selected
states but are interpretations, not source captures.

## Consumption rule

Use this package only as input to the governed chain defined by
`companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`:

```
handoff package -> normalized spec -> GitHub issue -> PR -> validation receipt
```

Do not treat an audit assertion or mockup as binding when it conflicts with a normalized issue,
owner document, shipped code/test evidence, or a validation receipt.
