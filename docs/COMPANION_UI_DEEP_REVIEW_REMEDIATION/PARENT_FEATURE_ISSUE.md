---
name: Parent Feature Issue — Companion UI Deep-Review Remediation
description: Live backlog/validation surface for the deep-review remediation capability.
parent_capability: Companion UI Deep-Review Remediation
github_issue: 2443
lifecycle: open — validation hub (agent:blocked while child slices outstanding)
---

# Parent Feature Issue

The GitHub parent feature issue now **exists and is authoritative** for backlog and validation state:

- **#2443** — feat: Companion UI deep-review remediation (J1–J7 + cross-cutting)
- Labels: `companion-ui`, `agent:blocked` (validation hub, not a direct pickup issue)
- https://github.com/RasmusTho/agentic-pkm-mvp/issues/2443

This file is a local pointer to that issue; the issue body carries the live acceptance checklist and
per-child validation receipts. Do not duplicate validation state here.

## Child issues (execution order)

| Task | GitHub | Wave | Initial label |
|------|--------|------|---------------|
| CUIDR-01 calm-degraded-grammar | #2444 | 1 | agent:ready |
| CUIDR-02 overlay-modal-frame | #2445 | 1 | agent:ready |
| CUIDR-03 rail-ambient-until-active | #2446 | 1 | agent:ready |
| CUIDR-04 edge-job-and-reachability | #2447 | 1 | agent:ready |
| CUIDR-05 front-door-and-copy-hygiene | #2448 | 1 | agent:ready |
| CUIDR-06 mist-ladder-subtractive | #2450 | 2 | agent:blocked |
| CUIDR-07 governed-receipt-first-class | #2451 | 2 | agent:blocked |
| CUIDR-08 blocked-recourse-and-lane-labeling | #2452 | 2 | agent:blocked |
| CUIDR-09 strategic-coldstart-and-rail-palette | #2453 | 3 | agent:needs-human |

## Lifecycle

- Wave-1 children (#2444–#2448) are `agent:ready` and may be picked up in parallel (isolated worktrees).
- Wave-2 children (#2450–#2452) are `agent:blocked` until their Wave-1 prerequisites merge (see each
  spec's `prerequisites`); flip to `agent:ready` on prerequisite merge.
- CUIDR-09 (#2453) is `agent:needs-human` until the owner records the E1/E2 decisions.
- When the parent #2443 closes, reconcile this file, the capability `README.md` state line, and the
  README relationship-to-GitHub-issues section together.
