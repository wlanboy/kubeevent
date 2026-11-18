"""FastAPI-App mit lifespan, Hintergrund-Tasks und Logging."""

import asyncio
import logging
import signal
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import FrameType
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from kubeevents import api, health
from kubeevents.auth import BasicAuthMiddleware
from kubeevents.config import Settings, get_settings
from kubeevents.db import init_db
from kubeevents.retention import retention_worker
from kubeevents.runtime import Runtime, supervise
from kubeevents.store import db_worker
from kubeevents.watcher import NamespaceWatcher

logger = logging.getLogger(__name__)

# So lange warten die Hintergrund-Tasks beim Shutdown, bevor sie abgebrochen werden
SHUTDOWN_TIMEOUT_SECONDS = 5


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def run_background(runtime: Runtime, settings: Settings) -> None:
    """DB-Worker, ein Watcher pro Namespace und Retention, jeweils mit Neustart nach Absturz."""
    namespaces = settings.namespaces
    logger.info("Watching namespaces: %s", ", ".join(namespaces))

    def make_watcher(namespace: str) -> NamespaceWatcher:
        return NamespaceWatcher(namespace, runtime.queue, runtime.stop, settings.watch_timeout_seconds)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(
            supervise(
                "db_worker",
                lambda: db_worker(runtime.queue, runtime.stop, runtime.notifier, settings),
                runtime.stop,
            ),
            name="db_worker",
        )
        for ns in namespaces:
            tg.create_task(
                supervise(f"watcher_{ns}", lambda ns=ns: make_watcher(ns).run(), runtime.stop),
                name=f"watcher_{ns}",
            )
        tg.create_task(
            supervise("retention", lambda: retention_worker(runtime.stop, settings), runtime.stop),
            name="retention",
        )

    logger.info("Background tasks stopped")


def close_streams_on_signal(runtime: Runtime) -> Callable[[], None]:
    """Schließt die SSE-Streams schon beim SIGINT oder SIGTERM.

    uvicorn wartet nach dem Signal erst auf offene Verbindungen und ruft danach den lifespan-Shutdown auf. SSE-Streams
    enden aber nie von selbst. Der Hook legt sich vor den Handler von uvicorn und ruft ihn danach auf. Gibt eine
    Funktion zurück, die die vorherigen Handler wiederherstellt.
    """
    loop = asyncio.get_running_loop()
    previous: dict[signal.Signals, Any] = {}

    def handler(sig: int, frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(lambda: loop.create_task(runtime.notifier.close()))
        prev = previous[signal.Signals(sig)]
        if callable(prev):
            prev(sig, frame)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, handler)
        except ValueError:
            # Nicht im Main-Thread, etwa im TestClient
            return lambda: None

    def restore() -> None:
        for sig, prev in previous.items():
            signal.signal(sig, prev)

    return restore


def create_app(settings: Settings | None = None, *, background: bool = True) -> FastAPI:
    """Baut die App. Mit background=False starten keine Watcher, das ist für Tests gedacht."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("Startup initiated")
        await asyncio.to_thread(init_db)

        runtime = Runtime(queue=asyncio.Queue(maxsize=settings.queue_maxsize))
        app.state.runtime = runtime
        restore_signals = close_streams_on_signal(runtime)
        if background:
            runtime.background = asyncio.create_task(run_background(runtime, settings), name="background")
        logger.info("Startup complete")

        yield

        logger.info("Shutdown initiated")
        restore_signals()
        runtime.stop.set()
        await runtime.notifier.close()
        if runtime.background is not None and not runtime.background.done():
            try:
                await asyncio.wait_for(runtime.background, timeout=SHUTDOWN_TIMEOUT_SECONDS)
            except TimeoutError:
                logger.warning("Background tasks did not stop within %ds, cancelled", SHUTDOWN_TIMEOUT_SECONDS)
        logger.info("Shutdown complete")

    app = FastAPI(title="kubeevents", lifespan=lifespan)
    if settings.basic_auth_enabled:
        app.add_middleware(
            BasicAuthMiddleware, username=settings.basic_auth_user, password_hash=settings.basic_auth_password_hash
        )
        logger.info("Basic auth enabled for user %s", settings.basic_auth_user)
    app.mount("/static", StaticFiles(directory=api.BASE_DIR / "static"), name="static")
    app.include_router(health.router)
    app.include_router(api.router)
    return app


app = create_app()
