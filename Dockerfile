# Multi-stage Dockerfile for Flask Backend
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install all dependencies globally
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite (if needed) with write permissions
RUN mkdir -p data && chmod 777 data

# Expose port (Koyeb will set PORT env variable)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, os; port = os.getenv('PORT', '8080'); urllib.request.urlopen(f'http://localhost:{port}/api/health')" || exit 1

# Explicitly set entrypoint to override Koyeb's default
ENTRYPOINT []

# Run the application with gunicorn (Flask, not FastAPI/uvicorn)
CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --timeout 120 --workers 3 --keep-alive 5"]

