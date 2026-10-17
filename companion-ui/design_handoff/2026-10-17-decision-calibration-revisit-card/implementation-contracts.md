# Implementation contracts (design-side)

These describe what the card renders. Route behaviour, persistence, and WriteGuard belong to existing authority (`SURFACE_REVISIT_REVIEW_CARD.md`, CAL-01, CAL-02). Where this file and that spec disagree, the spec wins.

## Render state enum
`pending | submitting_answer | answered | submitting_dismiss | dismissed | write_failed | degraded | absent`

Server-derived (from `WorkspaceStateResponse.calibration_revisit`):
- `null` / absent → `absent`
- `degraded: true`, or the projection could not be read → `degraded`
- otherwise → `pending`

Request-lifecycle (local, transient, never persisted): `submitting_answer`, `submitting_dismiss`, and `write_failed`, which comes from a non-2xx route response.
Route-confirmed: `answered` and `dismissed` render only after a 2xx response. The card then re-reads workspace state and renders whatever the server returns.

## Allowed transitions
```
pending            → submitting_answer   (pick activated)
pending            → submitting_dismiss  (Dismiss for now activated)
submitting_answer  → answered            (2xx)
submitting_answer  → write_failed[answer,failed|blocked]   (non-2xx / network)
submitting_dismiss → dismissed           (2xx)
submitting_dismiss → write_failed[dismiss,failed|blocked]
write_failed       → submitting_answer | submitting_dismiss   (user retries; nothing durable existed)
answered | dismissed → (re-read) → server-derived state
any                → server-derived state on workspace refresh
```
`write_failed` variants are not enum values. They are the failure-panel attributes `data-intent` (answer|dismiss) × `data-failure` (failed|blocked), and all four are rendered in the gallery (06–09).

Not allowed: `answered → submitting_answer` (no edit or re-answer), `dismissed → answered` without a re-read, and any `submitting_* → submitting_*`.

## Data attributes (on the card root `section.cal`)
| Attribute | Source |
|---|---|
| `data-state` | Render enum above |
| `data-decision-id` | `decision_id` |
| `data-decided-on` | `decided_on` (ISO date) |
| `data-rung-days` | `rung_days` |
| `data-degraded` | `degraded` |
| `data-outcome` | Answered only, from the route response |
| `aria-busy="true"` | `submitting_*` only |

Forms: `form[data-intent="answer"]` and `form[data-intent="dismiss"]`. Picks: `button[name="outcome"][value][data-outcome]`. Failure panel: `.cal-alert[data-intent][data-failure="failed|blocked"]`.

## Intents
| Intent | Control | Request | Body | Writes |
|---|---|---|---|---|
| answer | 4 picks | `POST /companion/calibration/revisits/{decision_id}/decision` | `{outcome: held|partly_held|did_not_hold|unknown_yet, note?}`. `note` is omitted when empty or whitespace. | CAL-01 append via the existing governed path, WriteGuard at the route |
| dismiss | Dismiss for now | `POST /companion/calibration/revisits/{decision_id}/dismiss` | none | CAL-02 dismissal ledger only. Never an outcome receipt. |

Label → enum: Held → `held`, Partly held → `partly_held`, Did not hold → `did_not_hold`, Not sure yet → `unknown_yet`.

## Client rules
- Never infer state client-side beyond the request lifecycle above. Do not reclassify `degraded`, and do not treat a fetch error as `absent`.
- The note is never sent by dismiss.
- One request in flight per card. Ignore activations while `submitting_*`.
- Without JavaScript, both forms post natively and the server re-renders (PRG). Duplicate-submit protection then depends on the server (see Q3).
