"""Benachrichtigt offene SSE-Streams, wenn der DB-Worker neue Events gespeichert hat."""

import asyncio


class EventNotifier:
    """Merkt sich die höchste gespeicherte Event-ID und weckt wartende Streams."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._latest_id = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def publish(self, latest_id: int) -> None:
        async with self._condition:
            self._latest_id = max(self._latest_id, latest_id)
            self._condition.notify_all()

    async def close(self) -> None:
        """Beendet alle offenen Streams beim Shutdown."""
        async with self._condition:
            self._closed = True
            self._condition.notify_all()

    async def wait_newer(self, last_id: int, max_wait: float) -> bool:
        """Wartet auf Events mit höherer ID als last_id.

        Gibt True zurück, wenn solche Events gemeldet wurden, und False nach max_wait Sekunden oder beim Shutdown.
        """
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self._closed or self._latest_id > last_id), max_wait
                )
            except TimeoutError:
                return False
            return self._latest_id > last_id
