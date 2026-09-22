# AI Operations Control Tower

Project 4 in this AI engineering portfolio series. Where the [Autonomous
Workflow Broker](https://github.com/Saurav2599-sys/autonomous-workflow-broker)
(Project 3) demonstrated agent orchestration and background processing,
this project is a working product: intelligent order ingestion, deterministic
scheduling and optimization, AI-assisted classification layered on top of
(not instead of) those deterministic rules, a live dashboard, and a
human-approval loop for the cases the system shouldn't decide alone.

This is being built in phases, on purpose -- see "Where this stands" below
for what's actually done versus what's planned.

## Why phases, not one big build

An AI-powered scheduling platform is a believable resume line whether or
not it works. The point of building it in phases, each with its own real
tests and (eventually) a real benchmark against a naive baseline, is that
every claim this README makes about the system is something you can
actually run and check -- not an invented business-impact percentage.

## Where this stands

- **Phase 1 -- Order ingestion:** done. REST API for submitting orders,
  deterministic validation (required fields, valid priority), and
  deterministic duplicate detection (normalized-content hash within a
  configurable time window). See "A note on Phase 1's design choices"
  below.
- **Phase 2 -- Scheduling & optimization:** done. `POST /assignments/run`
  assigns validated orders to employees by skill and location, under a
  per-employee capacity constraint, using either a naive first-come-
  first-served baseline or an OR-Tools CP-SAT optimized assignment.
  `scripts/benchmark.py` runs both against the same synthetic 1,000-order
  dataset -- see "Phase 2 benchmark results" below for what that actually
  showed.
- **Phase 3 -- AI-assisted classification:** not started. LLM tool-calling
  to interpret free-text order descriptions and extract structured
  requirements, feeding into (not overriding) Phase 2's deterministic
  assignment rules.
- **Phase 4 -- Dashboard:** not started. React/TypeScript frontend for
  monitoring orders, assignments, and bottlenecks.
- **Phase 5 -- Human approval & exception handling:** not started.
  Supervisor review queue for low-confidence classifications and
  scheduling overrides.
- **Phase 6 -- Deployment:** not started. Docker Compose already covers
  local Postgres; a real cloud deployment (AWS or GCP) and GitHub Actions
  CI come once there's a full stack worth deploying.

## Architecture

```
POST /orders      -> FastAPI -> validate_order()   -> Postgres (orders table)
                                   |
                                   +-- required-field checks
                                   +-- duplicate check (normalized hash,
                                       24h window by default)

POST /employees   -> FastAPI -> Postgres (employees table)

POST /assignments/run?strategy=fcfs|optimized
                   -> FastAPI -> app/assignment.py -> Postgres
                        (validated, unassigned orders)  (employees)
                                 |
                                 +-- fcfs_assign(): greedy, submission order
                                 +-- optimized_assign(): OR-Tools CP-SAT,
                                     maximizes priority-weighted, capacity-
                                     constrained matches
```

No LLM, no live queue/dashboard yet -- those are Phase 3 and Phase 4.

## A note on Phase 1's design choices

**Malformed orders are stored, not bounced.** A `POST /orders` with a
missing `customer_name` still returns `201` with `status: "rejected"` and
a `validation_errors` list, rather than a bare `422`. The brief for this
phase is "validate their data ... and identify missing information before
processing begins" -- that's a request for *visibility*, not just
gatekeeping. An operator (or, later, a supervisor review queue in Phase 5)
needs to see what came in and why it failed, not just know that something
was rejected somewhere upstream and lost.

**Duplicate detection doesn't reject anything by itself.** A matched
duplicate is recorded as `status: "duplicate"` with `duplicate_of_id` set
-- it's a flag for a human or downstream logic to weigh (a customer might
legitimately submit the same request twice), not an automatic bounce.
Only missing/malformed fields produce `status: "rejected"`.

**The duplicate check is a normalized-content hash, not an LLM call.**
`normalize_for_dedupe()` lowercases, trims, and collapses whitespace in
`customer_name` + `location` + `description`, then hashes the result. Two
submissions that normalize to the same string, within
`DUPLICATE_WINDOW_MINUTES` (24h by default) of each other, are the same
request. This won't catch a duplicate that's reworded ("fix the sensor"
vs. "the sensor needs fixing") -- that's a real limitation, and a
plausible place for Phase 3's LLM classification step to eventually help.
But it's deterministic, instant, free, and testable, and reaching for an
LLM call on every single order ingested (before there's any evidence a
hash-based check isn't good enough) would be optimizing for the resume
bullet over the actual problem.

## A note on Phase 2's design choices

**`daily_capacity` resets every assignment run, not every calendar day.**
There's no availability calendar in Phase 2 -- `Employee.daily_capacity` is
"how many orders this employee can take on in one `/assignments/run` call,"
full stop. Running the endpoint twice in a row gives every employee a
fresh capacity budget both times; nothing tracks "already handed 3 orders
to Jordan this morning." That's a real limitation for a system meant to
run continuously, and the honest fix is a proper availability/calendar
model, not a bigger `daily_capacity` number -- which is exactly the kind
of thing to build when there's a concrete reason to (a live dashboard
showing today's actual load, in Phase 4), not speculatively now.

**Unmatched orders aren't retried automatically, aren't discarded either.**
An order that can't be assigned (no employee covers its skills, or
everyone capable is already at capacity for this run) stays at status
`"validated"`. It's simply eligible for the next `/assignments/run` call
-- add the missing-skill employee, free up capacity, run again. Nothing
about "can't assign this right now" is treated as a failure.

