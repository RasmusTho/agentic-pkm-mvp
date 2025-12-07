State: Planned / partially implemented. Align carefully with STATUS (SoT v4.10) before applying.
# Agentminne v4.2 – Överblick
Syfte: stödja PER-loop med explicit episodiskt, semantiskt och proceduralt minne som första-klassiga artefakter i AMG/SetDB. SoT v4.2 förtydligar minnesnamnrymder, konsistens och gate-integration.
Mål: låg latens, idempotens, spårbarhet via trace_id och run_id, deterministisk läs/skriv-semantik, enkla UPSERTs.
Icke-mål: långlivad cross-user federation, extern vektordatabas, autoskalning.
Nyheter i 4.2: namngivna scopes (session|object|global), memory policy gates före/efter node, unified adapter API, reflektion som transaktion, retention v4, scorecards för hit-rate och drift.
