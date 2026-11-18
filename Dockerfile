ARG PYTHON_TAG=3.15-slim

# Build-Stage: venv nur aus fertigen Wheels, kein Compiler nötig
FROM python:${PYTHON_TAG} AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --only-binary=:all: -r requirements.txt && \
    mkdir -p /app/data


# Runtime-Stage
FROM python:${PYTHON_TAG}
ARG REVISION=unknown
LABEL org.opencontainers.image.title="kubeevents" \
      org.opencontainers.image.description="Real-time dashboard for collecting, storing and searching Kubernetes events" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.vendor="wlanboy" \
      org.opencontainers.image.source="https://github.com/wlanboy/kubeevent" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="python:3.15-slim"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd -r -g 1000 appuser && useradd -r -u 1000 -g appuser -s /usr/sbin/nologin -M appuser

WORKDIR /app

# venv gehört root, die App kann ihre eigenen Pakete nicht verändern
COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=appuser:appuser /app/data /app/data

COPY main.py db.py models.py metrics.py k8s_watcher.py runtime.py routes.py ./
COPY static/ ./static/
COPY templates/ ./templates/

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=3)"]

EXPOSE 5000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000", "--no-access-log", "--no-server-header", "--timeout-graceful-shutdown", "10"]
