# FIXES APPLIED: BUG #11, BUG #12, BUG #13, BUG #14 — Tracks active queue depth from active zone occupants, filters unique visitors by ENTRY events, and resolves visitor/funnel counting mismatches.

from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import EventModel, PosTransactionModel
from app.models import MetricResponseSchema

def calculate_store_metrics(db: Session, store_id: str) -> MetricResponseSchema:
    # BUG #13: Count only visitors who crossed the ENTRY threshold (excl staff & reentry)
    unique_visitors_query = db.query(func.count(func.distinct(EventModel.visitor_id)))\
        .filter(
            EventModel.store_id == store_id,
            EventModel.is_staff == False,
            EventModel.event_type == "ENTRY"
        )
    total_unique_visitors = unique_visitors_query.scalar() or 0
    
    # Conversion Rate Calculation (Temporal Correlation)
    # A visitor is converted if they entered the BILLING zone within 5 minutes preceding a transaction.
    pos_transactions = db.query(PosTransactionModel)\
        .filter(PosTransactionModel.store_id == store_id).all()
        
    converted_visitors = set()
    
    for tx in pos_transactions:
        # 5-minute window before checkout
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
    if total_unique_visitors > 0:
        conversion_rate = round((num_converted / total_unique_visitors) * 100, 2)
        
    # Average Dwell Time per Zone
    dwell_query = db.query(
        EventModel.zone_id,
        func.avg(EventModel.dwell_ms)
    ).filter(
        EventModel.store_id == store_id,
        EventModel.zone_id != None,
        EventModel.zone_id != "ENTRY",
        EventModel.zone_id != "EXIT",
        EventModel.dwell_ms > 0
    ).group_by(EventModel.zone_id).all()
    
    avg_dwell_by_zone = {}
    for zone_id, avg_dwell in dwell_query:
        avg_dwell_by_zone[zone_id] = round((avg_dwell or 0) / 1000.0, 1)
        
    # BUG #11: Calculate active queue depth (in queue without exit event)
    current_queue = db.query(func.count(func.distinct(EventModel.visitor_id)))\
        .filter(
            EventModel.store_id == store_id,
            EventModel.event_type.in_(["BILLING_QUEUE_JOIN", "ZONE_ENTER"]),
            EventModel.zone_id == "BILLING",
            EventModel.is_staff == False,
            ~EventModel.visitor_id.in_(
                db.query(EventModel.visitor_id).filter(
                    EventModel.store_id == store_id,
                    EventModel.event_type.in_(["EXIT", "ZONE_EXIT"]),
                    EventModel.zone_id == "BILLING"
                )
            )
        ).scalar() or 0
        
    queue_depth = current_queue

    # Abandonment Rate (Visitors who entered Billing zone but did not buy)
    billing_visitors = db.query(EventModel.visitor_id)\
        .filter(
            EventModel.store_id == store_id,
            EventModel.zone_id == "BILLING",
            EventModel.is_staff == False
        ).distinct().all()
        
    billing_visitor_ids = {v[0] for v in billing_visitors}
    total_in_billing = len(billing_visitor_ids)
    
    abandoned_visitors = billing_visitor_ids - converted_visitors
    num_abandoned = len(abandoned_visitors)
    
    abandonment_rate = 0.0
    if total_in_billing > 0:
        abandonment_rate = round((num_abandoned / total_in_billing) * 100, 2)
        
    return MetricResponseSchema(
        store_id=store_id,
        unique_visitors=total_unique_visitors,
        conversion_rate=conversion_rate,
        avg_dwell_by_zone=avg_dwell_by_zone,
        queue_depth=queue_depth,
        abandonment_rate=abandonment_rate
    )
