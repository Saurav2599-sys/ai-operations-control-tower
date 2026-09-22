"""Tests for app/assignment.py against plain dataclasses -- no DB, no
FastAPI, so these run fast and in isolation. The fcfs_assign tests need no
extra dependencies; the optimized_assign tests need ortools installed
(see requirements.txt) since they exercise the real CP-SAT solver rather
than a mock.
"""

import pytest

from app.assignment import EmployeeCandidate, OrderCandidate, fcfs_assign, optimized_assign


def _order(order_id, skills=(), location=None, priority="normal"):
    return OrderCandidate(
        order_id=order_id,
        required_skills=frozenset(skills),
        location=location,
        priority=priority,
    )


def _employee(employee_id, skills=(), location=None, daily_capacity=1):
    return EmployeeCandidate(
        employee_id=employee_id,
        skills=frozenset(skills),
        location=location,
        daily_capacity=daily_capacity,
    )


# ---- fcfs_assign -----------------------------------------------------

def test_fcfs_assigns_to_first_capable_employee():
    orders = [_order(1, skills={"plumbing"})]
    employees = [
        _employee(1, skills={"electrical"}, daily_capacity=1),
        _employee(2, skills={"plumbing"}, daily_capacity=1),
    ]
    result = fcfs_assign(orders, employees)
    assert result[0].employee_id == 2


def test_fcfs_respects_capacity():
    orders = [_order(1, skills={"plumbing"}), _order(2, skills={"plumbing"})]
    employees = [_employee(1, skills={"plumbing"}, daily_capacity=1)]
    result = fcfs_assign(orders, employees)
    assert result[0].employee_id == 1
    assert result[1].employee_id is None  # capacity exhausted


def test_fcfs_leaves_uncoverable_order_unassigned():
    orders = [_order(1, skills={"welding"})]
    employees = [_employee(1, skills={"plumbing"}, daily_capacity=5)]
    result = fcfs_assign(orders, employees)
    assert result[0].employee_id is None


def test_fcfs_prefers_location_match_but_falls_back():
    orders = [_order(1, skills={"plumbing"}, location="Austin, TX")]
    employees = [
        _employee(1, skills={"plumbing"}, location="Denver, CO", daily_capacity=1),
        _employee(2, skills={"plumbing"}, location="Austin, TX", daily_capacity=1),
    ]
    result = fcfs_assign(orders, employees)
    assert result[0].employee_id == 2
    assert result[0].location_match is True


def test_fcfs_falls_back_to_out_of_location_employee_when_needed():
    orders = [_order(1, skills={"plumbing"}, location="Austin, TX")]
    employees = [_employee(1, skills={"plumbing"}, location="Denver, CO", daily_capacity=1)]
    result = fcfs_assign(orders, employees)
    assert result[0].employee_id == 1
    assert result[0].location_match is False


def test_fcfs_order_with_blank_required_skills_stays_unassigned():
    """Blank required_skills means "unknown," not "no constraint" -- see
    _skills_covered's docstring for why this flipped from the original
    Phase 2 behavior once Phase 3 could also leave this blank (a
    low-confidence or guard-zeroed classification)."""
    orders = [_order(1, skills=set())]
    employees = [_employee(1, skills={"electrical"}, daily_capacity=1)]
    result = fcfs_assign(orders, employees)
    assert result[0].employee_id is None


# ---- optimized_assign --------------------------------------------------

ortools = pytest.importorskip(
    "ortools", reason="ortools not installed -- see requirements.txt"
)


def test_optimized_respects_capacity():
    orders = [_order(1, skills={"plumbing"}), _order(2, skills={"plumbing"})]
    employees = [_employee(1, skills={"plumbing"}, daily_capacity=1)]
    result = optimized_assign(orders, employees)
    assigned = [a for a in result if a.employee_id is not None]
    assert len(assigned) == 1


def test_optimized_prefers_higher_priority_when_capacity_is_scarce():
    """One slot, two otherwise-identical orders -- the solver should take
    the urgent one over the low-priority one, unlike FCFS which would
    just take whichever came first."""
    orders = [
        _order(1, skills={"plumbing"}, priority="low"),
        _order(2, skills={"plumbing"}, priority="urgent"),
    ]
    employees = [_employee(1, skills={"plumbing"}, daily_capacity=1)]
    result = optimized_assign(orders, employees)
    assigned_ids = {a.order_id for a in result if a.employee_id is not None}
    assert assigned_ids == {2}


def test_optimized_leaves_uncoverable_order_unassigned():
    orders = [_order(1, skills={"welding"})]
    employees = [_employee(1, skills={"plumbing"}, daily_capacity=5)]
    result = optimized_assign(orders, employees)
    assert result[0].employee_id is None


def test_optimized_never_exceeds_employee_capacity():
    orders = [_order(i, skills={"plumbing"}) for i in range(5)]
    employees = [_employee(1, skills={"plumbing"}, daily_capacity=2)]
    result = optimized_assign(orders, employees)
    assigned = [a for a in result if a.employee_id == 1]
    assert len(assigned) <= 2


def test_optimized_order_with_blank_required_skills_stays_unassigned():
    """Same fix, same reasoning, both strategies -- optimized_assign builds
    its pair_vars from the same _skills_covered() check as fcfs_assign, so
    this needs its own regression test rather than trusting the fcfs
    coverage to imply it."""
    orders = [_order(1, skills=set())]
    employees = [_employee(1, skills={"electrical"}, daily_capacity=1)]
    result = optimized_assign(orders, employees)
    assert result[0].employee_id is None
