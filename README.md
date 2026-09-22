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

- **Phase 1 -- Order ingestion (this commit):** done. REST API for
  submitting orders, deterministic validation (required fields, valid
  priority), and deterministic duplicate detection (normalized-content
  hash within a configurable time window). See "A note on Phase 1's design
  choices" below.
- **Phase 2 -- Scheduling & optimization:** not started. Assign orders to
  employees by skill/location/availability/workload using Google OR-Tools,
  benchmarked against first-come-first-served on a synthetic 1,000-order
  dataset (completion time, workload distribution, missed deadlines).
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

## Architecture (Phase 1)

```
POST /orders  ->  FastAPI  ->  validate_order()  ->  Postgres (orders table)
                                 |
                                 +-- required-field checks
                                 +-- duplicate check (normalized hash,
                                     24h window by default)
```

No LLM, no queue, no scheduler yet -- Phase 1 is deliberately just this.

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

## Setup

```bash
pip install -r requirements.txt --break-system-packages   # if using conda's base env
cp .env.example .env

docker compose up -d          # starts Postgres on localhost:5432
uvicorn app.api:app --reload --port 8001
```

Try it:

```bash
curl -s -X POST localhost:8001/orders \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "Acme Corp", "description": "Replace the broken conveyor sensor", "location": "Austin, TX", "priority": "high"}'

curl -s localhost:8001/orders
curl -s "localhost:8001/orders?status=rejected"
```

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

## Tech stack (Phase 1)

- **FastAPI** -- REST API
- **SQLAlchemy 2.0 + PostgreSQL** -- storage
- **pytest** -- tests, running against isolated in-memory SQLite
- **Docker Compose** -- local Postgres

(React, Redis, Celery, LangGraph, OR-Tools, and real cloud deployment
arrive in later phases -- see "Where this stands" above.)
