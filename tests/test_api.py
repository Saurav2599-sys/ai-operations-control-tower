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
