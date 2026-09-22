"""REST API: order ingestion/validation/duplicate detection (Phase 1),
employees and order-to-employee assignment (Phase 2), and LLM-based
classification of free-text order descriptions (Phase 3).

Run with:  uvicorn app.api:app --reload --port 8001
(port 8001, not 8000 -- the Autonomous Workflow Broker project's API
already uses 8000 and you may have both checked out at once.)
"""

import json
import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.assignment import EmployeeCandidate, OrderCandidate, fcfs_assign, optimized_assign
from app.classification import ClassificationError, classify_order
from app.db import get_db, init_db
from app.models import Employee, Order
from app.schemas import (
    AssignmentRunResult,
    EmployeeCreate,
    EmployeeOut,
    OrderCreate,
    OrderOut,
)
from app.validation import validate_order

app = FastAPI(title="AI Operations Control Tower")

# Phase 4: the dashboard (frontend/) runs on Vite's dev server (port 5173
# by default; 4173 for `vite preview`) and calls this API directly from
# the browser, which means the browser enforces CORS on every request.
# Wide open (any method, any header) rather than a curated allowlist --
# this is a local dev dashboard talking to a local dev API, not a public
# deployment with real users to protect; Phase 6 (real deployment) is the
# right place to tighten this to an actual origin allowlist.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Below this, an AI suggestion is stored for visibility but not applied.
# See "A note on Phase 3's design choices" in the README for why 0.6 and
# why this only ever fills required_skills, never priority.
CLASSIFICATION_CONFIDENCE_THRESHOLD = float(
    os.getenv("CLASSIFICATION_CONFIDENCE_THRESHOLD", "0.6")
)


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
        assigned_employee_id=order.assigned_employee_id,
        assigned_at=order.assigned_at,
        ai_suggested_skills=order.ai_suggested_skills,
        ai_suggested_priority=order.ai_suggested_priority,
        ai_confidence=order.ai_confidence,
        ai_reasoning=order.ai_reasoning,
        ai_classified_at=order.ai_classified_at,
        created_at=order.created_at,
    )


def _skills_set(comma_separated: str | None) -> frozenset[str]:
    if not comma_separated:
        return frozenset()
    return frozenset(s.strip().lower() for s in comma_separated.split(",") if s.strip())


def _apply_classification(order: Order, result) -> None:
    """Stamp the ai_* fields from a ClassificationResult, and fill
    required_skills only if it's still blank and confidence clears the
    threshold. Shared by submit_order() (silent on failure) and
    reclassify_order() (surfaces failure as a 502) -- both apply a
    successful result identically."""
    order.ai_suggested_skills = ",".join(sorted(result.suggested_skills)) or None
    order.ai_suggested_priority = result.suggested_priority
    order.ai_confidence = result.confidence
    order.ai_reasoning = result.reasoning
    order.ai_classified_at = datetime.now(timezone.utc)

    if (
        not order.required_skills
        and result.suggested_skills
        and result.confidence >= CLASSIFICATION_CONFIDENCE_THRESHOLD
    ):
        order.required_skills = ",".join(sorted(result.suggested_skills))


def _run_classification(order: Order) -> None:
    """Best-effort enrichment used at submission time: attempt to classify
    `order.description` and apply the result. Any failure (network, bad
    key, malformed response) is swallowed -- Phase 3 is an enrichment
    layer order ingestion doesn't depend on, not something that should
    turn a classification hiccup into a 500 on /orders."""
    try:
        result = classify_order(order.description)
    except ClassificationError:
        return
    _apply_classification(order, result)


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

    # Only classify when there's a gap to fill -- required_skills already
    # given is a human's explicit answer, and Phase 3 never second-guesses
    # that (see the README's design notes). Runs synchronously, so it adds
    # real LLM latency to this request when it fires; a background job
    # (Celery, as the Autonomous Workflow Broker project uses) would be
    # the fix if that latency ever becomes a problem worth solving.
    if status != "rejected" and not order.required_skills:
        _run_classification(order)

    db.add(order)
    db.commit()
    db.refresh(order)
    return _to_out(order)


