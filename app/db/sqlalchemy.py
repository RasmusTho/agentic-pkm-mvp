from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import create_engine as _create_engine

class Base(DeclarativeBase):
    pass

def create_sqlite_memory_engine():
    return _create_engine("sqlite+pysqlite:///:memory:", future=True)

engine: Optional[object] = create_sqlite_memory_engine()
SessionLocal: Optional[object] = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)

def ensure_schema(*_, **__):
    return None

def conn_ro():
    raise RuntimeError("conn_ro unavailable in smoke sqlalchemy stub")

def conn_rw():
    raise RuntimeError("conn_rw unavailable in smoke sqlalchemy stub")

__all__ = ("engine", "SessionLocal", "Base", "create_sqlite_memory_engine", "ensure_schema", "conn_ro", "conn_rw")
