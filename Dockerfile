# Build stage für Dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

# System-Dependencies für kompilierte Packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# Runtime stage
FROM python:3.12-slim

# Security: Non-root user
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app

# Wheels aus Builder kopieren und installieren
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Anwendungscode kopieren (einzelne COPY-Anweisung für besseres Caching)
COPY --chown=appuser:appgroup db.py models.py metrics.py k8s_watcher.py runtime.py routes.py main.py ./
COPY --chown=appuser:appgroup static/ ./static/
COPY --chown=appuser:appgroup templates/ ./templates/

# Datenverzeichnis erstellen
RUN mkdir -p /app/data && chown appuser:appgroup /app/data

# Auf non-root User wechseln
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/healthz')" || exit 1

EXPOSE 5000

# Uvicorn mit optimierten Settings
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000", "--no-access-log", "--timeout-graceful-shutdown", "10"]
