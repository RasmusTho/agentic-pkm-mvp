# 2026-07-07 UAT design audit — Companion UI

State: Design source-of-truth for the 2026-07-07 live-UAT design audit remediation set.

## What this is

A journey-based design audit of the Companion UI, run against **live 2026-07-07 UAT captures**
(dev channel, real runtime, Chromium 1440×900), followed by hi-fi before/after redesign mockups
for the four worst offenders. Produced in Claude Design; landed here as the durable design
source-of-truth for the remediation issues.

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

Note: `redesigns.html` is a *mockup artifact* — it uses a CDN icon script and emoji stand-ins
that are mockup-only conveniences. The product implementation must follow the repo design
system (no emoji, no external CDN; vendored/inline assets only).

## Evidence

The 24 UAT screenshots (`00a`–`23`) referenced by the audit live in the Claude Design project
(`audit/screenshots/` in project `73aa49b6-6885-485d-910e-02c6077513c0`), not in the repo —
bulky evidence stays out of git per handoff policy. The audit text names each screenshot it
relies on, and the "before" halves of `redesigns.html` recreate the relevant captures.

## Relationship to prior review rounds

- `2026-06-22-companion-ui-deep-review/` (+ hub issue #2443) is the previous design review
  round. This audit is a fresh pass on the **live runtime** after subsequent delivery waves;
  overlapping themes (rail ambient-until-active, calm degraded grammar) are re-verified here
  against reality, not re-litigated.
