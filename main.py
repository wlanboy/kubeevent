"""Einstiegspunkt: `uvicorn main:app` im Container, `uv run main.py` lokal."""

from kubeevents import main
from kubeevents.app import app

__all__ = ["app", "main"]

if __name__ == "__main__":
    main()