**FCFS and the optimizer share one skill-matching rule.** Both strategies
use the same `_skills_covered()` check (an employee needs *every* skill an
order lists, via plain `frozenset.issubset`) so the benchmark in the next
section is actually comparing *assignment strategy*, not two different
definitions of "can this employee do this job."

**Why CP-SAT over a greedy heuristic for the "optimized" path.** A hand-
written heuristic (e.g. "sort by priority, then greedily assign") gets
most of the benefit and is easier to reason about line by line -- but it's
still a heuristic, making locally-reasonable choices that can be globally
wrong (assigning a low-priority order to the one employee who could have
covered three urgent ones instead). CP-SAT solves the actual optimization
problem: maximize total priority-weighted value subject to the real
capacity constraints, all at once. `scripts/benchmark.py` is what turns
"CP-SAT should do better" into a number instead of an assumption.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate   # see note below
pip install -r requirements.txt
cp .env.example .env

docker compose up -d          # starts Postgres on localhost:5432
uvicorn app.api:app --reload --port 8001
```

A dedicated virtualenv isn't just tidiness here -- `ortools` bundles its
own compiled protobuf runtime, and installing it into an already-loaded
Anaconda `base` environment (particularly one with other native
extensions like pandas/pyarrow already present) risks a hard crash
(`Fatal Python error: Aborted`, protobuf "descriptor already in database")
the moment `ortools` gets imported, from two protobuf runtimes fighting
over the same descriptor registry. A clean venv sidesteps that instead of
trying to pin versions in a shared environment you don't fully control.

Try it:

```bash
curl -s -X POST localhost:8001/orders \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "Acme Corp", "description": "Replace the broken conveyor sensor", "location": "Austin, TX", "priority": "high"}'

curl -s localhost:8001/orders
curl -s "localhost:8001/orders?status=rejected"
```

Phase 2 -- add an employee, then run an assignment:

```bash
curl -s -X POST localhost:8001/employees \
  -H "Content-Type: application/json" \
  -d '{"name": "Jordan Diaz", "location": "Austin, TX", "skills": "electrical,hvac", "daily_capacity": 5}'

curl -s -X POST "localhost:8001/assignments/run?strategy=optimized"
curl -s localhost:8001/orders   # assigned orders now show assigned_employee_id
```

## Phase 2 benchmark results

```bash
python -m scripts.benchmark              # 1,000 orders, 40 employees, seed 42
python -m scripts.benchmark --orders 2000 --employees 80 --seed 7
```

Runs entirely in memory against synthetic data -- no Postgres, no API,
just `app/assignment.py`'s two functions on the same input, so the
comparison below is the algorithm difference and nothing else:

```
Synthetic dataset: 1000 orders, 40 employees (seed=42)

                                 FCFS            OR-Tools
-----------------------------------------------------------------
Orders assigned                  208/1000        208/1000
% assigned                       20.8%           20.8%
Priority-weight captured         20.4%           32.5%
Location match (of assigned)     54.3%           63.0%
Workload stdev across employees  1.54            1.54
Busiest employee's load          8               8
Runtime                          0.004s          ~1.1s
```

**What this actually shows.** With 40 employees averaging ~5.5 capacity
each against 1,000 incoming orders, total capacity is the hard ceiling --
both strategies assign exactly 208 orders, and neither can do better than
that without more staff. So the interesting comparison isn't "how many
got assigned," it's *which* 208. FCFS's priority-weight-captured (20.4%)
sits right where you'd expect from grabbing orders in arrival order with
no regard for urgency -- basically the same as its raw 20.8% assignment
rate, because arrival order doesn't correlate with priority. OR-Tools
captures 32.5%, a ~59% relative improvement: it's the same headcount and
the same total number of tickets closed, but urgent/high-priority work
gets through noticeably more often instead of losing out to whatever
happened to be submitted first. Location match improves too (54.3% ->
63.0%) for the same reason -- the solver is free to consider the whole
picture at once instead of committing to the first workable match it
finds. Workload balance across employees came out identical between the
two (both are equally capacity-bound, so there's no slack for either
strategy to distribute differently) -- that's a real result, not a
limitation of the benchmark.

The cost: OR-Tools takes roughly 1 second for this dataset size against
FCFS's 4 milliseconds. For a batch/periodic assignment run (which is what
`/assignments/run` is -- not a per-order real-time decision), that's a
non-issue; it would matter if this were called synchronously on every
single order submission instead.

*(These numbers are from one seeded run -- `python -m scripts.benchmark`
is right there to reproduce or challenge them.)*

## Tests

```bash
pytest
```

Tests run against an isolated in-memory SQLite database (see
`tests/conftest.py`) -- no Postgres required just to run the suite. The
app's real startup path still creates the Postgres schema via
`Base.metadata.create_all()`; tests skip that via `SKIP_DB_INIT=1` and use
their own engine instead, so `pytest` works the same on a laptop with no
Docker running as it does in CI.

`tests/test_assignment.py` tests `fcfs_assign()` and `optimized_assign()`
directly against plain dataclasses (no DB, no FastAPI) -- the
`optimized_assign` tests are skipped automatically (`pytest.importorskip`)
if `ortools` isn't installed, rather than failing the whole suite.

## Tech stack

- **FastAPI** -- REST API
- **SQLAlchemy 2.0 + PostgreSQL** -- storage
- **Google OR-Tools (CP-SAT)** -- Phase 2's optimized assignment
- **pytest** -- tests, running against isolated in-memory SQLite
- **Docker Compose** -- local Postgres

(React, Redis, Celery, LangGraph, and real cloud deployment arrive in
later phases -- see "Where this stands" above.)
