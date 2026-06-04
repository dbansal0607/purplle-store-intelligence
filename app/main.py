# FIXES APPLIED: BUG #7, BUG #10, BUG #12, BUG #19, BUG #20 — Imports sqlalchemy func and database EventModel, utilizes Pydantic array schema validation, uses request state for event counts logging, and returns HTTP 202 Accepted for ingestion.

import os
import time
import uuid
import json
import logging
from typing import List
from fastapi import FastAPI, Depends, HTTPException, Request, Response, status, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import Field

from app.database import init_db, get_db, EventModel
from app.models import (
    EventSchema,
    EventBatch,
    IngestResponseSchema,
    MetricResponseSchema,
    FunnelResponseSchema,
    HeatmapResponseSchema,
    HeatmapItemSchema,
    AnomalySchema
)
from app.ingestion import ingest_events_batch
from app.metrics import calculate_store_metrics
from app.funnel import calculate_store_funnel
from app.anomalies import detect_store_anomalies
from app.health import check_service_health

# Initialize Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("store_intelligence")

# Initialize database schemas
init_db()

app = FastAPI(
    title="Purplle Store Intelligence API",
    description="REST API for real-time store CV event ingestion, operational metrics, and anomaly detection.",
    version="1.0.0"
)

# Enable CORS for dashboard interactions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request-response logging middleware with X-Trace-ID injection
@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
    start_time = time.time()
    
    # Store trace_id in request state for downstream handlers
    request.state.trace_id = trace_id
    
    # Process request
    response = await call_next(request)
    
    # Calculate latency
    latency_ms = int((time.time() - start_time) * 1000)
    
    # BUG #12 Fix: Retrieve event count stored in state by route handlers
    event_count = getattr(request.state, "event_count", 0)
            
    # Structured JSON log payload
    log_payload = {
        "trace_id": trace_id,
        "store_id": request.path_params.get("id", "GLOBAL"),
        "endpoint": request.url.path,
        "method": request.method,
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "event_count": event_count
    }
    logger.info(json.dumps(log_payload))
    
    # Return response with Trace ID header
    response.headers["X-Trace-ID"] = trace_id
    return response

# Custom Database Unavailable Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log the crash details
    logger.error(f"Request failed: {str(exc)}", exc_info=True)
    
    # If it is a DB-related connection failure, return 503 Service Unavailable
    db_errors = ("OperationalError", "sqlite3.OperationalError", "TimeoutError", "ConnectionError")
    if any(err in type(exc).__name__ for err in db_errors):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "message": "Database temporarily unavailable due to concurrent locks or downtime.",
                "trace_id": getattr(request.state, "trace_id", None)
            }
        )
        
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "message": "An internal server error occurred.",
            "trace_id": getattr(request.state, "trace_id", None)
        }
    )

# REST ENDPOINTS

# BUG #19: Returns HTTP 202 Accepted instead of 200
# BUG #20 & BUG #E Fix: Validates payload body strictly as EventBatch containing List up to 500 items
@app.post("/events/ingest", response_model=IngestResponseSchema, status_code=status.HTTP_202_ACCEPTED)
def ingest_events(
    request: Request,
    payload: EventBatch,
    db: Session = Depends(get_db)
):
    """
    Ingests a batch of up to 500 store camera events.
    Enforces idempotency by ignoring duplicate event_ids.
    """
    # BUG #12 & BUG #E Fix: Store batch size from Pydantic root in request.state
    request.state.event_count = len(payload.root)
    response = ingest_events_batch(db, payload.root)
    return response

@app.get("/stores/{id}/metrics", response_model=MetricResponseSchema)
def get_store_metrics(id: str, db: Session = Depends(get_db)):
    """
    Computes real-time store metrics: conversion, unique visitors, queue depth, abandonment.
    """
    return calculate_store_metrics(db, id)

@app.get("/stores/{id}/funnel", response_model=FunnelResponseSchema)
def get_store_funnel(id: str, db: Session = Depends(get_db)):
    """
    Returns session-deduplicated conversion funnel steps.
    """
    return calculate_store_funnel(db, id)

@app.get("/stores/{id}/heatmap", response_model=HeatmapResponseSchema)
def get_store_heatmap(id: str, db: Session = Depends(get_db)):
    """
    Computes zone-wise shopping heatmaps normalized from 0 to 100.
    Flags LOW confidence if unique sessions are fewer than 20.
    """
    # BUG #7 Fix: Queries EventModel and func (now correctly imported)
    visits_by_zone = db.query(
        EventModel.zone_id,
        func.count(func.distinct(EventModel.visitor_id)),
        func.avg(EventModel.dwell_ms)
    ).filter(
        EventModel.store_id == id,
        EventModel.zone_id != None,
        EventModel.zone_id != "ENTRY",
        EventModel.zone_id != "EXIT",
        EventModel.zone_id != "BILLING"
    ).group_by(EventModel.zone_id).all()
    
    # Compute total unique sessions for confidence flag
    total_sessions = db.query(func.count(func.distinct(EventModel.visitor_id)))\
        .filter(EventModel.store_id == id).scalar() or 0
        
    data_confidence = "HIGH" if total_sessions >= 20 else "LOW"
    
    raw_heatmap = []
    max_score = 0.0
    
    for zone_id, visitor_count, avg_dwell_ms in visits_by_zone:
        avg_dwell_sec = round((avg_dwell_ms or 0) / 1000.0, 1)
        score = visitor_count * avg_dwell_sec
        raw_heatmap.append({
            "zone_id": zone_id,
            "visit_count": visitor_count,
            "avg_dwell_sec": avg_dwell_sec,
            "score": score
        })
        if score > max_score:
            max_score = score
            
    heatmap_items = []
    for item in raw_heatmap:
        intensity = 0.0
        if max_score > 0:
            intensity = round((item["score"] / max_score) * 100, 1)
            
        heatmap_items.append(HeatmapItemSchema(
            zone_id=item["zone_id"],
            visit_count=item["visit_count"],
            avg_dwell_sec=item["avg_dwell_sec"],
            intensity=intensity
        ))
        
    return HeatmapResponseSchema(
        store_id=id,
        data_confidence=data_confidence,
        heatmap=heatmap_items
    )

@app.get("/stores/{id}/anomalies", response_model=List[AnomalySchema])
def get_store_anomalies(id: str, db: Session = Depends(get_db)):
    """
    Exposes active operational warning anomalies (Queue Spike, Conversion Drop, Dead Zones).
    """
    return detect_store_anomalies(db, id)

@app.get("/health")
def get_health(db: Session = Depends(get_db)):
    """
    Health check endpoint reporting feed status and lag.
    """
    health_data = check_service_health(db)
    if health_data["status"] != "healthy":
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=health_data)
    return health_data

# Mount static files for dashboard (serve at /dashboard)
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
if os.path.exists(static_dir):
    app.mount("/dashboard", StaticFiles(directory=static_dir, html=True), name="static")
    
# Root endpoint redirects to API Docs or serves index.html if static files are set
@app.get("/", response_class=HTMLResponse)
def root():
    # If static index.html exists, return it, else direct to docs
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            return f.read()
    return "<html><body><h1>Store Intelligence API</h1><p>Navigate to <a href='/docs'>Swagger API docs</a> or <a href='/dashboard/'>Dashboard</a></p></body></html>"
