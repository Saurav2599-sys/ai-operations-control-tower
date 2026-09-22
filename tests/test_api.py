"""End-to-end tests through the actual HTTP layer (FastAPI TestClient),
against an isolated in-memory DB per test -- see tests/conftest.py."""


def test_submit_valid_order_returns_validated(client):
    resp = client.post("/orders", json={
        "customer_name": "Acme Corp",
        "description": "Replace the broken conveyor sensor",
        "location": "Austin, TX",
        "priority": "high",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "validated"
    assert body["validation_errors"] == []
    assert body["duplicate_of_id"] is None


def test_submit_order_missing_fields_is_recorded_not_bounced(client):
    """Malformed orders are still stored (status=rejected) rather than
    thrown away with a bare 4xx -- the whole point of Phase 1 is
    visibility into what came in and why it failed, not just gatekeeping."""
    resp = client.post("/orders", json={
        "customer_name": "",
        "description": "",
        "priority": "normal",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "rejected"
    assert "missing customer_name" in body["validation_errors"]
    assert "missing description" in body["validation_errors"]


def test_duplicate_submission_is_flagged_against_the_first(client):
    first = client.post("/orders", json={
        "customer_name": "Beta LLC",
        "description": "Onsite inspection of unit 4",
        "location": "Denver, CO",
        "priority": "normal",
    }).json()
    assert first["status"] == "validated"

    second = client.post("/orders", json={
        "customer_name": "Beta LLC",
        "description": "onsite inspection of unit 4",
        "location": "denver, co",
        "priority": "normal",
    }).json()
    assert second["status"] == "duplicate"
    assert second["duplicate_of_id"] == first["id"]


def test_list_orders_filters_by_status(client):
    client.post("/orders", json={
        "customer_name": "Gamma Inc", "description": "Valid order",
        "location": "Reno, NV", "priority": "low",
    })
    client.post("/orders", json={
        "customer_name": "", "description": "", "priority": "normal",
    })

    rejected = client.get("/orders", params={"status": "rejected"}).json()
    validated = client.get("/orders", params={"status": "validated"}).json()
    assert len(rejected) == 1
    assert len(validated) == 1
    assert rejected[0]["status"] == "rejected"
    assert validated[0]["status"] == "validated"


def test_get_nonexistent_order_is_404(client):
    resp = client.get("/orders/99999")
    assert resp.status_code == 404


# ---- Phase 2: employees + assignment -------------------------------------

def test_create_and_list_employees(client):
    resp = client.post("/employees", json={
        "name": "Jordan Diaz", "location": "Austin, TX",
        "skills": "plumbing,hvac", "daily_capacity": 3,
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Jordan Diaz"
    assert body["daily_capacity"] == 3

    listed = client.get("/employees").json()
    assert len(listed) == 1
    assert listed[0]["name"] == "Jordan Diaz"


def test_assignment_run_fcfs_assigns_matching_order(client):
    client.post("/employees", json={
        "name": "Jordan Diaz", "location": "Austin, TX",
        "skills": "plumbing", "daily_capacity": 5,
    })
    order = client.post("/orders", json={
        "customer_name": "Acme Corp", "description": "Fix the leaking pipe",
        "location": "Austin, TX", "priority": "high", "required_skills": "plumbing",
    }).json()
    assert order["status"] == "validated"

    result = client.post("/assignments/run", params={"strategy": "fcfs"}).json()
    assert result["assigned"] == 1
    assert order["id"] in result["assigned_order_ids"]

    refreshed = client.get(f"/orders/{order['id']}").json()
    assert refreshed["status"] == "assigned"
    assert refreshed["assigned_employee_id"] is not None
    assert refreshed["assigned_at"] is not None


def test_assignment_run_leaves_uncoverable_order_as_validated(client):
    client.post("/employees", json={
        "name": "Jordan Diaz", "location": "Austin, TX",
        "skills": "plumbing", "daily_capacity": 5,
    })
    order = client.post("/orders", json={
        "customer_name": "Acme Corp", "description": "Rewire the panel",
        "location": "Austin, TX", "priority": "high", "required_skills": "electrical",
    }).json()

    result = client.post("/assignments/run", params={"strategy": "fcfs"}).json()
    assert result["assigned"] == 0
    assert result["unassigned"] == 1

    refreshed = client.get(f"/orders/{order['id']}").json()
    assert refreshed["status"] == "validated"
    assert refreshed["assigned_employee_id"] is None


def test_assignment_run_rejects_unknown_strategy(client):
    resp = client.post("/assignments/run", params={"strategy": "bogus"})
    assert resp.status_code == 400


# ---- Phase 3: classification -----------------------------------------

def test_submit_order_without_skills_runs_classification_and_fills_on_high_confidence(
    client, monkeypatch
):
    import app.api as api_module
    from app.classification import ClassificationResult

    def fake_classify(description):
        return ClassificationResult(
            suggested_skills=frozenset({"hvac"}),
            suggested_priority="high",
            confidence=0.9,
            reasoning="Mentions a broken AC unit.",
        )

    monkeypatch.setattr(api_module, "classify_order", fake_classify)

    resp = client.post("/orders", json={
        "customer_name": "Acme Corp", "description": "The AC is broken",
        "location": "Austin, TX", "priority": "normal",
    })
    body = resp.json()
    assert body["required_skills"] == "hvac"
    assert body["ai_suggested_skills"] == "hvac"
    assert body["ai_suggested_priority"] == "high"
    assert body["ai_confidence"] == 0.9
    assert body["ai_classified_at"] is not None


def test_submit_order_low_confidence_suggestion_is_visible_but_not_applied(client, monkeypatch):
    import app.api as api_module
    from app.classification import ClassificationResult

    def fake_classify(description):
        return ClassificationResult(
            suggested_skills=frozenset({"electrical"}),
            suggested_priority="low",
            confidence=0.2,
            reasoning="Vague description.",
        )

    monkeypatch.setattr(api_module, "classify_order", fake_classify)

    resp = client.post("/orders", json={
        "customer_name": "Acme Corp", "description": "Something's off",
        "location": "Austin, TX", "priority": "normal",
    })
    body = resp.json()
    assert body["required_skills"] is None
    assert body["ai_suggested_skills"] == "electrical"
    assert body["ai_confidence"] == 0.2


def test_submit_order_with_explicit_skills_never_calls_classification(client, monkeypatch):
    import app.api as api_module

    calls = []

    def fake_classify(description):
        calls.append(description)
        return None  # would blow up if actually used -- shouldn't be

    monkeypatch.setattr(api_module, "classify_order", fake_classify)

    resp = client.post("/orders", json={
        "customer_name": "Acme Corp", "description": "Fix the pipe",
        "location": "Austin, TX", "priority": "normal", "required_skills": "plumbing",
    })
    body = resp.json()
    assert body["required_skills"] == "plumbing"
    assert body["ai_suggested_skills"] is None
    assert calls == []


def test_submit_order_classification_failure_degrades_gracefully(client, monkeypatch):
    import app.api as api_module
    from app.classification import ClassificationError

    def fake_classify(description):
        raise ClassificationError("boom")

    monkeypatch.setattr(api_module, "classify_order", fake_classify)

    resp = client.post("/orders", json={
        "customer_name": "Acme Corp", "description": "Fix the thing",
        "location": "Austin, TX", "priority": "normal",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "validated"
    assert body["ai_suggested_skills"] is None


def test_reclassify_endpoint_applies_result(client, monkeypatch):
    import app.api as api_module
    from app.classification import ClassificationResult

    order = client.post("/orders", json={
        "customer_name": "Acme Corp", "description": "Something vague",
        "location": "Austin, TX", "priority": "normal",
    }).json()
    assert order["required_skills"] is None

    def fake_classify(description):
        return ClassificationResult(
            suggested_skills=frozenset({"carpentry"}),
            suggested_priority="normal",
            confidence=0.95,
            reasoning="Reclassified.",
        )

    monkeypatch.setattr(api_module, "classify_order", fake_classify)

    resp = client.post(f"/orders/{order['id']}/classify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["required_skills"] == "carpentry"


def test_reclassify_endpoint_404_for_missing_order(client):
    resp = client.post("/orders/99999/classify")
    assert resp.status_code == 404


def test_reclassify_endpoint_surfaces_failure_as_502(client, monkeypatch):
    import app.api as api_module
    from app.classification import ClassificationError

    order = client.post("/orders", json={
        "customer_name": "Acme Corp", "description": "Something",
        "location": "Austin, TX", "priority": "normal",
    }).json()

    def fake_classify(description):
        raise ClassificationError("boom")

    monkeypatch.setattr(api_module, "classify_order", fake_classify)

    resp = client.post(f"/orders/{order['id']}/classify")
    assert resp.status_code == 502
