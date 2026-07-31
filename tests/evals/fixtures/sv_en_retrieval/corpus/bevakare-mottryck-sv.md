---
scope_id: scope:general/retrieval-eval
sphere: general
source_role: human_note
authority_state: draft
evidence_role: background
sensitivity: public
synthetic: true
lang: sv
topic: watcher_backpressure
---

# Mottryck i filbevakaren

Bevakaren läser ändringar snabbare än arbetarna hinner beta av dem. Utan tak växer
kön tills minnet tar slut, och då förlorar jag ändringar som aldrig skrevs ner
någon annanstans.

Lösningen var inte fler arbetare utan en gräns. När kön passerar sitt tak slutar
bevakaren att läsa nytt och låter operativsystemet buffra i stället. Det känns
långsammare men ingenting försvinner, och återhämtningen efter en topp blir
förutsägbar.

Jag loggar kölängd och väntetid per varv. Utan de två talen gissar jag, och mina
gissningar har varit fel varje gång jag jämfört dem med mätningen.
