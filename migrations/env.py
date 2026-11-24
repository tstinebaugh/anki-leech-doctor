"""Alembic environment for the app's SQLite database (db.py)."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from db import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    from config_defaults import DB_PATH
    return config.get_main_option("sqlalchemy.url") or f"sqlite:///{DB_PATH}"


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    # render_as_batch: SQLite can't ALTER most columns, so Alembic rebuilds the table
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        # Called from Database.migrate(): reuse the app's connection, keep the app's logging
        _run(connection)
        return
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)
    engine = create_engine(_url())
    with engine.connect() as connection:
        _run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
