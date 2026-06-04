# System Architecture Design — Store Intelligence API

This document provides a technical overview of the system architecture, component breakdown, and database schemas.

---

## 1. Architectural Overview

The system is split into two primary layers: a **Computer Vision Pipeline** that processes raw CCTV video feeds and emits structured events, and an **Asynchronous REST API** that ingests the events, computes real-time operational metrics, and detects store anomalies.

```
+-----------------------------------------------------------+
|               COMPUTER VISION EDGE PIPELINE               |
|  +------------------+     +------------+     +----------+ |
|  | YOLOv8 Object Det| --> | ByteTrack  | --> | Re-ID    | |
|  +------------------+     +------------+     +----------+ |
+-----------------------------------------------------+-----+
                                                      |
                                           Structured Event Stream
                                                      |
                                                      v
+-----------------------------------------------------------+
|                   FASTAPI ANALYTICS ENGINE                |
|  +------------------+     +------------+     +----------+ |
|  | Ingestion        | --> | SQLite DB  | --> | metrics  | |
|  | (/events/ingest) |     | (WAL Mode) |     | anomalies| |
|  +------------------+     +------------+     +----------+ |
+-----------------------------------------------------------+
```

---

## 2. AI-Assisted Decisions

We documented the interaction points where AI was utilized to shape the architecture:

### Decision 1: Spatial-Temporal Gating for Re-ID (Overrode AI)
* **LLM Suggestion**: The LLM proposed matching track embeddings against a global memory database containing all previously seen shoppers to unify visitor sessions.
* **Override Reason**: In a store layout, shoppers do not teleport. Matching against a global database increases processing complexity and false positives. We overrode the AI's design, implementing **spatial-temporal gating**. Tracks are only compared if the time gap is $< 5\text{ minutes}$ and they cross boundary-matching zones (e.g. exit Entry zone and enter Shelf zone), which we estimate reduces false positive Re-ID matches by limiting matching scope, though we did not measure the exact improvement on this dataset.

### Decision 2: Staff Detection using Color Hue (Agreed with AI)
* **LLM Suggestion**: The LLM suggested using a simple HSV color thresholding filter on the upper body crop to classify employees based on uniform color, rather than training a complex ResNet classifier.
* **Agreement Reason**: This approach runs instantly on CPU with $0$ training data. It is explainable, lightweight, and works robustly on the face-blurred CCTV videos where facial features are missing.

### Decision 3: SQLite WAL mode for concurrency (Agreed with AI)
* **LLM Suggestion**: The LLM recommended enabling WAL (Write-Ahead Logging) mode and setting check_same_thread=False for SQLite connections to allow concurrent reads during bulk event insertions.
* **Agreement Reason**: SQLite default locking locks the database during writes, causing HTTP 500 errors during load. Enabling WAL mode resolves concurrency bottlenecks, making the database extremely resilient during batch imports.

---

## 3. Component Design & Database Schema

The SQLite schema utilizes index points on query-heavy columns:
* **events**: Holds track state changes. Columns `store_id`, `visitor_id`, `event_type`, and `timestamp` are indexed to speed up metric queries.
* **pos_transactions**: Holds seed purchase records mapped across stores.

### Verification of Robustness
* **No division-by-zero**: If visitor counts are zero, `/metrics` and `/funnel` handle the exception gracefully, returning `0.0` rather than crashing.
* **Circuit-breaker for database connection**: FastAPI intercepts SQLAlchemy database connection failures, immediately returning an HTTP `503 Service Unavailable` instead of raw stack traces.
