# 2026-07-07 UAT design audit — Companion UI

State: Archived design guidance/input from the 2026-07-07 live-UAT design audit. Not a source of truth for implementation or shipped behavior.

## What this is

A journey-based design audit of the Companion UI, run against **live 2026-07-07 UAT captures**
(dev channel, real runtime, Chromium 1440×900), followed by hi-fi before/after redesign mockups
for the four worst offenders. Produced in Claude Design and retained here as design guidance
for the governed handoff chain; it does not bypass normalized specs, GitHub issues, PRs, or
validation receipts.

## Contents

- `DESIGN_AUDIT.md` — the full audit: journey verdicts (J1–J7), calm audit, trust audit,
  hierarchy/layout findings, confirmed bugs B1–B8, copy replacement table, and the top-10
  changes ranked by leverage.
- `redesigns.html` — hi-fi before/after mockups for top-10 items #1–#4
  (open on a wide viewport; red tag = current state recreated from capture, green tag = proposed):
  1. Panel rail — quiet resting state (audit §2)
  2. Receipts v2 (audit §3.2)
  3. Posture — one source of truth + corrected vault picker (audit §3.1)
  4. Note shell chrome — reserved status slot (audit §4.1)
- `colors_and_type.css` — Yggdrasil design-token sheet the mockups render against.
- `SOURCES.md` — durable source manifest: retained repo artifacts, GitHub delivery receipts,
  unavailable original inputs, and the evidence limits that follow from those gaps.

Note: `redesigns.html` is a *mockup artifact* — it uses a CDN icon script and emoji stand-ins
that are mockup-only conveniences. The product implementation must follow the repo design
system (no emoji, no external CDN; vendored/inline assets only).

## Evidence and authority

See `SOURCES.md` for the durable evidence boundary. The original prompt, UAT report, findings
exports, and 24 screenshots (`00a`–`23`) are not retained in this repository and therefore are
not reproducible repo evidence. Screenshot numbers in the audit are historical capture labels;
the "before" mockups in `redesigns.html` are interpretations, not replacements for the captures.

This package is guidance/input under `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`.
Remediation must flow through the governed chain:

```
handoff package -> normalized spec -> GitHub issue -> PR -> validation receipt
```

For this audit, the normalized executable contracts were hub issue #3360 and child issues
#3361–#3364. Their merged PRs and validation receipts, not this package, govern what shipped.

## Relationship to prior review rounds

- `2026-06-22-companion-ui-deep-review/` (+ hub issue #2443) is the previous design review
  round. This audit is a fresh pass on the **live runtime** after subsequent delivery waves;
  overlapping themes (rail ambient-until-active, calm degraded grammar) are re-verified here
  against reality, not re-litigated.
