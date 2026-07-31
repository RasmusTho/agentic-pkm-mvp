---
scope_id: scope:general/retrieval-eval
sphere: general
source_role: human_note
authority_state: draft
evidence_role: background
sensitivity: public
synthetic: true
lang: sv
topic: index_rebuild
---

# Omindexering när vektoridentiteten byts

Varje gång modellen eller dimensionen ändras blir hela den lagrade vektormängden
ogiltig. Det spelar ingen roll att texten är oförändrad — vektorerna är knutna till
den identitet som skapade dem, så en blandning av gamla och nya vektorer ger tyst
felaktig rangordning i stället för ett hårt fel.

Min rutin: frys skrivningarna, kör en full ombyggnad från den kanoniska texten,
och kör sedan en strikt hälsokontroll som vägrar passera om två identiteter
fortfarande samexisterar i lagret. Först därefter släpper jag på trafiken igen.

Det som brukar bita mig är att ombyggnaden tar längre tid än jag tror när
teckenbudgeten per dokument höjs. Längre stycken betyder färre delningar och
bättre vektorer, men varje anrop blir dyrare. Jag mäter alltid om innan jag lovar
ett tidsfönster.
