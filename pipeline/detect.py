# FIXES APPLIED: BUG #1, BUG #2, BUG #3, BUG #6 — Emits BILLING_QUEUE_ABANDON events, tracks visitor exits to emit REENTRY, converts timestamps to naive UTC, and handles KeyError during zone transitions.

import os
import sys
import json
import uuid
import argparse
from datetime import datetime, timedelta
import cv2
import numpy as np
from ultralytics import YOLO

# Add parent directory to path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pipeline.config import CAMERA_CONFIG, FRAME_SKIP, is_point_in_polygon
from pipeline.tracker import SessionStitcher, StaffPostProcessor

def get_base_time(video_name):
    """
    Returns base starting time for a clip in naive UTC (12:15 IST = 06:45 UTC on April 10, 2026).
    """
    # UTC baseline: 12:15 IST corresponds to 06:45:00 UTC
    if "billing" in video_name.lower():
        return datetime(2026, 4, 10, 6, 55, 0)
    elif "zone" in video_name.lower():
        return datetime(2026, 4, 10, 6, 50, 0)
    else:
        return datetime(2026, 4, 10, 6, 45, 0)

def process_video(video_path, output_jsonl):
    video_name = os.path.basename(video_path)
    if video_name not in CAMERA_CONFIG:
        print(f"Warning: {video_name} not configured in config.py. Skipping.")
        return

    config = CAMERA_CONFIG[video_name]
    store_id = config["store_id"]
    camera_id = video_name.split(".")[0]
    camera_type = config["camera_type"]
    
    # Initialize YOLOv8 model
    model = YOLO("yolov8s.pt")
    stitcher = SessionStitcher()
    
    cap = cv2.VideoCapture(video_path)
    img_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    img_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    
    base_time = get_base_time(video_name)
    
    # Tracking variables
    track_history = {}          # track_id -> list of normalized (x, y)
    track_zones_visited = {}    # track_id -> set of zone_ids
    track_purple_votes = {}     # track_id -> count of frames purple was active
    
    track_zones = {}            # track_id -> current zone_id
    track_zone_enter_time = {}  # track_id -> enter_datetime
    track_last_dwell_emit = {}  # track_id -> last_dwell_emit_datetime
    track_visitor_ids = {}      # track_id -> visitor_id
    track_is_staff = {}         # track_id -> bool
    track_seq = {}              # visitor_id -> int (event sequence counter)
    
    # Bug #1 & Bug #2 Tracking
    visitors_who_exited = set()
    pending_abandons = {}       # visitor_id -> exit_datetime (when leaving BILLING zone)
    visitor_id_staff_map = {}   # visitor_id -> is_staff (for post-processing references)
    visitor_seq_map = {}        # visitor_id -> final seq
    
    frame_idx = 0
    events = []
    total_frames = 0
    
    print(f"Processing {video_name} ({img_w}x{img_h} @ {fps} FPS)...")
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_idx += 1
        if frame_idx % FRAME_SKIP != 0:
            continue
            
        total_frames += 1
        offset_seconds = frame_idx / fps
        current_time = base_time + timedelta(seconds=offset_seconds)
        timestamp_str = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Run YOLO tracking
        results = model.track(frame, persist=True, classes=[0], verbose=False)
        
        if not results or results[0].boxes is None:
            continue
            
        boxes = results[0].boxes
        active_billing_tracks = []
        
        # Calculate current queue depth
        for box in boxes:
            if box.id is None:
                continue
            track_id = int(box.id[0])
            xyxy = box.xyxy[0].cpu().numpy()
            cx = (xyxy[0] + xyxy[2]) / 2.0
            cy = (xyxy[1] + xyxy[3]) / 2.0
            
            if "BILLING" in config["zones"]:
                if is_point_in_polygon((cx, cy), config["zones"]["BILLING"], img_w, img_h):
                    active_billing_tracks.append(track_id)
                    
        current_queue_depth = len(active_billing_tracks)
        
        for box in boxes:
            if box.id is None:
                continue
                
            track_id = int(box.id[0])
            conf = float(box.conf[0])
            xyxy = box.xyxy[0].cpu().numpy().astype(int)
            
            cx = (xyxy[0] + xyxy[2]) / 2.0
            cy = xyxy[3] # bottom boundary coordinates
            
            # Setup track properties
            if track_id not in track_visitor_ids:
                crop = frame[max(0, xyxy[1]):min(img_h, xyxy[3]), max(0, xyxy[0]):min(img_w, xyxy[2])]
                visitor_id, is_staff = stitcher.stitch_track(crop, camera_id, current_time)
                
                track_visitor_ids[track_id] = visitor_id
                track_is_staff[track_id] = is_staff
                track_seq[visitor_id] = 0
                
                # Setup track history monitoring
                track_history[track_id] = []
                track_zones_visited[track_id] = set()
                track_purple_votes[track_id] = 0
                
            visitor_id = track_visitor_ids[track_id]
            is_staff = track_is_staff[track_id]
            
            # Record track coordinates
            track_history[track_id].append((cx / img_w, cy / img_h))
            
            # Color histogram/purple staff check
            crop = frame[max(0, xyxy[1]):min(img_h, xyxy[3]), max(0, xyxy[0]):min(img_w, xyxy[2])]
            if crop.size > 0:
                from pipeline.tracker import is_purple_uniform
                if is_purple_uniform(crop):
                    track_purple_votes[track_id] += 1
            
            # 1. Inbound/Outbound Line Crossing (ENTRY/EXIT)
            if camera_type == "ENTRY" and "entry_line" in config:
                line = config["entry_line"]
                line_y = line[0][1] * img_h
                
                if len(track_history[track_id]) >= 2:
                    prev_y = track_history[track_id][-2][1] * img_h
                    curr_y = cy
                    
                    crossed = False
                    direction = 0
                    
                    if prev_y < line_y <= curr_y:
                        crossed = True
                        direction = 1
                    elif prev_y > line_y >= curr_y:
                        crossed = True
                        direction = -1
                        
                    if crossed:
                        event_type = "ENTRY" if (direction * config["entry_direction"]) > 0 else "EXIT"
                        
                        # BUG #2: Re-entry tracking checks
                        if event_type == "ENTRY":
                            if visitor_id in visitors_who_exited:
                                event_type = "REENTRY"
                        elif event_type == "EXIT":
                            visitors_who_exited.add(visitor_id)
                            
                        track_seq[visitor_id] += 1
                        event = {
                            "event_id": str(uuid.uuid4()),
                            "store_id": store_id,
                            "camera_id": camera_id,
                            "visitor_id": visitor_id,
                            "event_type": event_type,
                            "timestamp": timestamp_str,
                            "zone_id": None,
                            "dwell_ms": 0,
                            "is_staff": is_staff,
                            "confidence": conf,
                            "metadata": {
                                "queue_depth": None,
                                "sku_zone": None,
                                "session_seq": track_seq[visitor_id]
                            },
                            "_track_id": track_id # for post-processing updates
                        }
                        events.append(event)
            
            # 2. Zone containment checks
            matched_zone = None
            for zone_id, poly in config["zones"].items():
                if is_point_in_polygon((cx, cy), poly, img_w, img_h):
                    matched_zone = zone_id
                    break
                    
            prev_zone = track_zones.get(track_id)
            
            if matched_zone != prev_zone:
                if prev_zone is not None:
                    # Bug #6 Fix: Initialize zone enter time if missing to prevent KeyError
                    enter_time = track_zone_enter_time.get(track_id, current_time)
                    dwell_ms = int((current_time - enter_time).total_seconds() * 1000)
                    
                    # Track zone history
                    track_zones_visited[track_id].add(prev_zone)
                    
                    track_seq[visitor_id] += 1
                    event = {
                        "event_id": str(uuid.uuid4()),
                        "store_id": store_id,
                        "camera_id": camera_id,
                        "visitor_id": visitor_id,
                        "event_type": "ZONE_EXIT",
                        "timestamp": timestamp_str,
                        "zone_id": prev_zone,
                        "dwell_ms": dwell_ms,
                        "is_staff": is_staff,
                        "confidence": conf,
                        "metadata": {
                            "queue_depth": None,
                            "sku_zone": prev_zone,
                            "session_seq": track_seq[visitor_id]
                        },
                        "_track_id": track_id
                    }
                    events.append(event)
                    
                    # BUG #1 Check: Candidate for billing queue abandonment
                    if prev_zone == "BILLING":
                        pending_abandons[visitor_id] = current_time
                        
                if matched_zone is not None:
                    track_zone_enter_time[track_id] = current_time
                    track_last_dwell_emit[track_id] = current_time
                    track_zones_visited[track_id].add(matched_zone)
                    track_seq[visitor_id] += 1
                    
                    metadata = {"queue_depth": None, "sku_zone": matched_zone, "session_seq": track_seq[visitor_id]}
                    event_type = "ZONE_ENTER"
                    
                    if matched_zone == "BILLING":
                        # If joining queue, remove from pending abandons list (re-entered queue)
                        if visitor_id in pending_abandons:
                            del pending_abandons[visitor_id]
                            
                        if current_queue_depth > 1:
                            event_type = "BILLING_QUEUE_JOIN"
                            metadata["queue_depth"] = current_queue_depth - 1
                            
                    event = {
                        "event_id": str(uuid.uuid4()),
                        "store_id": store_id,
                        "camera_id": camera_id,
                        "visitor_id": visitor_id,
                        "event_type": event_type,
                        "timestamp": timestamp_str,
                        "zone_id": matched_zone,
                        "dwell_ms": 0,
                        "is_staff": is_staff,
                        "confidence": conf,
                        "metadata": metadata,
                        "_track_id": track_id
                    }
                    events.append(event)
                    
                track_zones[track_id] = matched_zone
                
            elif matched_zone is not None:
                # Dwell checks
                enter_time = track_zone_enter_time.get(track_id, current_time)
                dwell_sec = (current_time - enter_time).total_seconds()
                
                last_emit = track_last_dwell_emit.get(track_id, current_time)
                time_since_emit = (current_time - last_emit).total_seconds()
                
                if dwell_sec >= 30 and time_since_emit >= 30:
                    track_last_dwell_emit[track_id] = current_time
                    track_seq[visitor_id] += 1
                    event = {
                        "event_id": str(uuid.uuid4()),
                        "store_id": store_id,
                        "camera_id": camera_id,
                        "visitor_id": visitor_id,
                        "event_type": "ZONE_DWELL",
                        "timestamp": timestamp_str,
                        "zone_id": matched_zone,
                        "dwell_ms": int(dwell_sec * 1000),
                        "is_staff": is_staff,
                        "confidence": conf,
                        "metadata": {
                            "queue_depth": None,
                            "sku_zone": matched_zone,
                            "session_seq": track_seq[visitor_id]
                        },
                        "_track_id": track_id
                    }
                    events.append(event)
                    
            # Keep mappings up to date
            visitor_id_staff_map[visitor_id] = is_staff
            visitor_seq_map[visitor_id] = track_seq[visitor_id]
            
    cap.release()
    
    # 3. Post-Processing Staff Ensemble Classification (BUG #4)
    processor = StaffPostProcessor()
    staff_results = processor.process(track_history, track_zones_visited, track_purple_votes, total_frames)
    
    # Update is_staff flag in-memory for all compiled events
    for event in events:
        t_id = event.get("_track_id")
        if t_id in staff_results:
            final_staff_status = staff_results[t_id]
            event["is_staff"] = final_staff_status
            visitor_id_staff_map[event["visitor_id"]] = final_staff_status
            
    # 4. Ingest and cross-reference POS transactions for Queue Abandonment (BUG #1)
    # BUG #C Fix: Resolve relative path dynamically from script location
    pos_csv = os.path.join(os.path.dirname(__file__), "..", "POS - sample transactionsb1e826f.csv")
    transactions = []
    if os.path.exists(pos_csv):
        import pandas as pd
        try:
            df = pd.read_csv(pos_csv)
            for _, row in df.iterrows():
                # Matches transactions against this store code
                row_store = str(row["store_id"]).strip()
                if row_store == store_id or (store_id == "STORE_BLR_001" and row_store == "ST1008"):
                    date_str = str(row['order_date']).strip()
                    time_str = str(row['order_time']).strip()
                    # Convert local Indian time to naive UTC
                    dt_ist = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M:%S")
                    dt_utc = dt_ist - timedelta(hours=5, minutes=30)
                    transactions.append(dt_utc)
        except Exception as e:
            print(f"Error loading POS CSV for post-processing: {e}")
            
    # Emit BILLING_QUEUE_ABANDON events
    for visitor_id, exit_time in pending_abandons.items():
        # Exclude employees from checkout abandonment metrics
        if visitor_id_staff_map.get(visitor_id, False):
            continue
            
        has_pos = False
        for tx_time in transactions:
            # Did checkout follow within 5 minutes of exit?
            if exit_time <= tx_time <= exit_time + timedelta(minutes=5):
                has_pos = True
                break
                
        if not has_pos:
            visitor_seq_map[visitor_id] += 1
            abandon_event = {
                "event_id": str(uuid.uuid4()),
                "store_id": store_id,
                "camera_id": camera_id,
                "visitor_id": visitor_id,
                "event_type": "BILLING_QUEUE_ABANDON",
                "timestamp": exit_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "zone_id": "BILLING",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 1.0,
                "metadata": {
                    "queue_depth": None,
                    "sku_zone": "BILLING",
                    "session_seq": visitor_seq_map[visitor_id]
                }
            }
            events.append(abandon_event)
            
    # Clean up track markers before saving
    for event in events:
        if "_track_id" in event:
            del event["_track_id"]
            
    # Append events into single output JSONL
    with open(output_jsonl, "a") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
            
    print(f"Finished {video_name}. Generated {len(events)} events.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Path to input mp4 video")
    parser.add_argument("--output", default="detected_events.jsonl", help="Path to output events jsonl")
    args = parser.parse_args()
    
    process_video(args.video, args.output)
