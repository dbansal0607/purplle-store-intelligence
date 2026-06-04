# FIXES APPLIED: BUG #9, BUG #16, BUG #21 — Default 30-minute dead zone window, 7-day average baseline conversion checking, and direct query optimization to remove double DB queries.

import uuid
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import EventModel, PosTransactionModel
from app.models import AnomalySchema

def get_7day_conversion_avg(db: Session, store_id: str) -> float:
    """
    Returns average conversion rate over the past 7 days.
    Fallback default is 35% (standard beauty retail baseline) if history is empty.
    """
    latest_event = db.query(EventModel.timestamp)\
        .filter(EventModel.store_id == store_id)\
        .order_by(EventModel.timestamp.desc()).first()
        
    if not latest_event:
        return 35.0
        
    virtual_now = latest_event[0]
    seven_days_ago = virtual_now - timedelta(days=7)
    
    unique_visitors = db.query(func.count(func.distinct(EventModel.visitor_id)))\
        .filter(
            EventModel.store_id == store_id,
            EventModel.is_staff == False,
            EventModel.event_type == "ENTRY",
            EventModel.timestamp >= seven_days_ago
        ).scalar() or 0
        
    if unique_visitors < 20:
        return 35.0  # Fallback to standard baseline if samples are too small
        
    pos_transactions = db.query(PosTransactionModel)\
        .filter(
            PosTransactionModel.store_id == store_id,
            PosTransactionModel.order_timestamp >= seven_days_ago
        ).all()
        
    converted_visitors = set()
    for tx in pos_transactions:
        start_win = tx.order_timestamp - timedelta(minutes=5)
        end_win = tx.order_timestamp
        
        visitors = db.query(EventModel.visitor_id)\
            .filter(
                EventModel.store_id == store_id,
                EventModel.zone_id == "BILLING",
                EventModel.is_staff == False,
                EventModel.timestamp >= start_win,
                EventModel.timestamp <= end_win
            ).distinct().all()
            
        for v in visitors:
            converted_visitors.add(v[0])
            
    return (len(converted_visitors) / unique_visitors) * 100.0

def detect_store_anomalies(db: Session, store_id: str, dead_zone_minutes: int = 30) -> list[AnomalySchema]:
    anomalies = []
    
    # Check if there are any events at all to prevent false anomalies
    total_events = db.query(func.count(EventModel.event_id))\
        .filter(EventModel.store_id == store_id).scalar() or 0
    if total_events == 0:
        return []
        
    # Get virtual current time based on last recorded event
    latest_event = db.query(EventModel.timestamp)\
        .filter(EventModel.store_id == store_id)\
        .order_by(EventModel.timestamp.desc()).first()
        
    if not latest_event:
        return []
        
    virtual_now = latest_event[0]
    
    # BUG #21 Fix: Run optimized direct queries instead of calculate_store_metrics() to avoid duplicate execution
    unique_visitors = db.query(func.count(func.distinct(EventModel.visitor_id)))\
        .filter(
            EventModel.store_id == store_id,
            EventModel.is_staff == False,
            EventModel.event_type == "ENTRY"
        ).scalar() or 0
        
    # Compute conversion rate
    pos_transactions = db.query(PosTransactionModel)\
        .filter(PosTransactionModel.store_id == store_id).all()
        
    converted_visitors = set()
    for tx in pos_transactions:
        start_win = tx.order_timestamp - timedelta(minutes=5)
        end_win = tx.order_timestamp
        
        visitors = db.query(EventModel.visitor_id)\
            .filter(
                EventModel.store_id == store_id,
                EventModel.zone_id == "BILLING",
                EventModel.is_staff == False,
                EventModel.timestamp >= start_win,
                EventModel.timestamp <= end_win
            ).distinct().all()
            
        for v in visitors:
            converted_visitors.add(v[0])
            
    num_converted = len(converted_visitors)
    conversion_rate = 0.0
    if unique_visitors > 0:
        conversion_rate = (num_converted / unique_visitors) * 100.0

    # ANOMALY 1: Queue Spike (BILLING_QUEUE_SPIKE)
    two_mins_ago = virtual_now - timedelta(minutes=2)
    max_queue_depth = db.query(func.max(EventModel.queue_depth))\
        .filter(
            EventModel.store_id == store_id,
            EventModel.zone_id == "BILLING",
            EventModel.timestamp >= two_mins_ago
        ).scalar() or 0
        
    if max_queue_depth > 8:
        anomalies.append(AnomalySchema(
            anomaly_id=str(uuid.uuid4()),
            timestamp=virtual_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            anomaly_type="BILLING_QUEUE_SPIKE",
            severity="CRITICAL",
            details=f"Queue depth is critical at {max_queue_depth} shoppers.",
            suggested_action="Open register 3 immediately and deploy queue managers."
        ))
    elif max_queue_depth > 5:
        anomalies.append(AnomalySchema(
            anomaly_id=str(uuid.uuid4()),
            timestamp=virtual_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            anomaly_type="BILLING_QUEUE_SPIKE",
            severity="WARN",
            details=f"Queue depth is elevated at {max_queue_depth} shoppers.",
            suggested_action="Open register 2 immediately."
        ))

    # ANOMALY 2: Conversion Drop (CONVERSION_DROP)
    # BUG #16 Fix: Use 7-day average baseline (with 35% beauty industry fallback)
    seven_day_avg = get_7day_conversion_avg(db, store_id)
    baseline = seven_day_avg if seven_day_avg else 35.0
    
    # If conversion drops below 60% of the baseline and we have a valid sample size
    if unique_visitors >= 10 and conversion_rate < (baseline * 0.6):
        anomalies.append(AnomalySchema(
            anomaly_id=str(uuid.uuid4()),
            timestamp=virtual_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            anomaly_type="CONVERSION_DROP",
            severity="CRITICAL",
            details=f"Store conversion has dropped to {round(conversion_rate, 1)}% (Baseline: {round(baseline, 1)}%).",
            suggested_action="Suspected POS terminal or payment gateway breakdown. Validate transaction logs."
        ))
        
    # ANOMALY 3: Dead Zone (DEAD_ZONE)
    # BUG #9 Fix: Use configurable default dead zone window (30 minutes)
    dead_zone_window = timedelta(minutes=dead_zone_minutes)
    check_time = virtual_now - dead_zone_window
    
    zones = db.query(EventModel.zone_id)\
        .filter(
            EventModel.store_id == store_id,
            EventModel.zone_id != None,
            EventModel.zone_id != "ENTRY",
            EventModel.zone_id != "EXIT",
            EventModel.zone_id != "BILLING"
        ).distinct().all()
        
    for z_tuple in zones:
        zone_id = z_tuple[0]
        entries_count = db.query(func.count(EventModel.event_id))\
            .filter(
                EventModel.store_id == store_id,
                EventModel.zone_id == zone_id,
                EventModel.event_type == "ZONE_ENTER",
                EventModel.timestamp >= check_time
            ).scalar() or 0
            
        if entries_count == 0:
            anomalies.append(AnomalySchema(
                anomaly_id=str(uuid.uuid4()),
                timestamp=virtual_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                anomaly_type="DEAD_ZONE",
                severity="WARN",
                details=f"No shopper activity in zone {zone_id} for over {dead_zone_minutes} minutes.",
                suggested_action=f"Inspect aisle {zone_id} layout, display barriers, and check camera feed."
            ))
            
    return anomalies
