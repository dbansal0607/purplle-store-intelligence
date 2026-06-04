from pydantic import BaseModel, Field, RootModel
from typing import Optional, List
from datetime import datetime

class EventMetadata(BaseModel):
    queue_depth: Optional[int] = Field(None, description="Current queue depth for BILLING_QUEUE_JOIN events")
    sku_zone: Optional[str] = Field(None, description="SKU zone associated with the event")
    session_seq: int = Field(0, description="Sequence counter in visitor session")

class EventSchema(BaseModel):
    event_id: str = Field(..., description="UUIDv4 globally unique event identifier")
    store_id: str = Field(..., description="Unique code for physical store")
    camera_id: str = Field(..., description="Camera identifier that generated the event")
    visitor_id: str = Field(..., description="Unified visitor ID session token")
    event_type: str = Field(..., description="Category of event (ENTRY, EXIT, ZONE_ENTER, etc.)")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")
    zone_id: Optional[str] = Field(None, description="Identified store zone (e.g. SKINCARE)")
    dwell_ms: int = Field(0, description="Dwell time inside a zone in milliseconds")
    is_staff: bool = Field(False, description="Flag indicating if visitor is an employee")
    confidence: float = Field(1.0, description="Model tracking confidence score between 0.0 and 1.0")
    metadata: EventMetadata = Field(default_factory=EventMetadata)

class EventBatch(RootModel):
    root: List[EventSchema] = Field(..., max_length=500, description="Batch of up to 500 events")

class IngestResponseSchema(BaseModel):
    status: str = Field("success", description="Status of batch ingestion")
    processed: int = Field(..., description="Number of successfully stored events")
    duplicates: int = Field(0, description="Number of skipped duplicate event_ids")
    errors: List[dict] = Field(default_factory=list, description="Structured log of validation errors")

class MetricResponseSchema(BaseModel):
    store_id: str
    unique_visitors: int
    conversion_rate: float
    avg_dwell_by_zone: dict
    queue_depth: int
    abandonment_rate: float

class FunnelStageSchema(BaseModel):
    stage_name: str
    count: int
    drop_off_pct: float

class FunnelResponseSchema(BaseModel):
    store_id: str
    funnel: List[FunnelStageSchema]

class HeatmapItemSchema(BaseModel):
    zone_id: str
    visit_count: int
    avg_dwell_sec: float
    intensity: float  # Normalized 0 to 100

class HeatmapResponseSchema(BaseModel):
    store_id: str
    data_confidence: str  # 'HIGH' or 'LOW'
    heatmap: List[HeatmapItemSchema]

class AnomalySchema(BaseModel):
    anomaly_id: str
    timestamp: str
    anomaly_type: str  # 'BILLING_QUEUE_SPIKE', 'CONVERSION_DROP', 'DEAD_ZONE'
    severity: str  # 'INFO', 'WARN', 'CRITICAL'
    details: str
    suggested_action: str
