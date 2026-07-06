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
