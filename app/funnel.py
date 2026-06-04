# FIXES APPLIED: BUG #14, BUG #15 — Stage 1 counts strictly ENTRY events and documents how Re-ID manages visitor session deduplication under re-entries.

from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import EventModel, PosTransactionModel
from app.models import FunnelResponseSchema, FunnelStageSchema
from datetime import timedelta

def calculate_store_funnel(db: Session, store_id: str) -> FunnelResponseSchema:
    # BUG #14: Filter strictly by event_type == "ENTRY" to avoid counting pre-existing/zone-only tracks
    # BUG #15 Note: Re-entry sessions share the exact same visitor_id (assigned by Re-ID).
    # Using distinct visitor_id naturally deduplicates returning customers so they count only once.
    entry_visitors = db.query(EventModel.visitor_id)\
        .filter(
            EventModel.store_id == store_id,
            EventModel.is_staff == False,
            EventModel.event_type == "ENTRY"
        ).distinct().all()
    entry_visitor_ids = {v[0] for v in entry_visitors}
    n_entry = len(entry_visitor_ids)
    
    # Stage 2 - Visited at least one shelf zone
    zone_visitors = db.query(EventModel.visitor_id)\
        .filter(
            EventModel.store_id == store_id,
            EventModel.is_staff == False,
            EventModel.zone_id != None,
            EventModel.zone_id != "ENTRY",
            EventModel.zone_id != "EXIT",
            EventModel.zone_id != "BILLING"
        ).distinct().all()
    zone_visitor_ids = {v[0] for v in zone_visitors}
    zone_visitor_ids = zone_visitor_ids & entry_visitor_ids
    n_zone = len(zone_visitor_ids)
    
    # Stage 3 - Entered BILLING zone
    billing_visitors = db.query(EventModel.visitor_id)\
        .filter(
            EventModel.store_id == store_id,
            EventModel.is_staff == False,
            EventModel.zone_id == "BILLING"
        ).distinct().all()
    billing_visitor_ids = {v[0] for v in billing_visitors}
    billing_visitor_ids = billing_visitor_ids & entry_visitor_ids
    n_billing = len(billing_visitor_ids)
    
    # Stage 4 - Purchase (Converted)
    pos_transactions = db.query(PosTransactionModel)\
        .filter(PosTransactionModel.store_id == store_id).all()
        
    converted_visitor_ids = set()
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
            converted_visitor_ids.add(v[0])
            
    converted_visitor_ids = converted_visitor_ids & entry_visitor_ids
    n_purchase = len(converted_visitor_ids)
    
    # Calculate Drop-off Percentages
    drop_entry = 0.0
    
    drop_zone = 0.0
    if n_entry > 0:
        drop_zone = round(((n_entry - n_zone) / n_entry) * 100, 2)
        
    drop_billing = 0.0
    if n_zone > 0:
        drop_billing = round(((n_zone - n_billing) / n_zone) * 100, 2)
        
    drop_purchase = 0.0
    if n_billing > 0:
        drop_purchase = round(((n_billing - n_purchase) / n_billing) * 100, 2)
        
    funnel_data = [
        FunnelStageSchema(stage_name="Entry", count=n_entry, drop_off_pct=drop_entry),
        FunnelStageSchema(stage_name="Zone Visit", count=n_zone, drop_off_pct=drop_zone),
        FunnelStageSchema(stage_name="Billing Queue", count=n_billing, drop_off_pct=drop_billing),
        FunnelStageSchema(stage_name="Purchase", count=n_purchase, drop_off_pct=drop_purchase),
    ]
    
    return FunnelResponseSchema(
        store_id=store_id,
        funnel=funnel_data
    )
