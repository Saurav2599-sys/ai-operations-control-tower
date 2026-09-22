"""REST API: order ingestion/validation/duplicate detection (Phase 1) plus
employees and order-to-employee assignment (Phase 2).

Run with:  uvicorn app.api:app --reload --port 8001
(port 8001, not 8000 -- the Autonomous Workflow Broker project's API
already uses 8000 and you may have both checked out at once.)
"""

import json
import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from app.assignment import EmployeeCandidate, OrderCandidate, fcfs_assign, optimized_assign
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
        created_at=order.created_at,
    )


def _skills_set(comma_separated: str | None) -> frozenset[str]:
    if not comma_separated:
        return frozenset()
    return frozenset(s.strip().lower() for s in comma_separated.split(",") if s.strip())


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
