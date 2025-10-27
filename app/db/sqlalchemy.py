from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.settings import settings
from .db import conn_ro, conn_rw, ensure_schema

engine = create_engine(settings.db_dsn, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

__all__ = ("engine", "SessionLocal", "Base", "conn_ro", "conn_rw", "ensure_schema")
