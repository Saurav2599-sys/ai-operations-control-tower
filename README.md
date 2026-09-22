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
- **Phase 3 -- AI-assisted classification:** done. `POST /orders`
  automatically classifies the free-text `description` with an LLM
  (forced tool-calling, not a hopeful system prompt) whenever
  `required_skills` wasn't given, and `POST /orders/{id}/classify`
  re-runs it on demand. The suggestion is always visible; it only fills
  `required_skills` in, and only above a confidence threshold -- see "A
  note on Phase 3's design choices" below.
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

POST /orders (required_skills blank)
POST /orders/{id}/classify
                   -> FastAPI -> app/classification.py -> OpenAI
                        (forced tool call: extract_order_requirements)
                                 |
                                 +-- always stored: ai_suggested_skills,
                                     ai_suggested_priority, ai_confidence,
                                     ai_reasoning, ai_classified_at
                                 +-- required_skills filled in only if it
                                     was blank AND confidence clears
                                     CLASSIFICATION_CONFIDENCE_THRESHOLD
                                 +-- priority is never auto-applied, at
                                     any confidence
```

No live queue/dashboard yet -- that's Phase 4.

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

## A note on Phase 3's design choices

**A suggestion, never an override.** Every classification result is stored
in its own `ai_*` columns (`ai_suggested_skills`, `ai_suggested_priority`,
`ai_confidence`, `ai_reasoning`, `ai_classified_at`) -- separate from the
authoritative `required_skills` and `priority` fields the rest of the
system actually acts on. `required_skills` is copied over from the
suggestion only when it was blank to begin with *and* `ai_confidence`
clears `CLASSIFICATION_CONFIDENCE_THRESHOLD` (0.6 by default). If a human
already specified `required_skills`, classification for that order isn't
even run.

**`priority` is never auto-applied, at any confidence.** Skills and
priority get treated differently on purpose. A wrong guessed skill mostly
costs efficiency -- the wrong employee gets considered, or a coverable
order doesn't get matched this run, both recoverable. A wrong priority is
a different kind of mistake: it changes whose problem gets treated as
urgent, and getting that wrong has real consequences in a system meant to
actually run a business. `ai_suggested_priority` is always visible in the
response for a human (or Phase 5's review queue) to act on, but nothing
in Phase 3 writes it into `priority` for them.

**Why 0.6.** It's a starting point, not a tuned number -- there's no
labeled production traffic yet to tune it against. It's deliberately on
the conservative side (a coin-flip-confidence suggestion doesn't get
applied), and it's a single env var (`CLASSIFICATION_CONFIDENCE_THRESHOLD`)
specifically so it can move once real data says it should, without a code
change.

**The tool call is forced, not requested.** `classify_order()` passes
`tool_choice={"type": "function", "function": {"name":
"extract_order_requirements"}}` rather than leaving it to the model's
discretion. This is the same lesson the
[Autonomous Workflow Broker](https://github.com/Saurav2599-sys/autonomous-workflow-broker)
project learned the hard way: a system prompt that says "you must call
this tool" is a request the model is free to ignore; `tool_choice` pinned
to one specific tool isn't a request.

**Defense in depth on the model's output, even with a constrained schema.**
`required_skills` is JSON-schema-enum-constrained to
`app.constants.SKILL_POOL`, but `classify_order()` still filters the
returned list against that same pool before using it, clamps `confidence`
into `[0.0, 1.0]`, and falls back `suggested_priority` to `"normal"` if
it's not one of the four allowed values. None of that should be reachable
given the schema -- it's there because "should be unreachable" and "is
unreachable" aren't the same claim, and a hallucinated skill silently
making it into `required_skills` would make an order permanently
unassignable without anyone knowing why.

**A classification failure never fails order submission.** If the OpenAI
call errors, times out, or returns something `classify_order()` can't
parse, `_run_classification()` (used at submission time) catches
`ClassificationError` and simply leaves the `ai_*` fields blank -- the
order still gets created and validated normally. Phase 3 is an enrichment
layer order ingestion doesn't depend on, not a hard dependency; an
OpenAI outage shouldn't take `/orders` down with it. `POST
/orders/{id}/classify`, by contrast, does surface a failure (as a `502`)
-- there, the caller explicitly asked for a classification result and
deserves to know it didn't get one, rather than a silent no-op.

**It's a synchronous call inside the request, for now.** `POST /orders`
blocks on the OpenAI call when it fires, adding real LLM latency (see the
eval results below for what that latency actually is) to that request. No
queue, no background worker for this yet. That's an acceptable tradeoff at
current scale and becomes the obvious thing to fix -- a background job,
the same way the Autonomous Workflow Broker project uses Celery -- once
it's an actual measured problem rather than a hypothetical one.

**Plain OpenAI SDK over a framework.** No LangChain, no agent framework --
one function-calling request, one tool, one deterministic parse of the
result. A framework earns its keep when there's real multi-step agentic
complexity to manage; a single forced tool call isn't that, and pulling
one in here would be dependency weight without a matching benefit.

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

Phase 3 needs a real `OPENAI_API_KEY` in `.env` to actually call the
model -- without one, `POST /orders` and `POST /orders/{id}/classify`
still work, they just leave the `ai_*` fields blank (see "A classification
failure never fails order submission" above).

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

Phase 3 -- submit an order with no `required_skills` and let the model
suggest them, then re-classify an existing order on demand:

```bash
curl -s -X POST localhost:8001/orders \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "Acme Corp", "description": "The AC unit stopped working completely and it is 95 degrees inside the warehouse", "location": "Austin, TX", "priority": "normal"}'
# -> required_skills is filled in from ai_suggested_skills if confidence
#    cleared the threshold; ai_suggested_priority, ai_confidence, and
#    ai_reasoning are always in the response either way

