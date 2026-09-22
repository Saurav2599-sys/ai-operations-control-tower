"""Direct unit tests against validate_order() / normalize_for_dedupe() --
the actual logic, independent of the HTTP layer."""

from datetime import datetime, timedelta, timezone

from app.config import DUPLICATE_WINDOW_MINUTES
from app.models import Order
from app.validation import normalize_for_dedupe, validate_order


def test_missing_customer_name_is_flagged(db_session):
    result = validate_order(db_session, customer_name="", description="fix the thing",
                             location="Austin", priority="normal")
    assert not result.is_valid
    assert "missing customer_name" in result.errors


def test_missing_description_is_flagged(db_session):
    result = validate_order(db_session, customer_name="Acme", description="  ",
                             location="Austin", priority="normal")
    assert not result.is_valid
    assert "missing description" in result.errors


def test_missing_location_is_flagged(db_session):
    result = validate_order(db_session, customer_name="Acme", description="fix the thing",
                             location=None, priority="normal")
    assert not result.is_valid
    assert "missing location" in result.errors


def test_invalid_priority_is_flagged(db_session):
    result = validate_order(db_session, customer_name="Acme", description="fix the thing",
                             location="Austin", priority="asap!!")
    assert not result.is_valid
    assert any("invalid priority" in e for e in result.errors)


def test_well_formed_order_has_no_errors(db_session):
    result = validate_order(db_session, customer_name="Acme", description="fix the thing",
                             location="Austin", priority="high")
    assert result.is_valid
    assert result.errors == []
    assert result.duplicate_of_id is None


def test_duplicate_within_window_is_detected(db_session):
    existing = Order(
        customer_name="Acme", description="Fix the thing", location="Austin",
        priority="normal", status="validated", raw_payload="{}",
        dedupe_key=normalize_for_dedupe("Acme", "Austin", "Fix the thing"),
    )
    db_session.add(existing)
    db_session.commit()

    # Different case/whitespace on purpose -- normalization should still
    # catch this as the same request.
    result = validate_order(db_session, customer_name="  acme ", description="fix the thing",
                             location="AUSTIN", priority="normal")
    assert result.duplicate_of_id == existing.id
    assert any("possible duplicate" in e for e in result.errors)
    # A duplicate match alone doesn't make the order invalid -- it's a
    # flag for a human/downstream logic to weigh, not an automatic reject.
    assert result.is_valid


def test_duplicate_outside_window_is_not_flagged(db_session):
    stale = Order(
        customer_name="Acme", description="Fix the thing", location="Austin",
        priority="normal", status="validated", raw_payload="{}",
        dedupe_key=normalize_for_dedupe("Acme", "Austin", "Fix the thing"),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=DUPLICATE_WINDOW_MINUTES + 5),
    )
    db_session.add(stale)
    db_session.commit()

    result = validate_order(db_session, customer_name="Acme", description="Fix the thing",
                             location="Austin", priority="normal")
    assert result.duplicate_of_id is None
    assert result.is_valid


def test_different_orders_do_not_collide():
    key_a = normalize_for_dedupe("Acme", "Austin", "Fix the thing")
    key_b = normalize_for_dedupe("Acme", "Austin", "Fix the other thing")
    assert key_a != key_b
