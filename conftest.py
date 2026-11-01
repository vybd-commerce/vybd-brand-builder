"""Shared pytest fixtures.

DB tests use TEST_DATABASE_URL (a separate `vybd_test` database, created if missing).
If Postgres is unreachable they are skipped locally — but fail in CI (REQUIRE_DB_TESTS=1).
"""

from __future__ import annotations

import os
import pathlib

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = pathlib.Path(__file__).resolve().parent

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://vybd:vybd@localhost:5433/vybd_test"
)


def _ensure_database(url: str) -> None:
    target = make_url(url)
    admin = create_engine(
        target.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def db_url() -> str:
    try:
        _ensure_database(TEST_DATABASE_URL)
    except Exception as e:  # postgres not running
        if os.environ.get("REQUIRE_DB_TESTS") == "1":
            raise
        pytest.skip(f"Postgres unreachable ({type(e).__name__}); run `make db`")
    return TEST_DATABASE_URL


def alembic_cfg(package: str, url: str):
    from alembic.config import Config

    cfg = Config(str(ROOT / "packages" / package / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def migrated_db(db_url: str) -> str:
    """Test DB with both schemas at head. Tests isolate by using fresh brand ids."""
    from alembic import command

    command.upgrade(alembic_cfg("brain", db_url), "head")
    command.upgrade(alembic_cfg("server", db_url), "head")

    # Start each test session from empty tables (keeps fixed-email tests repeatable).
    engine = create_engine(db_url)
    with engine.begin() as conn:
        tables = conn.execute(text(
            "SELECT schemaname || '.' || tablename FROM pg_tables "
            "WHERE schemaname IN ('app', 'brain') AND tablename <> 'alembic_version'"
        )).scalars().all()
        if tables:
            conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
    engine.dispose()
    return db_url


@pytest.fixture(scope="session")
def session_factory(migrated_db: str):
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(migrated_db)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()
