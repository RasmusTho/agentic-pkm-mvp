"""Central registry of structured event type strings."""

INGEST_OBJECT_CREATED = "ingest.object.created"
INGEST_OBJECT_UPDATED = "ingest.object.updated"
INGEST_OBJECT_METADATA = "ingest.object.metadata"
INGEST_OBJECT_DELETED = "ingest.object.deleted"
INGEST_NORMALIZE_DONE = "ingest.normalize.done"
INGEST_CHUNK_DONE = "ingest.chunk.done"
INGEST_INDEX_DONE = "ingest.index.done"
INGEST_VAULT_CHANGED = "ingest.vault.changed"
PANEL_SCAN_REQUESTED = "panel.scan.requested"
INDEX_OBJECT_EMBEDDED = "index.object.embedded"
INDEX_EMBEDDING_FAILED = "index.embedding.failed"
TEXT_CHUNK_CREATED = "text.chunk.created"
CLEANUP_DONE = "cleanup.done"

REASONING_VALIDATION_ERROR = "reasoning.validation.error"
REASONING_CLAIM_ADDED = "reasoning.claim.added"
REASONING_INFERENCE_ADDED = "reasoning.inference.added"

PLANNER_PLAN_CREATED = "planner.plan.created"
PLANNER_PLAN_ERROR = "planner.plan.error"
PLANNER_PLAN_FALLBACK = "planner.plan.fallback"

ORCHESTRATOR_PLAN_INVALID = "orchestrator.plan.invalid"
ORCHESTRATOR_PLAN_ERROR = "orchestrator.plan.error"
ORCHESTRATOR_STEP_STARTED = "orchestrator.step.started"
ORCHESTRATOR_STEP_FINISHED = "orchestrator.step.finished"
ORCHESTRATOR_STEP_ERROR = "orchestrator.step.error"
ORCHESTRATOR_STEP_RETRY = "orchestrator.step.retry"
ORCHESTRATOR_STEP_RETRY_EXHAUSTED = "orchestrator.step.retry.exhausted"
ORCHESTRATOR_COMPENSATION_STARTED = "orchestrator.compensation.started"
ORCHESTRATOR_COMPENSATION_STEP_COMPLETED = "orchestrator.compensation.step.completed"
ORCHESTRATOR_COMPENSATION_STEP_FAILED = "orchestrator.compensation.step.failed"
ORCHESTRATOR_ROLLED_BACK = "orchestration.rolled_back"
MCP_TOOL_CALL_STARTED = "mcp.tool.call.started"
MCP_TOOL_CALL_FINISHED = "mcp.tool.call.finished"

AGENT_REQUEST_CREATED = "agent.request.created"
AGENT_RESPONSE_CREATED = "agent.response.created"
AGENT_ERROR_CREATED = "agent.error.created"

CURATION_CLASSIFY_DONE = "curation.classify.done"
CURATION_REVIEW_DONE = "curation.review.done"
CURATION_DEDUPE_DONE = "curation.dedupe.done"
CURATION_CITATION_CHECK_DONE = "curation.citation_check.done"
CURATION_CITATION_CHECKED = "curation.citation.checked"
CURATION_CITATION_SKIP = "curation.citation.skip"

PROMOTION_EVALUATE_DONE = "promotion.evaluate.done"
PROMOTION_PROJECT_DONE = "promotion.project.done"
PROMOTION_PROJECT_SKIP = "promotion.project.skip"
PROMOTION_PROJECT_MEMBERSHIP_UPSERT = "promotion.project.membership.upsert"
PROMOTION_ORPHAN_OVERRIDE = "promotion.orphan.override"

PROMOTE_INTENT_CREATED = "promote.intent.created"
PROMOTE_AGENT_PLAN = "promote.agent.plan"
PROMOTE_AGENT_RUN = "promote.agent.run"
PROMOTE_SKIP_MISSING = "promote.skip.missing"
PROMOTE_SKIP_RELATIONS = "promote.skip.relations"
PROMOTE_SKIP_ORPHAN = "promote.skip.orphan"
PROMOTE_SKIP_DECODE = "promote.skip.decode"
PROMOTE_ERROR = "promote.error"
PROMOTE_DONE = "promote.done"
PROMOTION_TRANSITION_APPLIED = "promotion.transition.applied"
PROMOTE_ORPHAN_OVERRIDE = "promote.orphan.override"
PROMOTION_DECISION_PENDING = "promotion.pending_move"
PROMOTE_SKIP_MOVE = "promote.skip.move"

