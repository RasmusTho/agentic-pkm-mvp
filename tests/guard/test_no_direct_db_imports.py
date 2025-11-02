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
    'app/store/vector_store.py',
    'app/store/relation_index.py',
    'app/store/object_store.py',
    'app/memory/store.py',
    'app/agent/repository.py',
    'app/api/routes/search.py',
    'app/agents/citation_checker/agent.py',
    'app/agents/projector/agent.py',
    'app/agents/base/audit.py',
    'app/agents/base/memory.py',
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
