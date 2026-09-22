"""SQLAlchemy engine/session setup, and the Base every model inherits from."""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: one session per request, always closed after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables if they don't exist. No Alembic yet -- Phase 1 has one
    table and no migrations to manage; a real migration tool earns its
    place once the schema actually needs to evolve under live data."""
    from app import models  # noqa: F401 -- registers Order with Base.metadata

    Base.metadata.create_all(bind=engine)
