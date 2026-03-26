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
PROMOTE_ORPHAN_OVERRIDE = "promote.orphan.override"
PROMOTION_DECISION_PENDING = "promotion.pending_move"
PROMOTE_SKIP_MOVE = "promote.skip.move"

PANEL_INTENT_CREATED = "panel.intent.created"
PANEL_INTENT_EXECUTED = "panel.intent.executed"
PANEL_ACTION_LOGGED = "panel.action.logged"
PANEL_LOG_CREATED = "panel.log.created"
PANEL_SCAN_REQUESTED = "panel.scan.requested"

WATCHER_RUN = "watcher.run"

ASK_QUERY_RECEIVED = "ask.query.received"
JOBS_BACKFILL_DONE = "jobs.backfill.done"
RELATION_MISSING = "relation.missing"

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
    "PROMOTE_ORPHAN_OVERRIDE",
    "PROMOTION_DECISION_PENDING",
    "PROMOTE_SKIP_MOVE",
    "PANEL_INTENT_CREATED",
    "PANEL_INTENT_EXECUTED",
    "PANEL_ACTION_LOGGED",
    "PANEL_LOG_CREATED",
    "PANEL_SCAN_REQUESTED",
    "WATCHER_RUN",
    "ASK_QUERY_RECEIVED",
    "JOBS_BACKFILL_DONE",
    "RELATION_MISSING",
]