PANEL_INTENT_CREATED = "panel.intent.created"
PANEL_INTENT_EXECUTED = "panel.intent.executed"
PANEL_ACTION_TRIGGERED = "panel.action.triggered"
PANEL_ACTION_LOGGED = "panel.action.logged"
PANEL_ACTION_BLOCKED = "panel.action.blocked"
PANEL_LOG_CREATED = "panel.log.created"
PANEL_SCAN_REQUESTED = "panel.scan.requested"

NOTE_MOVE_WORKBENCH = "note.move.workbench"

WATCHER_RUN = "watcher.run"

SYNC_LATENCY_SUMMARY = "sync.latency.summary"

ASK_QUERY_RECEIVED = "ask.query.received"
JOBS_BACKFILL_DONE = "jobs.backfill.done"
RELATION_MISSING = "relation.missing"

SETTINGS_WRITE_RECEIPT = "settings.write.receipt"

# Knowledge Acquisition refinement-pipeline stage events (KA-06, #2801).
# Stage-transition lineage/audit events on the existing DB outbox. KA-06 left
# them deliberately unconsumed (lineage/audit only); KA-07 (#3107) added the
# first consumer route in `outbox_worker._dispatch_topic`
# (`handle_knowledge_acquisition_stage_completed` /
# `handle_knowledge_acquisition_stage_dead_lettered`) with a bounded, minimal
# downstream action -- NOT the triage engine (see docs/EVENTS.md ::
# Knowledge Acquisition stage events, and
# docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md § Stage
# execution model / § Lineage and replay). Because they are now dispatched,
# KA-07 also registered their KERNEL-08 topic schemas
# (`schemas/events/knowledge_acquisition.stage.{completed,dead_lettered}.v1.schema.json`),
# so `emit_stage_completed` / `emit_stage_dead_letter` now hard-validate their
# payloads against those schemas and get `meta.payload_schema` stamped at write
# time via `write_outbox_event`.
KNOWLEDGE_ACQUISITION_STAGE_COMPLETED = "knowledge_acquisition.stage.completed"
KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED = "knowledge_acquisition.stage.dead_lettered"

# Heimdal entity register v0 mutation events (Epic #3019 slice A1, #3038).
# Register mutations (mint / merge / split / redirect-fold) are audit/lineage
# events on the existing DB outbox, mirroring the Knowledge Acquisition stage
# events above: NOT dispatched commands (no `outbox_worker._dispatch_topic`
# branch, no topic-schema registration) — they record that a register
# mutation happened, per FABLE_COMPANION.md §3.2 ("register mutations are
# themselves receipted events"). Canonical identity storage is the `.md`
# entity note (`app/heimdal/entity_register.py`); these events are the
# auditable record of *how* the note changed, never a parallel store.
HEIMDAL_REGISTER_ENTITY_MINTED = "heimdal.register.entity.minted"
HEIMDAL_REGISTER_ENTITY_MERGED = "heimdal.register.entity.merged"
HEIMDAL_REGISTER_ENTITY_SPLIT = "heimdal.register.entity.split"
HEIMDAL_REGISTER_ENTITY_REDIRECT_RESOLVED = "heimdal.register.entity.redirect_resolved"

# Heimdal event contract schemas (Epic #3019 slice A4, #3041).
#
# `HEIMDAL_OBSERVATION_PUBLISHED` is the cross-constituent seam topic (build-now,
# FABLE_COMPANION §11#3): the published, minimized, attributed observation event
# that Mimer and future constituents consume, published via
# `app.heimdal.publish.publish_observation` (A2, #3039) onto the append-only
# observation log (`app.heimdal.observation_log`, A2). Its payload schema is
# registered at `schemas/events/heimdal.observation.published.v1.schema.json`
# and validated via `app.events.topic_schema_registry.validate_topic_payload`
# (KERNEL-08 machinery, reused verbatim -- not forked).
#
# `HEIMDAL_CONSENT_GRANTED` / `HEIMDAL_CONSENT_REVOKED` / `HEIMDAL_OBSERVATION_CORRECTED`
# are **contract-stubs** per FABLE_COMPANION §11#3: schema-representable now,
# no runtime producer/consumer lands with this slice. `corrected` carries
# `supersedes` (§3.5); consent grant/revoke runtime is the consent ledger
# (A5, out of scope here). Like the register-mutation events above, none of
# these four topics are dispatched commands -- they are not branched on in
# `app.workers.outbox_worker._dispatch_topic` and are consumed only via the
# Heimdal observation log / publish path, never the shared DB `outbox` table.
HEIMDAL_OBSERVATION_PUBLISHED = "heimdal.observation.published"
HEIMDAL_CONSENT_GRANTED = "heimdal.consent.granted"
HEIMDAL_CONSENT_REVOKED = "heimdal.consent.revoked"
HEIMDAL_OBSERVATION_CORRECTED = "heimdal.observation.corrected"

