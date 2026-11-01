"""Alembic env for the `brain` schema. Own history, version table in `brain.alembic_version`."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, text

from brain.models import SCHEMA, Base

target_metadata = Base.metadata


def _url() -> str:
    url = context.config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _include_object(obj, name, type_, reflected, compare_to):
    # Only manage objects in our own schema; ignore `app` and anything else.
    if type_ == "table":
        return getattr(obj, "schema", None) == SCHEMA
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as conn:
        # Schema must exist before alembic creates its version table inside it.
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        conn.commit()
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_schemas=True,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
