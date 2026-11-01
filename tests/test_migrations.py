"""Both alembic histories apply cleanly, into their own schemas, and reach head."""

from __future__ import annotations

import pathlib

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

ROOT = pathlib.Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.db


def _head(package: str) -> str:
    cfg = Config(str(ROOT / "packages" / package / "alembic.ini"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def test_migrations_upgrade_head(migrated_db: str) -> None:
    engine = create_engine(migrated_db)
    with engine.connect() as conn:

        def one(sql: str):
            return conn.execute(text(sql)).scalar()

        schemas = set(
            conn.execute(text("SELECT schema_name FROM information_schema.schemata")).scalars()
        )
        assert {"app", "brain"} <= schemas
        assert one("SELECT version_num FROM brain.alembic_version") == _head("brain")
        assert one("SELECT version_num FROM app.alembic_version") == _head("server")
        assert one("SELECT 1 FROM pg_extension WHERE extname='vector'") == 1
        assert one("SELECT to_regclass('brain.claims')") is not None
    engine.dispose()
