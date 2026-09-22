"""The Order and Employee models.

Phase 1 shipped with just Order -- ingestion, validation, and duplicate
detection didn't need employees or a scheduler yet. Phase 2 adds Employee
and the assignment fields on Order (assigned_employee_id, assigned_at),
plus the "assigned" status the state machine comment below always said
was coming.
"""

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.db import Base


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    location = Column(String, nullable=True)
    skills = Column(String, nullable=True)  # comma-separated, same convention as Order
    # How many orders this employee can take on per assignment run. A
    # plain int rather than a real calendar/availability model -- Phase 2
    # is about the assignment algorithm, not staffing/scheduling UI; a
    # richer availability model is a reasonable place for a later phase
    # to extend this, not something to speculatively build now.
    daily_capacity = Column(Integer, nullable=False, default=5)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)

    customer_name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String, nullable=True)
    priority = Column(String, nullable=False, default="normal")
    required_skills = Column(String, nullable=True)  # comma-separated for now

    # received -> validated -> (duplicate | rejected) was the Phase 1 state
    # machine. Phase 2 adds "assigned": an order moves there once a
    # successful assignment run gives it an employee. An order that stays
    # "validated" just hasn't been matched yet (no capable/available
    # employee) -- it's eligible to be picked up by a later assignment run,
    # not stuck.
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

    # Set by an assignment run (see app/assignment.py + the /assignments/run
    # endpoint). Null until an employee is actually assigned.
    assigned_employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    assigned_employee = relationship("Employee")
    assigned_at = Column(DateTime(timezone=True), nullable=True)

    # Phase 3: LLM classification results, stored separately from the
    # authoritative required_skills/priority fields above -- see
    # app/classification.py and "A note on Phase 3's design choices" in
    # the README for why this is a suggestion, not an override.
    ai_suggested_skills = Column(String, nullable=True)  # comma-separated
    ai_suggested_priority = Column(String, nullable=True)
    ai_confidence = Column(Float, nullable=True)
    ai_reasoning = Column(Text, nullable=True)
    ai_classified_at = Column(DateTime(timezone=True), nullable=True)

    # The exact payload as submitted, for audit -- if validation logic
    # changes later, you can always see what was actually sent.
    raw_payload = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
