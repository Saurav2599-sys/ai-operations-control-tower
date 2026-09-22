"""Phase 2 benchmark: FCFS vs. the OR-Tools CP-SAT assignment, on the same
synthetic dataset. Run it yourself -- this script is the source of the
numbers in the README's "Phase 2 benchmark results" section, not the other
way around.

    python -m scripts.benchmark
    python -m scripts.benchmark --orders 1000 --employees 40 --seed 42

Runs entirely in memory -- no Postgres, no FastAPI -- so it's fast and
reproducible with a fixed --seed.
"""

import argparse
import random
import statistics
import time

from app.assignment import (
    PRIORITY_WEIGHT,
    EmployeeCandidate,
    OrderCandidate,
    fcfs_assign,
    optimized_assign,
)

SKILL_POOL = [
    "electrical",
    "plumbing",
    "hvac",
    "carpentry",
    "welding",
    "painting",
    "general_repair",
    "inspection",
]

LOCATIONS = [
    "Austin, TX",
    "Denver, CO",
    "Reno, NV",
    "Portland, OR",
    "Columbus, OH",
    "Raleigh, NC",
]

# Roughly what a real ticket queue looks like: mostly routine, a meaningful
# tail of urgent/high-priority work.
PRIORITY_WEIGHTS_FOR_SAMPLING = {"low": 0.20, "normal": 0.50, "high": 0.20, "urgent": 0.10}


def generate_employees(n: int, rng: random.Random) -> list[EmployeeCandidate]:
    employees = []
    for i in range(1, n + 1):
        num_skills = rng.choice([1, 1, 2, 2, 3])
        skills = frozenset(rng.sample(SKILL_POOL, num_skills))
        employees.append(
            EmployeeCandidate(
                employee_id=i,
                skills=skills,
                location=rng.choice(LOCATIONS),
                daily_capacity=rng.randint(3, 8),
            )
        )
    return employees


def generate_orders(n: int, rng: random.Random) -> list[OrderCandidate]:
    priorities = list(PRIORITY_WEIGHTS_FOR_SAMPLING.keys())
    weights = list(PRIORITY_WEIGHTS_FOR_SAMPLING.values())
    orders = []
    for i in range(1, n + 1):
        num_skills = rng.choice([1, 1, 1, 2])
        skills = frozenset(rng.sample(SKILL_POOL, num_skills))
        orders.append(
            OrderCandidate(
                order_id=i,
                required_skills=skills,
                location=rng.choice(LOCATIONS),
                priority=rng.choices(priorities, weights=weights, k=1)[0],
            )
        )
    return orders


def evaluate(
    strategy_name: str,
    assignments,
    orders: list[OrderCandidate],
    employees: list[EmployeeCandidate],
    elapsed_seconds: float,
) -> dict:
    orders_by_id = {o.order_id: o for o in orders}
    assigned = [a for a in assignments if a.employee_id is not None]
    unassigned = [a for a in assignments if a.employee_id is None]

    total_priority_weight = sum(PRIORITY_WEIGHT[o.priority] for o in orders)
    captured_priority_weight = sum(
        PRIORITY_WEIGHT[orders_by_id[a.order_id].priority] for a in assigned
    )

    location_matches = sum(1 for a in assigned if a.location_match)

    per_employee_load = {e.employee_id: 0 for e in employees}
    for a in assigned:
        per_employee_load[a.employee_id] += 1
    loads = list(per_employee_load.values())

    return {
        "strategy": strategy_name,
        "total_orders": len(orders),
        "assigned": len(assigned),
        "unassigned": len(unassigned),
        "pct_assigned": 100 * len(assigned) / len(orders) if orders else 0.0,
        "priority_weight_captured_pct": (
            100 * captured_priority_weight / total_priority_weight
            if total_priority_weight
            else 0.0
        ),
        "location_match_pct_of_assigned": (
            100 * location_matches / len(assigned) if assigned else 0.0
        ),
        "workload_stdev": statistics.pstdev(loads) if loads else 0.0,
        "workload_max": max(loads) if loads else 0,
        "elapsed_seconds": elapsed_seconds,
    }


def print_report(fcfs_stats: dict, optimized_stats: dict) -> None:
    rows = [
        ("Orders assigned", f"{fcfs_stats['assigned']}/{fcfs_stats['total_orders']}",
         f"{optimized_stats['assigned']}/{optimized_stats['total_orders']}"),
        ("% assigned", f"{fcfs_stats['pct_assigned']:.1f}%",
         f"{optimized_stats['pct_assigned']:.1f}%"),
        ("Priority-weight captured", f"{fcfs_stats['priority_weight_captured_pct']:.1f}%",
         f"{optimized_stats['priority_weight_captured_pct']:.1f}%"),
        ("Location match (of assigned)",
         f"{fcfs_stats['location_match_pct_of_assigned']:.1f}%",
         f"{optimized_stats['location_match_pct_of_assigned']:.1f}%"),
        ("Workload stdev across employees", f"{fcfs_stats['workload_stdev']:.2f}",
         f"{optimized_stats['workload_stdev']:.2f}"),
        ("Busiest employee's load", f"{fcfs_stats['workload_max']}",
         f"{optimized_stats['workload_max']}"),
        ("Runtime", f"{fcfs_stats['elapsed_seconds']:.3f}s",
         f"{optimized_stats['elapsed_seconds']:.3f}s"),
    ]

    label_width = max(len(r[0]) for r in rows) + 2
    col_width = 16
    header = f"{'':<{label_width}}{'FCFS':<{col_width}}{'OR-Tools':<{col_width}}"
    print(header)
    print("-" * len(header))
    for label, fcfs_val, opt_val in rows:
        print(f"{label:<{label_width}}{fcfs_val:<{col_width}}{opt_val:<{col_width}}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", type=int, default=1000)
    parser.add_argument("--employees", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    employees = generate_employees(args.employees, rng)
    orders = generate_orders(args.orders, rng)

    print(
        f"Synthetic dataset: {len(orders)} orders, {len(employees)} employees "
        f"(seed={args.seed})\n"
    )

    start = time.perf_counter()
    fcfs_result = fcfs_assign(orders, employees)
    fcfs_elapsed = time.perf_counter() - start
    fcfs_stats = evaluate("fcfs", fcfs_result, orders, employees, fcfs_elapsed)

    start = time.perf_counter()
    optimized_result = optimized_assign(orders, employees)
    optimized_elapsed = time.perf_counter() - start
    optimized_stats = evaluate("optimized", optimized_result, orders, employees, optimized_elapsed)

    print_report(fcfs_stats, optimized_stats)


if __name__ == "__main__":
    main()
