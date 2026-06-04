# run.ps1 - Runs the detection pipeline on all Store 1 and Store 2 videos.

$OutputFile = "pipeline_events.jsonl"

# Clear output file if exists
if (Test-Path $OutputFile) {
    Remove-Item $OutputFile
}
New-Item -Path $OutputFile -ItemType File | Out-Null

Write-Host "Starting Store Intelligence Computer Vision Pipeline..." -ForegroundColor Green

# Store 1 Video Processing
Write-Host "Processing Store 1 Videos..." -ForegroundColor Cyan
python pipeline/detect.py --video "Store 1/CAM 3 - entry.mp4" --output $OutputFile
python pipeline/detect.py --video "Store 1/CAM 1 - zone.mp4" --output $OutputFile
python pipeline/detect.py --video "Store 1/CAM 2 - zone.mp4" --output $OutputFile
python pipeline/detect.py --video "Store 1/CAM 5 - billing.mp4" --output $OutputFile

# Store 2 Video Processing
Write-Host "Processing Store 2 Videos..." -ForegroundColor Cyan
python pipeline/detect.py --video "Store 2/entry 1.mp4" --output $OutputFile
python pipeline/detect.py --video "Store 2/entry 2.mp4" --output $OutputFile
python pipeline/detect.py --video "Store 2/zone.mp4" --output $OutputFile
python pipeline/detect.py --video "Store 2/billing_area.mp4" --output $OutputFile

Write-Host "CV Pipeline completed. Output saved to $OutputFile" -ForegroundColor Green