curl -s -X POST localhost:8001/orders/1/classify
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

## Phase 3 eval results

```bash
python -m scripts.eval_classification
```

Unlike the Phase 2 benchmark, this makes real OpenAI API calls (18 of
them, one per hand-labeled case in `scripts/eval_classification.py`) --
needs a real `OPENAI_API_KEY` in `.env`, costs a small real amount of
money per run, and isn't reproducible bit-for-bit the way a seeded
in-memory benchmark is. The eval set is 18 realistic work-order
descriptions I hand-labeled myself, spanning all 8 skills in
`app.constants.SKILL_POOL` and all 4 priority levels -- a small,
subjective ground truth, not a rigorous benchmark, but enough to catch
obviously bad extractions and produce a real, reproducible-in-kind number
instead of a vibe.

```
                            Value
--------------------------------------
Cases evaluated              18/18
Failed calls                 0
Skill exact-match rate       66.7%
Skill precision (mean)       74.3%
Skill recall (mean)          86.1%
Skill F1 (mean)              74.1%
Priority accuracy            61.1%
Mean confidence reported     0.67
Mean latency/call            1.22s
```

**What this actually shows.** This run is after the majority-of-pool
guard described below was added, and its fingerprint is right there in
the numbers: 3 of 18 cases (17%) still got the same repeatable failure
mode a first, pre-guard run surfaced -- the model returning *all 8
skills in the pool* instead of the 1-2 that actually applied (e.g. "one
of the exposed wires near the breaker panel is sparking," expected:
`electrical`, came back with `carpentry, electrical, general_repair,
hvac, inspection, painting, plumbing, welding`) -- but this time reported
at `conf=0.00` instead of the 0.80-0.90 the pre-guard run showed for the
same pattern. `classify_order()` now clamps confidence to 0 whenever it
returns a majority of the entire pool at once (real orders never need
more than a couple of skills; see `tests/test_classification.py`'s
`test_classify_order_treats_majority_of_pool_as_untrustworthy`), so
these three can never clear `CLASSIFICATION_CONFIDENCE_THRESHOLD` and
silently overwrite `required_skills` -- the raw (still-wrong) suggestion
just stays visible in `ai_suggested_skills` for a human to look at.

Worth being honest about what the guard does and doesn't fix: skill
precision/recall/F1 here (74.3% / 86.1% / 74.1%) are barely different
from the pre-guard run (75.0% / 91.7% / 75.3%) -- and that's expected,
not a sign the guard failed. This eval script scores raw extraction
quality (`suggested_skills` vs. the hand-labeled answer), which the guard
doesn't touch; it only stops a bad extraction from being *trusted*. The
guard's actual effect shows up in mean confidence dropping from 0.81 to
0.67 -- that's three real cases getting hard-clamped to 0 instead of
sailing through the threshold. Fixing the extraction itself (getting the
model to stop returning the whole pool in the first place) is a separate,
open problem -- prompt tuning, a stricter system message, or a smaller
`max_tokens` are plausible next things to try, not attempted here.

Priority accuracy (61.1%) and the skill scores both moved a bit from the
first run purely from real API non-determinism -- same 18 cases, same
model, different day, slightly different answers (e.g. the ceiling-tile
repainting case was wrong the first run and right this one; the fire-
extinguisher inspection case was right the first run and missed this
one). That's disclosed here rather than smoothed over: these are live
calls to a non-deterministic model, not a seeded, reproducible benchmark
like Phase 2's.

Mean latency (1.22s/call) is the real cost of the synchronous design
choice described above -- every `POST /orders` that triggers
classification blocks for roughly that long.

*(These numbers are from one real run against an 18-case, hand-labeled
set -- `python -m scripts.eval_classification` is right there to
reproduce or challenge them, and a re-run will likely differ slightly for
the reasons above.)*

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

`tests/test_classification.py` tests `classify_order()` against a fake
OpenAI client (no real API key or network call needed) -- forced
tool-choice, skill-pool filtering, priority fallback, confidence clamping,
and error handling on a malformed or failed call. The Phase 3 tests in
`tests/test_api.py` go through the real HTTP layer with
`classify_order` monkeypatched, so they prove the suggest-don't-override
wiring (confidence threshold, graceful degradation on `POST /orders`,
`502` on a failed `POST /orders/{id}/classify`) without spending real API
calls on every test run.

## Tech stack

- **FastAPI** -- REST API
- **SQLAlchemy 2.0 + PostgreSQL** -- storage
- **Google OR-Tools (CP-SAT)** -- Phase 2's optimized assignment
- **OpenAI SDK (function/tool-calling)** -- Phase 3's classification
- **pytest** -- tests, running against isolated in-memory SQLite
- **Docker Compose** -- local Postgres

(React, Redis, Celery, LangGraph, and real cloud deployment arrive in
later phases -- see "Where this stands" above.)
