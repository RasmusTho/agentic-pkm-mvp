from pathlib import Path
import re

FORBIDDEN = [
    re.compile(r'^\s*import\s+psycopg\b'),
    re.compile(r'^\s*from\s+psycopg\b'),
    re.compile(r'^\s*from\s+app\.db\b'),
    re.compile(r'^\s*import\s+app\.db\b'),
]

ALLOW_DIRS = (
    'app/stores',
    'app/store',
    'app/db',
    'app/alembic',
    'app/_legacy',
)

ALLOW_FILES = (
    # BuilderOps independent PostgreSQL authority (BCP-01, #3792). This is the
    # dedicated storage adapter behind the domain-neutral control-plane port;
    # callers do not import psycopg or Product app.db through this exception.
    'app/builderops/control_plane/store.py',
    'app/services/outbox.py',
    'app/services/audit.py',
    'app/services/decisions.py',
    'app/services/vault_sync.py',
    'app/search/vector_index.py',
    'app/search/service.py',
    'app/jobs/backfill.py',
    # Decision-receipt log + its projection rebuild/doctor (feat #2969). The
    # receipt log is the canonical judgment record; the `decisions` table is a
    # rebuildable projection. Both read the projection / a bounded objects.uuid
    # lookup directly through conn_rw, the same bounded pattern already allowed
    # for app/services/decisions.py and app/jobs/backfill.py above.
    'app/receipts/decision_receipt_log.py',
    'app/jobs/decisions_projection.py',
    # Slice 4 (#2973): one-time DB->log export of historical decision rows.
    # Same bounded pattern as decisions_projection.py above: reads the
    # `decisions` projection table directly through conn_rw to find rows not
    # yet represented in the receipt log.
    'app/jobs/decisions_export.py',
    # Decision-outcome receipt log + its projection writer (issue #3502). Same
    # bounded pattern as the decision-receipt log / decisions-projection pair
    # above: the vault JSONL receipt is canonical, `decision_outcomes` is a
    # rebuildable projection written only through conn_rw after the receipt is
    # durable. Moved out of app.store (deprecated) into app/receipts/ so the
    # caller no longer touches the deprecated store facade; the projection
    # writer keeps its direct, bounded DB access here rather than routing
    # through app.store.
    'app/receipts/outcome_receipt_projection.py',
    # Episode notes projection rebuild/doctor (ERE-02, #3177). Vault-canonical
    # Episode notes are the SoR; the `episodes` table is a rebuildable projection.
    # Same bounded pattern already allowed for app/jobs/decisions_projection.py above.
    'app/jobs/episodes_projection.py',
    # Episode Resolution Engine tick-runtime state (ERE-04, #3179). Same bounded
    # pattern as app/heimdal/cursor_store.py below: a dedicated key/value state
    # table (`episode_engine_state`: durable vault-activity cursor + open-segment
    # state, rebuildable from the underlying streams), direct connection, no ORM
    # layer to route through.
    'app/episodes/engine_state.py',
    # vault.activity outbox cursor reader (ERE-04, #3179). Bounded topic-scoped
    # SELECT over the `outbox` table strictly after this consumer's own durable
    # position; never touches `delivered_at` (the worker dispatcher's flag).
    # Same bounded read pattern as app/services/outbox.py above.
    'app/episodes/vault_activity_stream.py',
    # episode_ref assignment ledger (ERE-05, #3180). Bounded reads over the
    # rebuildable `episodes` projection + idempotent ON CONFLICT upserts to the
    # `episode_artifact_binding` ledger (migration b7c8d9e0f1a2); same bounded
    # conn_rw pattern as app/episodes/engine_state.py above. episode_ref never
    # touches evidence_role/authority_state (pending is not authority).
    'app/episodes/assignment.py',
    # Episode closure detection + episode.closed emission (ERE-06, #3181). Bounded reads over the
    # rebuildable `episodes` projection (closure candidates) and the `episode_artifact_binding`
    # ledger (bound-artifact count); same bounded conn_rw pattern as app/episodes/assignment.py
    # above. No decay/salience field is ever written -- this module's only writes are the
    # guarded episode-note rewrite (app.episodes.store) and the outbox event.
    'app/episodes/closure.py',
    # Closure-derived retrieval salience decay reader (ERE-06, #3181). A single bounded SELECT
    # over the rebuildable `episodes` projection (which episode ids are closed) at the production
    # retrieve() call site; never a write, same bounded pattern as the entries above. The salience
    # contract's hard law (derived, never persisted) means this module has no write path at all.
    'app/episodes/closure_decay.py',
    # Human re-cut / silence-is-acceptance projection sync (ERE-07, #3182 review fix, mirrors
    # #3181's app/episodes/closure.py entry above). A targeted incremental UPDATE over the
    # rebuildable `episodes` projection issued from the relabel write path itself
    # (_sync_projection_row), keeping it current with an operator's re-cut edits; same bounded
    # conn_rw pattern as app/episodes/closure.py.
    'app/episodes/recut.py',
    # Episode creation -> episodes projection sync (#3532, ERE-02 follow-up, mirrors #3181's
    # app/episodes/closure.py entry above). A targeted incremental INSERT ... ON CONFLICT DO
    # NOTHING over the rebuildable `episodes` projection, issued from the note-creation write
    # path itself (_sync_new_episode_row) right after write_episode_note mints a brand-new
    # note; same bounded conn_rw pattern as app/episodes/closure.py / recut.py.
    'app/episodes/segmenter.py',
    # Standing Questions rebuildable projection (#3329, SQ-02). projection.py owns the
    # read (parse vault Question notes) and write (TRUNCATE + replay in one conn_rw
    # transaction) sides inline -- the same non-deprecated pattern as
    # app/jobs/episodes_projection.py / decisions_projection.py, rather than a separate
    # module under the deprecated app.store package (ADR-0013). Bounded conn_rw use.
    'app/standing_questions/projection.py',
    'app/store/relation_index.py',
    'app/memory_kv/store.py',
    'app/agent/repository.py',
    # #2989: /search now reads the canonical retrieval capability
    # (app.retrieval.capability.retrieve) instead of psycopg/app.db directly;
    # no allowlist entry needed.
    # Health contract reads the live DB reachability probe (ping_postgres) so
    # readiness reflects real dependency health (#2598). It consumes only the
    # bounded SELECT-1 ping, not the data layer.
    'app/health_contract.py',
    # Heimdal observation log + per-consumer cursor store (#3039, Epic #3019
    # slice A2). Same bounded pattern as the outbox/decisions/receipt-log
    # entries above: a dedicated append-only log / cursor table, direct DSN
    # connection, no ORM layer to route through.
    'app/heimdal/observation_log.py',
    'app/heimdal/cursor_store.py',
    'app/heimdal/_backend.py',
    # Consent ledger v0 (#3042, Epic #3019 slice A5). Same bounded pattern as
    # the observation log / cursor store above: a dedicated append-only
    # grants table, direct DSN connection, no ORM layer to route through.
    'app/heimdal/consent_ledger.py',
    # Raw-evidence store (#3025, Epic #3019 slice A6). Same bounded pattern
    # as the observation log / consent ledger above: a dedicated append-only
    # encrypted raw-record table, direct DSN connection, no ORM layer to
    # route through.
    'app/heimdal/raw_store.py',
    # Gated raw-read receipt log (#3027, Epic #3019 slice A7). Same bounded
    # pattern as the raw store above: a dedicated append-only receipt
    # table, direct DSN connection, no ORM layer to route through.
    'app/heimdal/raw_read_gate.py',
    # Hard-retention deletion-receipt log (#3032, Epic #3019 slice A12). Same
    # bounded pattern as the raw-read receipt log above: a dedicated
    # append-only receipt table, direct DSN connection, no ORM layer to
    # route through.
    'app/heimdal/retention.py',
    # Media-admission receipt store (CDLM-01, #4384). Same bounded pattern as
    # the raw-read receipt log above: a dedicated append-only receipt table
    # (heimdal_media_receipt) with a self-contained dual memory/pg backend,
    # direct DSN connection, and fail-loud schema preflight; no ORM layer to
    # route through.
    'app/heimdal/media_receipts.py',
    # Meeting session/segment ledger (CDLM-02, #4385). Same bounded pattern as
    # the media-receipt store above: dedicated migration-owned tables
    # (heimdal_meeting_session/_segment/_segment_conflict) with a
    # self-contained dual sqlite/pg backend, direct DSN connection, and
    # fail-loud schema preflight; no ORM layer to route through.
    'app/heimdal/meeting_ledger.py',
    # YouTube Source Sync durable source registry (YSS-01, #3916). Same bounded
    # pattern as app/heimdal/cursor_store.py above: a dedicated table
    # (acquisition_source_registry) with a self-contained dual memory/pg
    # backend, direct DSN connection, no ORM layer to route through.
    'app/knowledge_acquisition/source_registry.py',
    # YouTube Source Sync durable account-binding registry (YSS-02, #3917). Same
    # bounded pattern as source_registry.py above: a dedicated table
    # (youtube_account_binding) with a self-contained dual memory/pg backend,
    # direct DSN connection, no ORM layer to route through.
    'app/knowledge_acquisition/youtube_account_binding.py',
    # YouTube Source Sync bounded Data API client + daily quota counter (YSS-03,
    # #3918). The HTTP boundary owns one dedicated migration-backed quota table
    # with the same explicit memory/pg backend and fail-loud schema preflight as
    # the adjacent YSS stores; no other Data API caller or persistence path is
    # introduced.
    'app/knowledge_acquisition/youtube_api_client.py',
    # YouTube Source Sync durable acquisition request queue (YSS-04, #3919).
    # Same bounded pattern: a dedicated table (acquisition_requests) with a
    # self-contained dual memory/pg backend, direct DSN connection, no ORM
    # layer to route through.
    'app/knowledge_acquisition/acquisition_requests.py',
)

def _allowed(p: Path) -> bool:
    ps = p.as_posix()
    if ps in ALLOW_FILES:
        return True
    return any(ps == d or ps.startswith(d + '/') for d in ALLOW_DIRS)

def test_no_direct_db_imports():
    offenders = []
    for p in Path('app').rglob('*.py'):
        if _allowed(p):
            continue
        try:
            text = p.read_text(encoding='utf-8')
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith('#'):
                continue
            if any(rx.search(line) for rx in FORBIDDEN):
                offenders.append(f'{p}:{i}: {line.strip()}')
    assert not offenders, 'Direct DB imports are forbidden outside stores/db/alembic.\n' + '\n'.join(offenders)
