# Memory Design (SoT v4.3 plan)

## Syfte
Bevara erfarenhet mellan körningar utan att korrupta sanningsdata.

## Mål
1. Reflektera utfall (PER: Reflect).
2. Lagra episodiskt, semantiskt och procedurellt minne.
3. Ge Reviewer/SetEvaluator data för adaptiva trösklar.

## Modell
| Typ | Scope | Exempel | Lagring |
|---|---|---|---|
| Episodic | Körningsspår | audit + trace_id | Postgres (audit) |
| Semantic | Fakta/klassning | decisions, objects.payload | Postgres + vektor |
| Procedural | Handlingsregler | agentkonfig, policies | AMG-tabeller |

## Arkitektur
MemoryStore API: `put/get/query`. Reflektionssteg skriver `agent_reflections` med score/feedback och kanter mellan objekt.

## Loop
1. Agent `*.done`
2. Reviewer poängsätter
3. MemoryStore skriver feedback-edge
4. Nästa körning hämtar liknande kontext

## Svårigheter
Feedbackloopar, revision/rollback, låg overhead.

## Nästa steg
Schema för `agent_reflections`, PER-Reflect i agenterna, tester i `tests/memory`.
