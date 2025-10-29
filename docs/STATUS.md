# STATUS — 2025-10-27

Component | Status | Notes
--------- | ------ | -----
Promotion intent → promoted → index | 🟢 Green | Local and worker paths verified end-to-end
Promotion Agent thin wrapper | 🟢 Green | PER wrapper delegates to queue worker; interval job ready
Optional OTel spans (agent + worker) | 🟡 Added | Instrumented with shim; Jaeger verification pending
CI (GitHub Actions) | 🟡 Limited | Smoke (settings schema + promotion E2E) auto; remaining workflows manual
Indexer | 🟢 Stable | Responds to `review_state` updates → promotion reflected immediately
Outbox / Event Bus | 🟢 Stable | Extended with `promote.*` event types
Settings Schema | 🟢 Validated | Promotion block (cooldown + move_policy) tracked in system settings
YAML round-trip (`write_on_diff`) | Stub | CLI helper pending implementation
Merge/Conflict policy | Planned | Deterministic frontmatter/body resolver targeted for v4.4
Outbox broker eval | Planned | Debezium/Kafka prototype queued post-promotion agent launch
