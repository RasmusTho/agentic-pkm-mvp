import os
from alembic import context
from sqlalchemy import create_engine

def get_url() -> str:
    return os.environ["DATABASE_URL"]

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
