#!/bin/bash
set -euo pipefail

alembic -c app/alembic.ini upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
