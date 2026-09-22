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


@pytest.fixture(autouse=True)
def _no_real_llm_calls(monkeypatch):
    """No test may make a real call to OpenAI -- it would cost real money,
    depend on network/API-key state, and make `pytest` non-deterministic
    and slow. Every test's classify_order() fails closed by default
    (raises ClassificationError), which exercises the same graceful-
    degradation path a real OpenAI outage would -- see
    test_submit_order_classification_failure_degrades_gracefully for that
    behavior tested explicitly.

    Tests that care about a specific classification outcome (the Phase 3
    section of test_api.py) override this within the test body itself via
    their own monkeypatch.setattr(api_module, "classify_order", ...) --
    that's a second call to the same monkeypatch fixture, which simply
    replaces this patch for the rest of that test.

    tests/test_classification.py doesn't go through this at all -- it
    calls classify_order() directly against a FakeClient, never through
    the FastAPI app, so this autouse fixture (which patches app.api's
    reference to it) doesn't apply there.
    """
    import app.api as api_module
    from app.classification import ClassificationError

    def _fail(description):
        raise ClassificationError("classification disabled in tests")

    monkeypatch.setattr(api_module, "classify_order", _fail)
