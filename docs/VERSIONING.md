# Versioning & Migrations — SoT v4.2

## Alembic
All schema migrations live under `app/alembic/versions/`.

Rules:
1. Never edit existing migrations.
2. Always merge heads explicitly.
3. Apply with:
   PYTHONPATH="$(pwd)" alembic upgrade head

## Migration Naming
<YYYYMMDDHHMM>_<short_description>.py  
Example: `202510241200_sot42_amg_core.py`

## Version Synchronization
| Layer | Source of Truth |
|--------|----------------|
| Database schema | Alembic |
| File structure | Git |
| Data context | YAML |
| Docs | /docs (SoT v4.2) |

## Recovery
If migrations diverge:
PYTHONPATH=”$(pwd)” alembic heads

PYTHONPATH=”$(pwd)” alembic merge -m “merge heads”  

PYTHONPATH=”$(pwd)” alembic upgrade head

## Data Upgrades
For non-breaking migrations (e.g., new metadata fields):
- Add nullable columns
- Write a migration script
- Backfill asynchronously via agent
