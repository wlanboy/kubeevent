"""Löscht alte Events und entfernt veraltete Metrik-Zeitreihen."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, delete

from kubeevents import metrics
from kubeevents.config import Settings
from kubeevents.db import get_engine
from kubeevents.models import K8sEvent

logger = logging.getLogger(__name__)

RETENTION_INTERVAL_SECONDS = 3600


def delete_old_events(retention_days: int) -> int:
    """Löscht Events, die vor mehr als retention_days Tagen gespeichert wurden. Gibt deren Anzahl zurück."""
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=retention_days)
    with Session(get_engine()) as session:
        result = session.exec(delete(K8sEvent).where(col(K8sEvent.created_at) < cutoff))
        session.commit()
        return result.rowcount


async def retention_worker(stop: asyncio.Event, settings: Settings) -> None:
    """Läuft direkt nach dem Start und danach stündlich, bis stop gesetzt ist."""
    logger.info("Retention worker started (retention_days=%d)", settings.retention_days)

    while not stop.is_set():
        try:
            deleted = await asyncio.to_thread(delete_old_events, settings.retention_days)
            logger.info("Retention job deleted %d events", deleted)
        except Exception:
            logger.exception("Retention job failed")

        pruned = metrics.prune_stale_series(settings.metrics_series_ttl_hours * 3600)
        if pruned:
            logger.info("Removed %d stale metric series", pruned)

        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=RETENTION_INTERVAL_SECONDS)

    logger.info("Retention worker stopped")
