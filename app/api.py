"""Phase 1 REST API: order ingestion, validation, and duplicate detection.

Run with:  uvicorn app.api:app --reload --port 8001
(port 8001, not 8000 -- the Autonomous Workflow Broker project's API
already uses 8000 and you may have both checked out at once.)
"""

import json
import os

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db, init_db
from app.models import Order
from app.schemas import OrderCreate, OrderOut
from app.validation import validate_order

app = FastAPI(title="AI Operations Control Tower -- Phase 1: Order Ingestion")


@app.on_event("startup")
def on_startup():
    # Tests use their own isolated in-memory SQLite engine (see
    # tests/conftest.py) and override get_db entirely -- they never need
    # this app's real Postgres schema created, and shouldn't require a
    # live Postgres just to run `pytest`.
    if os.getenv("SKIP_DB_INIT") == "1":
        return
    init_db()


def _to_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        customer_name=order.customer_name,
        description=order.description,
        location=order.location,
        priority=order.priority,
        required_skills=order.required_skills,
        status=order.status,
        validation_errors=json.loads(order.validation_errors) if order.validation_errors else [],
        duplicate_of_id=order.duplicate_of_id,
        created_at=order.created_at,
    )


@app.post("/orders", response_model=OrderOut, status_code=201)
def submit_order(payload: OrderCreate, db: Session = Depends(get_db)):
    result = validate_order(
        db,
        customer_name=payload.customer_name,
        description=payload.description,
        location=payload.location,
        priority=payload.priority,
    )

    hard_errors = [e for e in result.errors if not e.startswith("possible duplicate")]
    if hard_errors:
        status = "rejected"
    elif result.duplicate_of_id is not None:
        status = "duplicate"
    else:
        status = "validated"

    order = Order(
        customer_name=payload.customer_name,
        description=payload.description,
        location=payload.location,
        priority=(payload.priority or "normal").strip().lower(),
        required_skills=payload.required_skills,
        status=status,
        validation_errors=json.dumps(result.errors) if result.errors else None,
        dedupe_key=result.dedupe_key,
        duplicate_of_id=result.duplicate_of_id,
        raw_payload=payload.model_dump_json(),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return _to_out(order)


@app.get("/orders", response_model=list[OrderOut])
def list_orders(
    status: str | None = Query(default=None, description="Filter by status"),
    db: Session = Depends(get_db),
):
    q = db.query(Order).order_by(Order.created_at.desc())
    if status:
        q = q.filter(Order.status == status)
    return [_to_out(o) for o in q.all()]


@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Not found")
    return _to_out(order)
