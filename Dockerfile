# Restaurant Ordering Assistant - Dockerfile
# Multi-stage build for optimized image size

FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies for Playwright and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright dependencies
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    # Additional utilities
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (fixed path so the app user can read them)
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN playwright install chromium

# Copy application code
COPY . .

# Create necessary directories and an unprivileged runtime user.
# The container no longer runs as root; /app/data is where volumes mount.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p data/sessions data/temp \
    && chown -R appuser:appuser /app /opt/pw-browsers

USER appuser

# Expose Streamlit port
EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Default command - run Streamlit app
CMD ["streamlit", "run", "app/Home.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