__all__ = [
    "INGEST_OBJECT_CREATED",
    "INGEST_OBJECT_UPDATED",
    "INGEST_OBJECT_METADATA",
    "INGEST_OBJECT_DELETED",
    "INGEST_NORMALIZE_DONE",
    "INGEST_CHUNK_DONE",
    "INGEST_INDEX_DONE",
    "INGEST_VAULT_CHANGED",
    "PANEL_SCAN_REQUESTED",
    "INDEX_OBJECT_EMBEDDED",
    "INDEX_EMBEDDING_FAILED",
    "TEXT_CHUNK_CREATED",
    "CLEANUP_DONE",
    "REASONING_VALIDATION_ERROR",
    "REASONING_CLAIM_ADDED",
    "REASONING_INFERENCE_ADDED",
    "PLANNER_PLAN_CREATED",
    "PLANNER_PLAN_ERROR",
    "PLANNER_PLAN_FALLBACK",
    "ORCHESTRATOR_PLAN_INVALID",
    "ORCHESTRATOR_PLAN_ERROR",
    "ORCHESTRATOR_STEP_STARTED",
    "ORCHESTRATOR_STEP_FINISHED",
    "ORCHESTRATOR_STEP_ERROR",
    "ORCHESTRATOR_STEP_RETRY",
    "ORCHESTRATOR_STEP_RETRY_EXHAUSTED",
    "ORCHESTRATOR_COMPENSATION_STARTED",
    "ORCHESTRATOR_COMPENSATION_STEP_COMPLETED",
    "ORCHESTRATOR_COMPENSATION_STEP_FAILED",
    "ORCHESTRATOR_ROLLED_BACK",
    "MCP_TOOL_CALL_STARTED",
    "MCP_TOOL_CALL_FINISHED",
    "AGENT_REQUEST_CREATED",
    "AGENT_RESPONSE_CREATED",
    "AGENT_ERROR_CREATED",
    "CURATION_CLASSIFY_DONE",
    "CURATION_REVIEW_DONE",
    "CURATION_DEDUPE_DONE",
    "CURATION_CITATION_CHECK_DONE",
    "CURATION_CITATION_CHECKED",
    "CURATION_CITATION_SKIP",
    "PROMOTION_EVALUATE_DONE",
    "PROMOTION_PROJECT_DONE",
    "PROMOTION_PROJECT_SKIP",
    "PROMOTION_PROJECT_MEMBERSHIP_UPSERT",
    "PROMOTION_ORPHAN_OVERRIDE",
    "PROMOTE_INTENT_CREATED",
    "PROMOTE_AGENT_PLAN",
    "PROMOTE_AGENT_RUN",
    "PROMOTE_SKIP_MISSING",
    "PROMOTE_SKIP_RELATIONS",
    "PROMOTE_SKIP_ORPHAN",
    "PROMOTE_SKIP_DECODE",
    "PROMOTE_ERROR",
    "PROMOTE_DONE",
    "PROMOTION_TRANSITION_APPLIED",
    "PROMOTE_ORPHAN_OVERRIDE",
    "PROMOTION_DECISION_PENDING",
    "PROMOTE_SKIP_MOVE",
    "PANEL_INTENT_CREATED",
    "PANEL_INTENT_EXECUTED",
    "PANEL_ACTION_TRIGGERED",
    "PANEL_ACTION_LOGGED",
    "PANEL_ACTION_BLOCKED",
    "PANEL_LOG_CREATED",
    "PANEL_SCAN_REQUESTED",
    "NOTE_MOVE_WORKBENCH",
    "WATCHER_RUN",
    "SYNC_LATENCY_SUMMARY",
    "ASK_QUERY_RECEIVED",
    "JOBS_BACKFILL_DONE",
    "RELATION_MISSING",
    "SETTINGS_WRITE_RECEIPT",
    "KNOWLEDGE_ACQUISITION_STAGE_COMPLETED",
    "KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED",
    "HEIMDAL_REGISTER_ENTITY_MINTED",
    "HEIMDAL_REGISTER_ENTITY_MERGED",
    "HEIMDAL_REGISTER_ENTITY_SPLIT",
    "HEIMDAL_REGISTER_ENTITY_REDIRECT_RESOLVED",
    "HEIMDAL_OBSERVATION_PUBLISHED",
    "HEIMDAL_CONSENT_GRANTED",
    "HEIMDAL_CONSENT_REVOKED",
    "HEIMDAL_OBSERVATION_CORRECTED",
]