@app.post("/orders/{order_id}/classify", response_model=OrderOut)
def reclassify_order(order_id: int, db: Session = Depends(get_db)):
    """Re-run classification for an existing order -- useful when the
    first attempt failed (e.g. a transient API error) or after the
    confidence threshold's been tuned. Same rule as at submission time:
    only fills required_skills if it's still blank."""
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Not found")

    try:
        result = classify_order(order.description)
    except ClassificationError as exc:
        raise HTTPException(502, f"classification failed: {exc}")

    _apply_classification(order, result)

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


# ---- Phase 2: employees + assignment ------------------------------------


def _employee_to_out(employee: Employee) -> EmployeeOut:
    return EmployeeOut(
        id=employee.id,
        name=employee.name,
        location=employee.location,
        skills=employee.skills,
        daily_capacity=employee.daily_capacity,
        created_at=employee.created_at,
    )


@app.post("/employees", response_model=EmployeeOut, status_code=201)
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db)):
    employee = Employee(
        name=payload.name,
        location=payload.location,
        skills=payload.skills,
        daily_capacity=payload.daily_capacity,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return _employee_to_out(employee)


@app.get("/employees", response_model=list[EmployeeOut])
def list_employees(db: Session = Depends(get_db)):
    employees = db.query(Employee).order_by(Employee.id).all()
    return [_employee_to_out(e) for e in employees]


@app.post("/assignments/run", response_model=AssignmentRunResult)
def run_assignment(
    strategy: str = Query(default="optimized", description="'fcfs' or 'optimized'"),
    db: Session = Depends(get_db),
):
    """Assign every currently-unassigned validated order to an employee,
    using either the naive FCFS baseline or the OR-Tools optimized
    assignment (app/assignment.py has both; scripts/benchmark.py compares
    them on synthetic data).

    Orders that can't be matched (no employee covers the required skills,
    or everyone capable is already at capacity) are left as "validated" --
    eligible to be picked up by a later run, not lost.
    """
    if strategy not in ("fcfs", "optimized"):
        raise HTTPException(400, "strategy must be 'fcfs' or 'optimized'")

    orders = (
        db.query(Order)
        .filter(Order.status == "validated", Order.assigned_employee_id.is_(None))
        .order_by(Order.created_at)
        .all()
    )
    # Ordered explicitly -- FCFS's "first capable employee" only means
    # something deterministic if the employee list itself has a stable
    # order; don't rely on whatever order the DB happens to return.
    employees = db.query(Employee).order_by(Employee.id).all()

    order_candidates = [
        OrderCandidate(
            order_id=o.id,
            required_skills=_skills_set(o.required_skills),
            location=o.location,
            priority=o.priority,
        )
        for o in orders
    ]
    employee_candidates = [
        EmployeeCandidate(
            employee_id=e.id,
            skills=_skills_set(e.skills),
            location=e.location,
            daily_capacity=e.daily_capacity,
        )
        for e in employees
    ]

    assign_fn = fcfs_assign if strategy == "fcfs" else optimized_assign
    results = assign_fn(order_candidates, employee_candidates)

    orders_by_id = {o.id: o for o in orders}
    assigned_ids: list[int] = []
    now = datetime.now(timezone.utc)
    for result in results:
        if result.employee_id is None:
            continue
        order = orders_by_id[result.order_id]
        order.assigned_employee_id = result.employee_id
        order.assigned_at = now
        order.status = "assigned"
        assigned_ids.append(order.id)

    db.commit()

    return AssignmentRunResult(
        strategy=strategy,
        considered=len(orders),
        assigned=len(assigned_ids),
        unassigned=len(orders) - len(assigned_ids),
        assigned_order_ids=assigned_ids,
    )
