"""Start über `uv run main.py` oder das Skript `kubeevents`."""

import uvicorn

from kubeevents.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run("kubeevents.app:app", host=settings.host, port=settings.port, reload=settings.reload)
