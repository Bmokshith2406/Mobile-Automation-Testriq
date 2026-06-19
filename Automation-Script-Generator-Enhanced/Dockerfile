FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgtk-3-0 \
    libgbm1 \
    libasound2 \
    libxshmfence1 \
    libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user to run the application.
# Running as root inside a container is a security risk — if the process
# is compromised, an attacker gains root over the container filesystem.
RUN adduser --disabled-password --gecos '' appuser

# Install Python dependencies as root (before switching user)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the application source — secrets, logs, and dev files
# are excluded by .dockerignore
COPY app/ ./app/

# Create runtime directories with correct ownership
RUN mkdir -p outputs/generated_scripts logs \
    && chown -R appuser:appuser /app

# Drop to non-root for all subsequent operations
USER appuser

EXPOSE 8080

# Healthcheck lets container orchestrators (K8s, ECS, Docker Compose)
# detect unhealthy instances and restart them automatically.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health/ || exit 1

# WEB_CONCURRENCY: number of gunicorn workers (default 2).
# Rule of thumb: 2 * CPU_cores + 1. Override via environment variable.
CMD ["sh", "-c", "gunicorn -k uvicorn.workers.UvicornWorker app.main:app \
  --bind 0.0.0.0:${PORT:-8080} \
  --workers ${WEB_CONCURRENCY:-2} \
  --timeout 120 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -"]