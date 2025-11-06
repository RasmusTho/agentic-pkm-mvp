from __future__ import annotations
from typing import Optional
from sqlalchemy import create_engine as _create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
engine: Optional[object] = None
SessionLocal: Optional[object] = None

def create_sqlite_memory_engine():
    return _create_engine("sqlite:///:memory:", future=True)

def ensure_schema(*_, **__):  # no-op i smoke
    return None
def conn_ro():
    raise RuntimeError("conn_ro unavailable in smoke sqlalchemy stub")
def conn_rw():
    raise RuntimeError("conn_rw unavailable in smoke sqlalchemy stub")
