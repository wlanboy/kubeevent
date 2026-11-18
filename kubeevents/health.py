"""Liveness und Readiness."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from kubeevents.db import get_engine
from kubeevents.runtime import Runtime
from kubeevents.schemas import HealthStatus

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/healthz", response_model_exclude_none=True)
async def healthz() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get(
    "/readyz", response_model=HealthStatus, response_model_exclude_none=True, responses={503: {"model": HealthStatus}}
)
def readyz(request: Request) -> HealthStatus | JSONResponse:
    runtime: Runtime = request.app.state.runtime
    if runtime.background_failed():
        return _not_ready("background tasks stopped")

    try:
        with Session(get_engine()) as session:
            session.exec(select(1)).one()
    except Exception:  # noqa: BLE001 - readiness probe must report any db failure
        logger.warning("Readiness check: database not reachable", exc_info=True)
        return _not_ready("db not ready")

    return HealthStatus(status="ready")


def _not_ready(details: str) -> JSONResponse:
    return JSONResponse(
        status_code=503, content=HealthStatus(status="error", details=details).model_dump(exclude_none=True)
    )
