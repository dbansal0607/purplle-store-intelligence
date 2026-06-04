from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import EventModel
from app.models import EventSchema, IngestResponseSchema
import json

def parse_utc_timestamp(ts_str: str) -> datetime:
    """
    Parses various ISO 8601 UTC timestamp formats into Python datetime objects.
    """
    clean_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(clean_str)
    except ValueError:
        # Fallback for older python formats or millisecond truncation
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(clean_str, fmt)
            except ValueError:
                continue
        raise ValueError(f"Could not parse timestamp format: {ts_str}")

def ingest_events_batch(db: Session, batch: list) -> IngestResponseSchema:
    processed = 0
    duplicates = 0
    errors = []
    
    if len(batch) > 500:
        errors.append({"error": "Batch size exceeds maximum limit of 500 events", "event_id": None})
        return IngestResponseSchema(status="error", processed=0, duplicates=0, errors=errors)
        
    for item in batch:
        try:
            # 1. Validate using Pydantic Schema
            if isinstance(item, dict):
                event_data = EventSchema(**item)
            else:
                event_data = item
                
            # Parse timestamp to python datetime
            dt = parse_utc_timestamp(event_data.timestamp)
            
            # 2. Check for duplicate in database before inserting to avoid transaction rollbacks
            existing = db.query(EventModel).filter(EventModel.event_id == event_data.event_id).first()
            if existing:
                duplicates += 1
                continue
                
            # 3. Build SQLAlchemy DB Model
            db_event = EventModel(
                event_id=event_data.event_id,
                store_id=event_data.store_id,
                camera_id=event_data.camera_id,
                visitor_id=event_data.visitor_id,
                event_type=event_data.event_type.upper(),
                timestamp=dt,
                zone_id=event_data.zone_id,
                dwell_ms=event_data.dwell_ms,
                is_staff=event_data.is_staff,
                confidence=event_data.confidence,
                
                # Metadata
                queue_depth=event_data.metadata.queue_depth,
                sku_zone=event_data.metadata.sku_zone,
                session_seq=event_data.metadata.session_seq
            )
            
            db.add(db_event)
            db.commit()
            processed += 1
            
        except Exception as e:
            db.rollback()
            event_id = item.get("event_id") if isinstance(item, dict) else getattr(item, 'event_id', None)
            errors.append({
                "event_id": event_id,
                "error": str(e)
            })
            
    status = "success" if not errors else "partial_success"
    if processed == 0 and errors:
        status = "error"
        
    return IngestResponseSchema(
        status=status,
        processed=processed,
        duplicates=duplicates,
        errors=errors
    )
