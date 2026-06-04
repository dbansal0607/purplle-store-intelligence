# System Architecture Design — Store Intelligence API

This document provides a production-grade technical design review of the Apex Retail Store Intelligence System. It details our architectural flow, computer vision tracking logic, database structures, and dynamic analytics handlers.

---

## 1. Comprehensive System Architecture

The application is structured into two primary operational layers:
1. **CV Edge Tracking Pipeline**: Processes raw video clips, handles spatial coordinate mapping, runs visual Re-ID, and outputs structured, schema-compliant JSON state events.
2. **REST API Service & Analytics Engine**: Ingests incoming event batches, enforces write idempotency, executes time-correlated POS conversion mapping, and evaluates operational warnings.

```mermaid
graph TD
    %% Video Input Section
    subgraph Video [CCTV Camera Input Streams]
        C1[Store 1: CAM 3 - Entry]
        C2[Store 1: CAM 1/2 - Aisle Zones]
        C3[Store 1: CAM 5 - Billing Wrap]
    end

    %% CV Edge Pipeline Section
    subgraph CV [Computer Vision Edge Pipeline]
        FR[OpenCV Frame Reader] -->|Frame Skip = 3| YOLO[YOLOv8-Small Person Detector]
        YOLO -->|Bounding Boxes| BT[ByteTrack Association]
        BT -->|Active Bounding Boxes| CH[torso HSV Color Histogram Extractor]
        CH -->|Normalised 64-Dim Embedding| SS[SessionStitcher Engine]
        SS -->|Spatial-Temporal Camera Transitions Gating| RE[Re-ID Stitching & Re-Entry Checks]
        RE -->|Track Coordinates & Centroids| ZM[Polygon Coordinate Zone Matcher]
        ZM -->|Line Crossing & Zone Dwell Triggers| EG[JSONL Event Generator]
    end

    %% Event Stream & API Ingest Section
    subgraph Ingest [Asynchronous Ingestion Service]
        EG -->|JSONL Stream File| IH[pipeline/ingest.py Batch Uploader]
        IH -->|HTTP POST JSON Array Chunks of 500| API[FastAPI /events/ingest]
        API -->|Pydantic RootModel Validation| VAL{Valid Batch?}
        VAL -->|Yes| DB[(SQLite Database WAL Mode)]
        VAL -->|No| ERR[Structured HTTP 400/422 Error Logs]
    end

    %% Analytics & Anomaly Section
    subgraph Analytics [Analytics & Operations Core]
        DB -->|Aggregated Selects| MET[metrics.py Analytics Engine]
        DB -->|Funnel Counts| FUN[funnel.py Funnel Engine]
        DB -->|Rolling 30m / 7d queries| ANOM[anomalies.py Alarms Ticker]
        MET -->|Visitors, Conversions, Queue depth| DASH[Dashboard Web UI /dashboard/]
        FUN -->|Drop-offs| DASH
        ANOM -->|Spikes, Conversion Drops, Dead Zones| DASH
    end

    %% Connections
    C1 --> FR
    C2 --> FR
    C3 --> FR
    DB -->|Seeded UTC POS Data| MET
    DB -->|Seeded UTC POS Data| FUN
    DB -->|Seeded UTC POS Data| ANOM
```

---

## 2. Component System Breakdown

### 2.1 Computer Vision Edge Processing
* **Object Detection**: Evaluates frame bounding boxes targeting the `person` class. Skips 2 of every 3 frames for high CPU frame-rate throughput.
* **Tracking (ByteTrack)**: Retains tracking states for occluded shoppers by preserving low-confidence boxes (down to $0.1$) that map to predicted Kalman filter trajectories.
* **Torso Re-ID & Spatial Gating**: Extracts a 64-dimensional normalized HSV color histogram of the torso (middle third of the bounding box). It matches tracks against active sessions seen within the last 5 minutes. Matches are gated by camera transition rules (e.g. preventing direct Re-ID matches between entry cameras and billing counters without intermediate aisle zone appearances), reducing false positive ID switches.
* **Event Generation**: Emits semantic events on state boundary crossings:
  * `ENTRY` / `EXIT`: Crossing the entry threshold line.
  * `ZONE_ENTER` / `ZONE_EXIT`: Traversing polygon boundaries.
  * `ZONE_DWELL`: Triggered every 30 seconds of continuous zone stay.
  * `BILLING_QUEUE_JOIN`: Triggered when entering the checkout zone when queue depth $> 0$.
  * `BILLING_QUEUE_ABANDON`: Computed post-processing by validating if billing exit was followed by a purchase within 5 minutes.

### 2.2 Ingestion & Database Cache (SQLite WAL)
* FastAPI intercepts incoming payloads via a Pydantic `RootModel` array validation scheme.
* Database operations run on SQLite in **WAL (Write-Ahead Logging) Mode** with `PRAGMA synchronous = NORMAL`. This decouples read and write threads, allowing concurrent query executions during bulk batch inserts.

### 2.3 Timezone Naive-UTC Data Alignment
To prevent temporal mismatches, the system standardizes all timestamps on naive UTC datetimes:
1. **POS transactions CSV**: `import_pos.py` parses transactions (local IST/UTC+5:30), shifts them by subtracting 5 hours and 30 minutes, and saves them as naive UTC objects.
2. **CCTV clips timeline**: `detect.py` maps the video start to 06:45:00 UTC (12:15:00 IST), ensuring video events line up with corresponding transaction timestamps.

### 2.4 Production Safety & Graceful Failure Handlers
* **Division-by-Zero Safety**: Metric and funnel queries intercept zero-visitor scenarios, returning `0.0` rather than raising divide-by-zero exceptions.
* **Database Down Circuit Breaker**: If SQLite files become locked or database access is lost, a FastAPI exception handler catches connection errors and immediately returns a clean JSON error schema with HTTP `503 Service Unavailable`, preventing raw traceback leakages.
