"""Test setup: a separate test database, migrated once, rolled back after every test."""

import os

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

# Point the app at a separate test database BEFORE any app module is imported,
# so tests can never touch your real data.
_base_url = os.environ.get("DATABASE_URL") or dotenv_values(".env")["DATABASE_URL"]
_test_url = make_url(_base_url).set(database=f"{make_url(_base_url).database}_test")
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from admissions.db.session import engine  # noqa: E402


def _create_test_database() -> None:
    # CREATE DATABASE can't run inside a transaction, hence AUTOCOMMIT.
    admin = create_engine(_test_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": _test_url.database},
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{_test_url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Once per test run: create the test database and run all migrations on it."""
    _create_test_database()
    command.upgrade(Config("alembic.ini"), "head")
    yield
    engine.dispose()


@pytest.fixture
def session():
    """A session whose changes are rolled back after each test, so tests never affect each other."""
    with engine.connect() as connection:
        transaction = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield db
        finally:
            db.close()
            transaction.rollback()
