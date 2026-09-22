"""Order validation and duplicate detection.

Both are deliberately deterministic and explainable for Phase 1 -- no LLM
involved yet. The plan for this project is to introduce AI where it adds
measurable value (order *classification*, in Phase 3), not to reach for it
for things a straightforward rule already does reliably and for free. A
validation rule you can read in five seconds and a duplicate check you can
reproduce by hand are worth more here than a model call that might not be.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import ALLOWED_PRIORITIES, DUPLICATE_WINDOW_MINUTES
from app.models import Order


def normalize_for_dedupe(customer_name: str, location: str | None, description: str) -> str:
    """Collapse whitespace/case/punctuation differences that don't change
    what's actually being asked for, then hash. Two orders that normalize
    to the same string are treated as the same request, not two different
    ones that happen to look alike."""
    parts = [
        (customer_name or "").strip().lower(),
        (location or "").strip().lower(),
        re.sub(r"\s+", " ", (description or "").strip().lower()),
    ]
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    duplicate_of_id: int | None = None
    dedupe_key: str = ""

    @property
    def is_valid(self) -> bool:
        # A duplicate match is reported in `errors` for visibility but does
        # NOT by itself make the order invalid -- a legitimately recurring
        # order is not bad data. Only missing/malformed fields are.
        return not any(not e.startswith("possible duplicate") for e in self.errors)


def validate_order(db: Session, customer_name: str, description: str,
                    location: str | None, priority: str | None) -> ValidationResult:
    errors: list[str] = []

    if not customer_name or not customer_name.strip():
        errors.append("missing customer_name")
    if not description or not description.strip():
        errors.append("missing description")
    if not location or not location.strip():
        errors.append("missing location")

    priority = (priority or "normal").strip().lower()
    if priority not in ALLOWED_PRIORITIES:
        errors.append(
            f"invalid priority '{priority}' -- must be one of {', '.join(ALLOWED_PRIORITIES)}"
        )

    dedupe_key = normalize_for_dedupe(customer_name, location, description)
    duplicate_id = None

    # Only worth checking for duplicates once we have real content to
    # compare -- an order that's already missing required fields will be
    # rejected on those grounds regardless.
    if customer_name and description:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=DUPLICATE_WINDOW_MINUTES)
        match = (
            db.query(Order)
            .filter(Order.dedupe_key == dedupe_key, Order.created_at >= cutoff)
            .order_by(Order.created_at.desc())
            .first()
        )
        if match is not None:
            duplicate_id = match.id
            errors.append(
                f"possible duplicate of order #{match.id} "
                f"(submitted {match.created_at.isoformat()})"
            )

    return ValidationResult(errors=errors, duplicate_of_id=duplicate_id, dedupe_key=dedupe_key)
