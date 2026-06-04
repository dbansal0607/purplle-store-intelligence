FROM python:3.10-slim

# Install system dependencies for OpenCV and PyTorch
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libglib2.0-0 \
    libgl1-mesa-glx \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose port 8000 for FastAPI
EXPOSE 8000

# Run FastAPI by default
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
