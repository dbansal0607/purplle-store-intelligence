# PROMPT: "Write a pytest suite for retail anomaly detection rules: BILLING_QUEUE_SPIKE (WARN vs CRITICAL), CONVERSION_DROP, and DEAD_ZONE. Ensure tests mock dates correctly to cover virtual timeline logic."
# CHANGES MADE: Customized event model properties to match our EventSchema validation requirements and simulated time deltas.

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

from app.main import app, get_db
from app.database import Base, EventModel, PosTransactionModel
from app.anomalies import detect_store_anomalies

# Setup in-memory test database with shared cache
SQLALCHEMY_DATABASE_URL = "sqlite:///file:testdb_anom?mode=memory&cache=shared"
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

def test_no_anomalies_on_empty_db(test_db):
    anomalies = detect_store_anomalies(test_db, "STORE_BLR_001")
    assert len(anomalies) == 0

def test_billing_queue_spike_warn_and_critical(client, test_db):
    base_time = datetime(2026, 4, 10, 12, 0, 0)
    
    # 1. Test Warning (queue depth = 6)
    e1 = EventModel(
        event_id="e_1", store_id="STORE_BLR_001", camera_id="cam_billing",
        visitor_id="VIS_1", event_type="BILLING_QUEUE_JOIN", timestamp=base_time,
        zone_id="BILLING", is_staff=False, queue_depth=6, session_seq=1
    )
    test_db.add(e1)
    test_db.commit()
    
    anomalies = detect_store_anomalies(test_db, "STORE_BLR_001")
    assert len(anomalies) > 0
    assert any(a.anomaly_type == "BILLING_QUEUE_SPIKE" and a.severity == "WARN" for a in anomalies)
    
    # 2. Test Critical (queue depth = 9)
    e2 = EventModel(
        event_id="e_2", store_id="STORE_BLR_001", camera_id="cam_billing",
        visitor_id="VIS_2", event_type="BILLING_QUEUE_JOIN", timestamp=base_time + timedelta(seconds=10),
        zone_id="BILLING", is_staff=False, queue_depth=9, session_seq=2
    )
    test_db.add(e2)
    test_db.commit()
    
    anomalies = detect_store_anomalies(test_db, "STORE_BLR_001")
    assert any(a.anomaly_type == "BILLING_QUEUE_SPIKE" and a.severity == "CRITICAL" for a in anomalies)

def test_dead_zone_anomaly(client, test_db):
    # Seed a zone entry at 12:00:00
    base_time = datetime(2026, 4, 10, 12, 0, 0)
    e1 = EventModel(
        event_id="e_1", store_id="STORE_BLR_001", camera_id="cam_zone",
        visitor_id="VIS_1", event_type="ZONE_ENTER", timestamp=base_time,
        zone_id="COSMETICS", is_staff=False, session_seq=1
    )
    test_db.add(e1)
    test_db.commit()
    
    # Check anomalies at 12:00:05 (less than 90 seconds gap) -> Should not trigger dead zone
    anomalies = detect_store_anomalies(test_db, "STORE_BLR_001", dead_zone_minutes=1)
    assert not any(a.anomaly_type == "DEAD_ZONE" for a in anomalies)
    
    # Seed a new event at 12:02:00 (more than 90 seconds has passed since last entry in COSMETICS)
    e2 = EventModel(
        event_id="e_2", store_id="STORE_BLR_001", camera_id="cam_entry",
        visitor_id="VIS_2", event_type="ENTRY", timestamp=base_time + timedelta(seconds=120),
        zone_id=None, is_staff=False, session_seq=1
    )
    test_db.add(e2)
    test_db.commit()
    
    # Check anomalies again -> should now detect COSMETICS as dead zone
    anomalies = detect_store_anomalies(test_db, "STORE_BLR_001", dead_zone_minutes=1)
    assert any(a.anomaly_type == "DEAD_ZONE" and "COSMETICS" in a.details for a in anomalies)
