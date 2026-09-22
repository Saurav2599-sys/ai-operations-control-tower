"""Order-to-employee assignment: a naive first-come-first-served baseline,
and an OR-Tools CP-SAT optimized assignment. scripts/benchmark.py runs both
on the same synthetic dataset and reports real numbers -- see that file and
the "Phase 2 benchmark" section of the README for what the comparison
actually showed, not what it was expected to show.

Both strategies work against the same plain dataclasses (OrderCandidate /
EmployeeCandidate) rather than the SQLAlchemy models directly. That's
deliberate: it keeps this module testable and runnable in isolation (no DB,
no FastAPI) and lets the benchmark script exercise 1,000 synthetic orders
without touching Postgres at all.
"""

from dataclasses import dataclass


PRIORITY_WEIGHT = {"urgent": 4, "high": 3, "normal": 2, "low": 1}


@dataclass(frozen=True)
class OrderCandidate:
    order_id: int
    required_skills: frozenset[str]
    location: str | None
    priority: str = "normal"


@dataclass(frozen=True)
class EmployeeCandidate:
    employee_id: int
    skills: frozenset[str]
    location: str | None
    daily_capacity: int


@dataclass
class Assignment:
    order_id: int
    employee_id: int | None  # None means left unassigned
    location_match: bool = False


def _skills_covered(order: OrderCandidate, employee: EmployeeCandidate) -> bool:
    """An employee can take the order if they have every skill it asks for.
    An order with blank/unknown required_skills is NOT eligible for
    matching -- it stays out of the assignment pool (same as "no employee
    covers it yet": left unassigned, eligible for a later run) until a
    human fills in required_skills or a (re)classification clears the
    confidence threshold.

    This used to return True for a blank required_skills -- "no
    constraint, anyone can do it" -- which was a reasonable rule back
    when Phase 2 was the only source of required_skills and blank only
    ever meant a human explicitly didn't specify one. Phase 3 changed
    what blank can mean: it's also what a low-confidence or
    majority-of-pool-guard-zeroed classification leaves behind (see "A
    note on Phase 3's design choices" in the README). Treating that the
    same as "no constraint" quietly defeated the point of the confidence
    guard -- an order the system explicitly doesn't trust a
    classification for would still get silently scheduled as if it
    needed nothing at all. Caught via real Phase 4 dashboard testing
    (a batch of seeded orders included several majority-of-pool guard
    hits that still showed up "Assigned"), not found in isolation."""
    if not order.required_skills:
        return False
    return order.required_skills.issubset(employee.skills)


def fcfs_assign(
    orders: list[OrderCandidate], employees: list[EmployeeCandidate]
) -> list[Assignment]:
    """First-come-first-served: walk the orders in the order given (i.e.
    submission order), hand each one to the first employee, in the order
    given, who covers its required skills and still has capacity left.
    Tries a location-matching employee first, then falls back to any
    capable employee regardless of location.

    This is the naive baseline every real scheduler gets compared against
    -- simple to explain, cheap to run, and exactly what "just assign them
    in the order they came in" looks like in code.
    """
    remaining_capacity = {e.employee_id: e.daily_capacity for e in employees}
    assignments: list[Assignment] = []

    for order in orders:
        chosen = None

        for employee in employees:
            if remaining_capacity[employee.employee_id] <= 0:
                continue
            if not _skills_covered(order, employee):
                continue
            if order.location and employee.location and order.location != employee.location:
                continue
            chosen = employee
            break

        if chosen is None:
            for employee in employees:
                if remaining_capacity[employee.employee_id] <= 0:
                    continue
                if not _skills_covered(order, employee):
                    continue
                chosen = employee
                break

        if chosen is not None:
            remaining_capacity[chosen.employee_id] -= 1
            assignments.append(
                Assignment(
                    order_id=order.order_id,
                    employee_id=chosen.employee_id,
                    location_match=(order.location == chosen.location),
                )
            )
        else:
            assignments.append(Assignment(order_id=order.order_id, employee_id=None))

    return assignments


def optimized_assign(
    orders: list[OrderCandidate], employees: list[EmployeeCandidate]
) -> list[Assignment]:
    """CP-SAT assignment: a capacitated bipartite matching (each order to
    at most one employee, each employee to at most `daily_capacity`
    orders), maximizing a weighted score instead of just filling slots in
    submission order.

    The weight per (order, employee) pair is priority-driven --
    urgent/high orders are worth more to assign than low-priority ones --
    plus a small bonus when the employee is in the order's location. When
    capacity is scarce, the solver is explicitly trading off "assign this
    urgent order" against "assign these three low-priority ones" instead
    of just taking whichever showed up first.

    This is a maximum-weight b-matching / generalized-assignment
    formulation -- a standard CP-SAT pattern, not a hand-rolled heuristic.
    """
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()

    order_by_id = {o.order_id: o for o in orders}
    employee_by_id = {e.employee_id: e for e in employees}

    pair_vars: dict[tuple[int, int], object] = {}
    for order in orders:
        for employee in employees:
            if not _skills_covered(order, employee):
                continue
            var = model.NewBoolVar(f"x_{order.order_id}_{employee.employee_id}")
            pair_vars[(order.order_id, employee.employee_id)] = var

    # Each order goes to at most one employee.
    for order in orders:
        vars_for_order = [
            var for (oid, _eid), var in pair_vars.items() if oid == order.order_id
        ]
        if vars_for_order:
            model.Add(sum(vars_for_order) <= 1)

    # Each employee takes on at most their daily capacity.
    for employee in employees:
        vars_for_employee = [
            var for (_oid, eid), var in pair_vars.items() if eid == employee.employee_id
        ]
        if vars_for_employee:
            model.Add(sum(vars_for_employee) <= employee.daily_capacity)

    objective_terms = []
    for (order_id, employee_id), var in pair_vars.items():
        order = order_by_id[order_id]
        employee = employee_by_id[employee_id]
        weight = PRIORITY_WEIGHT.get(order.priority, 2) * 10
        if order.location and employee.location and order.location == employee.location:
            weight += 3
        objective_terms.append(weight * var)
    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    assignments: list[Assignment] = []
    assigned_order_ids: set[int] = set()

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (order_id, employee_id), var in pair_vars.items():
            if solver.Value(var):
                order = order_by_id[order_id]
                employee = employee_by_id[employee_id]
                assignments.append(
                    Assignment(
                        order_id=order_id,
                        employee_id=employee_id,
                        location_match=(order.location == employee.location),
                    )
                )
                assigned_order_ids.add(order_id)

    for order in orders:
        if order.order_id not in assigned_order_ids:
            assignments.append(Assignment(order_id=order.order_id, employee_id=None))

    return assignments
