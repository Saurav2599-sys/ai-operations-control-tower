import os

# Must happen before `app.api` is imported anywhere -- see the startup
# handler in app/api.py.
os.environ["SKIP_DB_INIT"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db


@pytest.fixture()
def db_session():
    """A fresh, isolated in-memory SQLite DB per test -- fast, and no
    shared state can leak between tests. StaticPool keeps the single
    in-memory connection alive for the fixture's lifetime (a plain
    sqlite:///:memory: engine would otherwise hand out a new, empty
    database on every connection)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    from app.api import app  # imported here, after SKIP_DB_INIT is set

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
