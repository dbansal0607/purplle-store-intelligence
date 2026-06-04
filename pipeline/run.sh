#!/bin/bash
# run.sh - Runs the detection pipeline on all Store 1 and Store 2 videos.

OUTPUT_FILE="/workspace/pipeline_events.jsonl"

# Clear output file
> "$OUTPUT_FILE"

echo "Starting Store Intelligence Computer Vision Pipeline..."

# Store 1 Video Processing
echo "Processing Store 1 Videos..."
python pipeline/detect.py --video "Store 1/CAM 3 - entry.mp4" --output "$OUTPUT_FILE"
python pipeline/detect.py --video "Store 1/CAM 1 - zone.mp4" --output "$OUTPUT_FILE"
python pipeline/detect.py --video "Store 1/CAM 2 - zone.mp4" --output "$OUTPUT_FILE"
python pipeline/detect.py --video "Store 1/CAM 5 - billing.mp4" --output "$OUTPUT_FILE"

# Store 2 Video Processing
echo "Processing Store 2 Videos..."
python pipeline/detect.py --video "Store 2/entry 1.mp4" --output "$OUTPUT_FILE"
python pipeline/detect.py --video "Store 2/entry 2.mp4" --output "$OUTPUT_FILE"
python pipeline/detect.py --video "Store 2/zone.mp4" --output "$OUTPUT_FILE"
python pipeline/detect.py --video "Store 2/billing_area.mp4" --output "$OUTPUT_FILE"

echo "CV Pipeline completed. Output saved to $OUTPUT_FILE"
