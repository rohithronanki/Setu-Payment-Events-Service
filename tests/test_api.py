"""
Tests for Setu Payment Events Service.
conftest.py sets DATABASE_URL=sqlite:///./test.db before anything loads,
so all imports here already point at the SQLite engine.
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import TestingSessionLocal, engine_test
from app.db.session import Base, get_db
from app.models.models import Merchant, Transaction, PaymentEvent
from app.main import app as fastapi_app


# ── DB override: every request uses the SQLite test session ─────────────────
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

fastapi_app.dependency_overrides[get_db] = override_get_db


# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def clean_tables():
    """Delete all rows before each test — tables stay, data is wiped."""
    db = TestingSessionLocal()
    try:
        db.execute(PaymentEvent.__table__.delete())
        db.execute(Transaction.__table__.delete())
        db.execute(Merchant.__table__.delete())
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture()
def client():
    with TestClient(fastapi_app) as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────────────────
BASE_EVENT = {
    "event_id": "evt-001",
    "event_type": "payment_initiated",
    "transaction_id": "txn-001",
    "merchant_id": "merchant_1",
    "merchant_name": "QuickMart",
    "amount": 1000.00,
    "currency": "INR",
    "timestamp": "2026-01-10T10:00:00+00:00",
}


def make_event(**overrides):
    return {**BASE_EVENT, **overrides}


# ── Tests ─────────────────────────────────────────────────────────────────────
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ingest_single_event(client):
    r = client.post("/events", json=BASE_EVENT)
    assert r.status_code == 200
    assert r.json()["status"] == "created"


def test_ingest_duplicate_event_is_idempotent(client):
    client.post("/events", json=BASE_EVENT)
    r = client.post("/events", json=BASE_EVENT)
    assert r.status_code == 200
    assert r.json()["status"] == "duplicate"


def test_ingest_invalid_event_missing_field(client):
    bad = {k: v for k, v in BASE_EVENT.items() if k != "event_type"}
    r = client.post("/events", json=bad)
    assert r.status_code == 422


def test_ingest_invalid_event_type(client):
    r = client.post("/events", json=make_event(event_type="refund_initiated"))
    assert r.status_code == 422


def test_ingest_negative_amount(client):
    r = client.post("/events", json=make_event(amount=-100))
    assert r.status_code == 422


def test_full_happy_path(client):
    events = [
        make_event(event_id="e1", event_type="payment_initiated"),
        make_event(event_id="e2", event_type="payment_processed",
                   timestamp="2026-01-10T10:05:00+00:00"),
        make_event(event_id="e3", event_type="settled",
                   timestamp="2026-01-10T10:15:00+00:00"),
    ]
    for ev in events:
        r = client.post("/events", json=ev)
        assert r.json()["status"] == "created"

    r = client.get(f"/transactions/{BASE_EVENT['transaction_id']}")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "settled"
    assert data["is_settled"] is True
    assert len(data["events"]) == 3


def test_failed_payment_does_not_become_settled(client):
    events = [
        make_event(event_id="e1", event_type="payment_initiated"),
        make_event(event_id="e2", event_type="payment_failed",
                   timestamp="2026-01-10T10:05:00+00:00"),
        make_event(event_id="e3", event_type="settled",
                   timestamp="2026-01-10T10:15:00+00:00"),
    ]
    for ev in events:
        client.post("/events", json=ev)
    r = client.get(f"/transactions/{BASE_EVENT['transaction_id']}")
    assert r.json()["status"] == "failed"


def test_list_transactions_empty(client):
    r = client.get("/transactions")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_list_transactions_filter_by_merchant(client):
    client.post("/events", json=BASE_EVENT)
    client.post("/events", json=make_event(
        event_id="e-other", transaction_id="txn-002",
        merchant_id="merchant_2", merchant_name="FreshBasket"
    ))
    r = client.get("/transactions?merchant_id=merchant_1")
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["merchant_id"] == "merchant_1"


def test_list_transactions_filter_by_status(client):
    client.post("/events", json=BASE_EVENT)
    r = client.get("/transactions?status=initiated")
    assert r.json()["total"] == 1
    r = client.get("/transactions?status=settled")
    assert r.json()["total"] == 0


def test_list_transactions_pagination(client):
    for i in range(5):
        client.post("/events", json=make_event(
            event_id=f"e-{i}", transaction_id=f"txn-{i:03d}",
            timestamp=f"2026-01-{10+i:02d}T10:00:00+00:00"
        ))
    r = client.get("/transactions?page=1&page_size=2")
    data = r.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    r2 = client.get("/transactions?page=3&page_size=2")
    assert len(r2.json()["items"]) == 1


def test_get_transaction_not_found(client):
    r = client.get("/transactions/nonexistent-id")
    assert r.status_code == 404


def test_get_transaction_detail_with_events(client):
    client.post("/events", json=BASE_EVENT)
    r = client.get(f"/transactions/{BASE_EVENT['transaction_id']}")
    assert r.status_code == 200
    data = r.json()
    assert data["transaction_id"] == BASE_EVENT["transaction_id"]
    assert data["merchant"]["merchant_id"] == "merchant_1"
    assert len(data["events"]) == 1


def test_bulk_ingest(client):
    events = [make_event(event_id=f"bulk-{i}", transaction_id=f"btxn-{i}") for i in range(10)]
    r = client.post("/events/bulk", json=events)
    assert r.status_code == 200
    assert r.json()["created"] == 10
    assert r.json()["duplicate"] == 0


def test_bulk_ingest_with_duplicates(client):
    events = [make_event(event_id=f"bd-{i}", transaction_id=f"bdtxn-{i}") for i in range(5)]
    client.post("/events/bulk", json=events)
    r = client.post("/events/bulk", json=events)
    assert r.json()["duplicate"] == 5
    assert r.json()["created"] == 0


def test_bulk_ingest_exceeds_limit(client):
    events = [make_event(event_id=f"x-{i}", transaction_id=f"xtxn-{i}") for i in range(5001)]
    r = client.post("/events/bulk", json=events)
    assert r.status_code == 422


def test_reconciliation_summary_empty(client):
    r = client.get("/reconciliation/summary")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_reconciliation_summary_with_data(client):
    client.post("/events", json=BASE_EVENT)
    r = client.get("/reconciliation/summary")
    data = r.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert "merchant_id" in item
    assert "transaction_count" in item
    assert "total_amount" in item


def test_reconciliation_discrepancies_empty(client):
    r = client.get("/reconciliation/discrepancies")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_reconciliation_discrepancies_settled_after_failure(client):
    client.post("/events", json=make_event(event_id="d1", event_type="payment_initiated"))
    client.post("/events", json=make_event(event_id="d2", event_type="payment_failed",
                                           timestamp="2026-01-10T10:05:00+00:00"))
    client.post("/events", json=make_event(event_id="d3", event_type="settled",
                                           timestamp="2026-01-10T10:10:00+00:00"))
    r = client.get("/reconciliation/discrepancies")
    data = r.json()
    assert data["total"] >= 1
    types = [item["discrepancy_type"] for item in data["items"]]
    assert "settled_after_failure" in types


def test_reconciliation_discrepancies_filter_by_merchant(client):
    r = client.get("/reconciliation/discrepancies?merchant_id=merchant_99")
    assert r.status_code == 200
    assert r.json()["total"] == 0
