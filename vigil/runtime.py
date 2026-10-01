"""Bridge from worker threads to the asyncio loop (DB writes, async services)."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Future

log = logging.getLogger("vigil.runtime")
_loop: asyncio.AbstractEventLoop | None = None


def bind(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def loop() -> asyncio.AbstractEventLoop | None:
    return _loop


def submit(coro) -> Future | None:
    """Schedule a coroutine on the main loop from any thread; errors are logged, never raised."""
    if _loop is None or _loop.is_closed():
        coro.close()
        return None
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)

    def _done(f: Future) -> None:
        exc = f.exception()
        if exc:
            log.error("background task failed: %r", exc)
    fut.add_done_callback(_done)
    return fut
