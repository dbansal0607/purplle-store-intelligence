# FIXES APPLIED: BUG #10 — Python helper script to parse JSONL files and post them in batches of 500 as JSON arrays to the REST API, avoiding validation errors.

import json
import sys
import urllib.request
import os

def ingest(jsonl_path, api_url):
    print(f"Reading events from {jsonl_path}...")
    if not os.path.exists(jsonl_path):
        print(f"Error: {jsonl_path} not found.")
        sys.exit(1)
        
    events = []
    with open(jsonl_path, "r") as f:
        for line in f:
            if line.strip():
                try:
                    events.append(json.loads(line))
                except Exception as e:
                    print(f"Skipping malformed line: {e}")
                    
    total = len(events)
    print(f"Loaded {total} events. Posting in chunks of 500 to {api_url}...")
    
    chunk_size = 500
    success = 0
    duplicates = 0
    errors = 0
    
    for i in range(0, total, chunk_size):
        chunk = events[i:i+chunk_size]
        data = json.dumps(chunk).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as res:
                response_data = json.loads(res.read().decode("utf-8"))
                success += response_data.get("processed", 0)
                duplicates += response_data.get("duplicates", 0)
                if response_data.get("errors"):
                    errors += len(response_data["errors"])
        except Exception as e:
            print(f"Network error on batch {i // chunk_size + 1}: {e}")
            
    print(f"Ingestion completed. Mapped: {success} events, Skipped duplicates: {duplicates}, Errors: {errors}")

if __name__ == "__main__":
    jsonl_file = "pipeline_events.jsonl"
    url = "http://localhost:8000/events/ingest"
    
    if len(sys.argv) > 1:
        jsonl_file = sys.argv[1]
    if len(sys.argv) > 2:
        url = sys.argv[2]
        
    ingest(jsonl_file, url)
