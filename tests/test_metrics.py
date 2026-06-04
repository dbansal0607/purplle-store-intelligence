# PROMPT: "Write a pytest suite for FastAPI retail analytics testing all-staff exclusion, zero purchase conversion safety, batch ingestion idempotency, and entry/re-entry deduplication using an in-memory SQLite database."
# CHANGES MADE: Added fixtures for shared memory SQLite cache context, and implemented asserts checking unique visitor deduplication.

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

from app.main import app, get_db
from app.database import Base, EventModel, PosTransactionModel

# Setup in-memory test database with shared cache for thread-safety in FastAPI
SQLALCHEMY_DATABASE_URL = "sqlite:///file:testdb?mode=memory&cache=shared"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False, "uri": True})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def test_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def test_health_check(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"

def test_metrics_division_by_zero_safety(client):
    res = client.get("/stores/STORE_TEST/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["unique_visitors"] == 0
    assert data["conversion_rate"] == 0.0
    assert data["abandonment_rate"] == 0.0

def test_events_ingestion_and_idempotency(client):
    # Ingest a valid event batch (returns 202 Accepted)
    event_id = "test-event-uuid-1"
    payload = [
        {
            "event_id": event_id,
            "store_id": "STORE_BLR_001",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_test_1",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T12:00:00Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {
                "queue_depth": None,
                "sku_zone": None,
                "session_seq": 1
            }
        }
    ]
    
    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 202
    data = res.json()
    assert data["status"] == "success"
    assert data["processed"] == 1
    assert data["duplicates"] == 0
    
    # Send same payload to verify idempotency (should skip database write and flag duplicate)
    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 202
    data = res.json()
    assert data["status"] == "success"
    assert data["processed"] == 0
    assert data["duplicates"] == 1

def test_conversion_rate_calculation(client, test_db):
    tx_time = datetime(2026, 4, 10, 12, 15, 0)
    tx = PosTransactionModel(
        order_id="TX_1",
        order_timestamp=tx_time,
        store_id="STORE_BLR_001",
        product_id="prod_1",
        brand_name="Faces Canada",
        total_amount=500.0
    )
    test_db.add(tx)
    
    # Seed converting customer (entered BILLING zone at 12:12:00, within 5-min checkout window)
    event_time = datetime(2026, 4, 10, 12, 12, 0)
    e1 = EventModel(
        event_id="e_1",
        store_id="STORE_BLR_001",
        camera_id="cam_billing",
        visitor_id="VIS_customer_1",
        event_type="ZONE_ENTER",
        timestamp=event_time,
        zone_id="BILLING",
        dwell_ms=0,
        is_staff=False,
        confidence=0.99,
        queue_depth=None,
        sku_zone="BILLING",
        session_seq=1
    )
    test_db.add(e1)
    test_db.commit()
    
    # Request metrics
    res = client.get("/stores/STORE_BLR_001/metrics")
    assert res.status_code == 200
    data = res.json()
    
    # Unique visitors query looks for ENTRY event, let's make sure e1 has an entry event as well
    # (Otherwise unique visitors is 0, since we now filter by event_type == "ENTRY"!)
    # Let's seed e_entry first.
    e_entry = EventModel(
        event_id="e_entry",
        store_id="STORE_BLR_001",
        camera_id="cam_entry",
        visitor_id="VIS_customer_1",
        event_type="ENTRY",
        timestamp=event_time - timedelta(minutes=5),
        zone_id=None,
        dwell_ms=0,
        is_staff=False,
        confidence=0.95,
        queue_depth=None,
        sku_zone=None,
        session_seq=0
    )
    test_db.add(e_entry)
    test_db.commit()

    res = client.get("/stores/STORE_BLR_001/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["unique_visitors"] == 1
    assert data["conversion_rate"] == 100.0

def test_funnel_generation(client, test_db):
    tx = PosTransactionModel(
        order_id="TX_2",
        order_timestamp=datetime(2026, 4, 10, 12, 15, 0),
        store_id="STORE_BLR_001",
        product_id="prod_2",
        brand_name="NY Bae",
        total_amount=300.0
    )
    test_db.add(tx)
    
    # Events for VIS_1 (Entry only)
    e_vis1_entry = EventModel(
        event_id="e_vis1", store_id="STORE_BLR_001", camera_id="cam_entry",
        visitor_id="VIS_1", event_type="ENTRY", timestamp=datetime(2026, 4, 10, 12, 0, 0),
        zone_id=None, is_staff=False, session_seq=1
    )
    
    # Events for VIS_2 (Full conversion path)
    e_vis2_entry = EventModel(
        event_id="e_vis2_1", store_id="STORE_BLR_001", camera_id="cam_entry",
        visitor_id="VIS_2", event_type="ENTRY", timestamp=datetime(2026, 4, 10, 12, 5, 0),
        zone_id=None, is_staff=False, session_seq=1
    )
    e_vis2_shelf = EventModel(
        event_id="e_vis2_2", store_id="STORE_BLR_001", camera_id="cam_zone",
        visitor_id="VIS_2", event_type="ZONE_ENTER", timestamp=datetime(2026, 4, 10, 12, 6, 0),
        zone_id="SKINCARE", is_staff=False, session_seq=2
    )
    e_vis2_billing = EventModel(
        event_id="e_vis2_3", store_id="STORE_BLR_001", camera_id="cam_billing",
        visitor_id="VIS_2", event_type="ZONE_ENTER", timestamp=datetime(2026, 4, 10, 12, 12, 0),
        zone_id="BILLING", is_staff=False, session_seq=3
    )
    
    # BUG #23 Fix: Seed a third visitor with a non-ENTRY event (e.g. ZONE_ENTER only)
    # This visitor must be excluded from Stage 1 (Entry)
    e_vis3_no_entry = EventModel(
        event_id="e_vis3", store_id="STORE_BLR_001", camera_id="cam_zone",
        visitor_id="VIS_3", event_type="ZONE_ENTER", timestamp=datetime(2026, 4, 10, 12, 8, 0),
        zone_id="SKINCARE", is_staff=False, session_seq=1
    )
    
    test_db.add(e_vis1_entry)
    test_db.add(e_vis2_entry)
    test_db.add(e_vis2_shelf)
    test_db.add(e_vis2_billing)
    test_db.add(e_vis3_no_entry)
    test_db.commit()
    
    res = client.get("/stores/STORE_BLR_001/funnel")
    assert res.status_code == 200
    funnel = res.json()["funnel"]
    
    # Entry count: 2 (VIS_1, VIS_2. VIS_3 is ignored because they have no ENTRY event)
    assert funnel[0]["stage_name"] == "Entry"
    assert funnel[0]["count"] == 2
    
    # Zone Visit count: 1 (VIS_2)
    assert funnel[1]["stage_name"] == "Zone Visit"
    assert funnel[1]["count"] == 1
    assert funnel[1]["drop_off_pct"] == 50.0

def test_all_staff_clip_exclusion(client, test_db):
    """
    All-staff clip: Ingest multiple events with is_staff=True, verify unique_visitors = 0.
    """
    for i in range(20):
        e = EventModel(
            event_id=f"staff-e-{i}", store_id="STORE_BLR_001", camera_id="cam_entry",
            visitor_id=f"VIS_STAFF_{i}", event_type="ENTRY", timestamp=datetime(2026, 4, 10, 12, 0, 0),
            zone_id=None, is_staff=True, session_seq=1
        )
        test_db.add(e)
    test_db.commit()
    
    res = client.get("/stores/STORE_BLR_001/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["unique_visitors"] == 0

def test_zero_purchases_conversion_safety(client, test_db):
    """
    Zero purchases: Ingest ENTRY + BILLING events but no POS transactions, verify conversion_rate = 0.0.
    """
    e_entry = EventModel(
        event_id="e_ent", store_id="STORE_BLR_001", camera_id="cam_entry",
        visitor_id="VIS_shopper", event_type="ENTRY", timestamp=datetime(2026, 4, 10, 12, 0, 0),
        zone_id=None, is_staff=False, session_seq=1
    )
    e_bill = EventModel(
        event_id="e_bil", store_id="STORE_BLR_001", camera_id="cam_billing",
        visitor_id="VIS_shopper", event_type="ZONE_ENTER", timestamp=datetime(2026, 4, 10, 12, 10, 0),
        zone_id="BILLING", is_staff=False, session_seq=2
    )
    test_db.add(e_entry)
    test_db.add(e_bill)
    test_db.commit()
    
    res = client.get("/stores/STORE_BLR_001/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["conversion_rate"] == 0.0

def test_batch_ingestion_idempotency_bulk(client):
    """
    Idempotency: send same 10 events twice, verify duplicates = 10 on second call.
    """
    payload = []
    for i in range(10):
        payload.append({
            "event_id": f"event-bulk-{i}",
            "store_id": "STORE_BLR_001",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": f"VIS_bulk_{i}",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T12:00:00Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {
                "queue_depth": None,
                "sku_zone": None,
                "session_seq": 1
            }
        })
        
    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 202
    data = res.json()
    assert data["processed"] == 10
    assert data["duplicates"] == 0
    
    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 202
    data = res.json()
    assert data["processed"] == 0
    assert data["duplicates"] == 10

def test_reentry_not_double_counted(client, test_db):
    """
    Re-entry: ENTRY + REENTRY for same visitor_id results in exactly 1 unique visitor.
    """
    e_entry = EventModel(
        event_id="e_first", store_id="STORE_BLR_001", camera_id="cam_entry",
        visitor_id="VIS_returning_shopp", event_type="ENTRY", timestamp=datetime(2026, 4, 10, 12, 0, 0),
        zone_id=None, is_staff=False, session_seq=1
    )
    e_exit = EventModel(
        event_id="e_exit", store_id="STORE_BLR_001", camera_id="cam_entry",
        visitor_id="VIS_returning_shopp", event_type="EXIT", timestamp=datetime(2026, 4, 10, 12, 5, 0),
        zone_id=None, is_staff=False, session_seq=2
    )
    e_reentry = EventModel(
        event_id="e_again", store_id="STORE_BLR_001", camera_id="cam_entry",
        visitor_id="VIS_returning_shopp", event_type="REENTRY", timestamp=datetime(2026, 4, 10, 12, 10, 0),
        zone_id=None, is_staff=False, session_seq=3
    )
    
    test_db.add(e_entry)
    test_db.add(e_exit)
    test_db.add(e_reentry)
    test_db.commit()
    
    res = client.get("/stores/STORE_BLR_001/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["unique_visitors"] == 1
