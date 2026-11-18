"""Start über `uv run main.py` oder das Skript `kubeevents`."""

import uvicorn

from kubeevents.config import get_settings

# Offene SSE-Streams enden nicht von selbst. Nach dieser Frist bricht uvicorn sie ab und fährt die App herunter,
# wie `--timeout-graceful-shutdown` im Dockerfile
GRACEFUL_SHUTDOWN_SECONDS = 5


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "kubeevents.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
