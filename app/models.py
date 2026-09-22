"""The Order model. Phase 1 is deliberately just this one table -- ingestion,
validation, and duplicate detection don't need employees, assignments, or a
scheduler yet. Those arrive in Phase 2+ once this foundation is solid.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.db import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)

    customer_name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String, nullable=True)
    priority = Column(String, nullable=False, default="normal")
    required_skills = Column(String, nullable=True)  # comma-separated for now

    # received -> validated -> (duplicate | rejected) is the Phase 1 state
    # machine. assigned/in_progress/completed arrive with the scheduler in
    # Phase 2.
    status = Column(String, nullable=False, default="received")

    # JSON-encoded list of human-readable validation problems, e.g.
    # ["missing customer_name", "priority must be one of low/normal/high/urgent"].
    # Populated even when status ends up "validated", so a caller can see
    # non-fatal issues (e.g. a low-confidence duplicate match) alongside a
    # clean result -- see app/validation.py.
    validation_errors = Column(Text, nullable=True)

    # Deterministic normalization key used for duplicate lookups (see
    # app/validation.py: normalize_for_dedupe()). Indexed so the duplicate
    # check is a real query, not an in-memory scan of every order ever
    # submitted.
    dedupe_key = Column(String, nullable=True, index=True)
    duplicate_of_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    duplicate_of = relationship("Order", remote_side=[id])

    # The exact payload as submitted, for audit -- if validation logic
    # changes later, you can always see what was actually sent.
    raw_payload = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
