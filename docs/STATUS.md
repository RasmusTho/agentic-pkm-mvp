# STATUS — 2025-10-27

Component | Status | Notes
--------- | ------ | -----
Promotion Agent | 🟡 In Progress | Event-driven worker in PER loop; JSONL outbox complete, cooldown/idle/idempotence under test
Indexer | 🟢 Stable | Responds to `review_state` updates → promotion reflected immediately
Outbox / Event Bus | 🟢 Stable | Extended with `promote.*` event types
Settings Schema | 🟢 Validated | New promotion block (cooldown plus move_policy) added to system settings
YAML round-trip (`write_on_diff`) | Stub | CLI helper pending implementation
OTel tracing (Jaeger) | Planned | PER-loop spans instrumented but exporter wiring pending
Merge/Conflict policy | Planned | Deterministic frontmatter/body resolver targeted for v4.4
Outbox broker eval | Planned | Debezium/Kafka prototype queued post-promotion agent launch
