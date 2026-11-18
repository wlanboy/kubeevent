"""Speichert Events aus der Queue in Batches in der Datenbank."""

import asyncio
import logging

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, col

from kubeevents import metrics
from kubeevents.config import Settings
from kubeevents.db import get_engine
from kubeevents.models import K8sEvent
from kubeevents.notifier import EventNotifier

logger = logging.getLogger(__name__)

# So lange wartet der Worker auf das erste Event eines Batches, bevor er das Stop-Signal erneut prüft
IDLE_POLL_SECONDS = 1.0


def save_events(records: list[K8sEvent]) -> list[K8sEvent]:
    """Fügt Events ein und überspringt bekannte (uid, count). Gibt nur die neu eingefügten Events zurück."""
    if not records:
        return []

    rows = [record.model_dump(exclude={"id", "created_at"}) for record in records]
    stmt = (
        sqlite_insert(K8sEvent)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["uid", "count"])
        .returning(col(K8sEvent.id), col(K8sEvent.uid), col(K8sEvent.count))
    )

    with Session(get_engine()) as session:
        inserted = session.execute(stmt).all()
        session.commit()

    by_key: dict[tuple[str, int], K8sEvent] = {}
    for record in records:
        by_key.setdefault((record.uid, record.count), record)

    saved: list[K8sEvent] = []
    for event_id, uid, count in inserted:
        record = by_key[(uid, count)]
        record.id = event_id
        saved.append(record)
    return saved


async def flush(batch: list[K8sEvent], notifier: EventNotifier) -> None:
    """Speichert einen Batch, zählt die neuen Events in den Metriken und meldet sie den SSE-Streams."""
    try:
        saved = await asyncio.to_thread(save_events, batch)
    except Exception:
        logger.exception("Saving batch of %d events failed", len(batch))
        return

    for record in saved:
        metrics.record_event(record)

    if saved:
        logger.debug("Batch saved: %d of %d events are new", len(saved), len(batch))
        await notifier.publish(max(record.id or 0 for record in saved))


async def _collect_batch(queue: asyncio.Queue[K8sEvent], settings: Settings) -> list[K8sEvent]:
    """Wartet auf ein Event und sammelt danach bis zu batch_max_delay Sekunden weitere."""
    try:
        first = await asyncio.wait_for(queue.get(), timeout=IDLE_POLL_SECONDS)
    except TimeoutError:
        return []

    batch = [first]
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.batch_max_delay
    while len(batch) < settings.batch_max_size:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            batch.append(await asyncio.wait_for(queue.get(), timeout=remaining))
        except TimeoutError:
            break
    return batch


async def db_worker(
    queue: asyncio.Queue[K8sEvent], stop: asyncio.Event, notifier: EventNotifier, settings: Settings
) -> None:
    """Speichert Events aus der Queue, bis stop gesetzt ist, und danach den Rest der Queue."""
    logger.info("DB worker started")

    while not stop.is_set():
        batch = await _collect_batch(queue, settings)
        if batch:
            await flush(batch, notifier)

    remaining: list[K8sEvent] = []
    while not queue.empty():
        remaining.append(queue.get_nowait())
    for start in range(0, len(remaining), settings.batch_max_size):
        await flush(remaining[start : start + settings.batch_max_size], notifier)
    if remaining:
        logger.info("DB worker saved %d queued events during shutdown", len(remaining))

    logger.info("DB worker stopped")
