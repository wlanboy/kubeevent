"""Laufzeitzustand der App und Überwachung der Hintergrund-Tasks."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field

from kubeevents.metrics import watch_restarts
from kubeevents.models import K8sEvent
from kubeevents.notifier import EventNotifier

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 30
# Lief ein Task so lange ohne Fehler, beginnt der Backoff nach einem Absturz wieder bei einer Sekunde
STABLE_RUN_SECONDS = 60


@dataclass
class Runtime:
    """Wird im lifespan angelegt und liegt unter app.state.runtime."""

    queue: asyncio.Queue[K8sEvent]
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    notifier: EventNotifier = field(default_factory=EventNotifier)
    background: asyncio.Task[None] | None = None

    def background_failed(self) -> bool:
        """True, wenn die Hintergrund-Tasks beendet sind, obwohl kein Shutdown läuft."""
        return self.background is not None and self.background.done() and not self.stop.is_set()


async def supervise(name: str, factory: Callable[[], Awaitable[None]], stop: asyncio.Event) -> None:
    """Startet einen Task neu, wenn er abstürzt oder unerwartet endet, bis stop gesetzt ist."""
    loop = asyncio.get_running_loop()
    backoff = 1
    while not stop.is_set():
        started = loop.time()
        try:
            await factory()
        except Exception:
            logger.exception("Task %s crashed", name)
        else:
            if stop.is_set():
                return
            logger.warning("Task %s ended unexpectedly", name)

        if loop.time() - started > STABLE_RUN_SECONDS:
            backoff = 1
        watch_restarts.inc()
        logger.info("Restarting task %s in %ds", name, backoff)
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
