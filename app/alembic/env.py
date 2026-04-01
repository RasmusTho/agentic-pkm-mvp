from alembic import context
from sqlalchemy import create_engine

from app.db.dsn import resolve_sqlalchemy_url

def get_url() -> str:
    url = resolve_sqlalchemy_url()
    if not url:
        raise RuntimeError("DATABASE_URL is required for alembic migrations")
    return url

def run_migrations_offline() -> None:
    context.configure(url=get_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    engine = create_engine(get_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
